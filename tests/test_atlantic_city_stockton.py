import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from icalendar import Calendar, Event, vText

from roomquest import atlantic_city_stockton as st


NOW = datetime(2026, 11, 14, 20, 30, tzinfo=timezone.utc)


def preview(title, start, end, venue, street, city, url, identity, **kwargs):
    return {'id': identity, 'title': title, 'starts_at': start.isoformat(),
            'ends_at': end.isoformat() if end else None, 'venue_name': venue,
            'venue_address': street, 'venue_city': city, 'event_url': url,
            'lat': kwargs.get('lat'), 'lng': kwargs.get('lng')}


def pac_card(title='Mike Goodwin', *, subtitle='', day='Friday, November 20, 2026 @ 7:30 pm',
             body='<p>A complete public comedy program.</p>', identity='1815'):
    return f'''<div class="pac-event-item"><div class="event-details">
    <a href="https://stockton.universitytickets.com/w/event.aspx?id={identity}">
    <div class="event-title">{title}</div><div class="subtitle">{subtitle}</div></a>
    <div class="event-line1">{day}</div><div class="event-description">{body}</div>
    <div class="events-image"><img src="/pac/images/program.jpg"></div>
    </div></div>'''


def department_card(title='Public learning program', *, day='11/19/2026', clock='2:30 - 4 p.m.',
                    body='<p>Join a lecture. Free &amp; open to the public.</p>', subtitle='',
                    location="Stockton University's Galloway Campus | L-112 Lecture Hall | 101 Vera King Farris Drive, Galloway, NJ 08205"):
    return f'''<div class="cal-block-item"><div class="event-details">
    <div class="event-title">{title}</div><div class="subtitle">{subtitle}</div>
    <div class="date-time" data-day="{day}">Thursday, November 19, 2026 | {clock}</div>
    <div class="location">Location: {location}</div>
    <div class="event-description">{body}</div></div></div>'''


def native_event(title='Mike Goodwin- The Comedy Zone', *, start='2026-11-20T19:30:00',
                 end='2026-11-20T21:00:00', body='<p>A full native program description.</p>',
                 organization='PERFORMING ARTS CENTER', location=None, locator='2026-ACAMGW'):
    e = Event()
    e.add('UID', title + start)
    e.add('SUMMARY', title)
    e.add('DTSTART', datetime.fromisoformat(start).replace(tzinfo=ZoneInfo(st.ZONE)))
    e.add('DTEND', datetime.fromisoformat(end).replace(tzinfo=ZoneInfo(st.ZONE)))
    e.add('DESCRIPTION', body)
    e.add('LOCATION', location or sorted(st.MAIN_ROOMS)[0])
    for key, value in {'Event Type': 'Performance', 'Organization': organization,
                       'Event Locator': locator}.items():
        e.add('X-TRUMBA-CUSTOMFIELD', vText(value), parameters={'NAME': key})
    return e


def native_feed(*events):
    c = Calendar()
    c.add('VERSION', '2.0')
    c.add('PRODID', '-//Test//Stockton native//EN')
    for event in events:
        c.add_component(event)
    return c.to_ical().decode()


