"""The manual audit stays source-scoped, bounded and read-only under failures."""
import json
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import Mock

import pytest

from scripts import capture_mecklenburg_batch3 as audit

FIXTURES = Path(__file__).parent / 'fixtures' / 'mecklenburg_batch3'


def fixture(name):
    return (FIXTURES / name).read_text()


def success(events=None):
    return {'p_error': None, 'p_parser_capability': 'publisher_event_candidates_v1',
            'p_events': events if events is not None else []}


def test_injected_success_calls_only_the_three_reviewed_sources_with_deadlines(monkeypatch, capsys):
    now, calls = [100.0], []
    monkeypatch.setattr(audit, 'monotonic', lambda: now[0])
    def preview(source, *, deadline_at):
        calls.append((dict(source), deadline_at))
        now[0] += 2
        return success([{'id': 'test', 'title': 'PUBLIC_BODY_SENTINEL', 'image_url': 'https://publisher.example/event.jpg'}])
    monkeypatch.setattr(audit.preview_worker, 'preview_source', preview)
    result = audit.audit()
    assert result['read_only'] and result['complete']
    assert [(s['source_key'], s['feed_url']) for s, _ in calls] == list(audit.SOURCES)
    assert len(calls) == 3
    assert all(s['kind'] == s['platform_adapter'] == 'html' and s['timezone'] == 'America/New_York'
               and set(s) == {'source_key', 'feed_url', 'kind', 'platform_adapter', 'timezone'} for s, _ in calls)
    assert [deadline for _, deadline in calls] == [141.0, 143.0, 145.0]
    assert all(row['candidate_count'] == row['candidate_image_count'] == 1 for row in result['sources'])
    stdout = capsys.readouterr().out
    assert 'PUBLIC_BODY_SENTINEL' not in stdout
    assert len(stdout.splitlines()) == 3


def test_failure_is_sanitized_and_other_sources_are_still_checked(monkeypatch, capsys):
    calls = []
    def preview(source, **kwargs):
        calls.append(source['source_key'])
        if len(calls) == 1:
            raise OSError('SENSITIVE_SENTINEL https://private.example/token')
        if len(calls) == 2:
            return {'p_error': 'robots_denied'}
        return success()
    monkeypatch.setattr(audit.preview_worker, 'preview_source', preview)
    result = audit.audit()
    assert not result['complete'] and len(calls) == 3
    assert [r.get('error') for r in result['sources']] == ['source_audit_failed', 'robots_denied', None]
    assert result['sources'][-1]['candidate_count'] == 0
    assert 'SENSITIVE_SENTINEL' not in json.dumps(result) + capsys.readouterr().out


def test_overall_exhaustion_does_not_start_more_requests_or_keep_late_results(monkeypatch):
    now, calls = [0.0], []
    monkeypatch.setattr(audit, 'monotonic', lambda: now[0])
    def preview(source, *, deadline_at):
        calls.append(deadline_at)
        now[0] = 136.0
        return success([{'id': 'late'}])
    monkeypatch.setattr(audit.preview_worker, 'preview_source', preview)
    result = audit.audit()
    assert calls == [41.0]
    assert not result['complete']
    assert all(r['error'] == 'collection_deadline' and 'events' not in r for r in result['sources'])


@pytest.mark.parametrize('result,code', [
    ({}, 'snapshot_shape_missing'),
    ({'p_error': None, 'p_events': []}, 'snapshot_capability_missing'),
    (success('invalid'), 'snapshot_records_invalid'),
    (success([None]), 'snapshot_records_invalid'),
    (success([{}] * (audit.MAX_RECORDS + 1)), 'snapshot_records_invalid'),
    ({'p_error': 'SENSITIVE_SENTINEL https://private.example'}, 'source_audit_failed'),
])
def test_partial_or_unrecognized_output_cannot_claim_complete(monkeypatch, capsys, result, code):
    monkeypatch.setattr(audit.preview_worker, 'preview_source', lambda *args, **kwargs: result)
    report = audit.audit()
    assert not report['complete']
    assert all(row['error'] == code for row in report['sources'])
    assert 'SENSITIVE_SENTINEL' not in json.dumps(report) + capsys.readouterr().out


