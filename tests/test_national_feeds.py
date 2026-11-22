from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from roomquest import openactive as oa, wildlife_trusts as wildlife
from roomquest import national_feed_checkpoint as snapshot, national_feed_worker as national
from roomquest import preview_worker as worker
from roomquest import registered_native_content as native
from roomquest.registration_formats import source_key

FIXTURES = Path(__file__).parent / 'fixtures' / 'national_feeds'
NOW = datetime(2026, 11, 22, 9, tzinfo=timezone.utc)
OA_SOURCE = {'feed_url': oa.BETTER, 'source_key': source_key(oa.BETTER),
             'kind': 'json', 'platform_adapter': 'jsonld', 'registered_openactive_version': 1,
             'registered_native_content_version': 1}
WT_SOURCE = {'feed_url': wildlife.BCN, 'source_key': source_key(wildlife.BCN),
             'kind': 'html', 'platform_adapter': 'html', 'fetch_checkpoint_version': 1,
             'registered_native_content_version': 1}
DETAIL = wildlife.BCN + '/2026-11-23-nature-workshop'


@pytest.fixture(autouse=True)
def fixed_window(monkeypatch):
    monkeypatch.setattr(worker, '_future_datetime', lambda value: value.astimezone(timezone.utc)
                        if NOW <= value <= NOW + timedelta(days=60) else None)


def read(name):
    return (FIXTURES / name).read_text()


def page(name):
    return json.loads(read(name))


def rss(count=1, *, host='www.wildlifebcn.org', next_url=None):
    entries = ''.join('<item><title>23rd Nov2026 - Nature workshop</title>'
                      f'<link>https://{host}/events/2026-11-23-nature-workshop{str(i) if i else ""}</link>'
                      '<description>Native summary</description>'
                      '<pubDate>Mon, 23 Nov2026 12:00:00 +0000</pubDate></item>' for i in range(count))
    link = f'<atom:link rel="next" href="{next_url}"/>' if next_url else ''
    return ('<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>'
            f'<title>Events RSS feed</title><link>https://{host}/</link><description>Upcoming events</description>'
            + entries.replace('Nov2026', 'Nov 2026') + link + '</channel></rss>')


def detail_for(url):
    return read('wildlife-detail.html').replace(DETAIL, url)


def publisher(count=1):
    fetched = []
    def fetch(url, accept):
        fetched.append(url)
        if url == wildlife.BCN + '/rss.xml':
            return rss(count)
        return detail_for(url)
    return fetch, fetched


def test_wildlife_uses_real_detail_clock_not_rss_noon_and_preserves_venue_and_text():
    fetch, fetched = publisher()
    result = wildlife.collect_chunk(WT_SOURCE, fetch, now=NOW)
    assert result['complete'] is True
    row = result['events'][0]
    assert row['starts_at'] == '2026-11-23T10:00:00+00:00'
    assert row['ends_at'] == '2026-11-23T13:00:00+00:00'
    assert row['lat'] == 52.251619 and row['lng'] == -0.247675
    assert row['venue_city'] == 'Little Paxton'
    assert row['venue_address'].endswith('Cambridgeshire, PE19 6ET')
    assert 'Booking is required.' in row['description'] and 'About the event' not in row['description']
    assert row['image_url'].endswith('/sites/default/files/nature-workshop.jpg')
    wildlife.validate_native(row, WT_SOURCE)
    assert fetched == [wildlife.BCN + '/rss.xml', DETAIL]


def test_wildlife_regional_source_requires_complete_accounted_manifest():
    fetch, fetched = publisher(19)
    checkpoint = None
    for cursor in (8, 16):
        result = wildlife.collect_chunk(WT_SOURCE, fetch, checkpoint=checkpoint, now=NOW)
        assert result['complete'] is False and result['events'] == []
        checkpoint = result['checkpoint']
        assert checkpoint['cursor'] == cursor
    result = wildlife.collect_chunk(WT_SOURCE, fetch, checkpoint=checkpoint, now=NOW)
    assert result['complete'] is True and len(result['events']) == 19
    assert fetched.count(wildlife.BCN + '/rss.xml') == 1
    with pytest.raises(ValueError, match='publisher_checkpoint_required'):
        wildlife.collect(WT_SOURCE, fetch)


