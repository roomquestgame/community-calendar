import json
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
from urllib.parse import urlencode

from icalendar import Calendar, Event
from lzstring import LZString
from bs4 import BeautifulSoup

from roomquest import atlantic_city_community as ac


NOW = datetime(2026, 11, 14, 15, tzinfo=timezone.utc)


def widget(items):
    return json.dumps({'compressedEventsAndIds': [{
        'sourceCalendarGoogleId': 'library@group.calendar.google.com',
        'compressedEvents': LZString.compressToUTF16(json.dumps(items)),
    }]})


def library_item(**overrides):
    return {
        'id': 'tai-chi-series', 'title': 'Hybrid Tai Chi',
        'start': '2026-07-03T11:00:00-04:00', 'end': '2026-07-03T12:00:00-04:00',
        'allDay': False, 'timeZone': ac.ZONE,
        'recurrence': ['RRULE:FREQ=WEEKLY;BYDAY=FR'],
        'exdate': ['2026-11-27T11:00:00-05:00'],
        'extendedProps': {
            'location': 'Atlantic City Free Public Library, 1 N Tennessee Ave, Atlantic City, NJ 08401, USA',
            'description': '<p>Learn movement and breathing. All levels welcome.</p>',
        },
        **overrides,
    }


def detail(title='Community Art Workshop', *, body='<p>Paint, learn, and meet local artists.</p>',
           location='2200 Fairmount Ave, Atlantic City, NJ, 08401, United States',
           start='20261125T230000Z', end='20261126T010000Z', later=''):
    google = 'https://www.google.com/calendar/event?' + urlencode({
        'action': 'TEMPLATE', 'text': title, 'dates': start + '/' + end,
        'location': location,
    })
    return f'''<article class="eventitem">
    <h1 class="eventitem-title">{title}</h1>
    <a class="eventitem-meta-export-google" href="{google}">Google Calendar</a>
    <li class="eventitem-meta-address">Noyes Arts Garage 2200 Fairmount Ave Atlantic City, NJ, 08401</li>
    <div class="eventitem-column-content"><div class="sqs-layout">{body}</div></div>
    </article>{later}'''


def preview_record(title, start, end, venue, address, city, url, identity, **kwargs):
    return {'id': identity, 'title': title, 'starts_at': start, 'ends_at': end,
            'venue_name': venue, 'venue_address': address, 'venue_city': city,
            'event_url': url, 'lat': kwargs.get('lat'), 'lng': kwargs.get('lng')}


