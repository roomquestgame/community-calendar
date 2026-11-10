"""Real HTML chunks obey the leased worker's certification and retry boundary."""
from copy import deepcopy
from datetime import timedelta, timezone
from io import BytesIO
import json

import pytest

from roomquest import category_worker as category
from roomquest import discover_halifax as tourism
from roomquest import preview_worker as worker
from roomquest.publisher_pacing import observe_crawl_delay, observe_retry_after
from test_discover_halifax_chunks import NOW, SOURCE, descriptor, detail, publisher


READ = 'community_collector_read_fetch_checkpoint'
WRITE = 'community_collector_write_fetch_checkpoint'
STAGE = 'community_collector_record_staged_events'
RECORD = 'community_collector_record_preview_v3'
PUBLISH = 'community_collector_publish_category'
FINISH = 'community_collector_finish_category'


class Harness:
    """Small in-memory RPC contract; publisher parsing and workers remain real."""
    def __init__(self, monkeypatch, count=13):
        self.time = 100.0
        self.calls, self.waits, self.staged = [], [], []
        self.checkpoint, self.revision = None, 0
        self.fail_stage_once = False
        self.read_override = self.write_override = ...
        self.pacing = 1
        self.fetch_error = None
        self.pages, self.fetched, fetch = publisher([descriptor(i) for i in range(count)])
        self.publisher_fetch = fetch
        monkeypatch.setattr(category, 'monotonic', lambda: self.time)
        monkeypatch.setattr(worker, 'monotonic', lambda: self.time)
        monkeypatch.setattr(tourism, 'monotonic', lambda: self.time)
        monkeypatch.setattr(tourism, '_now', lambda value=None: NOW)
        monkeypatch.setattr(category, 'sleep', self.sleep)
        monkeypatch.setattr(worker, '_future_datetime', lambda value: value.astimezone(timezone.utc)
                            if NOW <= value <= NOW + timedelta(days=worker.LOOKAHEAD_DAYS) else None)
        monkeypatch.setattr(worker, 'fetch_publisher', self.fetch)
        monkeypatch.setattr(worker, 'supabase_rpc', self.rpc)
        monkeypatch.setattr(category, 'supabase_rpc', self.rpc)

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.time += seconds

    def fetch(self, url, accept, **kwargs):
        assert kwargs['respect_robots'] is True
        assert kwargs['allowed_hosts'] == ('gohalifaxva.com',)
        assert self.time < kwargs['deadline_at']
        self.time += 0.1
        observe_crawl_delay(self.pacing)
        if self.fetch_error and url != tourism.URL:
            raise worker.PreviewError(self.fetch_error)
        return self.publisher_fetch(url, accept)

    def rpc(self, operation, payload, **kwargs):
        self.calls.append((operation, deepcopy(payload)))
        if operation == 'community_collector_claim_category':
            return {**SOURCE, 'source_id': 5160, 'action': 'collect',
                    'fetch_checkpoint_version': 1}
        if operation in (READ, WRITE):
            assert payload['p_category'] == 'html'
            assert payload['p_ticket'] == 'private-test-ticket'
            assert payload['p_source_key'] == tourism.KEY
        if operation == READ:
            if self.read_override is not ...:
                return self.read_override
            return {'checkpoint': deepcopy(self.checkpoint), 'revision': self.revision}
        if operation == WRITE:
            assert payload['p_expected_revision'] == self.revision
            assert payload['p_publisher_wait_unbounded'] is False
            assert payload['p_publisher_crawl_delay_seconds'] == self.pacing
            self.checkpoint = deepcopy(payload['p_checkpoint'])
            self.revision += 1
            if self.write_override is not ...:
                if isinstance(self.write_override, Exception):
                    raise self.write_override
                return self.write_override
            return {'checkpoint_saved': True, 'revision': self.revision}
        if operation == STAGE:
            assert self.checkpoint['cursor'] == self.checkpoint['manifest_count']
            if self.fail_stage_once:
                self.fail_stage_once = False
                raise worker.PreviewError('database_unavailable')
            self.staged.extend(deepcopy(payload['p_events']))
            return len(payload['p_events'])
        if operation == RECORD:
            if payload['p_error'] is None:
                assert self.checkpoint['cursor'] == self.checkpoint['manifest_count']
                # Production's success trigger owns this atomic deletion.
                self.checkpoint, self.revision = None, 0
            return None
        if operation == PUBLISH:
            assert self.checkpoint is None
            assert any(op == RECORD and data['p_error'] is None for op, data in self.calls)
            return {'outcome': 'complete'}
        if operation == FINISH:
            return True
        raise AssertionError(operation)

    def run(self):
        return category.collect_category('html', 'private-test-ticket')


