import json
import sys
from datetime import datetime, timezone

import pytest

from roomquest import civic_local_calendars as local_civic
from scripts import capture_civic_sources as capture


def output(source):
    rows = [{'id': 'public-test-record', 'title': 'Public notice', 'lat': None, 'lng': None,
             'civic': {'version': 1, 'time_precision': 'date'}}]
    return {'p_source_key': source['source_key'], 'p_error': None, 'p_events': rows, 'p_future_count': len(rows)}


@pytest.fixture(autouse=True)
def forbid_writes(monkeypatch):
    monkeypatch.setattr(capture.preview_worker, 'supabase_rpc',
                        lambda *a, **k: pytest.fail('Read-only audit attempted a database RPC'))


def test_fixed_inventory_and_bounded_preview_receipts_do_not_claim_or_publish(monkeypatch):
    calls = []
    monkeypatch.setattr(capture, 'monotonic', lambda: 100.0)
    monkeypatch.setenv('GITHUB_SHA', 'a' * 40)

    def preview(source, *, deadline_at):
        calls.append((source, deadline_at))
        return output(source)

    monkeypatch.setattr(capture.preview_worker, 'preview_source', preview)
    result = capture.audit(overall_seconds=300)
    assert len(calls) == 9 and all(deadline == 141 for _, deadline in calls)
    assert all(type(source['civic_contract_version']) is int and source['civic_contract_version'] == 1
               and source['civic_jurisdiction_id'].startswith(('us-va', 'us-fl', 'us-md')) for source, _ in calls)
    assert result['complete'] and result['read_only']
    assert result['collector_sha'] == 'a' * 40
    assert all(len(value) == 64 for value in result['collector_files_sha256'].values())
    assert result['counts'] == {'sources': 9, 'complete': 9, 'failed': 0, 'candidates': 9, 'dated_notices': 9}
    scopes = {source['source_key']: source['scope'] for source in result['sources']}
    assert scopes['virginia_dmv_connect'] == 'publisher_first_page'
    assert scopes['clarksville_municipal_notices_va'] == 'publisher_news_first_page'
    assert len({source['source_key'] for source, _, _ in capture.source_specs()}) == 9


@pytest.mark.parametrize('error,code,category', [
    (capture.preview_worker.PreviewError('dns_unavailable'), 'dns_unavailable', 'dns_resolution'),
    (capture.preview_worker.PreviewError('publisher_http_403'), 'publisher_http_403', 'access'),
    (RuntimeError('secret-token https://untrusted.example/private'), 'source_audit_failed', 'unexpected'),
])
def test_failures_are_safe_failed_receipts_not_healthy_empty(monkeypatch, capsys, error, code, category):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(capture.preview_worker, 'preview_source', fail)
    result = capture.audit()
    assert not result['complete'] and result['counts']['failed'] == 9
    assert all(row['error'] == code and row['error_category'] == category for row in result['sources'])
    assert 'secret-token' not in json.dumps(result) + capsys.readouterr().out
    assert all('events' not in source for source in result['sources'])


def test_incomplete_output_and_missing_civic_metadata_are_failed(monkeypatch):
    def bad(source, **kwargs):
        result = output(source)
        result['p_events'][0].pop('civic')
        return result

    monkeypatch.setattr(capture.preview_worker, 'preview_source', bad)
    result = capture.audit()
    # Existing South Hill calendar intentionally contains mixed ordinary and civic records.
    assert result['counts']['failed'] == 8
    assert all(source['error'] == 'civic_metadata_missing' for source in result['sources'][:-1])


def test_timed_notice_receipt_excludes_date_and_window_notices(monkeypatch):
    def mixed(source, **kwargs):
        rows = [
            {'id': 'date', 'civic_notice': True, 'civic': {'version': 1, 'time_precision': 'date'}},
            {'id': 'window', 'civic_notice': True, 'civic': {'version': 1, 'time_precision': 'window'}},
            {'id': 'timed-service', 'civic_notice': True, 'civic': {'version': 1, 'time_precision': 'timed'}},
            {'id': 'meeting', 'civic': {'version': 1, 'time_precision': 'timed'}},
        ]
        return {'p_source_key': source['source_key'], 'p_error': None, 'p_events': rows, 'p_future_count': 4}

    monkeypatch.setattr(capture.preview_worker, 'preview_source', mixed)
    result = capture.audit()
    assert result['complete']
    for source in result['sources']:
        assert source['candidate_count'] == 4
        assert source['dated_notice_count'] == 2
        assert source['timed_candidate_count'] == 2
        assert source['timed_notice_count'] == 1


def test_overall_deadline_skips_later_requests_and_still_returns_every_inventory_receipt(monkeypatch):
    clock = iter(range(50))
    monkeypatch.setattr(capture, 'monotonic', lambda: next(clock))
    monkeypatch.setattr(capture.preview_worker, 'preview_source', lambda *_a, **_k: pytest.fail('Expired audit fetched a source'))
    result = capture.audit(overall_seconds=1)
    assert not result['complete'] and len(result['sources']) == 9
    assert all(source['network_skipped'] and not source['source_preview_attempted'] for source in result['sources'])


