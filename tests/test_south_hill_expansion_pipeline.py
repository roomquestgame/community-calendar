"""New adapters keep the shared demand, guarded transport, staging and v3 path."""
from copy import deepcopy
from datetime import datetime, timezone
import importlib
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

import pytest

from roomquest import preview_worker as worker, revize, south_hill_markets
from roomquest.publisher_evidence import attach, family, image_url
from roomquest.event_media import resolve_photo
from scripts.capture_south_hill_expansion import source

SPECS = [
    ('mcgregor_hall_henderson_nc', 'mcgregor_hall', 'https://www.mcgregorhall.org/frozen--the-broadway-musical'),
    ('victoria_town_calendar_va', 'victoria_calendar', 'https://victoriava.net/calendar-of-events'),
    ('vance_county_arts_council_nc', 'vance_arts', 'https://vanceartscouncil.com/event/tidings-of-comfort-and-joy-2026/'),
]
NOW = datetime(2026, 11, 10, 10, tzinfo=timezone.utc)
ROOT = Path(__file__).parent / 'fixtures/south_hill_expansion'


@pytest.mark.parametrize('key,module_name,url', SPECS)
@pytest.mark.parametrize('status', ['scheduled', 'cancelled', 'postponed'])
def test_worker_preserves_full_record_and_status_before_v3_certification(key, module_name, url, status):
    module = importlib.import_module('roomquest.' + module_name)
    config = source(key)
    event = attach({'id': 'publisher:one', 'title': 'Public program', 'event_url': url,
                    'starts_at': '2026-12-01T20:00:00+00:00', 'ends_at': None,
                    'lat': None, 'lng': None, 'description': 'Publisher narrative',
                    'publisher_status': status}, key)
    calls = []
    def collect(configured, fetch, *, deadline_at):
        assert configured == config and deadline_at is not None
        fetch(config['feed_url'], 'text/html')
        return [deepcopy(event)]
    def rpc(name, payload):
        calls.append((name, deepcopy(payload)))
        return len(payload.get('p_events', []))
    with patch.object(module, 'collect', side_effect=collect), \
         patch.object(worker, 'fetch_publisher', return_value='PUBLIC') as fetch, \
         patch.object(worker, 'supabase_rpc', side_effect=rpc):
        result = worker._process_claimed_source(config)
    assert result['complete'] == 1 and result['staged'] == 1
    assert [name for name, _ in calls] == ['community_collector_record_staged_events', 'community_collector_record_preview_v3']
    assert calls[0][1]['p_events'] == [event]
    assert calls[1][1]['p_parser_capability'] == 'publisher_event_candidates_v1'
    assert calls[1][1]['p_future_count'] == 1
    assert fetch.call_args.kwargs['respect_robots'] is True
    assert fetch.call_args.kwargs['allowed_hosts'] == (urlsplit(config['feed_url']).hostname,)


@pytest.mark.parametrize('key,module_name,url', SPECS)
def test_complete_empty_snapshot_and_failed_collection_keep_v3_boundary(key, module_name, url):
    module = importlib.import_module('roomquest.' + module_name)
    for error in (None, worker.PreviewError('robots_denied')):
        calls = []
        with patch.object(module, 'collect', return_value=[], side_effect=error), \
             patch.object(worker, 'supabase_rpc', side_effect=lambda name, payload: calls.append((name, deepcopy(payload))) or 0):
            result = worker._process_claimed_source(source(key))
        assert calls[-1][0] == 'community_collector_record_preview_v3'
        if error:
            assert result['failed'] == 1 and len(calls) == 1
            assert calls[0][1]['p_error'] == 'robots_denied'
        else:
            assert result['complete'] == 1 and calls[-1][1]['p_parser_capability'] == 'publisher_event_candidates_v1'


@pytest.mark.parametrize('version', [None, True, False, '1', 0, 2])
def test_legacy_or_unrecognized_town_claim_keeps_revize_only(version):
    config = source('south_hill_town_va')
    if version is None:
        config.pop('south_hill_market_contract_version')
    else:
        config['south_hill_market_contract_version'] = version
    old = {'id': 'revize:original', 'lat': None}
    with patch.object(revize, 'collect', return_value=[old]) as original, \
         patch.object(south_hill_markets, 'collect', side_effect=AssertionError('pre-migration supplement must not run')) as supplement:
        result = worker.preview_source(config)
    assert result['p_events'] == [old] and result['p_future_count'] == 1
    assert original.call_args.args[0] == config
    supplement.assert_not_called()


