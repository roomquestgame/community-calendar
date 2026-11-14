from copy import deepcopy
from datetime import datetime, timedelta, timezone
from html import escape
import json
import unittest
from unittest.mock import Mock, patch

from roomquest import atlantic_city_studio as ac


NOW = datetime(2026, 11, 14, 22, tzinfo=timezone.utc)


def source():
    return dict(source_key=ac.SOURCE_KEY, feed_url=ac.SOURCES[ac.SOURCE_KEY][0],
                kind='html', platform_adapter='html', timezone=ac.ZONE)


def preview_record(title, start, end, venue, address, city, url, identity, category='', **kw):
    return dict(id=identity, title=title, starts_at=start, ends_at=end, venue_name=venue,
                venue_address=address, venue_city=city, event_url=url, category=category,
                lat=kw.get('lat'), lng=kw.get('lng'))


def listing(*, mindful='Complete owner prose with &lt;literal wording&gt; and its final sentence.',
            omit=None, extra=''):
    service = {'@type': 'Service', 'provider': {'@type': 'YogaStudio', 'name': ac.VENUE[0],
               '@id': 'https://www.hummingbirdyoganj.com/#studio'},
               'areaServed': {'@type': 'City', 'name': 'Northfield, NJ'},
               'offers': [{'@type': 'Offer', 'name': 'Drop-in class', 'price': '20', 'priceCurrency': 'USD'}]}
    text = '<script type="application/ld+json">' + json.dumps(service) + '</script>'
    text += '<p>1637 New Rd, Suite 2, Northfield, NJ 08225</p>'
    for class_id, (title, _) in ac.CLASSES.items():
        if class_id == omit:
            continue
        body = mindful if class_id == ac.MINDFUL else 'Complete own-site class paragraph.'
        text += f'''<article><p class="when">Weekly publisher schedule</p><h3>{title}</h3>
        <p class="text-moss">{body}</p><a data-filter="{class_id}"
        href="/classes?class={class_id}">See class times</a></article>'''
    return text + extra


def detail_data(class_id=444005):
    title, slug = ac.CLASSES[class_id]
    location = dict(wBusinessId=ac.BUSINESS_ID, wLocationId=ac.LOCATION_ID,
                    title=ac.VENUE[0], streetAddress='1637 New Rd. Suite2', city='Northfield',
                    zipcode='08225', state='New Jersey', country='USA', timezone=ac.ZONE,
                    latitude=ac.LOCATION[0], longitude=ac.LOCATION[1],
                    urlSite='https://hummingbirdyoganj.com/')
    course = dict(wBusinessId=ac.BUSINESS_ID, wClassId=class_id, title=title, urlSlug=slug,
                  description='' if class_id == ac.MINDFUL else '<p>Complete native class body.</p>',
                  specialInstructions='', canShowSpecialInstructions=True,
                  isVirtual=False, onlineBookingEnabled=True, purchaseOptionsEnabled=True,
                  dropInEnabled=False, prerequisiteCourses=[], prerequisiteEvents=[],
                  periods=[{'repeatPeriod': 7, 'repeatInterval': 1, 'localDateEnd': '0000-00-00'}],
                  sessions=[])
    session = dict(wBusinessId=ac.BUSINESS_ID, wLocationId=ac.LOCATION_ID,
                   wClassId=class_id, id=900000000 + class_id, startDateTime='2026-11-15T15:00:00+00:00',
                   utcDateTimeStart='2026-11-15T15:00:00+00:00', localDateTimeStart='2026-11-15 10:00:00',
                   timezone='ET', durationMinutes=60, bookingSlotsTotal=10, bookingSlotsUsed=1,
                   isCancelled=False, isBookable=True, isVirtual=False, denyReasonId=0,
                   specialInstructions='')
    settings = dict(wBusinessId=ac.BUSINESS_ID, title=ac.VENUE[0], currencyCode='USD', clientMustSignIn=False)
    return {'page': '/listings/class/[slug]', 'query': {'slug': slug},
            'props': {'pageProps': {'defaults': {'location': location}, 'locations': [deepcopy(location)],
                                   'course': course, 'settings': settings, 'nextBookableSession': session}}}


def html(data):
    # Native SSR can render a closed loading shell while its dated session is
    # bookable. Decisions must use the complete explicit session record.
    return '<p>No times available CLOSED</p><script id="__NEXT_DATA__">' + json.dumps(data) + '</script>'


def fetcher(*, index=None, modifier=None):
    calls = []
    by_url = {ac.CLASS_BASE + slug + '/': class_id for class_id, (_, slug) in ac.CLASSES.items()}
    def fetch(url, accept):
        calls.append(url)
        if url == ac.SOURCES[ac.SOURCE_KEY][0]:
            return index if index is not None else listing()
        data = detail_data(by_url[url])
        if modifier:
            modifier(data['props']['pageProps'])
        return html(data)
    return fetch, calls


