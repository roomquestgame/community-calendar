"""Five reviewed publishers traverse the existing demand/staging/media pipeline."""
from copy import deepcopy
import importlib
import io
import json
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

import pytest

from roomquest import preview_worker, category_worker
from roomquest.event_media import resolve_photo
from roomquest.publisher_evidence import attach, family, image_url

SOURCES = [
    ('south_hill_town_va', 'revize', 'json', 'revize',
     'https://www.southhillva.gov/calendar.php', ('www.southhillva.gov',)),
    ('south_hill_chamber_va', 'south_hill_chamber', 'html', 'html',
     'https://members.southhillchamber.com/calendar/Details/holiday-lunch-1234',
     ('members.southhillchamber.com',)),
    ('clarksville_community_players_va', 'clarksville_players', 'html', 'html',
     'https://clarksvilleplayers.org/', ('clarksvilleplayers.org',)),
    ('maccallum_more_va', 'maccallum_more', 'html', 'html',
     'https://maccallummore.org/pages/grand-illumination', ('maccallummore.org',)),
    ('mecklenburg_ymca_programs_va', 'mecklenburg_ymca', 'html', 'html',
     'https://mecklenburg.recliquecore.com/programs/33/craft-classes/?locations=-1',
     ('mecklenburg.recliquecore.com', 'mecklenburgcountyymca.org')),
]
PICTURES = [
    ('clarksville_players', SOURCES[2],
     'https://img1.wsimg.com/isteam/ip/a33c590a-25e0-4bb6-979e-3d018e2af1b1/Steel%20Magnolias.jpg/:/rs=w:600,h:451.12781954887214,cg:true,m/cr=w:600,h:451.12781954887214'),
    ('maccallum_more', SOURCES[3],
     'https://maccallummore.org/cdn/shop/files/Grand_Illumination_at_MacCallum_More_1.webp?v=1793653457&width=3200'),
    ('mecklenburg_ymca', SOURCES[4],
     'https://reclique-core-mecklenburg.s3.amazonaws.com/wp-content/uploads/2026/10/09072400/Decoupage-Ornament-300x265.png'),
]


def source_config(spec):
    key, module_name, kind, adapter, _, _ = spec
    module = importlib.import_module('roomquest.' + module_name)
    return module, {'source_key': key, 'kind': kind, 'platform_adapter': adapter,
                    'timezone': 'America/New_York',
                    'feed_url': getattr(module, 'FEED_URL', None) or getattr(module, 'CALENDAR', None)
                                or getattr(module, 'FEED', None)}


@pytest.mark.parametrize('spec', SOURCES)
@pytest.mark.parametrize('status', ['scheduled', 'cancelled', 'postponed', None])
def test_normal_worker_stages_exact_records_before_certifying_snapshot(spec, status):
    module, source = source_config(spec)
    # The parser owns normalized records; the worker must not strip evidence or
    # an explicit publisher status before the database applies its own gates.
    event = attach({'id': 'stable-fixture', 'event_url': spec[4], 'title': 'Public event',
                    'starts_at': '2026-11-17T20:00:00+00:00', 'ends_at': None,
                    'lat': None, 'lng': None, 'description': 'Publisher narrative'},
                   source['source_key'], facts={'cost': '$10'})
    if status:
        event['publisher_status'] = status
    calls = []
    def collect(src, fetch, *, deadline_at):
        assert src == source and deadline_at is not None
        fetch(spec[4], 'text/html')
        return [deepcopy(event)]
    def rpc(name, payload):
        calls.append((name, deepcopy(payload)))
        return len(payload.get('p_events', []))
    with patch.object(module, 'collect', side_effect=collect), \
            patch.object(preview_worker, 'fetch_publisher', return_value='publisher body') as fetch, \
            patch.object(preview_worker, 'supabase_rpc', side_effect=rpc):
        result = preview_worker._process_claimed_source(source)
    assert result['complete'] == 1 and result['staged'] == 1
    assert [name for name, _ in calls] == [
        'community_collector_record_staged_events', 'community_collector_record_preview_v3']
    assert calls[0][1]['p_events'] == [event]
    assert calls[1][1]['p_parser_capability'] == 'publisher_event_candidates_v1'
    assert calls[1][1]['p_future_count'] == 1 and calls[1][1]['p_error'] is None
    assert fetch.call_args.kwargs['respect_robots'] is True
    assert fetch.call_args.kwargs['allowed_hosts'] == spec[5]
    assert fetch.call_args.kwargs['deadline_at'] is not None


