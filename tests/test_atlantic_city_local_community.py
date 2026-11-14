"""Full narratives and complete native snapshots at the new community seam."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import unittest
from unittest.mock import patch

from roomquest import atlantic_city_local_community as local
from roomquest import preview_worker as worker

NOW = datetime(2026, 11, 14, 23, tzinfo=timezone.utc)
IDENTITY = '6ad7635e2b40e729fed305cb'


def payload(body='<p>Complete publisher program narrative and final condition.</p>'):
    return {'events': {'items': [IDENTITY], 'pagination': {'count': 1, 'pages': 1, 'page': 1, 'limit': 100}},
        'entities': {'events': {IDENTITY: {'id': IDENTITY,
            'indexStart': '2026-11-16T15:00:00Z', 'indexEnd': '2026-11-16T16:00:00Z',
            'isFull': False, 'registrationClosed': False,
            'definition': {'title': 'Story Time Yoga', 'start': '2026-11-16T10:00',
                'end': '2026-11-16T11:00', 'description': body, 'branchLocationId': 'MAIN',
                'nonBranchLocationId': None, 'locationDetails': "Room: Children's Activity Room",
                'registrationInfo': {}, 'typeIds': [], 'isCancelled': False}}},
            'locations': {'MAIN': {'name': local.LIBRARY_VENUE[0], 'isHidden': False,
                'address': dict(number='1735', street='Simpson Ave', city='Ocean City',
                                state='New Jersey', zip='08226', country='US'),
                'mapLocation': {'timeZone': local.ZONE, 'centrePoint':
                    dict(lat=local.LIBRARY_POINT[0], lng=local.LIBRARY_POINT[1])},
                'specialHoursIds': []}}, 'specialHours': {}, 'eventTypes': {}, 'images': {}}}


def source(key):
    url, kind, adapter = local.SOURCES[key]
    return dict(source_key=key, feed_url=url, kind=kind, platform_adapter=adapter, timezone=local.ZONE)


class LocalCommunityTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(worker, '_future_datetime', lambda dt: dt.astimezone(timezone.utc))
        p.start(); self.addCleanup(p.stop)

    def library(self, data):
        return local.collect(source(local.LIBRARY), lambda u,a: json.dumps(data), now=NOW)

    def test_full_html_and_registration_instructions_survive(self):
        text = 'Complete native participation detail. ' * 100 + 'Final native sentence.'
        data = payload('<p>' + text + '</p>')
        data['entities']['events'][IDENTITY]['definition']['registrationInfo']['instructions'] = '<p>Register by calling the library.</p>'
        row, = self.library(data)
        self.assertEqual(row['description'], text + '\n\nRegister by calling the library.')
        self.assertGreater(len(row['description']), 2000)
        self.assertEqual(row['venue_address'], local.LIBRARY_VENUE[1])
        self.assertEqual((row['lat'], row['lng']), local.LIBRARY_POINT)
        self.assertEqual(row['starts_at'], '2026-11-16T15:00:00+00:00')

    def test_blank_and_unreviewed_poster_only_text_are_held(self):
        for body in ('', '<figure><img src="poster.jpg"></figure>'):
            self.assertEqual(self.library(payload(body)), [])
        for identity, body in [('695ff9e1c967cb412080c6d5', '2026 Movie Monday\nDecember 12/28 – The Holiday'),
                               ('695ff9e1c967cb412080c6d6', '2026 Movie Monday')]:
            data = payload(body)
            item = data['entities']['events'].pop(IDENTITY); item['id'] = identity
            data['entities']['events'][identity] = item; data['events']['items'] = [identity]
            self.assertEqual(self.library(data), [])
        self.assertEqual(self.library(payload('<p>Bring a mat.</p>'))[0]['description'], 'Bring a mat.')

    def test_full_closed_virtual_or_unreviewed_locations_are_held(self):
        for field, value, definition in [('isFull', True, False), ('registrationClosed', True, False),
            ('isVirtual', True, True), ('isCancelled', True, True), ('branchLocationId', 'OTHER', True)]:
            data = payload(); item = data['entities']['events'][IDENTITY]
            (item['definition'] if definition else item)[field] = value
            self.assertEqual(self.library(data), [])

    def test_branch_change_and_clock_mismatch_fail(self):
        data = payload(); data['entities']['locations']['MAIN']['address']['number'] = '1736'
        with self.assertRaisesRegex(ValueError, 'venue_changed'): self.library(data)
        data = payload(); data['entities']['events'][IDENTITY]['definition']['start'] = '2026-11-16T11:00'
        with self.assertRaisesRegex(ValueError, 'clock_mismatch'): self.library(data)

    def test_official_closure_and_early_close_exclude_conflicting_events(self):
        for close in (None, 'T10:30'):
            data = payload(); data['entities']['locations']['MAIN']['specialHoursIds'] = ['holiday']
            data['entities']['specialHours']['holiday'] = dict(startDate='2026-11-16', endDate='2026-11-16', openTime=None, closeTime=close)
            self.assertEqual(self.library(data), [])

    def test_incomplete_manifest_never_returns_a_partial_snapshot(self):
        data = payload(); data['events']['pagination']['count'] = 2
        with self.assertRaisesRegex(ValueError, 'manifest_incomplete'): self.library(data)
        data = payload(); data['events']['pagination']['count'] = 201; data['events']['pagination']['pages'] = 3
        with self.assertRaisesRegex(ValueError, 'manifest_incomplete'): self.library(data)

    def test_duplicate_identity_is_not_silently_deduplicated(self):
        data = payload(); data['events']['pagination']['count'] = 2; data['events']['items'].append(IDENTITY)
        with self.assertRaisesRegex(ValueError, 'duplicate_identity'): self.library(data)

    def test_complete_two_page_manifest_is_checked_before_return(self):
        one = payload(); item = one['entities']['events'][IDENTITY]
        ids = [format(n+1, '024x') for n in range(101)]
        two = deepcopy(one)
        for page, data, subset in [(1, one, ids[:100]), (2, two, ids[100:])]:
            data['events'] = dict(items=subset, pagination=dict(count=101,pages=2,page=page,limit=100))
            data['entities']['events'] = {id: dict(deepcopy(item), id=id) for id in subset}
        calls = []
        def fetch(url, accept):
            calls.append(url); return json.dumps(one if url.endswith('page=1') else two)
        self.assertEqual(len(local.collect_library(fetch, now=NOW)), 101)
        self.assertEqual(len(calls), 2)
        two['events']['pagination']['count'] = 102
        with self.assertRaisesRegex(ValueError, 'manifest_changed'): local.collect_library(fetch, now=NOW)

    def test_oversized_native_description_is_not_truncated(self):
        with self.assertRaisesRegex(ValueError, 'description_limit'): self.library(payload('x'*12001))

    def test_source_identity_and_event_url_are_exact(self):
        bad = source(local.LIBRARY); bad['feed_url'] += '?other=1'
        with self.assertRaisesRegex(ValueError, 'unregistered'): local.collect(bad, None)
        self.assertTrue(local.event_url(local.LIBRARY, local.SOURCES[local.LIBRARY][0]+'/'+IDENTITY))
        self.assertFalse(local.event_url(local.LIBRARY, local.SOURCES[local.LIBRARY][0]+'/'+IDENTITY+'?redirect=x'))
        self.assertFalse(local.event_url(local.NEWDAY, local.NEWDAY_DOCUMENT))

    def test_newday_changed_edition_fails_and_missing_calendar_fails(self):
        with self.assertRaisesRegex(ValueError, 'edition_unreviewed'): local.parse_newday(b'changed', now=NOW)
        with self.assertRaisesRegex(ValueError, 'edition_unreviewed'): local.discover_newday('<p>No calendar.</p>')

    def test_reviewed_pdf_keeps_every_paragraph_and_unknown_end(self):
        blob = b'reviewed test PDF'
        paragraphs = [first+' Full published narrative. '*70+last for *_,first,last in local.NEWDAY_PROGRAMS]
        pages = ['18 Martin Luther King Jr. Ave Pleasantville NJ 08232',
            'November 2026 **Please register on Eventbrite for All Events!!** '+' '.join(paragraphs)]
        with patch.object(local, 'NEWDAY_SHA256', sha256(blob).hexdigest()), patch.object(local, '_pages', return_value=pages):
            rows = local.parse_newday(blob, now=NOW)
        self.assertEqual(len(rows),4)
        for row, paragraph in zip(rows, paragraphs):
            self.assertEqual(row['description'],paragraph+'\n\nFree and Open to All of Atlantic County\n**Please register on Eventbrite for All Events!!**')
            self.assertEqual(row['venue_address'],local.NEWDAY_VENUE[1])
        self.assertIsNone(rows[1]['ends_at'])
        self.assertEqual(rows[1]['starts_at'],'2026-11-19T22:00:00+00:00')


if __name__ == '__main__': unittest.main()
