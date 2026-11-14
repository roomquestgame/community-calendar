from copy import deepcopy
from datetime import datetime, timezone
from html import escape
import json
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from roomquest import boston_arts as b
from tests.test_new_york_arts import fake_record


NOW = datetime(2026, 11, 14, 22, tzinfo=timezone.utc)


def source(key):
    return dict(source_key=key, feed_url=b.SOURCES[key][0], kind='html', platform_adapter='html', timezone=b.ZONE)


def card(index=1, month=11):
    return (f'<article class="event-list" id="event-{index}"><h3 class="event-list__title">'
            f'<a href="/event/2026-{month:02}-18/book-club-{index}">Book club {index}</a></h3>'
            f'<div><span class="event-list__details--label">Date: </span>Wed, {month}/18/2026</div>'
            '<div class="event-list__body">Short excerpt...</div></article>')


def listing(index=1, month=11, next_page=None):
    return ('<div class="view-indiecommerce-event-list">' + card(index, month)
            + (f'<nav class="pager"><a rel="next" href="{next_page}">Next</a></nav>' if next_page else '') + '</div>')


def detail(index=1, body='Full event description.', key=b.BROOKLINE):
    url = 'https://' + b.ALLOWED_HOSTS[key][0] + f'/event/2026-11-18/book-club-{index}'
    native = {'@type': 'Event', 'url': url, 'name': f'Book club {index}', 'description': 'Truncated summary...',
              'startDate': '2026-11-18T19:00:00-05:00', 'endDate': '2026-11-18T20:00:00-05:00',
              'eventStatus': 'https://schema.org/EventScheduled',
              'location': {'address': {'streetAddress': 'WRONG', 'addressLocality': 'Boston338 Newbury Street'}}}
    return (f'<script type="application/ld+json">{json.dumps(native)}</script>'
            f'<h1 class="event-details__info--title">Book club {index}</h1>'
            '<div class="event-details__location--location"><address>Brookline Booksmith<br>279 Harvard Street<br>'
            'Coolidge Corner<br>Brookline, MA 02446-2908</address></div>'
            f'<div class="event-details__info--body"><p>{escape(body)}</p></div>'
            '<div>Unrelated retail product summary.</div>')


def bpl_payload(page=1, pages=3, day=18, identity=None, body='A full community program description.'):
    identity = identity or f'{page:024x}'
    definition = dict(title=f'Library program {page}', start=f'2026-11-{day:02}T10:00', end=f'2026-11-{day:02}T11:00',
                      description=body, branchLocationId='1', typeIds=['kids'])
    return json.dumps({'events': {'items': [identity], 'pagination': dict(page=page, pages=pages, count=pages, limit=100)},
                      'entities': {'events': {identity: {'definition': definition, 'indexStart': f'2026-11-{day:02}T15:00:00Z',
                                                        'indexEnd': f'2026-11-{day:02}T16:00:00Z'}},
                                   'locations': {'1': {'name': 'Chinatown', 'address': {'number': 'Boston Public Library',
                                       'street': '2 Boylston Street', 'city': 'Boston', 'state': 'Massachusetts', 'zip': '02116'},
                                       'mapLocation': {'centrePoint': {'lat': 42.352, 'lng': -71.062}}}},
                                   'eventTypes': {'kids': {'name': 'Story Time'}}}})


