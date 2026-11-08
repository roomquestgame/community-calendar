"""Both captured API pages must complete before the reviewed source can stage."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

from roomquest import holly_hill_civic as civic, holly_hill_sources as sources
from roomquest import preview_worker as worker, publisher_evidence

FIXTURES = Path(__file__).parent / 'fixtures' / 'holly_hill_civic'
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    class ClockMeta(type):
        def __instancecheck__(cls, value):
            return isinstance(value, datetime)

    class Frozen(datetime, metaclass=ClockMeta):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    for module in (civic, worker):
        monkeypatch.setattr(module, 'datetime', Frozen)


def pages():
    return [json.loads((FIXTURES / f'scworks_page{page}.json').read_text()) for page in (1, 2)]


def fetcher(payloads=None):
    payloads = pages() if payloads is None else payloads

    def fetch(url, accept, **kwargs):
        parsed = urlsplit(url)
        assert parsed.scheme == 'https' and parsed.netloc == 'scworkstrident.org'
        assert parsed.path == '/wp-json/tribe/events/v1/events'
        assert accept == 'application/json'
        query = parse_qs(parsed.query)
        assert query['start_date'] == ['2026-11-08']
        assert query['end_date'] == ['2027-01-07']
        if kwargs:
            assert kwargs['respect_robots'] is True
            assert kwargs['allowed_hosts'] == ('scworkstrident.org',)
            assert kwargs['deadline_at'] is not None
        return json.dumps(payloads[int(query['page'][0]) - 1])
    return Mock(side_effect=fetch)


def test_full_85_record_snapshot_retains_57_physical_occurrences_and_exact_addresses():
    fetch = fetcher()
    rows = civic.collect_tec(sources.source_payload(civic.SCWORKS), fetch, now=NOW)
    assert fetch.call_count == 2
    assert sum(len(page['events']) for page in pages()) == 85
    assert len(rows) == len({row['id'] for row in rows}) == 57
    assert not any('virtual' in row['title'].lower() or 'closed' in row['title'].lower() for row in rows)
    first = rows[0]
    assert first['starts_at'] == '2026-11-09T14:00:00+00:00'
    assert first['venue_address'] == '1325-A Boone Hill Road, Summerville, SC 29483'
    assert all(row['lat'] is None and row['lng'] is None for row in rows)
    assert all(row['details_evidence_url'] == row['event_url'] for row in rows)
    assert all(publisher_evidence.family(civic.SCWORKS, row['event_url']) == 'holly_hill:' + civic.SCWORKS for row in rows)
    assert any(row['venue_address'] == '221 Easter Main Street, Moncks Corner, SC 29461' for row in rows)
    # Preserve the publisher's spelling for normal address verification; do not silently geocode a correction.
    assert not any(row['venue_address'].startswith('221 East Main') for row in rows)


@pytest.mark.parametrize('mutation,reason', [
    ('total', 'wordpress_snapshot_changed'), ('repeat', 'publisher_event_identity_changed'),
    ('missing', 'wordpress_snapshot_changed'), ('next', 'wordpress_snapshot_changed'),
])
def test_changed_or_incomplete_late_page_never_becomes_a_partial_success(mutation, reason):
    payloads = pages()
    if mutation == 'total':
        payloads[1]['total'] += 1
    elif mutation == 'repeat':
        payloads[1]['events'][0] = deepcopy(payloads[0]['events'][0])
    elif mutation == 'missing':
        payloads[1]['events'].pop()
    else:
        payloads[1]['next_rest_url'] = 'https://unreviewed.example/calendar'
    with pytest.raises(ValueError, match=reason):
        civic.collect_tec(sources.source_payload(civic.SCWORKS), fetcher(payloads), now=NOW)


def test_arbitrary_next_link_is_not_followed():
    payloads = pages()
    payloads[0]['next_rest_url'] = 'http://127.0.0.1/private'
    fetch = fetcher(payloads)
    assert len(civic.collect_tec(sources.source_payload(civic.SCWORKS), fetch, now=NOW)) == 57
    assert all(call.args[0].startswith(civic.SOURCES[civic.SCWORKS]['url'] + '?') for call in fetch.call_args_list)


def test_real_preview_stages_complete_snapshot_and_uses_versioned_recorder(monkeypatch):
    fetch = fetcher()
    monkeypatch.setattr(worker, 'fetch_publisher', fetch)
    calls = []
    def rpc(name, payload):
        calls.append((name, deepcopy(payload)))
        return len(payload.get('p_events', []))
    monkeypatch.setattr(worker, 'supabase_rpc', rpc)
    result = worker._process_claimed_source(sources.source_payload(civic.SCWORKS))
    assert result == {'complete': 1, 'failed': 0, 'staged': 57}
    assert calls[-1][0] == 'community_collector_record_preview_v3'
    assert calls[-1][1]['p_future_count'] == 57
    assert calls[-1][1]['p_parser_capability'] == 'publisher_event_candidates_v1'
    assert sum(len(payload['p_events']) for _, payload in calls[:-1]) == 57
    assert all(name == 'community_collector_record_staged_events' for name, _ in calls[:-1])


def test_second_page_transport_failure_records_error_without_staging(monkeypatch):
    page1 = json.dumps(pages()[0])
    monkeypatch.setattr(worker, 'fetch_publisher', Mock(side_effect=[page1, worker.PreviewError('publisher_pacing_deferred')]))
    calls = []
    monkeypatch.setattr(worker, 'supabase_rpc', lambda name, payload: calls.append((name, deepcopy(payload))))
    result = worker._process_claimed_source(sources.source_payload(civic.SCWORKS))
    assert (result['complete'], result['failed'], result['staged']) == (0, 1, 0)
    assert result['error_kind'] == 'pacing' and result['error_code'] == 'publisher_pacing_deferred'
    assert len(calls) == 1 and calls[0][0] == 'community_collector_record_preview_v3'
    assert calls[0][1]['p_error'] == 'publisher_pacing_deferred'
    assert calls[0][1]['p_future_count'] == 0 and calls[0][1]['p_samples'] == []


@pytest.mark.parametrize('field,value', [
    ('feed_url', 'https://scworkstrident.org/events/?tribe_redirected=1'),
    ('kind', 'html'), ('platform_adapter', 'html'), ('timezone', 'UTC'),
])
def test_unreviewed_source_tuple_fails_before_transport(monkeypatch, field, value):
    fetch = Mock()
    monkeypatch.setattr(worker, 'fetch_publisher', fetch)
    source = sources.source_payload(civic.SCWORKS) | {field: value}
    with pytest.raises(worker.PreviewError, match='unregistered_holly_hill_source'):
        worker.preview_source(source)
    fetch.assert_not_called()