def test_capable_town_claim_appends_supplement_under_same_transport_and_deadline():
    config = source('south_hill_town_va')
    original = {'id': 'revize:original', 'lat': None, 'civic': {'version': 1}}
    market = {'id': 'south_hill_market:christmas_open_house:2026-11-15', 'lat': None}
    with patch.object(revize, 'collect', return_value=[original]) as calendar, \
         patch.object(south_hill_markets, 'collect', return_value=[market]) as supplement:
        result = worker.preview_source(config)
    assert result['p_events'] == [original, market]
    assert result['p_parser_capability'] == 'publisher_event_candidates_v1'
    assert calendar.call_args.args[1] is supplement.call_args.args[1]
    assert calendar.call_args.kwargs['deadline_at'] == supplement.call_args.kwargs['deadline_at']


def test_town_supplement_failure_prevents_certification_and_partial_staging():
    calls = []
    with patch.object(revize, 'collect', return_value=[{'id': 'old', 'lat': None}]), \
         patch.object(south_hill_markets, 'collect', side_effect=worker.PreviewError('publisher_http_403')), \
         patch.object(worker, 'supabase_rpc', side_effect=lambda name, payload: calls.append((name, deepcopy(payload))) or 0):
        result = worker._process_claimed_source(source('south_hill_town_va'))
    assert result['failed'] == 1 and result['staged'] == 0
    assert [name for name, _ in calls] == ['community_collector_record_preview_v3']
    assert calls[0][1]['p_error'] == 'publisher_http_403'


@pytest.mark.parametrize('key,module_name,expected', [(SPECS[0][0], SPECS[0][1], 6), (SPECS[2][0], SPECS[2][1], 1)])
def test_captured_publisher_documents_flow_through_real_preview_route(key, module_name, expected, monkeypatch):
    module = importlib.import_module('roomquest.' + module_name)
    original_collect = module.collect
    monkeypatch.setattr(worker, '_future_datetime', lambda dt: dt.astimezone(timezone.utc))
    documents = {
        SPECS[0][2].rsplit('/', 1)[0] + '/shows-events': 'mcgregor-shows.html',
        'https://vanceartscouncil.com/events/': 'vance-events.html',
        SPECS[2][2]: 'vance-concert.html',
        'https://vanceartscouncil.com/event/henderson-nc-christmas-parade-2026/': 'vance-parade.html',
    }
    with patch.object(module, 'collect', side_effect=lambda src, fetch, **kwargs: original_collect(src, fetch, now=NOW, **kwargs)), \
         patch.object(worker, 'fetch_publisher', side_effect=lambda url, accept, **kwargs: (ROOT / documents[url]).read_text()) as transport:
        result = worker.preview_source(source(key))
    assert result['p_future_count'] == expected and len(result['p_events']) == expected
    assert all(call.kwargs['respect_robots'] is True for call in transport.call_args_list)
    assert all(call.kwargs['allowed_hosts'] == (urlsplit(source(key)['feed_url']).hostname,) for call in transport.call_args_list)


@pytest.mark.parametrize('key,url,picture', [
    (SPECS[0][0], SPECS[0][2], 'https://irp.cdn-website.com/34057905/dms3rep/multi/Frozen+Logo-4fb10a6c.jpg'),
    (SPECS[2][0], SPECS[2][2], 'https://vanceartscouncil.com/wp-content/uploads/2026/10/tidings-of-comfort-and-joy-2025-16.jpg'),
])
def test_reviewed_images_use_existing_candidate_probe_without_page_recrawl(key, url, picture):
    assert family(key, url) == key and image_url(picture, key) == picture
    no_page_fetch = Mock(side_effect=AssertionError('must not recrawl'))
    claim = {'source_key': key, 'event_url': url, 'title': 'Public performance',
             'candidate_only': True, 'candidate_url': picture}
    assert resolve_photo(claim, fetcher=no_page_fetch, probe=lambda _: (picture, 'image/jpeg'))['image_url'] == picture
    assert resolve_photo(claim, fetcher=no_page_fetch, probe=lambda _: ('https://example.com/other.jpg', 'image/jpeg')) is None
    no_page_fetch.assert_not_called()


def test_town_market_evidence_route_is_narrow_and_images_remain_uninferred():
    key = 'south_hill_town_va'
    assert family(key, south_hill_markets.CALENDAR) == 'south_hill_town'
    for url in (south_hill_markets.CALENDAR + '?x=1', south_hill_markets.CALENDAR + '#x',
                south_hill_markets.CALENDAR.replace('.gov/', '.gov.other.example/')):
        assert family(key, url) is None
    row = attach({'event_url': south_hill_markets.CALENDAR}, key,
                 candidate='https://www.southhillva.gov/Christmas%20Application%202026.pdf')
    assert 'image_url' not in row