class StocktonCalendarTest(unittest.TestCase):
    @patch.object(st, 'record', side_effect=preview)
    def test_full_native_description_survives_beyond_two_thousand(self, _):
        prose = 'A complete paragraph about the performance. ' * 80 + 'Final admission instructions.'
        raw = '<h2 id="LiteralEventName">Copied title</h2><div id="ctl00_cphMainContent_divborderwrap">Copied first-show clock</div><p>' + prose + '</p>'
        row = st._pac(pac_card(), native_feed(native_event(body=raw)), NOW)[0]
        self.assertGreater(len(row['description']), 2000)
        self.assertIn(prose, row['description'])
        self.assertTrue(row['description'].endswith('Final admission instructions.'))
        self.assertNotIn('Copied first-show clock', row['description'])
        self.assertNotIn('Copied title', row['description'])
        self.assertEqual(row['venue_address'], st.MAIN_STREET)

    @patch.object(st, 'record', side_effect=preview)
    def test_normalized_literals_and_complete_final_suffix_survive_merge(self, _):
        card_text = 'Read <card-only condition> and keep the final condition.'
        native_text = ('Read <native-only condition> and keep the final condition.\n'
                       + 'A complete publisher paragraph. ' * 80
                       + 'Final instruction: retain <literal text> exactly.')
        card_html = '<p>' + card_text.replace('<', '&lt;').replace('>', '&gt;') + '</p>'
        native_html = '<p>' + native_text.replace('<', '&lt;').replace('>', '&gt;') + '</p>'
        row = st._pac(pac_card(body=card_html),
                      native_feed(native_event(body=native_html)), NOW)[0]
        self.assertEqual(row['description'], card_text + '\n' + native_text)
        self.assertGreater(len(row['description']), 2000)
        self.assertTrue(row['description'].endswith('Final instruction: retain <literal text> exactly.'))

    def test_native_oversize_is_rejected_without_clipping(self):
        with self.assertRaisesRegex(ValueError, 'publisher_description_limit'):
            st._native_performances(native_feed(native_event(body='<p>' + 'x' * 12001 + '</p>')))

    def test_explicit_multi_performance_dates_and_shared_year_context(self):
        starts = st._pac_starts('Thu-Sat, November 12-14, 2026 @ 7:30pm & Sun November 15, 2026 @ 2:00pm', {})
        self.assertEqual([v.isoformat() for v in starts], [
            '2026-11-12T19:30:00-05:00', '2026-11-13T19:30:00-05:00',
            '2026-11-14T19:30:00-05:00', '2026-11-15T14:00:00-05:00'])
        starts = st._pac_starts('Fri, December 11 @ 7:00pm | Sat, December 12 @ 11:00am and 3:00pm', {'december': {2026}})
        self.assertEqual([v.hour for v in starts], [19, 11, 15])
        self.assertEqual(starts[-1].date().isoformat(), '2026-12-12')
        self.assertEqual(len(st._pac_starts('Thu-Sat, April 29-May 1, 2027 @ 7:30pm', {})), 3)

    def test_year_is_never_guessed_from_system_clock(self):
        for years in ({}, {'december': {2026, 2027}}):
            with self.assertRaisesRegex(ValueError, 'stockton_event_year_unresolved'):
                st._pac_starts('December 12 @ 3pm', years)
        with self.assertRaisesRegex(ValueError, 'stockton_event_time_changed'):
            st._pac_starts('December 12, 2026 @ 3', {})

    @patch.object(st, 'record', side_effect=preview)
    def test_calendar_conflicting_time_only_hydrates_narrative(self, _):
        html = pac_card('The Nutcracker', subtitle='Atlantic City Ballet',
                        day='Saturday, December 12, 2026 @ 11:00am and 3:00pm', identity='1830')
        title = 'The Nutcracker by Atlantic City Ballet Public Performance'
        feed = native_feed(native_event(title, start='2026-12-12T11:00:00', end='2026-12-12T13:00:00'),
                           native_event(title, start='2026-12-12T14:00:00', end='2026-12-12T16:00:00'))
        rows = st._pac(html, feed, NOW)
        self.assertEqual([row['starts_at'] for row in rows], ['2026-12-12T11:00:00-05:00', '2026-12-12T15:00:00-05:00'])
        self.assertEqual(rows[0]['ends_at'], '2026-12-12T13:00:00-05:00')
        self.assertIsNone(rows[1]['ends_at'])
        self.assertEqual(rows[0]['description'], rows[1]['description'])
        self.assertNotEqual(rows[0]['id'], rows[1]['id'])

    @patch.object(st, 'record', side_effect=preview)
    def test_homeschool_program_keeps_published_audience_restriction(self, _):
        html = pac_card('The Nutcracker', subtitle='Student Matinee',
                        day='Friday, December 11, 2026 @ 10:30am', identity='1848')
        eligibility = 'Student Matinee for School Groups and Home-Schooled Children Only (GRADES 2-8).'
        native = native_event('The Nutcracker Educational Performance by Atlantic City Ballet',
                              start='2026-12-11T10:30:00', end='2026-12-11T12:30:00',
                              body='<p>' + eligibility + '</p><p>Celebrate the performance.</p>')
        row = st._pac(html, native_feed(native), NOW)[0]
        self.assertIn(eligibility, row['description'])
        self.assertIn('Student Matinee', row['title'])

    @patch.object(st, 'record', side_effect=preview)
    def test_school_only_and_sold_out_programs_are_held(self, _):
        html = pac_card('A More Perfect Union', subtitle='Student Matinee',
                        day='Tuesday, November 17, 2026 @ 10:30am', identity='1847')
        for body in ('For school groups only. A history performance.',
                     'For School Groups and Home-Schooled Children Only. This performance is sold out.'):
            feed = native_feed(native_event('A More Perfect Union by Pushcart Players',
                               start='2026-11-17T10:30:00', end='2026-11-17T12:00:00', body=body))
            self.assertEqual(st._pac(html, feed, NOW), [])

    def test_duplicate_categories_must_have_equal_complete_bodies(self):
        event = native_event()
        self.assertEqual(len(st._native_performances(native_feed(event, event))), 1)
        with self.assertRaisesRegex(ValueError, 'stockton_calendar_duplicate_conflict'):
            st._native_performances(native_feed(event, native_event(body='A conflicting version.')))

    def test_native_200_row_cap_and_unlisted_student_events(self):
        event = native_event()
        with self.assertRaisesRegex(ValueError, 'stockton_calendar_result_limit'):
            st._native_performances(native_feed(*([event] * 200)))
        self.assertEqual(st._native_performances(native_feed(native_event(
            organization='Stockton Theatre Club', body=''))), [])
        row = st._native_performances(native_feed(native_event(
            organization='PERFORMING ARTS CENTER, ARTS &amp; HUMANITIES, SCHOOL OF')))[0]
        self.assertTrue(row['description'])

    @patch.object(st, 'record', side_effect=preview)
    def test_missing_native_program_uses_complete_reviewed_card(self, _):
        html = pac_card('The Figuring', subtitle='Stockton Theatre Project',
                        day='Thu-Sat, November 12-14, 2026 @ 7:30pm & Sun November 15, 2026 @ 2:00pm',
                        identity='1853', body='<p>The entire publisher narrative.</p>')
        rows = st._pac(html, native_feed(), NOW)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row['venue_name'] == st.EXPERIMENTAL_VENUE for row in rows))
        self.assertTrue(all(row['description'] == 'The entire publisher narrative.' for row in rows))
        self.assertTrue(all(row['ends_at'] is None for row in rows))
        self.assertTrue(all((row['lat'], row['lng']) == st.PAC_BUILDING_POINT for row in rows))

    @patch.object(st, 'record', side_effect=preview)
    def test_campus_street_does_not_claim_an_unverified_room_or_building_pin(self, _):
        html = pac_card('A Charlie Brown Christmas', subtitle='Ed Vezinho & The Jim Ward Big Band',
                        day='Monday, December 14, 2026 @ 7:30pm', identity='1859')
        row = st._pac(html, native_feed(), NOW)[0]
        self.assertEqual(row['venue_name'], st.GALLOWAY_CAMPUS)
        self.assertEqual(row['venue_address'], st.MAIN_STREET)
        self.assertEqual((row['lat'], row['lng']), (39.491192, -74.534683))
        self.assertNotEqual((row['lat'], row['lng']), st.PAC_BUILDING_POINT)
        self.assertNotIn((st.HRC, st.GALLOWAY_CAMPUS, st.MAIN_STREET), st.REVIEWED_VENUE_POINTS)
        self.assertNotIn((st.PAC, st.GALLOWAY_CAMPUS, st.AC_STREET), st.REVIEWED_VENUE_POINTS)

    @patch.object(st, 'record', side_effect=preview)
    def test_department_full_prose_exact_clock_and_room(self, _):
        prose = 'A complete public lecture paragraph. ' * 80 + 'Free & open to the public. RSVP required.'
        html = department_card(body='<p>' + prose + '</p>')
        row = st._department(st.HRC, html, NOW)[0]
        self.assertEqual(row['description'], prose)
        self.assertGreater(len(row['description']), 2000)
        self.assertEqual(row['starts_at'], '2026-11-19T14:30:00-05:00')
        self.assertEqual(row['ends_at'], '2026-11-19T16:00:00-05:00')
        self.assertIn('L-112 Lecture Hall', row['venue_name'])
        self.assertEqual(row['venue_address'], st.MAIN_STREET)

    @patch.object(st, 'record', side_effect=preview)
    def test_monthly_subtitle_does_not_generate_unpublished_occurrences(self, _):
        html = department_card('Players and Playwrights', day='11/21/2026', clock='1 - 4 p.m.',
                                subtitle='Monthly Program - Every third Saturday of the month',
                                body='<p>Interested players are invited to attend a meeting once before joining.</p>',
                                location='Stockton Atlantic City Campus')
        rows = st._department(st.SCOSA, html, NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['venue_address'], st.AC_STREET)
        self.assertEqual((rows[0]['lat'], rows[0]['lng']), (39.3497122, -74.4546789))
        self.assertIn('third Saturday', rows[0]['description'])

    @patch.object(st, 'record', side_effect=preview)
    def test_department_blanks_virtual_unknown_venue_and_pac_duplicates_held(self, _):
        self.assertEqual(st._department(st.HRC, department_card(body='', subtitle='Public program'), NOW), [])
        self.assertEqual(st._department(st.HRC, department_card(location='Online via Zoom'), NOW), [])
        self.assertEqual(st._department(st.HRC, department_card(location='Unspecified room'), NOW), [])
        self.assertEqual(st._department(st.SCOSA, department_card(location='Stockton PAC'), NOW), [])

    @patch.object(st, 'record', side_effect=preview)
    def test_collection_fetches_only_allowed_pages_and_bounded_export(self, _):
        fetch = Mock(side_effect=[pac_card(), native_feed(native_event())])
        source = {'source_key': st.PAC, 'feed_url': st.SOURCES[st.PAC][0],
                  'kind': 'html', 'platform_adapter': 'html', 'timezone': st.ZONE}
        self.assertEqual(len(st.collect(source, fetch, now=NOW)), 1)
        urls = [call.args[0] for call in fetch.call_args_list]
        self.assertEqual([urlsplit(url).hostname for url in urls], ['stockton.edu', '25livepub.collegenet.com'])
        query = parse_qs(urlsplit(urls[1]).query)
        self.assertEqual(query['startdate'], ['20261114'])
        self.assertEqual(query['enddate'], ['20270114'])
        self.assertEqual(query['customnotes'], ['0'])
        self.assertEqual(query['search'], ['PERFORMING ARTS CENTER'])

    def test_source_and_event_links_are_strictly_bound(self):
        self.assertTrue(st.event_url(st.PAC, 'https://stockton.universitytickets.com/w/event.aspx?id=1815'))
        for url in ('https://other.example/w/event.aspx?id=1815',
                    'https://stockton.universitytickets.com/w/event.aspx?id=1815&next=evil',
                    'https://stockton.universitytickets.com/w/event.aspx?id=1815#x',
                    'https://stockton.universitytickets.com:444/w/event.aspx?id=1815'):
            self.assertFalse(st.event_url(st.PAC, url))
        source = {'source_key': st.HRC, 'feed_url': 'https://other.example/calendar',
                  'kind': 'html', 'platform_adapter': 'html', 'timezone': st.ZONE}
        fetch = Mock()
        with self.assertRaisesRegex(ValueError, 'unregistered_atlantic_city_stockton_source'):
            st.collect(source, fetch, now=NOW)
        fetch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
