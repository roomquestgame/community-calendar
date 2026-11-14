import copy
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import Mock, patch

from roomquest import atlantic_city_outdoors_more as ac


NOW = datetime(2026, 11, 14, 21, tzinfo=timezone.utc)


def source():
    return {'source_key': ac.ATLANTIC_CAPE, 'feed_url': ac.SOURCES[ac.ATLANTIC_CAPE][0],
            'kind': 'html', 'platform_adapter': 'html', 'timezone': ac.ZONE}


def event(**updates):
    result = {
        'id': 100, 'title': 'Star Party', 'private': False, 'rejected': False,
        'publish_status': 'published', 'status': 'live', 'experience': 'inperson',
        'description': '<p>Explore the night sky. Registration required.</p>',
        'location_name': 'Mays Landing Campus - STEM Lobby', 'room_number': None,
        'address': '5100 Black Horse Pike, Mays Landing, New Jersey 8330',
        'geo': {'latitude': '39.460636', 'longitude': '-74.679674',
                'street': '5100 Black Horse Pike', 'city': 'Hamilton', 'state': 'NJ', 'zip': '08330'},
        'filters': {'event_audiences': [{'name': 'General Public'}],
                    'event_types': [{'name': 'Public'}], 'event_topics': [{'name': 'Entertainment'}]},
        'localist_url': 'https://events.atlanticcape.edu/event/star-party-2026',
        'photo_url': 'https://localist-images.azureedge.net/photos/123/huge/abc123.jpg',
        'event_instances': [{'event_instance': {'id': 101, 'event_id': 100, 'all_day': False,
                            'start': '2026-12-04T18:00:00-05:00', 'end': '2026-12-04T20:30:00-05:00'}}],
    }
    result.update(updates)
    return result


def preview(title, start, end, venue, street, city, url, identity, category='', **kwargs):
    return {'id': identity, 'title': title, 'starts_at': start, 'ends_at': end,
            'venue_name': venue, 'venue_address': street, 'venue_city': city,
            'event_url': url, 'category': category, 'lat': kwargs.get('lat'), 'lng': kwargs.get('lng')}


def payload(*events, page=1, pages=1, total=None):
    return json.dumps({'events': [{'event': e} for e in events],
                       'page': {'current': page, 'size': 100, 'total': pages,
                                'total_items': len(events) if total is None else total,
                                'next_page': page + 1 if page < pages else None}})


def race_pages():
    parent = {'@type': 'SportsEvent', 'additionalType': 'Product', 'url': ac.EHT_ROOT,
              'startDate': '2026-11-28T09:00:00-05:00',
              'location': {'address': {'addressRegion': 'NJ'}}}
    narrative = ('Saturday, NOVEMBER 28, 2026 at 9 AM. '
                 'The EHT Nature Reserve is located at 318 Zion Road. '
                 + 'Complete participant directions. ' * 90
                 + 'Final instruction: shuttle parking at 391 Zion Road.')
    main = f'<script type="application/ld+json">{json.dumps(parent)}</script><div id="raceFullDesc">{narrative}</div>'
    details = ''
    for identity, label, minute in ((1156456, '5k Turkey Trot', '00'), (1156457, '1 Mile Nature Walk', '15')):
        url = ac.EHT_EVENTS + '#event-' + str(identity)
        main += (f'<div class="rsuEventTile__content"><h2 class="rsuEventTile__header">'
                 f'<a href="{url}">{label}</a></h2>'
                 f'<a href="/Race/Register/?raceId=13178&amp;eventId={identity}">Sign up</a></div>')
        obj = {'@type': 'SportsEvent', 'name': label, 'url': url,
               'startDate': f'2026-11-28T09:{minute}:00-05:00',
               'endDate': f'2026-11-28T11:{minute}:59-05:00',
               'location': {'address': {'streetAddress': ac.EHT_VENUE,
                            'addressLocality': 'Egg Harbor Township', 'addressRegion': 'NJ', 'postalCode': '08234'}}}
        details += (f'<script type="application/ld+json">{json.dumps(obj)}</script>'
                    f'<div class="event" id="event-{identity}"><h2>{label}</h2>'
                    f'<dl><dt>Start Time:</dt><dd>9:{minute}am EST</dd></dl>'
                    '<div class="margin-tb-10">Race-specific registration details.</div></div>')
    return main, details