def test_wildlife_national_catalog_is_not_a_local_demand_source():
    source = dict(WT_SOURCE, feed_url=wildlife.NATIONAL, source_key=source_key(wildlife.NATIONAL))
    with pytest.raises(ValueError, match='national_catalog_requires_regional_sources'):
        wildlife.collect_chunk(source, lambda *args: pytest.fail('national feed fetched'), now=NOW)
    assert wildlife.allowed_hosts(wildlife.BCN) == ('www.wildlifebcn.org',)
    assert wildlife.NATIONAL not in wildlife.URLS


def test_cornwall_scope_uses_the_origin_linked_by_the_official_national_catalog():
    url = 'https://www.cornwallwildlifetrust.org.uk/events'
    source = dict(WT_SOURCE, feed_url=url, source_key=source_key(url))
    wildlife.validate_source(source)
    assert wildlife.event_url_matches(source, url + '/2026-12-20-seaquest-southwest-public-seawatch-st-ives')
    wrong_url = 'https://www.cornwallwildlifetrust.co.uk/events'
    with pytest.raises(ValueError, match='wildlife_source_identity'):
        wildlife.validate_source(dict(source, feed_url=wrong_url, source_key=source_key(wrong_url)))


def test_wildlife_never_follows_a_cross_region_or_arbitrary_item_link():
    data = rss().replace(DETAIL, 'https://www.ywt.org.uk/events/2026-11-23-example')
    seen = []
    def fetch(url, accept):
        seen.append(url)
        assert url == wildlife.BCN + '/rss.xml'
        return data
    result = wildlife.collect_chunk(WT_SOURCE, fetch, now=NOW)
    assert result['complete'] and result['events'] == []
    state = snapshot.decode(WT_SOURCE, result['checkpoint'], at=NOW)
    assert state['outcomes'][0]['reason'] == 'wildlife_event_link_unreviewed'
    assert len(seen) == 1


def test_wildlife_does_not_expand_date_ranges_or_publish_cancelled_details():
    item = {'url': DETAIL, 'title': 'Nature workshop', 'start': '2026-11-23', 'end': '2026-11-30'}
    assert wildlife.parse_detail(detail_for(DETAIL), item, source=WT_SOURCE)[1] == 'wildlife_multiple_dates_unresolved'
    item['end'] = item['start']
    text = detail_for(DETAIL).replace('Nature workshop</h1>', 'Cancelled: Nature workshop</h1>')
    assert wildlife.parse_detail(text, item, source=WT_SOURCE) == ([], 'cancelled')


def test_wildlife_pagination_and_checkpoint_integrity():
    url = wildlife.BCN + '/rss.xml'
    with pytest.raises(ValueError, match='wildlife_rss_pagination_invalid'):
        wildlife.parse_feed(rss(next_url='https://example.org/feed'), url, WT_SOURCE)
    fetch, _ = publisher(10)
    checkpoint = wildlife.collect_chunk(WT_SOURCE, fetch, now=NOW)['checkpoint']
    changed = dict(checkpoint, source_key='another_source')
    with pytest.raises(ValueError, match='national_feed_checkpoint_invalid'):
        snapshot.decode(WT_SOURCE, changed, at=NOW)
    changed = dict(checkpoint, payload=checkpoint['payload'][:-4] + 'AAAA')
    with pytest.raises(ValueError, match='national_feed_checkpoint_invalid'):
        snapshot.decode(WT_SOURCE, changed, at=NOW)
    with pytest.raises(ValueError, match='national_feed_checkpoint_expired'):
        snapshot.decode(WT_SOURCE, checkpoint, at=NOW + timedelta(hours=5))


def test_wildlife_access_denial_is_accounted_without_bypass_but_503_is_retryable():
    def fetch(url, accept):
        if url.endswith('/rss.xml'):
            return rss()
        raise worker.PreviewError('publisher_http_403')
    result = wildlife.collect_chunk(WT_SOURCE, fetch, now=NOW)
    assert result['complete'] and not result['events']
    assert snapshot.decode(WT_SOURCE, result['checkpoint'], at=NOW)['outcomes'][0]['reason'] == 'publisher_http_403'
    def unavailable(url, accept):
        if url.endswith('/rss.xml'):
            return rss()
        raise worker.PreviewError('publisher_http_503')
    with pytest.raises(worker.PreviewError, match='publisher_http_503'):
        wildlife.collect_chunk(WT_SOURCE, unavailable, now=NOW)