class AtlanticCityStudioTest(unittest.TestCase):
    def setUp(self):
        self.patch_record = patch.object(ac, 'record', side_effect=preview_record)
        self.patch_record.start()
        self.addCleanup(self.patch_record.stop)

    def parse(self, data=None, class_id=444005, index=None, now=NOW):
        item = next(i for i in ac.manifest(index or listing()) if i['class_id'] == class_id)
        return ac.parse_detail(html(data or detail_data(class_id)), item, now=now)

    def complete(self, fetch, *, checkpoint=None, now=NOW):
        for _ in range(4):
            result = ac.collect_chunk(source(), fetch, checkpoint=checkpoint, now=now)
            checkpoint = result['checkpoint']
            if result['complete']:
                return result
        self.fail('bounded studio manifest did not complete')

    def test_explicit_next_session_overrides_empty_render_shell_without_recurring_projection(self):
        row, reason = self.parse()
        self.assertIsNone(reason)
        self.assertEqual(row['starts_at'], '2026-11-15T10:00:00-05:00')
        self.assertEqual(row['ends_at'], '2026-11-15T11:00:00-05:00')
        self.assertEqual(row['id'], '900444005')
        self.assertEqual(row['venue_address'], ac.VENUE[1])
        self.assertEqual((row['lat'], row['lng']), ac.LOCATION)
        self.assertEqual(row['location_provenance'], ac.LOCATION_PROVENANCE)

    def test_three_chunks_emit_only_complete_snapshot_and_never_request_widget(self):
        fetch, calls = fetcher()
        first = ac.collect_chunk(source(), fetch, now=NOW)
        self.assertFalse(first['complete'])
        self.assertEqual(first['events'], [])
        self.assertEqual(first['checkpoint']['cursor'], 2)
        with patch.object(ac, 'parse_detail', wraps=ac.parse_detail) as parse:
            second = ac.collect_chunk(source(), fetch, now=NOW + timedelta(minutes=5),
                                      checkpoint=first['checkpoint'])
            self.assertEqual([call.kwargs['now'] for call in parse.call_args_list], [NOW, NOW])
        self.assertFalse(second['complete'])
        self.assertEqual(second['events'], [])
        third = ac.collect_chunk(source(), fetch, now=NOW + timedelta(minutes=10),
                                 checkpoint=second['checkpoint'])
        self.assertTrue(third['complete'])
        self.assertEqual(len(third['events']), 6)
        self.assertEqual(third['checkpoint']['diagnostics'], [])
        self.assertEqual(len(calls), 9)
        self.assertFalse(any('widgets.' in u for u in calls))
        self.assertEqual(len({r['id'] for r in third['events']}), 6)

    def test_full_native_body_and_both_instruction_fields_preserve_suffix_and_literal(self):
        data = detail_data()
        p = data['props']['pageProps']
        body = 'Full native condition. ' * 140 + 'Final paragraph with <literal wording>.'
        p['course']['description'] = '<p>' + escape(body) + '</p>'
        p['course']['specialInstructions'] = '<p>Complete class access condition.</p>'
        p['nextBookableSession']['specialInstructions'] = '<p>Complete dated session access condition.</p>'
        row, _ = self.parse(data)
        self.assertGreater(len(row['description']), 2000)
        self.assertTrue(row['description'].startswith(body))
        self.assertIn('Complete class access condition.', row['description'])
        self.assertTrue(row['description'].endswith('Complete dated session access condition.'))

    def test_missing_or_oversized_prose_fails_instead_of_clipping(self):
        for description in ('', ' ', '<p>' + 'x' * 12001 + '</p>'):
            data = detail_data()
            data['props']['pageProps']['course']['description'] = description
            with self.subTest(length=len(description)), self.assertRaisesRegex(ValueError, 'description_'):
                self.parse(data)
        data = detail_data()
        data['props']['pageProps']['course']['description'] = 'a' * 11999
        data['props']['pageProps']['nextBookableSession']['specialInstructions'] = 'Full final instruction.'
        with self.assertRaisesRegex(ValueError, 'description_limit'):
            self.parse(data)

    def test_mindful_exact_native_identity_uses_complete_own_paragraph_once(self):
        row, _ = self.parse(class_id=ac.MINDFUL)
        self.assertEqual(row['description'], 'Complete owner prose with <literal wording> and its final sentence.')
        self.assertEqual(row['description_source_url'], ac.SOURCES[ac.SOURCE_KEY][0] + '?class=521671')
        data = detail_data(ac.MINDFUL)
        data['props']['pageProps']['course']['title'] = 'Another class'
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.parse(data, class_id=ac.MINDFUL)
        other = detail_data()
        other['props']['pageProps']['course']['description'] = ''
        with self.assertRaisesRegex(ValueError, 'description_missing'):
            self.parse(other, class_id=444005)

    def test_source_and_event_urls_are_exactly_fenced_before_fetch(self):
        fetch = Mock()
        for field, value in [('source_key', 'other_studio'), ('feed_url', 'https://other.example/classes'),
                             ('timezone', 'UTC'), ('kind', 'json'), ('platform_adapter', 'jsonld')]:
            config = source()
            config[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'unregistered_'):
                ac.collect_chunk(config, fetch, now=NOW)
        fetch.assert_not_called()
        good = ac.CLASS_BASE + ac.CLASSES[444005][1] + '/'
        self.assertTrue(ac.event_url(ac.SOURCE_KEY, good))
        for wrong in (good + '?date=tomorrow', good + '#extra', good.replace('141251', '141252'),
                      good.replace('www.wellnessliving.com', 'widgets.wellnessliving.com')):
            self.assertFalse(ac.event_url(ac.SOURCE_KEY, wrong))

    def test_foreign_business_class_location_or_geographic_point_cannot_enter_source(self):
        cases = [('course', 'wBusinessId', 99), ('course', 'wClassId', 99),
                 ('nextBookableSession', 'wLocationId', 99), ('nextBookableSession', 'wClassId', 99),
                 ('nextBookableSession', 'id', True)]
        for owner, field, value in cases:
            data = detail_data()
            data['props']['pageProps'][owner][field] = value
            with self.subTest(owner=owner, field=field), self.assertRaisesRegex(ValueError, 'identity'):
                self.parse(data)
        for field, value in [('streetAddress', '1 Other Road'), ('latitude', 39.0),
                             ('timezone', 'America/Chicago')]:
            data = detail_data()
            data['props']['pageProps']['defaults']['location'][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'location_changed'):
                self.parse(data)

    def test_cancelled_unbookable_full_virtual_and_prerequisite_sessions_are_held(self):
        for field, value, reason in [('isCancelled', True, 'cancelled'),
                                     ('isBookable', False, 'not_bookable'),
                                     ('bookingSlotsUsed', 10, 'sold_out'),
                                     ('isVirtual', True, 'not_public_in_person')]:
            data = detail_data()
            data['props']['pageProps']['nextBookableSession'][field] = value
            self.assertEqual(self.parse(data), (None, reason))
        data = detail_data()
        data['props']['pageProps']['course']['prerequisiteCourses'] = [{'id': 123}]
        self.assertEqual(self.parse(data), (None, 'prerequisite_unresolved'))
        # Purchase passes are publicly offered even when this native class has
        # dropInEnabled=false; that does not make its bookable session private.
        self.assertIsNotNone(self.parse()[0])

    def test_unknown_eligibility_is_not_assumed_bookable(self):
        for field, value in [('isBookable', None), ('bookingSlotsTotal', None),
                             ('bookingSlotsUsed', -1), ('denyReasonId', 2)]:
            data = detail_data()
            data['props']['pageProps']['nextBookableSession'][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'identity|eligibility'):
                self.parse(data)

    def test_native_utc_local_timezone_and_duration_must_agree(self):
        for field, value in [('utcDateTimeStart', '2026-11-15T16:00:00+00:00'),
                             ('startDateTime', '2026-11-15T15:00:00'),
                             ('localDateTimeStart', '2026-11-15 10:00:00+00:00'),
                             ('timezone', 'PT'), ('durationMinutes', 0), ('durationMinutes', True)]:
            data = detail_data()
            data['props']['pageProps']['nextBookableSession'][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'clock_conflict'):
                self.parse(data)
        data = detail_data()
        s = data['props']['pageProps']['nextBookableSession']
        s.update(localDateTimeStart='2027-03-14 02:30:00',
                 utcDateTimeStart='2027-03-14T07:30:00+00:00', startDateTime='2027-03-14T07:30:00+00:00')
        with self.assertRaisesRegex(ValueError, 'clock_conflict'):
            self.parse(data)

    def test_explicit_past_or_outside_window_is_held(self):
        self.assertEqual(self.parse(now=NOW + timedelta(days=2)), (None, 'outside_window'))
        data = detail_data()
        data['props']['pageProps']['nextBookableSession'].update(
            localDateTimeStart='2027-02-15 10:00:00', utcDateTimeStart='2027-02-15T15:00:00+00:00',
            startDateTime='2027-02-15T15:00:00+00:00')
        self.assertEqual(self.parse(data), (None, 'outside_window'))

    def test_all_classes_without_native_next_session_form_valid_complete_empty_snapshot(self):
        fetch, _ = fetcher(modifier=lambda p: p.update(nextBookableSession=None))
        result = self.complete(fetch)
        self.assertEqual(result['events'], [])
        self.assertEqual(len(result['checkpoint']['diagnostics']), 6)
        self.assertEqual({d['reason'] for d in result['checkpoint']['diagnostics']}, {'no_published_next_session'})

    def test_changed_or_partial_own_manifest_cannot_claim_completion(self):
        for index in (listing(omit=444005), listing().replace('data-filter="444005"', 'data-filter="99999"'),
                      listing().replace('1637 New Rd', '1638 New Rd'),
                      listing().replace('<h3>Kripalu</h3>', '<h3>Different class</h3>')):
            fetch, _ = fetcher(index=index)
            with self.subTest(index=index[:40]), self.assertRaisesRegex(ValueError, 'manifest_invalid'):
                ac.collect_chunk(source(), fetch, now=NOW)

    def test_checkpoint_prefix_clock_pin_and_prose_are_validated_before_resume(self):
        fetch, _ = fetcher()
        saved = ac.collect_chunk(source(), fetch, now=NOW)['checkpoint']
        alterations = [lambda s: s.update(version=True), lambda s: s.update(contract='other'),
                       lambda s: s.update(cursor=3), lambda s: s['events'][0].update(lat=39.0),
                       lambda s: s['events'][0].update(description=''),
                       lambda s: s['events'][0].update(venue_address='1 Unknown Street'),
                       lambda s: s['events'][0].update(ends_at='2026-11-14T10:00:00-05:00'),
                       lambda s: s['events'][0].update(event_url=s['queue'][4]['url']),
                       lambda s: s['queue'][0].update(studio_description='Altered prose')]
        for change in alterations:
            state = deepcopy(saved)
            change(state)
            transport = Mock()
            with self.assertRaisesRegex(ValueError, 'checkpoint_invalid'):
                ac.collect_chunk(source(), transport, checkpoint=state, now=NOW)
            transport.assert_not_called()

    def test_expired_or_changed_manifest_restarts_without_mixing_old_rows(self):
        fetch, _ = fetcher()
        saved = ac.collect_chunk(source(), fetch, now=NOW)['checkpoint']
        changed, calls = fetcher(index=listing(mindful='New complete publisher description.'))
        result = ac.collect_chunk(source(), changed, checkpoint=saved, now=NOW + timedelta(minutes=1))
        self.assertEqual(result['checkpoint']['cursor'], 2)
        self.assertEqual(calls[1], saved['queue'][0]['url'])
        expired, calls = fetcher()
        result = ac.collect_chunk(source(), expired, checkpoint=saved, now=NOW + timedelta(hours=5))
        self.assertEqual(result['checkpoint']['cursor'], 2)
        self.assertEqual(calls[1], saved['queue'][0]['url'])

    def test_deadline_and_transport_failures_never_publish_partial_manifest(self):
        fetch, _ = fetcher()
        with self.assertRaisesRegex(ValueError, 'publisher_checkpoint_required'):
            ac.collect(source(), fetch, now=NOW)
        with patch.object(ac, 'monotonic', return_value=100):
            with self.assertRaisesRegex(ValueError, 'collection_deadline'):
                ac.collect_chunk(source(), fetch, now=NOW, deadline_at=114)
        # Unexpected detail failure aborts the invocation; it is never recorded
        # as an eligible empty class or a successfully finished manifest.
        index = listing()
        transport = Mock(side_effect=[index, ValueError('publisher_http_403')])
        with self.assertRaisesRegex(ValueError, 'publisher_http_403'):
            ac.collect_chunk(source(), transport, now=NOW)

    def test_observed_transport_pacing_preserves_completed_detail_for_next_chunk(self):
        from roomquest.preview_worker import PreviewError

        fetch, _ = fetcher()
        count = 0
        def paced(url, accept):
            nonlocal count
            count += 1
            if count == 3:
                raise PreviewError('publisher_pacing_deferred')
            return fetch(url, accept)
        first = ac.collect_chunk(source(), paced, now=NOW)
        self.assertFalse(first['complete'])
        self.assertEqual(first['events'], [])
        self.assertEqual(first['checkpoint']['cursor'], 1)
        result = self.complete(fetch, checkpoint=first['checkpoint'])
        self.assertEqual(len(result['events']), 6)

    def test_duplicate_native_session_identity_cannot_overwrite_another_class(self):
        fetch, _ = fetcher(modifier=lambda p: p['nextBookableSession'].update(id=12345678))
        with self.assertRaisesRegex(ValueError, 'checkpoint_invalid|duplicate_session'):
            self.complete(fetch)


if __name__ == '__main__':
    unittest.main()
