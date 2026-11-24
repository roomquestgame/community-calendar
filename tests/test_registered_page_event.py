"""Regression coverage for exact-page event identity and published sessions.

Fixtures are reduced to the factual shapes observed Nov 24, 2026 on the two
London publishers. No publisher host is special-cased by the extractor.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import patch

from roomquest import registered_html_calendar as calendar
from roomquest import preview_worker
from roomquest.registration_formats import source_key
from roomquest.registered_native_content import validate_record

FEED = 'https://venue.example.org/events/'
URL = 'https://venue.example.org/event/open-studio/'


class ReplayMeta(type):
    def __instancecheck__(cls, value):
        return isinstance(value, datetime)


class ReplayClock(datetime, metaclass=ReplayMeta):
    @classmethod
    def now(cls, tz=None):
        at = datetime(2026, 11, 24, 17, 20, tzinfo=timezone.utc)
        return at.astimezone(tz) if tz else at.replace(tzinfo=None)


def source():
    return {'source_key': source_key(FEED), 'feed_url': FEED, 'kind': 'html',
            'platform_adapter': 'html', 'registered_html_calendar_version': 1,
            'registered_native_content_version': 1}


def event(**extra):
    return dict({'@context': 'https://schema.org', '@type': 'Event',
                 'name': 'Open Studio & Stories', 'startDate': '2026-11-25UTC11:00:00',
                 'description': 'A publisher-described activity.',
                 'location': {'@type': 'Place', 'name': 'Community Hall',
                              'address': {'@type': 'PostalAddress',
                                          'streetAddress': '2 Main Street',
                                          'addressLocality': 'London',
                                          'postalCode': 'E14 6TL',
                                          'addressCountry': 'GB'}}}, **extra)


def session(day, clock='11:00 am', venue='Community Hall'):
    return ('<div class="event-time"><div class="date">' + day
            + '</div><div class="time">' + clock + '</div><div class="location">'
            + venue + '</div></div>')


def sessions(*rows):
    return '<div class="event-time-container">' + ''.join(rows) + '</div>'


def detail(item, body='', *, canonical=URL, og=URL,
           heading='Open Studio &amp; Stories', raw=None, newsletter=False):
    if raw is None:
        raw = json.dumps(item)
    return ('<html><head>'
            + ('<link rel="canonical" href="' + canonical + '">' if canonical else '')
            + ('<meta property="og:url" content="' + og + '">' if og else '')
            + '<script type="application/ld+json">' + raw + '</script></head>'
            + '<body><main><div><h1>' + heading + '</h1>' + body
            + '</div></main>' + ('<footer><h1>Newsletter</h1></footer>' if newsletter else '')
            + '</body></html>')


class PageBoundEventTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch.object(preview_worker, 'datetime', ReplayClock)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def rows(self, html):
        rows = calendar._detail(source(), html, URL)
        for row in rows:
            validate_record(row, source())
        return rows

    def test_publisher_sessions_exact_year_rollover(self):
        item = event(name='Open Studio &#038; Stories')
        body = sessions(session('Wed 25 Nov', venue='Room 1- Community Hall'),
                        session('Wed 2 Dec', venue='Room 1- Community Hall'),
                        session('Wed 6 Jan', venue='Room 1- Community Hall'),
                        session('Wed 27 Jan', venue='Room 1- Community Hall'))
        rows = self.rows(detail(item, body))
        self.assertEqual([row['starts_at'] for row in rows],
                         ['2026-11-25T11:00:00+00:00', '2026-12-02T11:00:00+00:00',
                          '2027-01-06T11:00:00+00:00'])
        self.assertEqual({row['id'] for row in rows}, {URL + '#event'})
        self.assertTrue(all(row['ends_at'] is None for row in rows))
        self.assertTrue(all(row['event_url'] == URL for row in rows))

    def test_og_url_and_title_local_full_range(self):
        item = event(startDate='2026-11-29 15:00:00', endDate='2026-11-29 16:30:00')
        [row] = self.rows(detail(item, '<p>29th November 2026 · 3:00pm - 4:30pm</p>',
                                 canonical=None, newsletter=True))
        self.assertEqual(row['starts_at'], '2026-11-29T15:00:00+00:00')
        self.assertEqual(row['ends_at'], '2026-11-29T16:30:00+00:00')

    def test_ordinary_offset_without_identity(self):
        [row] = self.rows(detail(event(startDate='2026-11-29T15:00:00+00:00')))
        self.assertEqual(row['id'], URL + '#event')

    def test_existing_explicit_identity_preserved(self):
        item = event(url=URL, **{'@id': '#publisher-original'},
                     startDate='2026-11-29T15:00:00+00:00')
        [row] = self.rows(detail(item))
        self.assertEqual(row['id'], URL + '#publisher-original')

    def test_wrong_or_ambiguous_identity_never_rebound(self):
        for item, kwargs in [
            (event(url='https://venue.example.org/event/other/'), {}),
            (event(**{'@id': 'https://other.example.org/event/other/'}), {}),
            (event(), {'canonical': None, 'og': None}),
            (event(), {'canonical': URL, 'og': 'https://venue.example.org/event/other/'}),
            (event(), {'canonical': 'https://other.example.org/event/other/'}),
            (event(), {'heading': 'Different event'}),
            ([event(), event(name='Sidebar event')], {}),
        ]:
            with self.subTest(item=item, kwargs=kwargs):
                with self.assertRaisesRegex(ValueError, 'html_calendar_detail_identity_conflict'):
                    self.rows(detail(item, sessions(session('Wed 25 Nov')), **kwargs))

    def test_bad_session_facts_hold(self):
        good = session('Wed 25 Nov')
        for body in [
            sessions(session('Wed 25 Nov', '12:00 pm')),
            sessions(session('Tue 25 Nov')),
            sessions(good, good),
            sessions(good, session('Wed 2 Dec', venue='Different venue')),
            sessions(good, session('Wed 2 Dec', clock='Times vary')),
        ]:
            with self.subTest(body=body):
                with self.assertRaisesRegex(ValueError, 'html_calendar_(?:clock|venue)_conflict'):
                    self.rows(detail(event(), body))

    def test_corroborated_audience_session_labels_keep_structured_venue(self):
        item = event(startDate='2026-11-28UTC12:00:00')
        blocks = sessions(session('Sat 28 Nov', '12:00 pm', 'Family session'),
                          session('Sat 28 Nov', '1:30 pm', 'Adult session'))
        rows = self.rows(detail(item, '<p>We offer family sessions and adult sessions.</p>' + blocks))
        self.assertEqual([r['title'] for r in rows],
                         ['Open Studio & Stories — Family session',
                          'Open Studio & Stories — Adult session'])
        self.assertTrue(all(r['venue_name'] == 'Community Hall' for r in rows))
        self.assertTrue(all(r['ends_at'] is None for r in rows))
        with self.assertRaisesRegex(ValueError, 'html_calendar_venue_conflict'):
            self.rows(detail(item, blocks))
        with self.assertRaisesRegex(ValueError, 'html_calendar_venue_conflict'):
            self.rows(detail(item, '<p>We offer family sessions.</p>' + blocks))

    def test_naive_clock_must_be_independently_verified(self):
        item = event(startDate='2026-11-29 15:00:00', endDate='2026-11-29 16:30:00')
        for body in ('', '<p>29th November 2026 · 3:00pm - 5:30pm</p>',
                     '<p>29th November 2026 · 3:00pm - 4:30pm</p>' * 2):
            with self.subTest(body=body):
                with self.assertRaisesRegex(ValueError, 'html_calendar_clock_conflict'):
                    self.rows(detail(item, body))
        foreign = deepcopy(item)
        foreign['location']['address']['addressCountry'] = 'US'
        with self.assertRaisesRegex(ValueError, 'html_calendar_clock_conflict'):
            self.rows(detail(foreign, '<p>29th November 2026 · 3:00pm - 4:30pm</p>'))

    def test_summer_utc_label_cannot_be_reinterpreted_as_local(self):
        item = event(startDate='2027-07-07UTC11:00:00')
        with self.assertRaisesRegex(ValueError, 'html_calendar_clock_conflict'):
            self.rows(detail(item, sessions(session('Wed 7 Jul'))))

    def test_literal_description_newline_recovered_only_in_narrative(self):
        item = event(startDate='2026-11-29T15:00:00+00:00', description='First\nSecond')
        raw = json.dumps(item).replace(r'First\nSecond', 'First\nSecond')
        [row] = self.rows(detail(item, raw=raw))
        self.assertIn('First', row['description'])
        self.assertIn('Second', row['description'])
        broken = json.dumps(item).replace('Open Studio & Stories', 'Open Studio\n& Stories')
        with self.assertRaises(ValueError):
            self.rows(detail(item, raw=broken))

    def test_filter_links_not_event_pages(self):
        actual = 'https://venue.example.org/events/platform/real-event/'
        nav = 'https://venue.example.org/events/platform/category/'
        soup = calendar._html('<html><main><h1>Events</h1><article><a href="' + actual
                              + '">Real event</a></article><div class="filters"><a href="'
                              + nav + '">Category</a></div></main></html>')
        self.assertEqual(calendar._links(FEED, soup), [actual])


if __name__ == '__main__':
    unittest.main()