def test_rpde_short_nonempty_page_is_not_tail_and_tail_requires_self_next():
    seed = oa.PROFILES['better']['streams'][0]
    result = oa.parse_page(read('openactive-series.json'), seed, seed)
    assert result['tail'] is False and len(result['items']) == 1
    tail = json.dumps({'items': [], 'next': result['next'], 'license': result['license']})
    assert oa.parse_page(tail, result['next'], seed, previous=result['position'])['tail'] is True
    changed = page('openactive-series.json')
    changed['next'] = seed
    with pytest.raises(ValueError, match='openactive_cursor_stalled'):
        oa.parse_page(json.dumps(changed), seed, seed)


def test_rpde_cursor_cannot_skip_the_last_item_or_cycle_empty_pages():
    seed = oa.PROFILES['better']['streams'][0]
    changed = page('openactive-series.json')
    changed['next'] = seed + '?afterTimestamp=999999&afterId=not-the-last-item'
    with pytest.raises(ValueError, match='openactive_cursor_invalid'):
        oa.parse_page(json.dumps(changed), seed, seed)
    request = seed + '?afterTimestamp=100&afterId=last'
    body = {'items': [], 'next': seed, 'license': changed['license']}
    with pytest.raises(ValueError, match='openactive_cursor_stalled'):
        oa.parse_page(json.dumps(body), request, seed)


@pytest.mark.parametrize('next_url', ['https://example.org/steal', oa.BETTER + '/slots',
    oa.BETTER + '/session-series?afterTimestamp=100', oa.BETTER + '/session-series?token=secret'])
def test_rpde_rejects_cursor_escape(next_url):
    seed = oa.PROFILES['better']['streams'][0]
    data = page('openactive-series.json')
    data['next'] = next_url
    with pytest.raises(ValueError, match='openactive_payload_invalid'):
        oa.parse_page(json.dumps(data), seed, seed)


def test_rpde_tombstone_has_same_item_key_and_cannot_regress_position():
    seed = oa.PROFILES['better']['streams'][0]
    first = oa.parse_page(read('openactive-series.json'), seed, seed)
    data = page('openactive-series.json')
    data['items'] = [{'state': 'deleted', 'kind': 'SessionSeries', 'id': 'series-1', 'modified': 101}]
    data['next'] = seed + '?afterTimestamp=101&afterId=series-1'
    deleted = oa.parse_page(json.dumps(data), first['next'], seed, previous=first['position'])
    assert deleted['items'] == [{'key': first['items'][0]['key'], 'deleted': True}]
    with pytest.raises(ValueError, match='openactive_page_order_invalid'):
        oa.parse_page(read('openactive-series.json'), seed, seed, previous=first['position'])


def native_items():
    seeds = oa.PROFILES['better']['streams']
    parent = oa.parse_page(read('openactive-series.json'), seeds[0], seeds[0])['items'][0]
    child = oa.parse_page(read('openactive-session.json'), seeds[1], seeds[1])['items'][0]
    return parent, child


def test_openactive_samples_respect_database_utf8_byte_limit_without_truncating_native_rows():
    rows = [{'description': 'é' * 5000}, {'description': 'é' * 5000}]
    samples = national._samples(rows)
    assert samples == rows[:1]
    assert len(rows) == 2 and all(len(row['description']) == 5000 for row in rows)
    checkpoint, _ = oa.new_checkpoint(OA_SOURCE, now=NOW)
    checkpoint['phase'] = 'stage'
    for stream in checkpoint['streams']:
        stream['complete'] = True
    checkpoint['samples'] = samples
    oa.validate_checkpoint(OA_SOURCE, checkpoint, now=NOW)
    checkpoint['samples'] = rows
    with pytest.raises(ValueError, match='openactive_checkpoint_invalid'):
        oa.validate_checkpoint(OA_SOURCE, checkpoint, now=NOW)


