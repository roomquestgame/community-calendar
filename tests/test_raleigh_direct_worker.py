"""Complete captured narratives and streets cross the ordinary preview-v2 path."""
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pytest

from roomquest import preview_worker as w, category_worker
from roomquest import raleigh_direct_community as community, raleigh_direct_arts as arts
from roomquest import raleigh_direct_sources as profiles


def source(module, key):
    return dict(source_key=key, feed_url=module.SOURCES[key][0], kind='html', platform_adapter='html', timezone=profiles.ZONE)


def row():
    return dict(id='native-occurrence', title='Public performance', description='Complete native performer biography. '*110,
                starts_at='2026-12-01T19:00:00-05:00', ends_at=None, venue_name='Goodnights Comedy Club',
                venue_address='401 Woodburn Road, Raleigh, NC 27605', venue_city='Raleigh', lat=None, lng=None,
                event_url='https://www.goodnightscomedy.com/shows/123')


def chunk(*, complete=True):
    event = row()
    now = datetime.now(timezone.utc)
    cp = community._state(community.GOODNIGHTS, [], [event], [], now)
    if not complete:
        cp['manifest_count'] = 2; cp['cursor'] = 1
    return {'checkpoint': cp, 'events': [event] if complete else [], 'complete': complete}


def run_chunk(value, module=community, key=community.GOODNIGHTS):
    calls = []
    def rpc(operation, payload):
        calls.append((operation, payload))
        if operation.endswith('read_fetch_checkpoint'): return {'checkpoint': None, 'revision': 0}
        if operation.endswith('write_fetch_checkpoint'): return {'checkpoint_saved': True, 'revision': 1}
        raise AssertionError(operation)
    with patch.object(w, 'supabase_rpc', side_effect=rpc), patch.object(module, 'collect_chunk', return_value=value):
        result = w._preview_raleigh_direct_chunk(source(module, key),
                {'wait_unbounded': False, 'crawl_delay_seconds': 0, 'retry_after_seconds': 0},
                collection_context={'p_category': 'html', 'p_ticket': 'test-ticket'}, deadline_at=w.monotonic()+50)
    return result, calls


def test_all_new_sources_require_exact_profile_and_durable_checkpoint():
    for module in profiles.adapters():
        for key in module.SOURCES:
            assert profiles.validate_source(source(module, key)) is module
            assert key in profiles.checkpoint_keys()
            with pytest.raises(w.PreviewError, match='checkpoint_required'):
                w.preview_source(source(module, key))
    with patch.object(w, 'fetch_publisher') as fetch:
        with pytest.raises(w.PreviewError, match='unregistered_raleigh_direct_source'):
            w.preview_source({**source(community, community.GOODNIGHTS), 'feed_url': 'https://example.com/calendar'})
        fetch.assert_not_called()


def test_complete_rows_preserve_full_text_and_address_after_checkpoint_ack():
    value = chunk()
    result, calls = run_chunk(value)
    assert [c[0] for c in calls] == ['community_collector_read_fetch_checkpoint', 'community_collector_write_fetch_checkpoint']
    assert calls[1][1]['p_checkpoint'] == value['checkpoint']
    assert result['p_events'] == value['events']
    assert len(result['p_events'][0]['description']) > 2000
    assert result['p_samples'][0]['venue_address'] == row()['venue_address']


def test_partial_capture_never_returns_staging_events():
    result, calls = run_chunk(chunk(complete=False))
    assert result == {'fetch_pending': True} and len(calls) == 2


def test_empty_cursor_does_not_certify_unfinished_listing():
    now = datetime.now(timezone.utc)
    cp = dict(version=1, source_key=arts.CARY, manifest_hash='a'*64, manifest_count=0, cursor=0,
              started_at=now.isoformat(), window_start=now.astimezone(ZoneInfo(profiles.ZONE)).date().isoformat(),
              events=[], diagnostics=[], queue=[], listing_complete=False, pending_pages=[{'kind': 'cary', 'index': 0}])
    with patch.object(w, 'supabase_rpc', return_value={'checkpoint': None, 'revision': 0}) as rpc, \
         patch.object(arts, 'collect_chunk', return_value={'checkpoint': cp, 'complete': True, 'events': []}):
        with pytest.raises(w.PreviewError, match='raleigh_direct_checkpoint_invalid'):
            w._preview_raleigh_direct_chunk(source(arts, arts.CARY),
                {'wait_unbounded': False, 'crawl_delay_seconds': 0, 'retry_after_seconds': 0},
                collection_context={'p_category': 'html', 'p_ticket': 'test-ticket'}, deadline_at=w.monotonic()+50)
    assert rpc.call_count == 1


@pytest.mark.parametrize('change', [{'description': ''}, {'description': 'x'*12001},
    {'venue_address': 'Raleigh, NC 27605'}, {'event_url': 'https://example.com/event/1'}])
def test_incomplete_row_cannot_enter_staging(change):
    value = chunk(); value['events'][0].update(change)
    with pytest.raises(w.PreviewError, match='raleigh_direct_incomplete_event'):
        run_chunk(value)


def test_diagnostics_are_controlled_and_do_not_expose_publisher_values():
    assert category_worker._error_code(w.PreviewError('invalid_game_theory_request')) == 'invalid_game_theory_request'
    assert category_worker._error_code(w.PreviewError('private_unexpected_value')) == 'unclassified_preview_error'