@pytest.mark.parametrize('spec', SOURCES)
def test_successful_empty_snapshot_and_failure_take_same_reviewed_v3_path(spec):
    module, source = source_config(spec)
    for error in (None, preview_worker.PreviewError('robots_denied')):
        calls = []
        with patch.object(module, 'collect', return_value=[], side_effect=error), \
                patch.object(preview_worker, 'supabase_rpc',
                             side_effect=lambda name, payload: calls.append((name, deepcopy(payload))) or 0):
            result = preview_worker._process_claimed_source(source)
        assert calls[-1][0] == 'community_collector_record_preview_v3'
        assert result['complete'] == (error is None)
        assert result['failed'] == (error is not None)
        if error is None:
            assert calls[0][0] == 'community_collector_record_staged_events'
            assert calls[-1][1]['p_parser_capability'] == 'publisher_event_candidates_v1'
        else:
            assert len(calls) == 1 and calls[-1][1]['p_error'] == 'robots_denied'


@pytest.mark.parametrize('publisher,spec,picture', PICTURES)
def test_reviewed_publisher_images_use_candidate_probe_without_detail_recrawl(publisher, spec, picture):
    assert family(spec[0], spec[4]) == publisher
    item = attach({'event_url': spec[4]}, spec[0], candidate=picture)
    assert item['image_url'] == picture
    fetch = Mock(side_effect=AssertionError('No page recrawl for enrolled media'))
    claim = {'source_key': spec[0], 'event_url': spec[4], 'title': 'Public event',
             'candidate_only': True, 'candidate_url': picture}
    assert resolve_photo(claim, fetcher=fetch, probe=lambda _: (picture, 'image/jpeg'))['image_url'] == picture
    assert resolve_photo(claim, fetcher=fetch, probe=lambda _: ('https://other.example/a.jpg', 'image/jpeg')) is None
    claim['candidate_url'] = None
    assert resolve_photo(claim, fetcher=fetch, probe=Mock()) is None
    fetch.assert_not_called()


@pytest.mark.parametrize('publisher,spec,picture', PICTURES)
def test_new_media_scope_rejects_other_tenants_ports_credentials_traversal_and_queries(publisher, spec, picture):
    host = urlsplit(picture).netloc
    bare = picture.split('?')[0]
    invalid = [
        picture.replace('https:', 'http:'), picture.replace(host, host + '.other.example'),
        picture.replace(host, 'user@' + host), picture.replace(host, host + ':443'),
        picture + '#fragment', bare.replace('/wp-content/', '/wp-content/../'),
        bare.replace('/cdn/shop/', '/cdn/../shop/'),
        bare.replace('/isteam/ip/', '/isteam/%2e%2e/ip/'),
        bare + '?redirect=https://other.example/image.jpg',
    ]
    # Only include mutations that changed a path present in this publisher URL.
    for value in invalid:
        if value != bare and value != picture:
            assert image_url(value, publisher) is None, value
    assert image_url(picture, 'unrelated') is None
    assert family('unrelated_source', spec[4]) is None


@pytest.mark.parametrize('query', ['v=1&v=2', 'width=0', '%76=1', 'v=1&width=2&height=3',
                                    'width=-1', 'v=1;', 'v=', 'v=12345678901234'])
def test_maccallum_image_query_scope(query):
    base = PICTURES[1][2].split('?')[0]
    assert image_url(base + '?' + query, 'maccallum_more') is None


def test_revize_uses_existing_ticket_entrypoint_and_finishes_once():
    from api import category_demand
    payload = {'category': 'revize', 'ticket': '00000000-0000-0000-0000-000000000000'}
    raw = json.dumps(payload).encode()
    h = object.__new__(category_demand.handler)
    h.path = '/api/category-demand'
    h.headers = {'Content-Length': str(len(raw))}
    h.rfile = io.BytesIO(raw)
    with patch.object(h, 'reply') as reply, \
            patch.object(category_worker, 'supabase_rpc', side_effect=[None, True]) as rpc:
        h.do_POST()
    reply.assert_called_once_with(200, {'outcome': 'idle'})
    assert [call.args[0] for call in rpc.call_args_list] == [
        'community_collector_claim_category', 'community_collector_finish_category']
    assert rpc.call_args_list[-1].args[1]['p_outcome'] == 'idle'