@pytest.mark.parametrize('complete,exit_code', [(True, 0), (False, 1)])
def test_cli_writes_reviewable_receipt_and_returns_failure_status(monkeypatch, tmp_path, complete, exit_code):
    report = {'read_only': True, 'complete': complete, 'sources': []}
    target = tmp_path / 'audit.json'
    monkeypatch.setattr(audit, 'audit', lambda: report)
    monkeypatch.setattr(audit.sys, 'argv', ['capture_mecklenburg_batch3.py', '--output', str(target)])
    assert audit.main() == exit_code
    assert json.loads(target.read_text()) == report


def test_observer_records_id_mismatch_without_changing_calls_or_original_responses(monkeypatch, capsys):
    initial = fixture('good_calendar.html')
    request = audit.good_shepherd.calendar_request(initial)
    original_id = request['calendar_id']
    different_id = 'r999999999999999'
    rendered = fixture('good_calendar_rendered.html').replace(original_id, different_id)
    fetch, render = Mock(return_value=initial), Mock(return_value=rendered)
    monkeypatch.setattr(audit.preview_worker, 'fetch_publisher', fetch)
    monkeypatch.setattr(audit.preview_worker, 'render_good_shepherd_calendar', render)
    def preview(source, *, deadline_at):
        if source['source_key'] != audit.good_shepherd.SOURCE_KEY:
            return success()
        assert audit.preview_worker.fetch_publisher(
            source['feed_url'], 'text/html', respect_robots=True, deadline_at=deadline_at) == initial
        assert audit.preview_worker.render_good_shepherd_calendar(
            nonce=request['nonce'], args=request['args'], deadline_at=deadline_at) == rendered
        raise audit.preview_worker.PreviewError('good_shepherd_calendar_identity_unverified')
    monkeypatch.setattr(audit.preview_worker, 'preview_source', preview)
    report = audit.audit()
    receipt = report['sources'][2]
    details = receipt['transport_observation']
    assert receipt['outcome'] == 'failed'
    assert details['calendar_get_calls'] == details['render_calls'] == 1
    assert details['placeholder_count'] == details['rendered_calendar_count'] == 1
    assert details['placeholder_id_valid'] and details['rendered_id_valid']
    assert details['placeholder_render_id_equal'] is False
    assert details['pagination_selector_count'] == 0
    assert details['month_selector_count'] == 1 and details['month_grid_count'] == 6
    assert details['rendered_label'] != details['placeholder_label']
    assert 'CALENDAR_RENDERED-202611' in receipt['calendar_diagnostic_html']
    assert original_id not in json.dumps(report) and different_id not in json.dumps(report)
    fetch.assert_called_once()
    render.assert_called_once_with(nonce=request['nonce'], args=request['args'],
                                   deadline_at=fetch.call_args.kwargs['deadline_at'])
    assert audit.preview_worker.fetch_publisher is fetch
    assert audit.preview_worker.render_good_shepherd_calendar is render
    assert '<section' not in capsys.readouterr().out


def test_observer_retains_matching_identity_and_removes_active_content_tokens_and_other_programs(monkeypatch):
    initial = fixture('good_calendar.html')
    request = audit.good_shepherd.calendar_request(initial)
    rendered = fixture('good_calendar_rendered.html')
    rendered = rendered.replace('</section>',
        '<script>SECRET_SCRIPT</script><form>SECRET_FORM<input value="SECRET_INPUT"></form>'
        '<a href="https://private.example/SECRET_URL" onclick="SECRET_HANDLER">public</a>'
        '<p>' + request['nonce'] + ' ' + request['args'] + '</p></section>')
    fetch, render = Mock(return_value=initial), Mock(return_value=rendered)
    monkeypatch.setattr(audit.preview_worker, 'fetch_publisher', fetch)
    monkeypatch.setattr(audit.preview_worker, 'render_good_shepherd_calendar', render)
    receipt = {}
    with audit._observe_existing_transport(audit.good_shepherd.SOURCE_KEY, receipt):
        assert audit.preview_worker.fetch_publisher(audit.good_shepherd.CALENDAR, 'text/html') == initial
        assert audit.preview_worker.render_good_shepherd_calendar(nonce=request['nonce'], args=request['args']) == rendered
    markup = receipt['calendar_diagnostic_html']
    assert receipt['transport_observation']['placeholder_render_id_equal'] is True
    assert receipt['transport_observation']['calendar_diagnostic_truncated'] is False
    assert 'CALENDAR_PLACEHOLDER' in markup and 'CALENDAR_RENDERED' not in markup
    assert 'Food Pantry' in markup and '[outside pantry scope]' in markup
    assert request['nonce'] not in markup and request['args'] not in markup
    assert 'SECRET_' not in markup and 'private.example' not in markup
    assert '<script' not in markup and '<form' not in markup and 'onclick' not in markup
    assert len(markup) <= audit.MAX_DIAGNOSTIC_MARKUP


