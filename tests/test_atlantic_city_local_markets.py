from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html import escape
import json
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from roomquest import atlantic_city_local_markets as ac
from roomquest import mapsee_adapter


NOW = datetime(2026, 11, 14, 23, 0, tzinfo=timezone.utc)
TURKEY_BODY = '<p><strong>Annual Fast &amp; Furriest 5k Turkey Trot </strong>down the OC Boardwalk. Sponsored by the Humane Society of Ocean City. For more information call 609-398-9500 ext. 4 or visit <a href="http://www.hsocnj.org">hsocnj.org</a></p>'
CARRIAGE_BODY = '<p><strong>Horse &amp; Carriage Rides</strong> noon to 3:00 p.m., 9th &amp; Asbury Ave in front of City Hall.</p>'
FIRST_DAY_BODY = '<p><strong>First Day 5k Boardwalk Run</strong> Pre-register at <a href="https://www.firstnightocnj.com/first-day">www.firstnightocnj.com/first-day</a> or race day 11:00 a.m. &#8211; 12:30 p.m. at the Music Pier.\xa0 Race kicks off at 1:00 p.m.\xa0</p>'


def source(key):
    return dict(source_key=key, feed_url=ac.SOURCES[key][0], kind="html", platform_adapter="html", timezone=ac.ZONE)


def record(title, start, end, venue, street, city, url, identity, category="", lat=None, lng=None, tz=None, **kw):
    return dict(id=str(identity), title=title, starts_at=ac.timestamp(start, tz).astimezone(timezone.utc).isoformat(),
                ends_at=ac.timestamp(end, tz).astimezone(timezone.utc).isoformat() if end else None,
                venue_name=venue, venue_address=street, venue_city=city, event_url=url, category=category,
                lat=lat, lng=lng, reason=None if lat is not None else "missing_verified_venue_geo")


def tec_event(identity=42, body="<p>Full native event information.</p>", start="2026-12-02 18:00:00", end="2026-12-02 20:00:00", **updates):
    def utc(wall):
        return ac.timestamp(wall, ac.ZONE).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    event = dict(id=identity, title="Community performance", status="publish", timezone="UTC-5",
                 start_date=start, end_date=end, utc_start_date=utc(start), utc_end_date=utc(end),
                 description=body, url=f"https://oceancityvacation.com/events-calendar/performance-{identity}/",
                 categories=[dict(name="Community")],
                 venue=dict(venue="Music Pier", address="825 Boardwalk", city="Ocean City", state="NJ",
                            zip="08226", geo_lat=39.2751976, geo_lng=-74.5695462))
    event.update(updates)
    return event


def payload(events, total=None, pages=1):
    return json.dumps(dict(events=events, total=len(events) if total is None else total, total_pages=pages))


def wix_event(tree=False, hidden_end=True):
    if tree:
        identity, slug, title = "5db02f30-416d-45cb-96b0-8f6015ee87e9", "hammonton-tree-lighting-ceremony", "Hammonton Tree Lighting Ceremony"
        street, address, lat, lng, name = "", "Central Ave, Hammonton, NJ 08037, USA", 39.6546632, -74.8567854, "Hammonton"
        start, end, hidden_end = "2026-12-05T22:00:00.000Z", "2026-12-06T02:00:00.000Z", False
    else:
        identity, slug, title = "fe1bd8c0-1305-4d2f-827f-d1eec3381dcf", "small-business-saturday", "Small Business Saturday"
        street, address, lat, lng, name = "10", "10 S Egg Harbor Rd, Hammonton, NJ 08037, USA", 39.6348791, -74.80395949999999, "Downtown Hammonton"
        start, end = "2026-11-28T14:00:00.000Z", "2026-11-28T18:00:00.000Z"
    return dict(id=identity, slug=slug, title=title, status=0,
                scheduling=dict(config=dict(scheduleTbd=False, startDate=start, endDate=end, timeZoneId=ac.ZONE,
                                            endDateHidden=hidden_end, recurrences=dict(occurrences=[], status=0))),
                location=dict(name=name, type=0, tbd=False, address=address, coordinates=dict(lat=lat, lng=lng),
                              fullAddress=dict(country="US", subdivision="NJ", city="Hammonton", postalCode="08037",
                                               formattedAddress=address, streetAddress=dict(number=street, name="South Egg Harbor Road" if street else "Central Avenue", apt=""),
                                               geocode=dict(latitude=lat, longitude=lng))))