def test_bounded_chunks_only_certify_and_publish_the_complete_aggregate(monkeypatch):
    state = Harness(monkeypatch, count=30)
    for cursor in (6, 12, 18, 24):
        before = len(state.calls)
        result = state.run()
        assert result['complete'] == result['failed'] == result['staged'] == 0
        assert result['fetch_pending'] is True
        assert state.checkpoint['cursor'] == cursor
        assert [op for op, _ in state.calls[before:]] == [
            'community_collector_claim_category', READ, WRITE, FINISH]
        assert state.calls[-1][1]['p_outcome'] == 'fetch_pending'
    result = state.run()
    assert result['complete'] == 1 and result['failed'] == 0 and result['staged'] == 30
    assert result['publication'] == {'outcome': 'complete'}
    assert [op for op, _ in state.calls].count(RECORD) == 1
    assert [op for op, _ in state.calls].count(PUBLISH) == 1
    assert len({row['id'] for row in state.staged}) == 30
    assert state.calls[-1][1]['p_outcome'] == 'complete'
    assert state.waits == [1] * 5


@pytest.mark.parametrize('capability', [None, False, True, '1', 0, 2])
def test_missing_or_unknown_backend_capability_retains_legacy_worker_contract(monkeypatch, capability):
    calls, collected = [], []
    source = {**SOURCE, 'source_id': 5160, 'action': 'collect'}
    if capability is not None:
        source['fetch_checkpoint_version'] = capability

    def legacy(selected, fetch, *, deadline_at):
        collected.append(selected)
        return []

    def rpc(operation, payload, **kwargs):
        calls.append(operation)
        if operation == 'community_collector_claim_category':
            return source
        if operation == STAGE:
            assert payload['p_events'] == []
            return 0
        if operation == RECORD:
            assert payload['p_error'] is None
            return None
        if operation == PUBLISH:
            return {'outcome': 'complete'}
        if operation == FINISH:
            return True
        raise AssertionError('Unsupported checkpoint RPC reached an old backend: ' + operation)

    monkeypatch.setattr(tourism, 'collect_legacy', legacy)
    monkeypatch.setattr(worker, 'supabase_rpc', rpc)
    monkeypatch.setattr(category, 'supabase_rpc', rpc)
    monkeypatch.setattr(category, 'sleep', lambda seconds: None)
    result = category.collect_category('html', 'private-test-ticket')
    assert result['complete'] == 1 and result['failed'] == 0
    assert collected == [source]
    assert calls == ['community_collector_claim_category', STAGE, RECORD, PUBLISH, FINISH]


def test_completed_checkpoint_survives_staging_failure_and_avoids_refetching_details(monkeypatch):
    state = Harness(monkeypatch, count=3)
    state.fail_stage_once = True
    first = state.run()
    assert first['failed'] == 1 and first['failure_scope'] == 'worker'
    assert state.calls[-1][1]['p_outcome'] == 'failed'
    assert state.checkpoint['cursor'] == state.checkpoint['manifest_count'] == 3
    assert not any(op == PUBLISH for op, _ in state.calls)
    last = state.run()
    assert last['complete'] == 1 and last['staged'] == 3
    assert state.checkpoint is None
    assert state.fetched.count(tourism.URL) == 2
    assert all(state.fetched.count(descriptor(i)[0]) == 1 for i in range(3))


@pytest.mark.parametrize('response', [None, {}, {'revision': True, 'checkpoint': None},
    {'revision': -1, 'checkpoint': None}, {'revision': 0, 'checkpoint': []},
    {'revision': 4, 'checkpoint': None}])
def test_invalid_checkpoint_read_never_fetches_stages_or_publishes(monkeypatch, response):
    state = Harness(monkeypatch)
    state.read_override = response
    result = state.run()
    assert result['error_code'] == 'fetch_checkpoint_invalid_response'
    assert result['failure_scope'] == 'worker'
    assert state.fetched == []
    assert [op for op, _ in state.calls] == [
        'community_collector_claim_category', READ, RECORD, FINISH]
    assert state.calls[-1][1]['p_outcome'] == 'failed'


