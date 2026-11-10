from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from roomquest import civic_schedule, legistar, preview_worker as worker, virginia_civic

FIXTURES = Path(__file__).parent / 'fixtures' / 'civic'
NOW = datetime(2026, 11, 9, 10, tzinfo=timezone.utc)
SOURCES = [
    (legistar.source_payload('richmond_va_legistar'), 'richmondva_legistar.json', ('webapi.legistar.com',), 13),
    (legistar.source_payload('alexandria_va_legistar'), 'alexandria_legistar.json', ('webapi.legistar.com',), 5),
    (virginia_civic.source_payload(virginia_civic.COMMONWEALTH), 'commonwealth.html', ('commonwealthcalendar.virginia.gov',), 69),
    (virginia_civic.source_payload(virginia_civic.DMV), 'dmv_connect.html', ('www.dmv.virginia.gov',), 10),
    (civic_schedule.public_works_source(), 'south_hill_public_works.html', ('www.southhillva.gov',), 2),
]


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    class ClockMeta(type):
        def __instancecheck__(cls, value):
            return isinstance(value, datetime)

    class Frozen(datetime, metaclass=ClockMeta):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    for module in (civic_schedule, legistar, virginia_civic, worker):
        monkeypatch.setattr(module, 'datetime', Frozen)
        monkeypatch.setattr(module, 'monotonic', lambda: 100.0)


@pytest.mark.parametrize('source,name,hosts,count', SOURCES)
def test_real_source_fixtures_use_guarded_dispatch_and_existing_v2_staging(monkeypatch, source, name, hosts, count):
    requests, calls = [], []

    def fetch(url, accept, **kwargs):
        requests.append(url)
        assert kwargs['respect_robots'] is True
        assert kwargs['allowed_hosts'] == hosts
        assert kwargs['deadline_at'] == 125.0
        return (FIXTURES / name).read_text()

    def rpc(name, payload):
        calls.append((name, deepcopy(payload)))
        return len(payload.get('p_events', []))

    monkeypatch.setattr(worker, 'fetch_publisher', fetch)
    monkeypatch.setattr(worker, 'supabase_rpc', rpc)
    handoff = {}
    result = worker._process_claimed_source(source, publisher_handoff=handoff)
    assert result['complete'] == 1 and result['failed'] == 0 and result['staged'] == count
    assert len(requests) == 1
    assert calls[-1][0] == 'community_collector_record_preview_v2'
    assert all(name == 'community_collector_record_staged_events' for name, _ in calls[:-1])
    assert all(len(payload['p_events']) <= 20 for _, payload in calls[:-1])
    rows = [row for _, payload in calls[:-1] for row in payload['p_events']]
    assert all(row['civic']['version'] == 1 for row in rows)
    assert all(row['civic']['source_url'] == row['event_url'] for row in rows)
    assert 'p_parser_capability' not in calls[-1][1]
    assert 'p_events' not in calls[-1][1]
    assert handoff['ready_at'] >= 101.0
    if source['source_key'] == virginia_civic.COMMONWEALTH:
        notices = [row for row in rows if row['civic']['time_precision'] == 'date']
        assert notices == []  # All three captured All Day rows are meetings with unresolved times.


@pytest.mark.parametrize('source,name,hosts,count', SOURCES)
def test_transport_failure_records_error_without_staging(monkeypatch, source, name, hosts, count):
    calls = []

    def fail(*args, **kwargs):
        raise worker.PreviewError('http_403')

    monkeypatch.setattr(worker, 'fetch_publisher', fail)
    monkeypatch.setattr(worker, 'supabase_rpc', lambda name, payload: calls.append((name, payload)))
    result = worker._process_claimed_source(source)
    assert result['complete'] == 0 and result['failed'] == 1 and result['staged'] == 0
    assert len(calls) == 1 and calls[0][0] == 'community_collector_record_preview_v2'
    assert calls[0][1]['p_error'] == 'http_403'


def test_failed_second_staging_batch_never_records_success(monkeypatch):
    monkeypatch.setattr(worker, 'fetch_publisher', lambda *a, **k: (FIXTURES / 'commonwealth.html').read_text())
    calls = []

    def rpc(name, payload):
        calls.append((name, deepcopy(payload)))
        if name == 'community_collector_record_staged_events' and len(calls) == 2:
            raise worker.PreviewError('database_unavailable')
        return len(payload.get('p_events', []))

    monkeypatch.setattr(worker, 'supabase_rpc', rpc)
    result = worker._process_claimed_source(virginia_civic.source_payload(virginia_civic.COMMONWEALTH))
    assert result['complete'] == 0 and result['failed'] == 1
    assert calls[-1][0] == 'community_collector_record_preview_v2'
    assert calls[-1][1]['p_error'] == 'database_unavailable'


def test_existing_civic_ics_path_forwards_only_explicit_source_contract_metadata(monkeypatch):
    from roomquest import ics_adapter
    source = {'source_key': 'halifax_county_main_va', 'kind': 'ical', 'platform_adapter': 'ical',
              'feed_url': worker.VIRGINIA_CIVIC_ICS['halifax_county_main_va'],
              'timezone': 'America/New_York', 'civic_contract_version': 1,
              'civic_jurisdiction_id': 'us-va-halifax-county', 'civic_jurisdiction_name': 'Halifax County'}
    observed = []
    monkeypatch.setattr(worker, 'fetch_publisher', lambda *a, **k: 'BEGIN:VCALENDAR\nEND:VCALENDAR')
    monkeypatch.setattr(ics_adapter, 'parse', lambda payload, config, **kwargs: observed.append(config) or [])
    assert worker.preview_source(source)['p_events'] == []
    assert observed == [{'url': source['feed_url'], 'source_key': source['source_key'],
                         **{key: source[key] for key in ('timezone', 'civic_contract_version',
                             'civic_jurisdiction_id', 'civic_jurisdiction_name')}}]


def test_public_works_dispatch_accepts_actual_backend_claim_display_name(monkeypatch):
    source = {**civic_schedule.public_works_source(), 'action': 'collect',
              'civic_jurisdiction_name': 'South Hill, Virginia'}
    monkeypatch.setattr(worker, 'fetch_publisher',
                        lambda *a, **k: (FIXTURES / 'south_hill_public_works.html').read_text())
    result = worker.preview_source(source)
    assert result['p_future_count'] == 2
    assert all(row['civic']['jurisdiction_id'] == 'us-va-south-hill' for row in result['p_events'])


@pytest.mark.parametrize('version', [None, True, '1', 2])
def test_public_works_dispatch_requires_integer_capability_before_fetch(monkeypatch, version):
    source = {**civic_schedule.public_works_source(), 'civic_contract_version': version}
    monkeypatch.setattr(worker, 'fetch_publisher', lambda *a, **k: pytest.fail('Network must not be used'))
    with pytest.raises(worker.PreviewError, match='unregistered_public_works_source'):
        worker.preview_source(source)
