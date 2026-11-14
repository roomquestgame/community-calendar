"""Contract checks for venue schedule ambiguities and bounded pagination."""
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from roomquest import gulf_venues as venues

NOW = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)


class FrozenMeta(type):
    def __instancecheck__(cls, value):
        return isinstance(value, datetime)


class FrozenDateTime(datetime, metaclass=FrozenMeta):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


def source(key):
    return {'source_key': key, 'feed_url': venues.SOURCES[key], 'kind': 'html',
            'platform_adapter': 'html', 'timezone': venues.ZONE}


def show(identity, title='Benefit concert', clock='8:00 pm'):
    return f'''<div class="tw-section"><div class="tw-name"><a
      href="https://tipitinas.com/event/{identity}/benefit-concert">{title}</a></div>
      <span class="tw-event-date">Nov 20, 2026</span>
      <span class="tw-event-door-time">7:00 pm</span>
      <span class="tw-event-time">{clock}</span>
      <div class="tw-age-restriction">Ages 18 and Up</div></div>'''


def tip_page(cards):
    return '<a href="https://tipitinas.com/location/">501 Napoleon Ave, New Orleans, LA 70115</a>' + \
           '<div class="tw-plugin-upcoming-event-list">' + cards + '</div>'


def museum_card(identity, day='11/20/2026', title='Museum storytime', description='For children and families.'):
    return f'''<article id="node-{identity}" about="/events-programs/events/storytime-{identity}">
      <h3 class="f--title"><a href="/events-programs/events/storytime-{identity}">{title}</a></h3>
      <div class="f--date">{day} | 10:00 AM - 10:20 AM</div>
      <div class="f--desc">{description}</div>
      <div class="field--name-field-program-type">Kids &amp; Families</div></article>'''


def museum_page(cards, *, location='1', next_page=None):
    nav = f'<a rel="next" href="?field_offsite_value=1&amp;page={next_page}">Next</a>' if next_page else ''
    return f'''<link rel="canonical" href="{venues.SOURCES[venues.WWII]}">
      <p>945 Magazine Street, New Orleans, LA 70130</p><div class="views-events-calendar">
      <input name="field_offsite_value" checked value="{location}">{cards}{nav}</div>'''


class GulfVenuesTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch('roomquest.preview_worker.datetime', FrozenDateTime)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_show_time_and_same_title_occurrences_are_preserved(self):
        page = tip_page(show('12345678') + show('12345679', clock='10:00 pm'))
        rows = venues.collect(source(venues.TIPITINAS), lambda *_: page)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['starts_at'], '2026-11-21T02:00:00+00:00')
        self.assertIsNone(rows[0]['ends_at'])
        self.assertIsNone(rows[0]['lat'])
        self.assertEqual(rows[0]['publisher_details'], {'audience': 'Ages 18 and Up'})
        self.assertIn('Doors: 7:00 pm', rows[0]['description'])

    def test_disagreeing_mobile_and_desktop_schedules_fail(self):
        card = show('12345678').replace('</div></div>', '</div><span class="tw-event-time">9:00 pm</span></div>')
        with self.assertRaisesRegex(ValueError, 'schedule_conflict'):
            venues.collect(source(venues.TIPITINAS), lambda *_: tip_page(card))

    def test_ticket_bundle_does_not_duplicate_show_or_poison_calendar(self):
        bundle = show('12345679').replace('</div></div>',
            '</div><div class="tw-prefix-text">**Two Night Pass**</div>'
            '<span class="tw-event-date">Nov 21, 2026</span></div>')
        rows = venues.collect(source(venues.TIPITINAS), lambda *_: tip_page(show('12345678') + bundle))
        self.assertEqual([r['id'] for r in rows], ['12345678'])

    def test_museum_pagination_excludes_virtual_and_follows_horizon(self):
        pages = {
            venues.SOURCES[venues.WWII] + '?field_offsite_value=1': museum_page(
                museum_card('100') + museum_card('101', title='Online lecture'), next_page=1),
            venues.SOURCES[venues.WWII] + '?field_offsite_value=1&page=1': museum_page(
                museum_card('102', day='01/20/2027'), next_page=2),
        }
        rows = venues.collect(source(venues.WWII), lambda url, _: pages[url], now=NOW)
        self.assertEqual([r['id'] for r in rows], ['node-100'])
        self.assertEqual(rows[0]['ends_at'], '2026-11-20T16:20:00+00:00')

    def test_unapplied_location_filter_and_unbounded_pagination_fail(self):
        with self.assertRaisesRegex(ValueError, 'location_filter_unverified'):
            venues.collect(source(venues.WWII), lambda *_: museum_page(museum_card('100'), location='All'), now=NOW)
        with self.assertRaisesRegex(ValueError, 'pagination_unverified'):
            venues.collect(source(venues.WWII), lambda *_: museum_page(museum_card('100'), next_page=9), now=NOW)

    def test_source_and_event_photo_ownership_are_narrow(self):
        invalid = {**source(venues.TIPITINAS), 'feed_url': 'https://tipitinas.com/'}
        with self.assertRaisesRegex(ValueError, 'source_unverified'):
            venues.collect(invalid, lambda *_: self.fail('unreviewed source fetched'))
        photo = 'https://i.ticketweb.com/i/00/13/59/84/83_Listings.jpg?v=10'
        self.assertEqual(venues.photo_url(venues.TIPITINAS, photo), photo)
        self.assertIsNone(venues.photo_url(venues.WWII, photo))
        self.assertFalse(venues.event_url(venues.TIPITINAS, 'https://tipitinas.com.evil.test/event/12345678/example'))


if __name__ == '__main__':
    unittest.main()