@pytest.mark.parametrize('status', [401, 403])
def test_observer_keeps_robots_http_status_without_retries_or_sensitive_exception_details(monkeypatch, capsys, status):
    def blocked(*args, **kwargs):
        try:
            raise HTTPError('https://private.example/SECRET_URL', status, 'SECRET_MESSAGE', {'Authorization': 'SECRET_HEADER'}, None)
        except HTTPError as error:
            raise audit.preview_worker.PreviewError('robots_denied') from error
    fetch = Mock(side_effect=blocked)
    render = Mock()
    monkeypatch.setattr(audit.preview_worker, 'fetch_publisher', fetch)
    monkeypatch.setattr(audit.preview_worker, 'render_good_shepherd_calendar', render)
    def preview(source, **kwargs):
        if source['source_key'] == audit.coopers_landing.SOURCE_KEY:
            audit.preview_worker.fetch_publisher(source['feed_url'], 'text/html', respect_robots=True)
        return success()
    monkeypatch.setattr(audit.preview_worker, 'preview_source', preview)
    report = audit.audit()
    receipt = report['sources'][1]
    assert receipt['error'] == 'robots_denied'
    assert receipt['transport_observation'] == {'transport_error_type': 'PreviewError', 'caused_by_http_status': status}
    fetch.assert_called_once()
    render.assert_not_called()
    assert report['sources'][2]['outcome'] == 'complete'
    assert audit.preview_worker.fetch_publisher is fetch
    assert 'SECRET_' not in json.dumps(report) + capsys.readouterr().out


def test_parsed_robots_denial_does_not_invent_an_http_status(monkeypatch):
    error = audit.preview_worker.PreviewError('robots_denied')
    fetch = Mock(side_effect=error)
    monkeypatch.setattr(audit.preview_worker, 'fetch_publisher', fetch)
    receipt = {}
    with pytest.raises(audit.preview_worker.PreviewError) as caught:
        with audit._observe_existing_transport(audit.coopers_landing.SOURCE_KEY, receipt):
            audit.preview_worker.fetch_publisher(audit.coopers_landing.CALENDAR, 'text/html')
    assert caught.value is error
    assert receipt['transport_observation'] == {'transport_error_type': 'PreviewError'}
    fetch.assert_called_once()
    assert audit.preview_worker.fetch_publisher is fetch


def test_diagnostic_capture_is_bounded_and_does_not_turn_an_unrecognized_response_into_success(monkeypatch):
    raw = 'x' * (audit.MAX_DIAGNOSTIC_INPUT + 1)
    fetch, render = Mock(return_value=raw), Mock(return_value=raw)
    monkeypatch.setattr(audit.preview_worker, 'fetch_publisher', fetch)
    monkeypatch.setattr(audit.preview_worker, 'render_good_shepherd_calendar', render)
    receipt = {}
    with audit._observe_existing_transport(audit.good_shepherd.SOURCE_KEY, receipt):
        assert audit.preview_worker.fetch_publisher(audit.good_shepherd.CALENDAR, 'text/html') == raw
        assert audit.preview_worker.render_good_shepherd_calendar(nonce='0123456789', args='a' * 40) == raw
    assert receipt['transport_observation']['placeholder_observation_failed'] is True
    assert receipt['transport_observation']['render_observation_failed'] is True
    assert 'calendar_diagnostic_html' not in receipt and 'outcome' not in receipt
    fetch.assert_called_once()
    render.assert_called_once()