class BostonArtsTests(unittest.TestCase):
    def setUp(self):
        patches = [patch('roomquest.mapsee_adapter.record', side_effect=fake_record), patch.object(b, 'record', side_effect=fake_record)]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

    def test_native_detail_replaces_truncated_metadata_and_malformed_address(self):
        text = 'An original sentence. ' * 160 + 'Final attendance instruction.'
        queue, _ = b._book_listing(b.BROOKLINE, listing(), b.SOURCES[b.BROOKLINE][0], NOW)
        row = b._book_detail(b.BROOKLINE, queue[0], detail(body=text), NOW)
        self.assertEqual(row['description'], text)
        self.assertGreater(len(row['description']), 2000)
        self.assertEqual(row['venue_address'], '279 Harvard Street, Brookline, MA 02446-2908')
        self.assertNotIn('Truncated', row['description'])
        self.assertNotIn('retail', row['description'])

    def test_missing_or_overlimit_description_never_falls_back_to_excerpt(self):
        item = b._book_listing(b.BROOKLINE, listing(), b.SOURCES[b.BROOKLINE][0], NOW)[0][0]
        for body, error in (('', 'description_missing'), ('x' * 12001, 'description_limit')):
            with self.assertRaisesRegex(ValueError, error):
                b._book_detail(b.BROOKLINE, item, detail(body=body), NOW)

    def test_pao_uses_full_body_and_embedded_utc_dates_without_export_fetch(self):
        url = 'https://www.paoartscenter.org/events/2026/family-workshop'
        google = 'http://www.google.com/calendar/event?action=TEMPLATE&amp;dates=20261118T210000Z/20261118T230000Z'
        text = 'Native workshop paragraph. ' * 100 + 'Final accessibility detail.'
        item = dict(url=url, title='Family workshop', id='/events/2026/family-workshop', day='2026-11-18',
                    start='2026-11-18T21:00:00+00:00', end='2026-11-18T23:00:00+00:00')
        payload = (f'<link rel="canonical" href="{url}"><h1 class="eventitem-title">Family workshop</h1>'
                   f'<a class="eventitem-meta-export-google" href="{google}">Google Calendar</a>'
                   '<li class="eventitem-meta-address">Pao Arts Center 99 Albany Street Boston, MA 02111</li>'
                   f'<div class="sqs-layout" id="item-123"><p>{text}</p></div>'
                   '<footer>Do not capture navigation or footer.</footer>')
        row = b._pao_detail(item, payload, NOW)
        self.assertEqual(row['description'], text)
        self.assertEqual(row['venue_address'], '99 Albany Street, Boston, MA 02111')
        self.assertEqual(row['lat'], 42.3498258)
        wrong = payload.replace('20261118T230000Z', '20261119T230000Z')
        with self.assertRaisesRegex(ValueError, 'schedule_conflict'):
            b._pao_detail(item, wrong, NOW)

    def test_book_phases_account_for_all_pages_and_publish_only_complete(self):
        fetch = Mock(side_effect=[listing(1, next_page='?page=1'), listing(2), detail(1), detail(2)])
        first = b.collect_chunk(source(b.BROOKLINE), fetch, now=NOW)
        self.assertFalse(first['complete'])
        self.assertEqual(first['checkpoint']['cursor'], 0)
        second = b.collect_chunk(source(b.BROOKLINE), fetch, checkpoint=first['checkpoint'], now=NOW)
        self.assertFalse(second['complete'])
        self.assertEqual(second['checkpoint']['manifest_count'], 2)
        third = b.collect_chunk(source(b.BROOKLINE), fetch, checkpoint=second['checkpoint'], now=NOW, max_details=1)
        self.assertFalse(third['complete'])
        self.assertEqual(third['events'], [])
        final = b.collect_chunk(source(b.BROOKLINE), fetch, checkpoint=third['checkpoint'], now=NOW)
        self.assertTrue(final['complete'])
        self.assertEqual(len(final['events']), 2)
        used = fetch.call_count
        retry = b.collect_chunk(source(b.BROOKLINE), fetch, checkpoint=final['checkpoint'], now=NOW)
        self.assertEqual(retry['events'], final['events'])
        self.assertEqual(fetch.call_count, used)

    def test_checkpoint_tampering_and_external_links_are_rejected(self):
        part = b.collect_chunk(source(b.BROOKLINE), Mock(return_value=listing()), now=NOW)
        state = deepcopy(part['checkpoint'])
        state['queue'][0]['url'] = 'https://attacker.example/event/steal'
        state['manifest_hash'] = b._hash(state['queue'])
        with self.assertRaisesRegex(ValueError, 'checkpoint_invalid'):
            b.collect_chunk(source(b.BROOKLINE), Mock(), checkpoint=state, now=NOW)
        self.assertFalse(b.event_url(b.TRIDENT, 'https://tridentbookscafe.com/event/a?next=http://127.0.0.1'))

    def test_tribe_restores_complete_native_body_after_legacy_parser(self):
        body = 'Workshop details. ' * 250 + 'Bring a smock.'
        native = dict(id=42, title='Woodworking workshop', status='publish', description=body, timezone=b.ZONE,
                      start_date='2026-11-18 18:00:00', end_date='2026-11-18 20:00:00',
                      utc_start_date='2026-11-18 23:00:00', utc_end_date='2026-11-19 01:00:00',
                      url='https://millforge.org/event/workshop/', categories=[],
                      venue=dict(venue='Mill Forge Makerspace', address='61 Endicott St., Building 46', city='Norwood', state='MA', zip='02062'))
        fetch = Mock(return_value=json.dumps(dict(events=[native], total_pages=1)))
        row = b.collect(source(b.MILL), fetch, now=NOW)[0]
        self.assertEqual(row['description'], body)
        self.assertEqual(row['venue_address'], '61 Endicott St. Building 46, Norwood, MA 02062')

    def test_armory_preserves_full_ics_text_strips_only_known_tracking_and_no_end_guess(self):
        text = "Opening instructions.\\n$('#getTixButton').click(function() {\\nfbq('track', 'Purchase', {currency: \"USD\", value: 0.00});\\n});\\nFinal instructions."
        payload = ('BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:42@artsatthearmory.org\n'
                   'SUMMARY:Community open mic\nDTSTART;TZID=America/New_York:20261118T190000\n'
                   'DTEND;TZID=America/New_York:20261118T190000\nCATEGORIES:Cafe,Music\n'
                   'URL:https://artsatthearmory.org/events/open-mic/\nDESCRIPTION:' + text + '\nEND:VEVENT\nEND:VCALENDAR\n')
        row = b._armory(payload, NOW)[0]
        self.assertEqual(row['description'], 'Opening instructions.\nFinal instructions.')
        self.assertEqual(row['venue_address'], '191 Highland Avenue, Somerville, MA 02143')
        self.assertIsNone(row['ends_at'])

    def test_bpl_traverses_all_pages_and_retains_long_body_and_chinatown_street(self):
        long = 'A story and a song. ' * 130 + 'Final library instruction.'
        fetch = Mock(side_effect=[bpl_payload(1, body=long), bpl_payload(2, day=28), bpl_payload(3)])
        first = b.collect_chunk(source(b.BPL), fetch, now=NOW)
        self.assertFalse(first['complete'])
        self.assertEqual(first['checkpoint']['cursor'], 2)
        self.assertEqual(first['events'], [])
        b._bpl_checkpoint(first['checkpoint'], NOW)
        final = b.collect_chunk(source(b.BPL), fetch, checkpoint=first['checkpoint'], now=NOW)
        self.assertTrue(final['complete'])
        self.assertEqual(len(final['events']), 2)
        self.assertEqual(final['events'][0]['description'], long)
        self.assertEqual(final['events'][0]['venue_address'], '2 Boylston Street, Boston, MA 02116')
        self.assertTrue(all(row['lat'] == 42.352 for row in final['events']))
        self.assertEqual([parse_qs(urlsplit(c.args[0]).query)['page'][0] for c in fetch.call_args_list], ['1', '2', '3'])

    def test_bpl_changed_page_manifest_and_cross_source_checkpoint_fail(self):
        first = b.collect_chunk(source(b.BPL), Mock(side_effect=[bpl_payload(1), bpl_payload(2)]), now=NOW)
        with self.assertRaisesRegex(ValueError, 'manifest_changed'):
            b.collect_chunk(source(b.BPL), Mock(return_value=bpl_payload(3, pages=4)), checkpoint=first['checkpoint'], now=NOW)
        state = deepcopy(first['checkpoint'])
        state['source_key'] = b.PAO
        with self.assertRaisesRegex(ValueError, 'checkpoint_invalid'):
            b.collect_chunk(source(b.BPL), Mock(), checkpoint=state, now=NOW)


if __name__ == '__main__':
    unittest.main()