def test_failed_cli_writes_complete_artifact_and_exits_nonzero(monkeypatch, tmp_path):
    def fail(*args, **kwargs):
        raise capture.preview_worker.PreviewError('dns_unavailable')

    path = tmp_path / 'civic-audit.json'
    monkeypatch.setattr(capture.preview_worker, 'preview_source', fail)
    monkeypatch.setattr(sys, 'argv', ['capture_civic_sources.py', '--output', str(path)])
    assert capture.main() == 1
    result = json.loads(path.read_text())
    assert not result['complete'] and result['counts']['failed'] == 9


@pytest.mark.parametrize('seconds', [0, -1, 601, True, 1.5])
def test_audit_deadline_cannot_be_unbounded(seconds):
    with pytest.raises(ValueError, match='invalid_audit_deadline'):
        capture.audit(overall_seconds=seconds)


_NOW = datetime(2026, 11, 10, 16, tzinfo=timezone.utc)


def test_tampa_only_uses_regular_meetings_with_the_reviewed_venue(monkeypatch):
    monkeypatch.setattr(capture.preview_worker, '_future_datetime', lambda value: value.astimezone(timezone.utc))
    start = '2026-11-19T09:00:00-05:00'
    regular = {'ID': 2941, 'MeetingTypeName': 'Council Regular', 'Time': start,
               'TimeStamp': int(datetime.fromisoformat(start).timestamp()), 'Location': None,
               'Name': 'City Council Regular - November 19, 2026'}
    meetings = [regular,
                {**regular, 'ID': 2986, 'MeetingTypeName': 'Council Special'},
                {**regular, 'ID': 3000, 'Name': 'City Council Regular Addendum - November 19, 2026'},
                {**regular, 'ID': 2942, 'Location': 'Offsite facility'},
                {**regular, 'ID': 2943, 'Name': 'CANCELED - ' + regular['Name']}]
    payload = 'showSearchResults(new SearchResults(' + json.dumps({'Meetings': meetings}) + '));'
    rows = local_civic.collect(local_civic.source_payload(local_civic.TAMPA), lambda *_: payload, now=_NOW)
    assert [row['id'] for row in rows] == ['tampa-agenda:2941', 'tampa-agenda:2943']
    assert rows[0]['civic']['jurisdiction_id'] == 'us-fl-tampa'
    assert rows[0]['event_url'] == local_civic.TAMPA_AGENDAS
    assert rows[0]['venue_address'] == local_civic.TAMPA_ADDRESS
    assert not rows[0].get('ends_at') and rows[0]['lat'] is None
    assert rows[1]['publisher_status'] == 'cancelled'


def test_howard_keeps_holiday_date_and_holds_unresolved_venues(monkeypatch):
    monkeypatch.setattr(capture.preview_worker, '_future_datetime', lambda value: value.astimezone(timezone.utc))
    meeting = {'id': '10006', 'url': 'https://cc.howardcountymd.gov/calendar/inspector-general-advisory-board-11',
               'title': 'Inspector General Advisory Board', 'date_published': '2026-12-03',
               'content_html': '06:30 PM', 'content_text': 'taskforces', 'summary': 'george-howard-building'}
    holiday = {**meeting, 'id': '10121', 'url': 'https://cc.howardcountymd.gov/calendar/thanksgiving-day-holiday-office-closed-3',
               'title': 'Thanksgiving Day Holiday - Office Closed', 'date_published': '2026-11-26',
               'content_html': '12:00 AM', 'content_text': 'non-legislative-not-on-cascade'}
    unresolved = {**meeting, 'id': '10007', 'summary': 'hybrid'}
    payload = json.dumps({'feed_url': local_civic.HOWARD_FEED, 'items': [meeting, holiday, unresolved]})
    rows = local_civic.collect(local_civic.source_payload(local_civic.HOWARD), lambda *_: payload, now=_NOW)
    assert [row['id'] for row in rows] == ['howard-council:10121', 'howard-council:10006']
    assert rows[0]['civic_notice'] and rows[0]['civic']['jurisdiction_id'] == 'us-md-howard'
    assert rows[0]['starts_on'] == '2026-11-26' and rows[0]['ends_on'] == '2026-11-27'
    assert rows[1]['venue_address'] == local_civic.HOWARD_ADDRESS
    assert rows[1]['starts_at'] == '2026-12-03T23:30:00+00:00'


@pytest.mark.parametrize('key', [local_civic.TAMPA, local_civic.HOWARD])
def test_civic_scope_must_match_before_fetch(key):
    source = local_civic.source_payload(key)
    source['civic_jurisdiction_id'] = 'us'
    with pytest.raises(ValueError, match='unregistered_local_civic_source'):
        local_civic.collect(source, lambda *_: pytest.fail('Mismatched jurisdiction fetched a publisher'))