def test_parent_join_full_native_description_image_and_publisher_geo():
    parent, child = native_items()
    parent['data']['description'] = 'Complete publisher paragraph. ' * 120
    rows, held = oa.project(OA_SOURCE, child, {parent['identity']: parent})
    assert held == 0 and len(rows) == 1
    row = rows[0]
    assert len(row['description']) > 2000
    assert row['venue_city'] == 'Cambridge' and row['lat'] == 52.2
    assert row['event_url'] == child['data']['url']
    assert row['registered_native_content']['evidence_url'] == parent['evidence_url']
    assert row['image_evidence_url'] == parent['evidence_url']
    oa.validate_native(row, OA_SOURCE)
    native.validate_record(row, OA_SOURCE)
    row['registered_native_content']['evidence_url'] = 'https://example.org/unrelated'
    with pytest.raises(ValueError, match='registered_native_evidence_invalid'):
        oa.validate_native(row, OA_SOURCE)


def test_partial_schedules_cancelled_and_missing_parents_never_become_occurrences():
    parent, child = native_items()
    assert oa.project(OA_SOURCE, parent, {}) == ([], 0)
    assert oa.project(OA_SOURCE, child, {}) == ([], 1)
    child['data']['eventStatus'] = 'https://schema.org/EventCancelled'
    assert oa.project(OA_SOURCE, child, {parent['identity']: parent}) == ([], 0)


def test_occurrence_identity_includes_the_concrete_utc_start():
    parent, child = native_items()
    first, _ = oa.project(OA_SOURCE, child, {parent['identity']: parent})
    second_child = deepcopy(child)
    second_child['data']['startDate'] = '2026-11-24T10:00:00Z'
    second_child['data']['endDate'] = '2026-11-24T11:00:00Z'
    second, _ = oa.project(OA_SOURCE, second_child, {parent['identity']: parent})
    assert first[0]['id'] != second[0]['id']


def test_96h_refresh_reuses_tails_but_tombstone_gap_requires_full_bootstrap():
    checkpoint, reset = oa.new_checkpoint(OA_SOURCE, now=NOW)
    assert reset
    for stream in checkpoint['streams']:
        stream.update(next=stream['url'] + '?afterTimestamp=100&afterId=last',
                      complete=True, pages=5, license=next(iter(oa.LICENSES)), last_modified=100, last_id='last')
    checkpoint.update(phase='ready', last_complete_at=NOW.isoformat())
    oa.validate_checkpoint(OA_SOURCE, checkpoint, now=NOW + timedelta(days=4))
    following, reset = oa.new_checkpoint(OA_SOURCE, now=NOW + timedelta(days=4), previous=checkpoint)
    assert not reset and following['streams'][0]['next'] == checkpoint['streams'][0]['next']
    restarted, reset = oa.new_checkpoint(OA_SOURCE, now=NOW + timedelta(days=7), previous=checkpoint)
    assert reset and restarted['streams'][0]['next'] == restarted['streams'][0]['url']