@pytest.mark.parametrize('response', [None, {}, {'checkpoint_saved': False, 'revision': 1},
    {'checkpoint_saved': True, 'revision': True}, {'checkpoint_saved': True, 'revision': 0},
    worker.PreviewError('database_unavailable')])
def test_unacknowledged_checkpoint_is_not_a_successful_prefix(monkeypatch, response, caplog):
    state = Harness(monkeypatch)
    state.write_override = response
    result = state.run()
    assert result['failed'] == 1 and result['failure_scope'] == 'worker'
    assert 'fetch_pending' not in result
    assert not any(op in (STAGE, PUBLISH) for op, _ in state.calls)
    assert state.calls[-1][1]['p_outcome'] == 'failed'
    records = [json.loads(item.message) for item in caplog.records
               if item.name == 'roomquest.category_worker']
    assert records[0]['rpc_operation'] == WRITE
    assert records[0]['error_code'] in ('fetch_checkpoint_invalid_response', 'database_unavailable')
    assert 'private-test-ticket' not in caplog.text


def test_later_publisher_access_failure_preserves_prior_progress_and_normal_hold(monkeypatch):
    state = Harness(monkeypatch)
    state.run()
    checkpoint = deepcopy(state.checkpoint)
    state.fetch_error = 'publisher_http_403'
    result = state.run()
    assert result['failure_scope'] == 'source' and result['error_kind'] == 'access'
    assert state.checkpoint == checkpoint
    assert not any(op in (STAGE, PUBLISH) for op, _ in state.calls)
    assert state.calls[-1][1]['p_outcome'] == 'source_error'


def test_unbounded_publisher_wait_is_not_saved_or_finished_as_pending(monkeypatch):
    state = Harness(monkeypatch)
    state.pacing = 86401
    result = state.run()
    assert result['error_code'] == 'publisher_wait_requires_review'
    assert not any(op in (WRITE, STAGE, PUBLISH) for op, _ in state.calls)
    assert state.calls[-1][1]['p_outcome'] == 'source_error'
    assert next(data for op, data in state.calls if op == RECORD)['p_publisher_wait_unbounded'] is True


def test_raw_clock_parser_value_never_enters_diagnostics(monkeypatch, caplog):
    state = Harness(monkeypatch, count=1)
    item = descriptor(0)
    state.pages[item[0]] = detail(item, fields={'Start Time': 'private-arbitrary-clock-content'})
    result = state.run()
    assert result['error_code'] == 'invalid_html_event_payload'
    assert 'private-arbitrary-clock-content' not in caplog.text
    assert not any(op in (WRITE, STAGE, PUBLISH) for op, _ in state.calls)


def test_long_bounded_publisher_wait_is_persisted_without_sleeping_past_invocation(monkeypatch):
    state = Harness(monkeypatch)
    state.pacing = 30
    result = state.run()
    assert result['fetch_pending'] is True
    saved = next(data for op, data in state.calls if op == WRITE)
    assert saved['p_publisher_crawl_delay_seconds'] == 30
    assert state.waits == []


@pytest.mark.parametrize('operation,maximum', [(READ, 920_000), (WRITE, 150_000)])
def test_rpc_body_limit_is_larger_only_for_private_checkpoint_reads(monkeypatch, operation, maximum):
    monkeypatch.setenv('SUPABASE_URL', worker.ROOMQUEST_DB)
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY', 'test-publishable')
    monkeypatch.setenv('ROOMQUEST_COLLECTOR_TOKEN', '0' * 64)
    received = []

    def response(request, **kwargs):
        received.append(json.loads(request.data))
        return BytesIO(json.dumps({'value': 'x' * 200_000}).encode())

    monkeypatch.setattr('urllib.request.urlopen', response)
    if operation == READ:
        assert len(worker.supabase_rpc(operation, {})['value']) == 200_000
    else:
        with pytest.raises(worker.PreviewError, match='database_unavailable'):
            worker.supabase_rpc(operation, {})
    assert received == [{'p_token': '0' * 64}]
    monkeypatch.setattr('urllib.request.urlopen', lambda *_args, **_kwargs: BytesIO(b'x' * (maximum + 1)))
    with pytest.raises(worker.PreviewError, match='database_unavailable'):
        worker.supabase_rpc(operation, {})