def warmup(app):
    return '<script id="wix-warmup-data" type="application/json">' + json.dumps(dict(appsWarmupData={ac.WIX_APP: app})) + '</script>'


def wix_listing(events, has_more=False):
    links = ''.join('<a href="' + ac.SOURCES[ac.HAMMONTON][0] + 'event-details-registration/' + e['slug'] + '">Event</a>' for e in events)
    return warmup({ac.WIX_WIDGET: dict(events=dict(events=events, hasMore=has_more, moreLoading=False))}) + links


def wix_detail(event, body="Complete details for the town event.", *, visible=None, ld_end=None):
    event = deepcopy(event)
    event['longDescription'] = dict(nodes=[dict(type="PARAGRAPH", nodes=[dict(type="TEXT", textData=dict(text=body), nodes=[])])])
    url = ac.SOURCES[ac.HAMMONTON][0] + 'event-details-registration/' + event['slug']
    config = event['scheduling']['config']
    ld = dict(**{'@type': 'Event'}, name=event['title'], description="Short JSON-LD tagline.",
              startDate=config['startDate'], eventStatus="https://schema.org/EventScheduled",
              eventAttendanceMode="https://schema.org/OfflineEventAttendanceMode")
    if not config['endDateHidden']:
        ld['endDate'] = config['endDate']
    if ld_end is not None:
        ld['endDate'] = ld_end
    return (warmup(dict(EventsPageInitialState=dict(event=dict(event=event))))
            + f'<link rel="canonical" href="{url}"><h1 data-hook="event-title">{escape(event["title"])}</h1>'
            + '<div data-hook="about-section"><h2>About the event</h2><div data-id="content-viewer"><p>'
            + escape(body if visible is None else visible) + '</p></div><button>Show More</button></div>'
            + '<script type="application/ld+json">' + json.dumps(ld) + '</script>')