class StateHarness:
    def __init__(self, monkeypatch):
        self.revision, self.checkpoint, self.items = 0, None, {}
        self.calls, self.fetched, self.staged, self.previews = [], [], {}, []
        self.fail_url = None
        seeds = oa.PROFILES['better']['streams']
        self.pages = {seeds[0]: read('openactive-series.json'), seeds[1]: read('openactive-session.json')}
        for name in ('openactive-series.json', 'openactive-session.json'):
            data = page(name)
            self.pages[data['next']] = json.dumps({'items': [], 'next': data['next'], 'license': data['license']})
        monkeypatch.setattr(worker, 'supabase_rpc', self.rpc)
        monkeypatch.setattr(worker, 'fetch_publisher', self.fetch)

    def fetch(self, url, accept, **kwargs):
        assert kwargs['respect_robots'] is True
        assert kwargs['allowed_hosts'] == ('better-admin.org.uk',)
        self.fetched.append(url)
        if url == self.fail_url:
            raise worker.PreviewError('publisher_http_503')
        return self.pages[url]

    def rpc(self, operation, payload, **kwargs):
        self.calls.append((operation, deepcopy(payload)))
        if operation == national.STATE_RPC:
            assert payload['p_category'] == 'jsonld' and payload['p_ticket'] == 'private-ticket'
            action = payload['p_action']
            if action == 'read':
                return {'revision': self.revision, 'checkpoint': deepcopy(self.checkpoint)}
            if action == 'apply':
                assert payload['p_expected_revision'] == self.revision
                if payload['p_reset']:
                    self.items = {}
                for item in payload['p_items']:
                    if item.get('deleted'):
                        self.items.pop(item['key'], None)
                    else:
                        self.items[item['key']] = deepcopy(item)
                self.checkpoint = deepcopy(payload['p_checkpoint'])
                self.revision += 1
                return {'revision': self.revision, 'checkpoint_saved': True}
            if action == 'items':
                rows = [self.items[key] for key in sorted(self.items) if key > (payload['p_after'] or '')]
                return {'items': deepcopy(rows[:payload['p_limit']]), 'has_more': len(rows) > payload['p_limit']}
            if action == 'references':
                return {'items': deepcopy([v for v in self.items.values() if v['identity'] in payload['p_references']])}
            pytest.fail(action)
        if operation == 'community_collector_record_staged_events':
            assert all(s['complete'] for s in self.checkpoint['streams'])
            assert payload['p_registered_native_content_version'] == 1
            for row in payload['p_events']:
                self.staged[(row['id'], row['starts_at'])] = deepcopy(row)
            return len(payload['p_events'])
        if operation == 'community_collector_record_preview_v3':
            self.previews.append(deepcopy(payload))
            if payload['p_error'] is None:
                assert self.checkpoint['phase'] == 'complete'
                self.checkpoint.update(phase='ready', last_complete_at=datetime.now(timezone.utc).isoformat())
            return None
        pytest.fail(operation)

    def run(self):
        return worker._process_claimed_source(OA_SOURCE, collection_context={
            'p_category': 'jsonld', 'p_ticket': 'private-ticket'})


def test_worker_commits_all_tails_before_staging_and_retains_state(monkeypatch):
    harness = StateHarness(monkeypatch)
    result = harness.run()
    assert result['complete'] == 1 and result['staged'] == 1 and not result['failed']
    assert len(harness.items) == 2 and harness.checkpoint['phase'] == 'ready'
    assert len(harness.staged) == 1 and harness.previews[-1]['p_future_count'] == 1
    assert len(harness.fetched) == 4
    harness.fetched.clear()
    assert harness.run()['complete'] == 1
    assert len(harness.fetched) == 2 and all('?afterTimestamp=' in url for url in harness.fetched)
    assert len(harness.items) == 2


def test_worker_outage_keeps_transactional_prefix_and_never_certifies_partial(monkeypatch):
    harness = StateHarness(monkeypatch)
    harness.fail_url = page('openactive-series.json')['next']
    result = harness.run()
    assert result['failed'] == 1 and not result['complete']
    assert not harness.staged and len(harness.items) == 1
    assert harness.checkpoint['phase'] == 'fetch'
    assert harness.previews[-1]['p_error'] == 'publisher_http_503'
    harness.fail_url = None
    harness.fetched.clear()
    assert harness.run()['complete'] == 1
    assert harness.fetched[0] == page('openactive-series.json')['next']
    assert oa.PROFILES['better']['streams'][0] not in harness.fetched


def test_oversized_retained_page_never_advances_cursor_or_writes_a_prefix(monkeypatch):
    harness = StateHarness(monkeypatch)
    source = page('openactive-series.json')
    original = source['items'][0]
    source['items'] = []
    seed = oa.PROFILES['better']['streams'][0]
    for index in range(500):
        item = deepcopy(original)
        item.update(id=f'series-{index:04}', modified=100 + index)
        item['data']['@id'] = seed + '/' + item['id']
        item['data']['description'] = 'Complete native narrative. ' * 250
        source['items'].append(item)
    source['next'] = seed + '?afterTimestamp=599&afterId=series-0499'
    harness.pages[seed] = json.dumps(source)
    result = harness.run()
    assert result['failed'] == 1 and not harness.items and not harness.staged
    assert harness.checkpoint['streams'][0]['next'] == seed
    assert harness.checkpoint['streams'][0]['pages'] == 0
    assert harness.previews[-1]['p_error'] == 'openactive_page_size_limit'