class AtlanticCityCommunityTest(unittest.TestCase):
    def test_publisher_text_keeps_more_than_two_thousand_characters(self):
        narrative = 'A complete workshop paragraph. ' * 110 + 'The final admission instruction.'
        link = ac.SOURCES[ac.NOYES][0] + '/2026/art-workshop'
        with patch.object(ac, 'record', side_effect=preview_record):
            row, _, _ = ac._squarespace_detail(ac.NOYES, link, detail(body='<p>' + narrative + '</p>'), NOW)
        self.assertEqual(row['description'], narrative)
        self.assertGreater(len(row['description']), 2000)
        self.assertTrue(row['description'].endswith('The final admission instruction.'))

    def test_description_limit_is_an_error_not_truncation(self):
        with self.assertRaisesRegex(ValueError, 'publisher_description_limit'):
            ac._full_description('x' * 12001)

    def test_missing_body_and_virtual_venue_are_held(self):
        link = ac.SOURCES[ac.NOYES][0] + '/2026/art-workshop'
        self.assertIsNone(ac._squarespace_detail(ac.NOYES, link, detail(body='<p>&nbsp;</p>'), NOW)[0])
        self.assertIsNone(ac._squarespace_detail(ac.NOYES, link, detail(location='Online'), NOW)[0])

    def test_equal_start_end_means_unknown_end_not_invented_hour(self):
        link = ac.SOURCES[ac.NOYES][0] + '/2026/art-workshop'
        with patch.object(ac, 'record', side_effect=preview_record):
            row, _, _ = ac._squarespace_detail(ac.NOYES, link, detail(end='20261125T230000Z'), NOW)
        self.assertIsNone(row['ends_at'])

    def test_county_offsite_stays_at_senior_center(self):
        actual = ac._county_location(
            '22-98 N Ambler Rd, Somers Point, NJ 08244, Somers Point, NJ, 08244, US',
            'This event will be held at the Somers Point Senior Center.')
        self.assertEqual(actual, ('Somers Point Senior Center',
                                 '22 North Ambler Road, Somers Point, NJ 08244', 'Somers Point'))
        other = ac._county_location('999 Other Street, Somers Point, NJ, 08244, US', 'A craft workshop.')
        self.assertEqual(other[1], '999 Other Street, Somers Point, NJ 08244')

    def test_county_malformed_branch_street_uses_official_directory(self):
        actual = ac._county_location('801 Shore 08244, Somers Point, NJ, 08244, US', 'Pre-K storytime.')
        self.assertEqual(actual[1], '801 Shore Road, Somers Point, NJ 08244')

    def test_county_normalizes_markup_before_shared_cap_and_keeps_override_prose(self):
        start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(
            hour=14, minute=0, second=0, microsecond=0)
        calendar = Calendar()
        calendar.add('VERSION', '2.0')
        expected = []
        for index in range(2):
            prose = f'Full occurrence {index} narrative with <literal text>.\nFinal admission condition {index}.'
            raw = (f'<p>Full occurrence {index} narrative with &lt;literal text&gt;.</p><span data-layout="'
                   + 'x' * 12000 + f'"></span><p>Final admission condition {index}.</p>')
            self.assertGreater(len(raw), 12000)
            self.assertEqual(ac._full_description(raw), prose)
            event = Event()
            event.add('UID', 'county-markup-boundary')
            event.add('SUMMARY', 'Public library workshop')
            event.add('DTSTART', start + timedelta(days=index))
            event.add('DTEND', start + timedelta(days=index, hours=1))
            event.add('DESCRIPTION', raw)
            event.add('LOCATION', '1 Swift Drive, Egg Harbor Township, NJ 08234')
            event.add('URL', 'https://atlanticcounty.librarycalendar.com/event/public-workshop')
            if index:
                event.add('RECURRENCE-ID', start + timedelta(days=index))
            else:
                event.add('RRULE', {'FREQ': 'DAILY', 'COUNT': 2})
            calendar.add_component(event)
            expected.append(prose)
        rows = ac._normalize_ics(calendar.to_ical().decode(), ac.COUNTY)
        self.assertEqual([row['description'] for row in rows], expected)
        # StyledCalendar enters this seam with plain text already extracted.
        # Its literal angle brackets must survive without a second HTML pass.
        for event, prose in zip(calendar.walk('VEVENT'), expected):
            event.pop('DESCRIPTION')
            event.add('DESCRIPTION', prose)
            event.pop('URL')
            event.add('URL', ac.SOURCES[ac.CITY_LIBRARY][0])
        rows = ac._normalize_ics(calendar.to_ical().decode(), ac.CITY_LIBRARY,
                                 locations={'county-markup-boundary': ac.MAIN_LIBRARY},
                                 already_normalized=True)
        self.assertEqual([row['description'] for row in rows], expected)

    def test_numbered_street_preserves_suite_in_street_component(self):
        address, city = ac._nj_address('160 S. Pitney Road, Suite 3-4, Galloway, NJ 08205')
        self.assertEqual(address, '160 S. Pitney Road Suite 3-4, Galloway, NJ 08205')
        self.assertEqual(city, 'Galloway')

    def test_branch_resolution_does_not_pin_virtual_or_unspecified_events(self):
        self.assertIsNone(ac._city_library_location('Virtual'))
        self.assertIsNone(ac._city_library_location(''))
        self.assertEqual(ac._city_library_location('Richmond Branch Library'), ac.RICHMOND_LIBRARY)
        self.assertEqual(ac._city_library_location('atlantic city free public library'), ac.MAIN_LIBRARY)

    def test_widget_preserves_recurrence_timezone_and_exception(self):
        raw, locations, _ = ac._styled_ical(widget([library_item()]), now=NOW)
        events = Calendar.from_ical(raw).walk('VEVENT')
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(str(event['DTSTART'].params['TZID']), ac.ZONE)
        self.assertEqual(event['RRULE']['FREQ'], ['WEEKLY'])
        self.assertEqual(event['EXDATE'].dts[0].dt.isoformat(), '2026-11-27T11:00:00-05:00')
        self.assertEqual(locations[str(event['UID'])], ac.MAIN_LIBRARY)
        self.assertEqual(str(event['DESCRIPTION']), 'Learn movement and breathing. All levels welcome.')

    def test_expired_recurring_history_is_not_counted_as_active_rules(self):
        expired = library_item(recurrence=['RRULE:FREQ=WEEKLY;BYDAY=FR;UNTIL=20260801T035959Z'])
        items = [{**expired, 'id': 'old-' + str(i)} for i in range(60)] + [library_item()]
        raw, locations, _ = ac._styled_ical(widget(items), now=NOW)
        self.assertEqual(len(Calendar.from_ical(raw).walk('VEVENT')), 1)
        self.assertEqual(len(locations), 1)

    def test_widget_keeps_long_description_and_library_closures(self):
        long_text = 'Community learning with a complete explanation. ' * 60
        item = library_item(extendedProps={'location': 'Main Library', 'description': '<p>' + long_text + '</p>'})
        closure = {'id': 'holiday', 'title': 'LIBRARY CLOSED - THANKSGIVING',
                   'start': '2026-11-26', 'end': '2026-11-27', 'allDay': True, 'timeZone': ac.ZONE}
        raw, _, closures = ac._styled_ical(widget([item, closure]), now=NOW)
        event = Calendar.from_ical(raw).walk('VEVENT')[0]
        self.assertEqual(str(event['DESCRIPTION']), long_text.strip())
        self.assertEqual(closures[0][0].isoformat(), '2026-11-26T00:00:00-05:00')

    def test_noyes_follows_actual_forward_link_into_next_month(self):
        base = ac.SOURCES[ac.NOYES][0]
        first, second = base + '/2026/november-workshop', base + '/2026/december-workshop'
        listing = '<noscript><ul><li><h1><a href="' + first + '">Workshop</a></h1><div>Monday, November 30, 2026, 6:00 PM</div></li></ul></noscript>'
        later = '<div class="eventitem-pager-newer"><div>Later Event: December 1</div><a href="' + second + '">Next workshop</a></div>'
        pages = {
            base: listing,
            first: detail(start='20261130T230000Z', end='20261201T000000Z', later=later),
            second: detail(start='20261201T230000Z', end='20261202T000000Z'),
        }
        fetch = Mock(side_effect=lambda url, accept: pages[url])
        with patch.object(ac, 'record', side_effect=preview_record):
            rows = ac._squarespace(ac.NOYES, fetch, NOW)
        self.assertEqual(len(rows), 2)
        self.assertEqual({call.args[0] for call in fetch.call_args_list}, set(pages))
        self.assertFalse(any('?' in call.args[0] for call in fetch.call_args_list))

    def test_source_and_next_link_identity_are_enforced(self):
        self.assertFalse(ac.event_url(ac.NOYES, 'https://other.example/all-noyes-events/2026/test'))
        self.assertFalse(ac.event_url(ac.NOYES, ac.SOURCES[ac.NOYES][0] + '?format=json'))
        source = {'source_key': ac.NOYES, 'feed_url': 'https://other.example/events',
                  'kind': 'html', 'platform_adapter': 'html', 'timezone': ac.ZONE}
        with self.assertRaisesRegex(ValueError, 'unregistered_atlantic_city_community_source'):
            ac.collect(source, Mock())

    def checkpoint_pages(self):
        base = ac.SOURCES[ac.NOYES][0]
        first, second, third = [base + '/2026/' + month for month in ('november', 'december', 'january')]
        listing = '<noscript><ul><li><h1><a href="' + first + '">Workshop</a></h1><div>November 30, 2026</div></li></ul></noscript>'
        later = lambda url: '<a class="eventitem-pager-newer" href="' + url + '">Later Event</a>'
        pages = {
            base: listing,
            first: detail(start='20261130T230000Z', end='20261201T000000Z', later=later(second)),
            second: detail(start='20261201T230000Z', end='20261202T000000Z', later=later(third)),
            third: detail(start='20270102T230000Z', end='20270103T000000Z'),
        }
        source = {'source_key': ac.NOYES, 'feed_url': base, 'kind': 'html',
                  'platform_adapter': 'html', 'timezone': ac.ZONE}
        return source, pages, [first, second, third]

    @patch.object(ac, 'record', side_effect=preview_record)
    def test_checkpoint_resumes_forward_chain_without_publishing_prefix(self, _):
        source, pages, urls = self.checkpoint_pages()
        fetch = Mock(side_effect=lambda url, accept: pages[url])
        first = ac.collect_chunk(source, fetch, now=NOW, max_details=1)
        self.assertFalse(first['complete'])
        self.assertEqual(first['events'], [])
        self.assertEqual(first['checkpoint']['cursor'], 1)
        self.assertEqual(first['checkpoint']['manifest_count'], 2)
        resumed = ac.collect_chunk(source, fetch, now=NOW, checkpoint=first['checkpoint'])
        self.assertTrue(resumed['complete'])
        self.assertEqual(len(resumed['events']), 3)
        self.assertEqual(resumed['checkpoint']['cursor'], resumed['checkpoint']['manifest_count'])
        self.assertEqual([call.args[0] for call in fetch.call_args_list].count(urls[0]), 1)
        fetch.reset_mock()
        repeated = ac.collect_chunk(source, fetch, now=NOW, checkpoint=resumed['checkpoint'])
        self.assertEqual(repeated['events'], resumed['events'])
        fetch.assert_called_once_with(source['feed_url'], 'text/html')

    @patch.object(ac, 'record', side_effect=preview_record)
    def test_checkpoint_detects_cursor_or_row_tampering(self, _):
        source, pages, _ = self.checkpoint_pages()
        fetch = Mock(side_effect=lambda url, accept: pages[url])
        first = ac.collect_chunk(source, fetch, now=NOW, max_details=1)
        for mutation in ('skip', 'blank', 'offsite', 'injected_link'):
            state = deepcopy(first['checkpoint'])
            if mutation == 'skip':
                state['cursor'] += 1
            elif mutation == 'blank':
                state['events'][0]['description'] = ''
            elif mutation == 'offsite':
                state['events'][0]['event_url'] = 'https://untrusted.example/event'
            else:
                state['queue'].append(source['feed_url'] + '/2026/injected')
                state['manifest_count'] += 1
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'noyes_checkpoint_invalid'):
                ac.collect_chunk(source, fetch, now=NOW, checkpoint=state)

    @patch.object(ac, 'record', side_effect=preview_record)
    def test_checkpoint_listing_change_restarts_and_deadline_preserves_old_state(self, _):
        source, pages, urls = self.checkpoint_pages()
        fetch = Mock(side_effect=lambda url, accept: pages[url])
        first = ac.collect_chunk(source, fetch, now=NOW, max_details=1)
        original = deepcopy(first['checkpoint'])
        with patch.object(ac, 'monotonic', return_value=100), self.assertRaisesRegex(ValueError, 'collection_deadline'):
            ac.collect_chunk(source, fetch, now=NOW, checkpoint=first['checkpoint'], deadline_at=110)
        self.assertEqual(first['checkpoint'], original)
        pages[source['feed_url']] = pages[source['feed_url']].replace('November 30', 'November 29')
        restart = ac.collect_chunk(source, fetch, now=NOW, checkpoint=original, max_details=1)
        self.assertNotEqual(restart['checkpoint']['manifest_hash'], original['manifest_hash'])
        self.assertEqual([call.args[0] for call in fetch.call_args_list].count(urls[0]), 2)

    @patch.object(ac, 'record', side_effect=preview_record)
    def test_checkpoint_held_detail_still_discovers_next_month(self, _):
        source, pages, urls = self.checkpoint_pages()
        pages[urls[0]] = pages[urls[0]].replace('Paint, learn, and meet local artists.', '')
        result = ac.collect_chunk(source, lambda url, accept: pages[url], now=NOW)
        self.assertTrue(result['complete'])
        self.assertEqual(len(result['events']), 2)
        self.assertEqual(result['checkpoint']['diagnostics'][0]['event_url'], urls[0])

    def test_municipal_exact_council_venue_and_other_locations(self):
        council = ac._municipal_location('City Council Chambers, 2nd Floor, Room 206', 'Zoning Board')
        self.assertEqual(council[1], '1301 Bacharach Boulevard, Atlantic City, NJ 08401')
        dinner = ac._municipal_location('St. Augustine’s Episcopal Church - 1709 Arctic Ave., Atlantic City', 'Dinner')
        self.assertEqual(dinner[1], '1709 Arctic Ave., Atlantic City, NJ 08401')
        self.assertIsNone(ac._municipal_location('Atlantic Avenue, Atlantic City', 'Holiday Parade'))
        block = ac._municipal_location('1800 Block of Marmora Ave., Atlantic City', 'Shredding')
        self.assertEqual(block, ac.MARMORA_BLOCK)
        self.assertIn('approximate map location', block[0])

    def test_municipal_retains_full_description_and_actual_time(self):
        url = 'https://www.acnj.gov/Calendar/ViewMeeting/607'
        card = {'id': '607', 'className': 'Meeting', 'title': 'Zoning Board',
                'start': '2026-11-20T10:00:00', 'end': None, 'allDay': False}
        narrative = 'The full published public meeting agenda. ' * 70
        data = {'Meeting_ID': 607, 'Meeting_IsCanceled': False, 'Meeting_Title': None,
                'Meeting_Type': 'Zoning Board', 'Meeting_DateTime': '2026-11-20T10:00:00',
                'Meeting_Location': 'City Council Chambers, 2nd Floor, Room 206',
                'Meeting_Description': '<p>' + narrative + '</p>'}
        with patch.object(ac, 'record', side_effect=preview_record):
            row = ac._municipal_detail(url, card, json.dumps(data))
        self.assertEqual(row['description'], narrative.strip())
        self.assertGreater(len(row['description']), 2000)
        self.assertEqual(row['starts_at'].astimezone(timezone.utc).isoformat(), '2026-11-20T15:00:00+00:00')
        self.assertIsNone(row['ends_at'])
        data['Meeting_Description'] = '<p><a href="https://example.org/meeting">https://example.org/meeting</a></p>'
        self.assertIsNone(ac._municipal_detail(url, card, json.dumps(data)))
        data['Meeting_DateTime'] = '2026-11-20T11:00:00'
        with self.assertRaisesRegex(ValueError, 'municipal_event_schedule_changed'):
            ac._municipal_detail(url, card, json.dumps(data))

    def test_municipal_checkpoint_tracks_all_held_and_published_records(self):
        source = {'source_key': ac.CITY, 'feed_url': ac.SOURCES[ac.CITY][0], 'kind': 'html',
                  'platform_adapter': 'html', 'timezone': ac.ZONE}
        cards = [{'id': str(i), 'className': 'Meeting', 'title': 'Public Meeting',
                  'start': '2026-12-02T17:00:00', 'end': None, 'allDay': False} for i in (700, 701)]
        def fetch(url, accept):
            if '/GetCalendarData?' in url:
                return json.dumps(cards)
            identity = int(url.split('=')[-1])
            return json.dumps({'Meeting_ID': identity, 'Meeting_IsCanceled': False,
                               'Meeting_Title': 'Public Meeting', 'Meeting_DateTime': cards[0]['start'],
                               'Meeting_Location': 'City Council Chambers, 2nd Floor, Room 206',
                               'Meeting_Description': '<p>Public discussion and resident questions.</p>' if identity == 700 else None})
        first = ac.collect_chunk(source, fetch, now=NOW, max_details=1)
        self.assertFalse(first['complete'])
        self.assertEqual(first['events'], [])
        final = ac.collect_chunk(source, fetch, checkpoint=first['checkpoint'], now=NOW)
        self.assertTrue(final['complete'])
        self.assertEqual(len(final['events']), 1)
        self.assertEqual(len(final['checkpoint']['diagnostics']), 1)
        self.assertTrue(ac.event_url(ac.CITY, final['events'][0]['event_url']))
        self.assertFalse(ac.event_url(ac.CITY, 'https://www.acnj.gov/api/data/GetEvent?id=700'))
        with self.assertRaisesRegex(ValueError, 'publisher_checkpoint_required'):
            ac.collect(source, fetch)

    def test_reviewed_points_require_exact_source_venue_and_street(self):
        original = {'venue_name': ac.MAIN_LIBRARY[0], 'venue_address': ac.MAIN_LIBRARY[1],
                    'lat': None, 'lng': None, 'reason': 'missing_verified_venue_geo'}
        row = deepcopy(original)
        ac._apply_reviewed_venue_point(row, ac.CITY_LIBRARY)
        self.assertEqual((row['lat'], row['lng']), (39.3625922, -74.4281244))
        self.assertIsNone(row['reason'])
        for change in ({'venue_name': ac.RICHMOND_LIBRARY[0]},
                       {'venue_address': ac.RICHMOND_LIBRARY[1]},
                       {'venue_address': '99 Other Street, Atlantic City, NJ 08401'}):
            row = {**original, **change}
            ac._apply_reviewed_venue_point(row, ac.CITY_LIBRARY)
            self.assertIsNone(row['lat'])
        row = deepcopy(original)
        ac._apply_reviewed_venue_point(row, ac.COUNTY)
        self.assertIsNone(row['lat'])
        row = {**original, 'lat': 39.36, 'lng': -74.42}
        ac._apply_reviewed_venue_point(row, ac.CITY_LIBRARY)
        self.assertEqual((row['lat'], row['lng']), (39.36, -74.42))

    def test_reviewed_offsite_and_church_points_do_not_supply_block_estimate(self):
        for key, location, expected in [
                (ac.COUNTY, ('Somers Point Senior Center', '22 North Ambler Road, Somers Point, NJ 08244'),
                 (39.3252475, -74.6081318)),
                (ac.CITY, ('St. Augustine’s Episcopal Church', '1709 Arctic Ave., Atlantic City, NJ 08401'),
                 (39.361884, -74.433525))]:
            row = {'venue_name': location[0], 'venue_address': location[1]}
            ac._apply_reviewed_venue_point(row, key)
            self.assertEqual((row['lat'], row['lng']), expected)
        block = {'venue_name': '1800 Block of Marmora Avenue',
                 'venue_address': '1800 Marmora Avenue, Atlantic City, NJ 08401'}
        ac._apply_reviewed_venue_point(block, ac.CITY)
        self.assertNotIn('lat', block)

    def test_reviewed_marmora_street_point_keeps_approximation_visible(self):
        block = {'venue_name': ac.MARMORA_BLOCK[0],
                 'venue_address': ac.MARMORA_BLOCK[1],
                 'reason': 'missing_verified_venue_geo'}
        ac._apply_reviewed_venue_point(block, ac.CITY)
        self.assertEqual((block['lat'], block['lng']),
                         (39.369920418545, -74.440134563461))
        self.assertIsNone(block['reason'])
        for source, name, street in (
                (ac.COUNTY, ac.MARMORA_BLOCK[0], ac.MARMORA_BLOCK[1]),
                (ac.CITY, ac.MARMORA_BLOCK[0], '1900 Marmora Avenue, Atlantic City, NJ 08401'),
                (ac.CITY, '1800 Block of Marmora Avenue', ac.MARMORA_BLOCK[1])):
            row = {'venue_name': name, 'venue_address': street}
            ac._apply_reviewed_venue_point(row, source)
            self.assertNotIn('lat', row)

    def test_event_metadata_points_require_matching_address_and_local_bounds(self):
        url = ac.SOURCES[ac.NOYES][0] + '/2026/independent-living-art'
        street = '160 S. Pitney Road, Suite 3-4, Galloway, NJ 08205'
        meta = f'<meta property="og:url" content="{url}"><meta property="og:latitude" content="39.4722933"><meta property="og:longitude" content="-74.4921719">'
        address = ('<li class="eventitem-meta-address"><span class="eventitem-meta-address-line eventitem-meta-address-line--title">Atlantic Center for Independent Living</span>'
                   '<span class="eventitem-meta-address-line">' + street + '</span>'
                   '<a class="eventitem-meta-address-maplink" href="https://maps.google.com?' + urlencode({'q': street}) + '">map</a></li>')
        body = meta + '<article class="eventitem">' + address + '</article>'
        def point(html):
            soup = BeautifulSoup(html, 'html.parser')
            return ac._squarespace_venue_point(soup, soup.select_one('.eventitem'), url, street)
        self.assertEqual(point(body), (39.4722933, -74.4921719))
        self.assertIsNone(point(body.replace('39.4722933', '40.7207559').replace('-74.4921719', '-74.0007613')))
        self.assertIsNone(point(body.replace('39.4722933', 'NaN')))
        self.assertIsNone(point(body.replace('content="' + url + '"', 'content="https://other.example/event"')))
        self.assertIsNone(point(body.replace('q=160+', 'q=999+')))
        self.assertIsNone(point(body.replace('>160 S. Pitney Road', '>999 Other Road')))

    def test_event_point_keeps_complete_long_narrative(self):
        url = ac.SOURCES[ac.NOYES][0] + '/2026/full-workshop'
        street = '2200 Fairmount Ave, Atlantic City, NJ, 08401, United States'
        narrative = 'A complete explanation of the workshop and its accessibility. ' * 50 + 'Final registration instruction.'
        page = detail(body='<p>' + narrative + '</p>', location=street)
        address = '<li class="eventitem-meta-address"><span class="eventitem-meta-address-line eventitem-meta-address-line--title">Noyes Arts Garage</span><span class="eventitem-meta-address-line">' + street + '</span><a class="eventitem-meta-address-maplink" href="https://maps.google.com?' + urlencode({'q': street}) + '">map</a></li>'
        page = page.replace('<li class="eventitem-meta-address">Noyes Arts Garage 2200 Fairmount Ave Atlantic City, NJ, 08401</li>', address)
        page = f'<meta property="og:url" content="{url}"><meta property="og:latitude" content="39.3604205"><meta property="og:longitude" content="-74.440793">' + page
        with patch.object(ac, 'record', side_effect=preview_record):
            row, _, _ = ac._squarespace_detail(ac.NOYES, url, page, NOW)
        self.assertEqual((row['lat'], row['lng']), (39.3604205, -74.440793))
        self.assertEqual(row['description'], narrative)
        self.assertTrue(row['description'].endswith('Final registration instruction.'))


if __name__ == '__main__':
    unittest.main()