class AtlanticCapeTest(unittest.TestCase):
    @patch.object(ac, 'record', side_effect=preview)
    def test_complete_narrative_explicit_offsets_and_publisher_location(self, _):
        prose = 'Full publisher instructions. ' * 100 + 'Keep &lt;the final eligibility condition&gt;.'
        rows = ac.collect(source(), Mock(return_value=payload(event(description='<p>' + prose + '</p>'))), now=NOW)
        self.assertEqual(len(rows), 1)
        self.assertGreater(len(rows[0]['description']), 2000)
        self.assertTrue(rows[0]['description'].endswith('Keep <the final eligibility condition>.'))
        self.assertEqual(rows[0]['starts_at'], '2026-12-04T18:00:00-05:00')
        self.assertEqual(rows[0]['venue_address'], ac.MAYS_STREET)
        self.assertEqual(rows[0]['lat'], 39.460636)
        self.assertEqual(rows[0]['publisher_categories'], ['Public', 'Entertainment'])

    @patch.object(ac, 'record', side_effect=preview)
    def test_private_student_only_virtual_cancelled_not_published(self, _):
        for updates in ({'private': True}, {'rejected': True}, {'status': 'canceled'},
                        {'experience': 'virtual'}, {'publish_status': 'draft'},
                        {'filters': {'event_audiences': [{'name': 'Students'}]}},
                        {'description': '<p>This is a students-only program.</p>'}):
            with self.subTest(updates=updates):
                self.assertEqual(ac.parse_events([{'event': event(**updates)}], NOW), [])

    @patch.object(ac, 'record', side_effect=preview)
    def test_reviewed_open_13_plus_esports_keeps_terms_and_uses_campus_address(self, _):
        esports = event(title='Esports Tournament Series: Atlantic Cape Clash',
                        description='<p>Players from Cape May, Cumberland, and Atlantic counties. '
                                    'Open to players ages 13+. Entry $10. Registration required.</p>',
                        filters={'event_audiences': [{'name': 'Students'}]},
                        location_name='Mays Landing Campus-Innovation Center', address='', geo={})
        row = ac.parse_events([{'event': esports}], NOW)[0]
        self.assertIn('ages 13+', row['description'])
        self.assertIsNone(row['lat'])
        self.assertEqual(row['venue_address'], ac.MAYS_STREET)
        esports['description'] = '<p>Players from Cape May, Cumberland, and Atlantic counties.</p>'
        self.assertEqual(ac.parse_events([{'event': esports}], NOW), [])

    @patch.object(ac, 'record', side_effect=preview)
    def test_away_or_conflicting_venues_never_get_college_address(self, _):
        for updates in ({'location_name': 'Bergen County College', 'address': '', 'geo': {}},
                        {'geo': {'street': '777 Different Road'}},
                        {'geo': {'street': '5100 Completely Different Road'}},
                        {'address': '5100 Completely Different Road, Mays Landing, NJ 08330'},
                        {'address': '5100 Black Horse Pike, Atlantic City, NJ 08401'},
                        {'geo': {'street': '5100 Black Horse Pike', 'state': 'PA', 'zip': '08330'}},
                        {'location_name': 'Unreviewed Campus Room'}):
            self.assertEqual(ac.parse_events([{'event': event(**updates)}], NOW), [])

    @patch.object(ac, 'record', side_effect=preview)
    def test_bacharach_street_state_and_postal_aliases_are_supported(self, _):
        e = event(location_name='Atlantic City Campus',
                  address='1535 Bacharach Blvd, Atlantic City, New Jersey 8401',
                  geo={'street': '1535 Bacharach Boulevard', 'state': 'NJ', 'zip': '08401'})
        row = ac.parse_events([{'event': e}], NOW)[0]
        self.assertEqual(row['venue_address'], ac.AC_STREET)
        e['address'] = '1535 Bacharach Blvd, Atlantic City, NJ 08401'
        self.assertEqual(len(ac.parse_events([{'event': e}], NOW)), 1)

    @patch.object(ac, 'record', side_effect=preview)
    def test_missing_clock_is_held_and_incomplete_offset_fails(self, _):
        e = event()
        e['event_instances'][0]['event_instance']['all_day'] = True
        self.assertEqual(ac.parse_events([{'event': e}], NOW), [])
        e = event()
        e['event_instances'][0]['event_instance']['start'] = '2026-12-04T18:00:00'
        with self.assertRaisesRegex(ValueError, 'time_unresolved'):
            ac.parse_events([{'event': e}], NOW)

    def test_description_limit_fails_without_clipping(self):
        with self.assertRaisesRegex(ValueError, 'publisher_description_limit'):
            ac.parse_events([{'event': event(description='<p>' + 'x' * 12001 + '</p>')}], NOW)

    @patch.object(ac, 'record', side_effect=preview)
    def test_recurring_dates_have_independent_stable_identity_and_no_duplicates(self, _):
        first = event()
        second = copy.deepcopy(first)
        instance = second['event_instances'][0]['event_instance']
        instance.update(id=102, start='2026-12-05T18:00:00-05:00', end='2026-12-05T20:30:00-05:00')
        rows = ac.parse_events([{'event': first}, {'event': second}, {'event': first}], NOW)
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]['id'], rows[1]['id'])

    @patch.object(ac, 'record', side_effect=preview)
    def test_all_pages_required_and_counts_must_match(self, _):
        e2 = event(id=200)
        e2['event_instances'][0]['event_instance'].update(id=201, event_id=200)
        fetch = Mock(side_effect=[payload(event(), page=1, pages=2, total=2), payload(e2, page=2, pages=2, total=2)])
        rows = ac.collect(source(), fetch, now=NOW)
        self.assertEqual(len(rows), 2)
        self.assertEqual(fetch.call_count, 2)
        self.assertIn('page=2', fetch.call_args_list[-1].args[0])
        with self.assertRaisesRegex(ValueError, 'snapshot_incomplete'):
            ac.collect(source(), Mock(return_value=payload(event(), total=2)), now=NOW)
        with self.assertRaisesRegex(ValueError, 'pagination_limit'):
            ac.collect(source(), Mock(return_value=payload(event(), pages=6, total=501)), now=NOW)

    @patch.object(ac, 'record', side_effect=preview)
    def test_changed_pagination_or_duplicate_conflict_never_returns_partial(self, _):
        fetch = Mock(side_effect=[payload(event(), page=1, pages=2, total=2), payload(event(), page=2, pages=2, total=3)])
        with self.assertRaisesRegex(ValueError, 'pagination_changed'):
            ac.collect(source(), fetch, now=NOW)
        altered = event(description='<p>Changed full narrative.</p>')
        with self.assertRaisesRegex(ValueError, 'conflicting_occurrence'):
            ac.parse_events([{'event': event()}, {'event': altered}], NOW)

    @patch.object(ac, 'record', side_effect=preview)
    def test_expired_and_outside_window_omitted(self, _):
        e = event()
        e['event_instances'][0]['event_instance'].update(start='2026-11-13T18:00:00-05:00', end='2026-11-13T20:30:00-05:00')
        self.assertEqual(ac.parse_events([{'event': e}], NOW), [])
        e['event_instances'][0]['event_instance'].update(start='2027-02-13T18:00:00-05:00', end='2027-02-13T20:30:00-05:00')
        self.assertEqual(ac.parse_events([{'event': e}], NOW), [])

    def test_exact_source_identity_and_link_allowlists(self):
        with self.assertRaisesRegex(ValueError, 'unregistered'):
            ac.collect({**source(), 'feed_url': 'https://evil.example/'}, Mock())
        for url in ('https://events.atlanticcape.edu.evil.test/event/x',
                    'https://events.atlanticcape.edu/event/x?token=secret',
                    'https://events.atlanticcape.edu/event/../x'):
            self.assertFalse(ac.event_url(ac.ATLANTIC_CAPE, url))
        self.assertIsNone(ac.photo_url(ac.ATLANTIC_CAPE, 'https://evil.example/photos/123/huge/abc.jpg'))