def test_worker_late_tombstone_removes_current_occurrence_before_projection(monkeypatch):
    harness = StateHarness(monkeypatch)
    assert harness.run()['complete'] == 1
    last = page('openactive-session.json')['next']
    after = oa.PROFILES['better']['streams'][1] + '?afterTimestamp=201&afterId=session-1'
    harness.pages[last] = json.dumps({'items': [{'state': 'deleted', 'kind': 'ScheduledSession',
        'id': 'session-1', 'modified': 201}], 'next': after, 'license': next(iter(oa.LICENSES))})
    # Use the same explicit licence spelling as the established stream.
    current = json.loads(harness.pages[last])
    current['license'] = page('openactive-session.json')['license']
    harness.pages[last] = json.dumps(current)
    harness.pages[after] = json.dumps({'items': [], 'next': after, 'license': current['license']})
    assert harness.run()['complete'] == 1
    assert len(harness.items) == 1
    assert harness.previews[-1]['p_future_count'] == 0


def test_manual_preview_cannot_bypass_durable_capture():
    with pytest.raises(worker.PreviewError, match='publisher_checkpoint_required'):
        worker.preview_source(OA_SOURCE)
    with pytest.raises(worker.PreviewError, match='publisher_checkpoint_required'):
        worker.preview_source(WT_SOURCE)


def test_large_parent_keeps_core_facts_without_unrelated_partial_schedule_payload():
    data = page('openactive-series.json')
    body = data['items'][0]['data']
    original_description = body['description'] = 'Full publisher description. ' * 100
    body['eventSchedule'] *= 2000
    body['offers'] = [{'unused_booking_detail': 'x' * 100000}]
    seed = oa.PROFILES['better']['streams'][0]
    reduced = oa.parse_page(json.dumps(data), seed, seed)['items'][0]
    assert reduced['data']['description'] == original_description
    assert reduced['data']['eventSchedule'] == [{'@type': 'PartialSchedule', 'scheduleTimezone': 'Europe/London'}]
    assert 'offers' not in reduced['data']
    assert reduced['data']['location']['geo']['latitude'] == 52.2
    body['description'] = 'x' * 70000
    with pytest.raises(ValueError, match='openactive_item_size_limit'):
        oa.parse_page(json.dumps(data), seed, seed)


def test_larger_response_bound_is_exact_to_better_series_and_robots_transport():
    url = oa.BETTER + '/session-series?afterTimestamp=100&afterId=series-1'
    assert worker._publisher_body_limit(url, 'application/json', ('better-admin.org.uk',), True) == 8000000
    assert worker._publisher_body_limit(url, 'text/html', ('better-admin.org.uk',), True) == worker.MAX_BODY
    assert worker._publisher_body_limit(url, 'application/json', ('better-admin.org.uk',), False) == worker.MAX_BODY
    assert worker._publisher_body_limit(oa.BETTER + '/scheduled-sessions', 'application/json', ('better-admin.org.uk',), True) == worker.MAX_BODY


def test_native_media_claim_is_candidate_only_capability_bound_and_evidence_scoped():
    parent, child = native_items()
    claim = dict(OA_SOURCE, candidate_only=True, event_url=child['data']['url'], extraction_url=parent['evidence_url'])
    assert native.media_claim(claim)
    assert not native.media_claim(dict(claim, candidate_only=False))
    assert not native.media_claim(dict(claim, extraction_url='https://example.org/other'))
    assert not native.media_claim(dict(claim, registered_openactive_version=True))
    assert not native.media_claim(dict(claim, source_key='other_source'))
    regional = dict(WT_SOURCE, candidate_only=True, event_url=DETAIL, extraction_url=DETAIL)
    assert native.media_claim(regional)
    assert not native.media_claim(dict(regional, event_url='https://www.ywt.org.uk/events/other'))


