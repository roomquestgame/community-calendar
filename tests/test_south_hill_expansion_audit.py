"""The allowlisted acceptance audit is read-only and cannot certify partial data."""
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest

from roomquest import preview_worker as worker
from scripts import capture_south_hill_expansion as audit

KEY = 'mcgregor_hall_henderson_nc'
BODY = 'PUBLIC_DOCUMENT_BODY_SENTINEL'


@pytest.fixture
def setup(monkeypatch):
    transport = Mock(return_value=BODY)
    database = Mock(side_effect=AssertionError('actual database must not run'))
    monkeypatch.setattr(worker, 'fetch_publisher', transport)
    monkeypatch.setattr(worker, 'supabase_rpc', database)
    results = {}
    def preview(source, *, deadline_at):
        worker.fetch_publisher(source['feed_url'], 'text/html', respect_robots=True,
                               allowed_hosts=(urlsplit(source['feed_url']).hostname,), deadline_at=deadline_at)
        return deepcopy(results.get(source['source_key'], {
            'p_source_key': source['source_key'], 'p_error': None,
            'p_future_count': 1, 'p_parser_capability': 'publisher_event_candidates_v1',
            'p_events': [{'id': 'test:one', 'title': 'Public performance',
                          'description': 'FULL_PROSE_SENTINEL', 'headers': {'Authorization': 'SECRET'},
                          'starts_at': '2026-12-01T20:00:00Z'}]}))
    route = Mock(side_effect=preview)
    monkeypatch.setattr(worker, 'preview_source', route)
    return transport, database, results, route


def run(keys=None, **kwargs):
    with redirect_stdout(io.StringIO()):
        return audit.audit(keys or [KEY], **kwargs)


def test_exact_source_scope_and_real_town_claim_capabilities():
    assert set(audit.SOURCES) == {KEY, 'victoria_town_calendar_va',
                                 'vance_county_arts_council_nc', 'south_hill_town_va'}
    town = audit.source('south_hill_town_va')
    assert town['civic_contract_version'] == 1
    assert town['civic_jurisdiction_id'] == 'us-va-south-hill'
    assert type(town['south_hill_market_contract_version']) is int
    assert town['south_hill_market_contract_version'] == 1
    assert 'civic_contract_version' not in audit.source(KEY)
    assert 'venue_association_contract_version' not in audit.source(KEY)
    assert 'venue_association_contract_version' not in town
    for key in ('victoria_town_calendar_va', 'vance_county_arts_council_nc'):
        assert type(audit.source(key)['venue_association_contract_version']) is int
        assert audit.source(key)['venue_association_contract_version'] == 1
    with pytest.raises(ValueError, match='unreviewed_audit_source'):
        audit.audit(['unregistered'])


def test_normal_transport_preserved_with_bounded_hashes_and_no_database_calls(setup):
    transport, database, _, route = setup
    report = run(list(audit.SOURCES))
    assert report['complete'] and report['read_only'] and report['authoritative_state_unchanged']
    assert report['collection_ready'] is False
    assert report['counts'] == {'parsed': 4, 'blocked': 0, 'candidates': 4}
    assert route.call_count == transport.call_count == 4
    for source, call in zip(report['sources'], transport.call_args_list):
        assert call.kwargs['respect_robots'] is True
        assert call.kwargs['allowed_hosts'] == (urlsplit(source['feed_url']).hostname,)
        assert call.kwargs['deadline_at'] is not None
        assert source['documents'][0]['sha256'] == hashlib.sha256(BODY.encode()).hexdigest()
        assert source['hold_cleared'] is False
    database.assert_not_called()
    serialized = json.dumps(report)
    assert BODY not in serialized and 'FULL_PROSE_SENTINEL' not in serialized and 'SECRET' not in serialized


def test_capture_files_are_exact_fetched_public_bodies_not_extra_requests(setup, tmp_path):
    transport, database, _, _ = setup
    report = run(documents_dir=tmp_path)
    doc = report['sources'][0]['documents'][0]
    assert (tmp_path / doc['artifact_file']).read_text() == BODY
    assert transport.call_count == 1
    database.assert_not_called()