class LocalMarketsTests(unittest.TestCase):
    def setUp(self):
        self.patches = [patch.object(ac, 'record', side_effect=record), patch.object(mapsee_adapter, 'record', side_effect=record)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def collect_tec(self, events):
        return ac.collect(source(ac.OCEAN_CITY), lambda u, a: payload(events), now=NOW)

    def test_full_tec_description_over_2000_and_escaped_literal_are_preserved(self):
        full = 'All workshop information. ' * 180 + 'Read <literal text> and keep the final condition & fee.'
        rows = self.collect_tec([tec_event(body='<p>' + escape(full) + '</p>')])
        self.assertEqual(rows[0]['description'], full)
        self.assertGreater(len(rows[0]['description']), 4000)
        self.assertEqual(rows[0]['venue_address'], '825 Boardwalk, Ocean City, NJ 08226')

    def test_blank_and_oversized_tec_descriptions_fail_without_fallback(self):
        for body, error in [('<p> </p>', 'description_missing'), ('<p>' + 'x' * 12001 + '</p>', 'description_limit')]:
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                self.collect_tec([tec_event(body=body)])

    def test_tec_pagination_is_complete_and_uses_worker_callback_mime(self):
        responses = [payload([tec_event(1)], total=2, pages=2), payload([tec_event(2)], total=2, pages=2)]
        fetch = Mock(side_effect=lambda url, accept: responses.pop(0))
        rows = ac.collect(source(ac.OCEAN_CITY), fetch, now=NOW)
        self.assertEqual(len(rows), 2)
        self.assertEqual(fetch.call_count, 2)
        self.assertTrue(all(c.args[1] == 'application/json' for c in fetch.call_args_list))
        self.assertIn('page=2', fetch.call_args_list[-1].args[0])

    def test_incomplete_changed_and_duplicate_tec_pages_return_no_snapshot(self):
        cases = [([payload([tec_event(1)], total=2)], 'incomplete_snapshot'),
                 ([payload([tec_event(1)], total=2, pages=2), payload([tec_event(2)], total=3, pages=2)], 'snapshot_changed'),
                 ([payload([tec_event(1)], total=2, pages=2), payload([tec_event(1)], total=2, pages=2)], 'duplicate_occurrence')]
        for values, error in cases:
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                ac.collect(source(ac.OCEAN_CITY), Mock(side_effect=values), now=NOW)

    def test_native_cancellation_nonpublic_and_elapsed_rows_are_excluded(self):
        events = [tec_event(1, event_status='cancelled'), tec_event(2, title='Private event'),
                  tec_event(3, start='2026-11-13 12:00:00', end='2026-11-13 14:00:00'),
                  tec_event(4, is_virtual=True), tec_event(5, all_day=True), tec_event(6)]
        self.assertEqual([x['id'] for x in self.collect_tec(events)], ['6'])

    def test_native_timezone_and_utc_mismatch_are_rejected(self):
        for updates in [dict(timezone='UTC+0'), dict(utc_start_date='2026-12-02 18:00:00')]:
            with self.subTest(updates=updates), self.assertRaisesRegex(ValueError, 'timezone_changed|schedule_conflict'):
                self.collect_tec([tec_event(**updates)])

    def test_turkey_race_clock_is_0830_and_end_remains_unknown(self):
        event = tec_event(388436, TURKEY_BODY, '2026-11-26 08:00:00', '2026-11-26 17:00:00',
                          title='Annual Fast &amp; Furriest 5k Turkey Trot', venue=[])
        row = self.collect_tec([event])[0]
        self.assertEqual(row['starts_at'], '2026-11-26T13:30:00+00:00')
        self.assertIsNone(row['ends_at'])
        self.assertEqual(row['description'], ac.narrative(TURKEY_BODY))
        self.assertEqual(row['venue_address'], ac.MUSIC_PIER[1])
        event['description'] += '<p>A changed race edition.</p>'
        with self.assertRaisesRegex(ValueError, 'clock_review_changed'):
            self.collect_tec([event])

    def test_first_day_uses_race_start_not_registration_start(self):
        row = self.collect_tec([tec_event(388452, FIRST_DAY_BODY, '2027-01-01 11:00:00', '2027-01-01 13:30:00')])[0]
        self.assertEqual(row['starts_at'], '2027-01-01T18:00:00+00:00')
        self.assertEqual(row['ends_at'], '2027-01-01T18:30:00+00:00')
        self.assertIn('11:00 a.m.', row['description'])
        self.assertTrue(row['description'].endswith('Race kicks off at 1:00 p.m.'))

    def test_reviewed_race_rejects_changed_conflicting_clock_and_accepts_publisher_correction(self):
        with self.assertRaisesRegex(ValueError, 'clock_review_changed'):
            self.collect_tec([tec_event(388452, FIRST_DAY_BODY, '2027-01-01 12:00:00', '2027-01-01 13:30:00')])
        corrected = self.collect_tec([tec_event(388452, FIRST_DAY_BODY, '2027-01-01 13:00:00', '2027-01-01 13:30:00')])[0]
        self.assertEqual(corrected['starts_at'], '2027-01-01T18:00:00+00:00')
        self.assertEqual(corrected['description'], ac.narrative(FIRST_DAY_BODY))
        self.assertEqual(corrected['ends_at'], '2027-01-01T18:30:00+00:00')

    def test_carriage_address_association_does_not_apply_to_changed_venue(self):
        event = tec_event(388424, CARRIAGE_BODY, '2026-11-21 12:00:00', '2026-11-21 15:00:00',
                          title='Horse &amp; Carriage Rides', venue=[])
        row = self.collect_tec([event])[0]
        self.assertEqual(row['venue_address'], ac.CITY_HALL[1])
        event['description'] = event['description'].replace('9th', '6th')
        with self.assertRaisesRegex(ValueError, 'street_missing'):
            self.collect_tec([event])

    def test_partial_street_or_remote_generic_point_cannot_publish(self):
        for field, value, error in [('zip', '', 'street_missing'), ('geo_lat', 40.7128, 'venue_point_invalid'),
                                    ('city', 'New York', 'venue_changed')]:
            event = tec_event()
            event['venue'][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, error):
                self.collect_tec([event])

    def test_wix_full_body_beats_tagline_and_preserves_literal_angle_text(self):
        event = wix_event()
        body = 'Entire event information. ' * 180 + 'Read <literal text> and keep the final condition.'
        fetch = Mock(side_effect=[wix_listing([event]), wix_detail(event, body)])
        row = ac.collect(source(ac.HAMMONTON), fetch, now=NOW)[0]
        self.assertEqual(row['description'], body)
        self.assertIsNone(row['ends_at'])
        self.assertTrue(all(c.args[1] == 'text/html' for c in fetch.call_args_list))

    def test_wix_rich_body_and_visible_body_must_match_fully(self):
        event = wix_event()
        body = 'Read <literal text> and keep the full final condition.'
        for visible in ['Read and keep the full final condition.', 'Read <literal text> and keep']:
            with self.subTest(visible=visible), self.assertRaisesRegex(ValueError, 'full_description_mismatch'):
                ac.collect(source(ac.HAMMONTON), Mock(side_effect=[wix_listing([event]), wix_detail(event, body, visible=visible)]), now=NOW)

    def test_wix_blank_or_oversized_full_body_is_not_replaced_by_tagline(self):
        event = wix_event()
        for body, error in [('', 'description_missing'), ('x' * 12001, 'description_limit')]:
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                ac.collect(source(ac.HAMMONTON), Mock(side_effect=[wix_listing([event]), wix_detail(event, body)]), now=NOW)

    def test_wix_has_more_is_not_a_partial_manifest(self):
        fetch = Mock(return_value=wix_listing([wix_event()], has_more=True))
        with self.assertRaisesRegex(ValueError, 'incomplete_manifest'):
            ac.collect(source(ac.HAMMONTON), fetch, now=NOW)
        self.assertEqual(fetch.call_count, 1)

    def test_wix_changed_detail_identity_or_schedule_aborts_batch(self):
        event = wix_event()
        for field, value in [('title', 'Changed event'), ('id', '11111111-2222-3333-4444-555555555555')]:
            changed = deepcopy(event)
            changed[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'snapshot_changed'):
                ac.collect(source(ac.HAMMONTON), Mock(side_effect=[wix_listing([event]), wix_detail(changed)]), now=NOW)
        with self.assertRaisesRegex(ValueError, 'schedule_conflict'):
            ac.collect(source(ac.HAMMONTON), Mock(side_effect=[wix_listing([event]), wix_detail(event, ld_end=event['scheduling']['config']['endDate'])]), now=NOW)

    def test_wix_recurrence_is_not_projected_without_review(self):
        event = wix_event()
        event['scheduling']['config']['recurrences']['occurrences'] = ['2026-12-05']
        with self.assertRaisesRegex(ValueError, 'recurrence_unreviewed'):
            ac.collect(source(ac.HAMMONTON), Mock(return_value=wix_listing([event])), now=NOW)

    def test_tree_uses_labeled_nearby_landmark_not_generic_road_center(self):
        event = wix_event(tree=True)
        body = 'Visit the tree festivities and The Bellevue Christmas Village with the whole family.'
        row = ac.collect(source(ac.HAMMONTON), Mock(side_effect=[wix_listing([event]), wix_detail(event, body)]), now=NOW)[0]
        self.assertEqual(row['venue_name'], ac.APPROXIMATE_VENUE)
        self.assertEqual(row['venue_address'], '236 Bellevue Avenue, Hammonton, NJ 08037')
        self.assertEqual((row['lat'], row['lng']), (39.636711000003, -74.802199500001))
        self.assertEqual(row['description'], body)
        self.assertIn('Central Ave', row['publisher_venue_address'])
        with self.assertRaisesRegex(ValueError, 'street_missing'):
            ac.collect(source(ac.HAMMONTON), Mock(side_effect=[wix_listing([event]), wix_detail(event, 'A different event with no participating landmark.')]), now=NOW)

    def test_source_fence_deadline_and_event_url_scope(self):
        bad = source(ac.HAMMONTON)
        bad['feed_url'] += 'unregistered'
        fetch = Mock()
        with self.assertRaisesRegex(ValueError, 'unregistered_'):
            ac.collect(bad, fetch, now=NOW)
        with self.assertRaisesRegex(ValueError, 'collection_deadline'):
            ac.collect(source(ac.OCEAN_CITY), fetch, now=NOW, deadline_at=1)
        fetch.assert_not_called()
        self.assertTrue(ac.event_url(ac.OCEAN_CITY, 'https://oceancityvacation.com/events-calendar/frozen-jr/2026-12-19/2/'))
        self.assertIsNone(ac.photo_url(ac.HAMMONTON, 'https://static.wixstatic.com/media/cdcb18_3a3e04382cd146aabb19722a0f41a5bc~mv2.png'))
        self.assertEqual(ac.photo_url(ac.OCEAN_CITY, 'https://oceancityvacation.com/wp-content/uploads/2026/11/event.jpg'),
                         'https://oceancityvacation.com/wp-content/uploads/2026/11/event.jpg')
        for url in ['https://oceancityvacation.com.evil.test/events-calendar/x/',
                    'https://oceancityvacation.com/events-calendar/../private/',
                    'https://oceancityvacation.com/events-calendar/x/?next=other']:
            self.assertFalse(ac.event_url(ac.OCEAN_CITY, url))


if __name__ == '__main__':
    unittest.main()