class EhtTurkeyTrotTest(unittest.TestCase):
    @patch.object(ac, 'record', side_effect=preview)
    def test_two_distances_keep_explicit_clocks_full_prose_and_no_synthetic_end(self, _):
        rows = ac._turkey_trot(*race_pages(), NOW)
        self.assertEqual(len(rows), 2)
        self.assertEqual([r['id'] for r in rows], ['runsignup:13178:1156456', 'runsignup:13178:1156457'])
        self.assertEqual([r['starts_at'] for r in rows], ['2026-11-28T09:00:00-05:00', '2026-11-28T09:15:00-05:00'])
        self.assertTrue(all(r['ends_at'] is None for r in rows))
        self.assertTrue(all(len(r['description']) > 2000 for r in rows))
        self.assertTrue(all('Final instruction: shuttle parking at 391 Zion Road.' in r['description'] for r in rows))
        self.assertTrue(all(r['venue_address'] == ac.EHT_STREET for r in rows))

    @patch.object(ac, 'record', side_effect=preview)
    def test_only_confirmed_cancellation_is_omitted_without_partial_manifest(self, _):
        main, details = race_pages()
        details = details.replace('"name": "5k Turkey Trot"', '"name": "5k Turkey Trot", "eventStatus": "https://schema.org/EventCancelled"')
        rows = ac._turkey_trot(main, details, NOW)
        self.assertEqual([r['title'] for r in rows], ['1 Mile Nature Walk'])
        with self.assertRaisesRegex(ValueError, 'identity_changed'):
            ac._turkey_trot(main, details.replace('#event-1156457', '#event-999'), NOW)

    def test_old_year_and_visible_clock_conflicts_are_rejected(self):
        main, details = race_pages()
        with self.assertRaisesRegex(ValueError, 'clock_conflict'):
            ac._turkey_trot(main.replace('NOVEMBER 28, 2026', 'NOVEMBER 28, 2025'), details, NOW)
        with self.assertRaisesRegex(ValueError, 'clock_conflict'):
            ac._turkey_trot(main, details.replace('9:00am EST', '8:00am EST'), NOW)
        with self.assertRaisesRegex(ValueError, 'venue_changed'):
            ac._turkey_trot(main.replace('318 Zion Road', '391 Zion Road'), details, NOW)

    @patch.object(ac, 'record', side_effect=preview)
    def test_exact_native_source_two_fetches_and_url_boundaries(self, _):
        main, details = race_pages()
        race_source = {'source_key': ac.EHT_TROT, 'feed_url': ac.EHT_ROOT,
                       'kind': 'html', 'platform_adapter': 'html', 'timezone': ac.ZONE}
        fetch = Mock(side_effect=[main, details])
        self.assertEqual(len(ac.collect(race_source, fetch, now=NOW)), 2)
        self.assertEqual([c.args[0] for c in fetch.call_args_list], [ac.EHT_ROOT, ac.EHT_EVENTS])
        self.assertFalse(ac.event_url(ac.EHT_TROT, ac.EHT_EVENTS + '#event-abc'))
        self.assertFalse(ac.event_url(ac.EHT_TROT, ac.EHT_EVENTS.replace('runsignup.com', 'evil.test') + '#event-123'))
        self.assertFalse(ac.event_url(ac.ATLANTIC_CAPE, ac.EHT_EVENTS + '#event-123'))


if __name__ == '__main__':
    unittest.main()