def test_registration_keeps_original_urls_and_does_not_read_partial_events(monkeypatch):
    from roomquest import feed_registration as intake
    for original, expected in ((oa.BETTER, 'jsonld'), (wildlife.BCN, 'html')):
        calls = []
        def rpc(operation, payload, **kwargs):
            calls.append((operation, payload))
            if operation == 'community_collector_claim_registration':
                return {'url': original}
            if operation == 'community_collector_finish_registration':
                assert payload['p_endpoint'] == original and payload['p_type'] == expected
                return True
            pytest.fail(operation)
        def fetch(url, accept, **kwargs):
            assert kwargs['respect_robots'] is True
            if url == oa.BETTER:
                streams = oa.PROFILES['better']['streams']
                return '<script type="application/ld+json">' + json.dumps({
                    '@type': 'Dataset', '@id': oa.BETTER, 'distribution': [{'contentUrl': u} for u in streams]}) + '</script>'
            if url.endswith('/session-series'):
                return read('openactive-series.json')
            if url.endswith('/scheduled-sessions'):
                return read('openactive-session.json')
            if url == wildlife.BCN:
                return '<a href="/events/rss.xml">RSS</a>'
            if url == wildlife.BCN + '/rss.xml':
                return rss(75)
            pytest.fail('Registration tried to fetch event detail: ' + url)
        monkeypatch.setattr(intake, 'supabase_rpc', rpc)
        monkeypatch.setattr(intake, 'fetch_publisher', fetch)
        assert intake.register('private-ticket')['outcome'] == 'verified'
        assert len(calls) == 2


def test_regional_feed_at_upstream_ceiling_needs_explicit_continuation():
    with pytest.raises(ValueError, match='wildlife_rss_capacity_unverified'):
        wildlife.probe(WT_SOURCE, lambda url, accept: rss(500))


def test_regional_worker_waits_for_complete_manifest_and_replays_failed_staging(monkeypatch):
    monkeypatch.setattr(snapshot, 'now', lambda value=None: NOW)
    saved, revision, staged, previews = None, 0, {}, []
    fetch, fetched = publisher(20)
    fail_stage = True
    def transport(url, accept, **kwargs):
        assert kwargs['respect_robots'] is True and kwargs['allowed_hosts'] == ('www.wildlifebcn.org',)
        return fetch(url, accept)
    def rpc(operation, payload, **kwargs):
        nonlocal saved, revision, fail_stage
        if operation == 'community_collector_read_fetch_checkpoint':
            return {'checkpoint': deepcopy(saved), 'revision': revision}
        if operation == 'community_collector_write_fetch_checkpoint':
            assert payload['p_expected_revision'] == revision
            saved = deepcopy(payload['p_checkpoint'])
            revision += 1
            return {'checkpoint_saved': True, 'revision': revision}
        if operation == 'community_collector_record_staged_events':
            assert saved['phase'] == 'stage' and saved['cursor'] == saved['manifest_count'] == 20
            if fail_stage:
                fail_stage = False
                raise worker.PreviewError('database_unavailable')
            for row in payload['p_events']:
                wildlife.validate_native(row, WT_SOURCE)
                staged[(row['id'], row['starts_at'])] = row
            return len(payload['p_events'])
        if operation == 'community_collector_record_preview_v3':
            assert saved['stage_cursor'] == saved['record_count'] == 20
            assert payload['p_error'] is None
            previews.append(payload)
            saved, revision = None, 0
            return None
        pytest.fail(operation)
    monkeypatch.setattr(worker, 'fetch_publisher', transport)
    monkeypatch.setattr(worker, 'supabase_rpc', rpc)
    def run():
        return worker._process_claimed_source(WT_SOURCE, collection_context={
            'p_category': 'html', 'p_ticket': 'private-ticket'})
    for cursor in (8, 16):
        result = run()
        assert result['fetch_pending'] and not staged and not previews
        assert saved['cursor'] == cursor
    with pytest.raises(worker.PreviewError, match='database_unavailable'):
        run()
    assert saved['phase'] == 'stage' and saved['stage_cursor'] == 0
    count = len(fetched)
    result = run()
    assert result['complete'] == 1 and result['staged'] == 20
    assert len(staged) == 20 and len(previews) == 1 and saved is None
    assert len(fetched) == count