def test_bounded_candidate_receipt_preserves_inference_evidence(setup):
    _, _, results, _ = setup
    association = {'method': 'owner_authorized_inferred_venue_association',
                   'evidence_urls': ['https://victoriava.net/community-centers'],
                   'matched_activity': 'Skate Night', 'venue_name': 'Victoria-Lunenburg Community Centre',
                   'venue_address': '1421 6th Street, Victoria, VA 23974'}
    results[KEY] = {'p_source_key': KEY, 'p_error': None, 'p_future_count': 1,
                    'p_parser_capability': 'publisher_event_candidates_v1',
                    'p_events': [{'id': 'test:one', 'title': 'Skate Night',
                                  'venue_association': association,
                                  'location_provenance': association['method']}]}
    candidate = run()['sources'][0]['candidates'][0]
    assert candidate['venue_association'] == association
    assert candidate['location_provenance'] == association['method']


@pytest.mark.parametrize('change', [
    {'p_source_key': 'other'}, {'p_future_count': 0}, {'p_future_count': True},
    {'p_parser_capability': 'other'}, {'p_error': 'upstream_failure'},
    {'p_events': []}, {'p_events': [None]}, {'p_events': [{'id': ''}]},
    {'p_events': [{'id': 'duplicate'}, {'id': 'duplicate'}], 'p_future_count': 2},
])
def test_mismatched_source_count_identity_and_capability_never_certify_snapshot(setup, change):
    _, _, results, _ = setup
    value = {'p_source_key': KEY, 'p_error': None, 'p_future_count': 1,
             'p_parser_capability': 'publisher_event_candidates_v1', 'p_events': [{'id': 'one'}]}
    value.update(change)
    results[KEY] = value
    report = run()
    row = report['sources'][0]
    assert not report['complete'] and row['outcome'] == 'blocked'
    assert 'candidates' not in row and 'candidate_count' not in row


def test_empty_complete_source_remains_empty_and_does_not_clear_hold(setup):
    _, _, results, _ = setup
    results[KEY] = {'p_source_key': KEY, 'p_error': None, 'p_future_count': 0,
                    'p_parser_capability': 'publisher_event_candidates_v1', 'p_events': []}
    row = run()['sources'][0]
    assert row['complete'] and row['candidate_count'] == 0 and row['hold_cleared'] is False


def test_accidental_preview_database_call_is_blocked_before_rpc(setup):
    _, database, _, route = setup
    route.side_effect = lambda *args, **kwargs: worker.supabase_rpc('claim', {})
    row = run()['sources'][0]
    assert row['error'] == 'read_only_audit_rpc_forbidden'
    database.assert_not_called()


@pytest.mark.parametrize('code', ['dns_unavailable', 'robots_denied', 'publisher_http_403', 'publisher_rate_limited'])
def test_transport_failure_is_reported_once_without_fallback_or_partial_rows(setup, code):
    transport, _, _, _ = setup
    transport.side_effect = worker.PreviewError(code)
    row = run()['sources'][0]
    assert row['error'] == code and row['outcome'] == 'blocked'
    assert row['documents'] == [] and 'candidates' not in row
    assert transport.call_count == 1


def test_transport_policy_downgrade_is_rejected_before_network(setup):
    transport, _, _, route = setup
    route.side_effect = lambda source, **kw: worker.fetch_publisher(
        source['feed_url'], 'text/html', respect_robots=False,
        allowed_hosts=('www.mcgregorhall.org',), deadline_at=kw['deadline_at'])
    row = run()['sources'][0]
    assert row['error'] == 'audit_publisher_scope_changed'
    transport.assert_not_called()


def test_late_result_and_exhausted_overall_budget_are_not_accepted(setup, monkeypatch):
    _, _, _, route = setup
    clock = [100.0]
    monkeypatch.setattr(audit, 'monotonic', lambda: clock[0])
    def late(source, **kwargs):
        clock[0] = 900.0
        return {'p_source_key': source['source_key'], 'p_error': None, 'p_future_count': 0,
                'p_parser_capability': 'publisher_event_candidates_v1', 'p_events': []}
    route.side_effect = late
    report = run([KEY, 'vance_county_arts_council_nc'])
    assert route.call_count == 1
    assert [row['error'] for row in report['sources']] == ['collection_deadline', 'collection_deadline']
