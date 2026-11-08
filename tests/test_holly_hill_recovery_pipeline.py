"""New institution fixtures through the shared guarded preview/staging route."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest

from roomquest import holly_hill_institution_recovery as parser
from roomquest import holly_hill_sources as sources
from roomquest import preview_worker as worker
from roomquest import publisher_evidence as evidence

FIXTURES = Path(__file__).parent / 'fixtures' / 'holly_hill_institution_recovery'


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    class ClockMeta(type):
        def __instancecheck__(cls, value):
            return isinstance(value, datetime)

    class Frozen(datetime, metaclass=ClockMeta):
        @classmethod
        def now(cls, tz=None):
            now = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    for module in (parser, worker):
        monkeypatch.setattr(module, 'datetime', Frozen)


def fixture(name):
    return (FIXTURES / name).read_text()


def transport(monkeypatch, key):
    def fetch(url, accept, **kwargs):
        assert kwargs['respect_robots'] is True
        assert kwargs['allowed_hosts'] == sources.SOURCES[key]['hosts']
        assert urlsplit(url).hostname in kwargs['allowed_hosts']
        assert kwargs['deadline_at'] is not None
        if key == parser.OLD_SANTEE:
            assert parser.event_url(key, url) and accept == 'text/html'
            return fixture('recdesk_' + url.split('=')[-1] + '.html')
        if url == parser.YMCA_RSS:
            assert accept == 'application/rss+xml'
            return fixture('ymca_branch_feed.xml')
        assert parser.event_url(key, url) and accept == 'text/html'
        return fixture('ymca_craft.html')

    get = Mock(side_effect=fetch)
    display = Mock(return_value=fixture('recdesk_programs.html'))
    monkeypatch.setattr(worker, 'fetch_publisher', get)
    monkeypatch.setattr(worker, 'render_old_santee_programs', display)
    return get, display


@pytest.mark.parametrize('key,count', [(parser.OLD_SANTEE, 5), (parser.ORANGEBURG_YMCA, 1)])
def test_real_institutions_flow_through_registered_host_deadline_and_media_contract(monkeypatch, key, count):
    get, display = transport(monkeypatch, key)
    result = worker.preview_source(sources.source_payload(key))
    assert result['p_error'] is None and result['p_future_count'] == count
    assert result['p_parser_capability'] == evidence.IMAGE_VERSION
    assert len(result['p_events']) == count
    assert result['p_venue_count'] == 0  # Verified geocoding remains a downstream gate.
    if key == parser.OLD_SANTEE:
        assert get.call_count == 5
        display.assert_called_once_with(deadline_at=get.call_args_list[0].kwargs['deadline_at'])
    else:
        assert get.call_count == 2
        display.assert_not_called()
        assert sources.source_payload(key)['feed_url'] == 'https://columbiaymca.org/events/'
    for row in result['p_events']:
        family = evidence.family(key, row['event_url'])
        assert family == 'holly_hill:' + key
        assert evidence.image_url(row.get('image_url'), family) == row.get('image_url')
        assert row['details_evidence_url'] == row['event_url']


@pytest.mark.parametrize('key,count', [(parser.OLD_SANTEE, 5), (parser.ORANGEBURG_YMCA, 1)])
def test_recovery_rows_stage_before_success_on_v3_contract(monkeypatch, key, count):
    transport(monkeypatch, key)
    calls = []

    def rpc(name, payload):
        calls.append((name, deepcopy(payload)))
        return len(payload.get('p_events', []))

    monkeypatch.setattr(worker, 'supabase_rpc', rpc)
    result = worker._process_claimed_source(sources.source_payload(key))
    assert (result['complete'], result['failed'], result['staged']) == (1, 0, count)
    assert all(name == 'community_collector_record_staged_events' for name, _ in calls[:-1])
    assert len([row for _, payload in calls[:-1] for row in payload['p_events']]) == count
    assert calls[-1][0] == 'community_collector_record_preview_v3'
    status = calls[-1][1]
    assert status['p_error'] is None and status['p_future_count'] == count
    assert status['p_parser_capability'] == evidence.IMAGE_VERSION
    assert 'p_events' not in status


@pytest.mark.parametrize('key', [parser.OLD_SANTEE, parser.ORANGEBURG_YMCA])
def test_required_transport_failure_records_hold_without_staging(monkeypatch, key):
    get = Mock(side_effect=worker.PreviewError('robots_denied'))
    display = Mock(side_effect=worker.PreviewError('robots_denied'))
    monkeypatch.setattr(worker, 'fetch_publisher', get)
    monkeypatch.setattr(worker, 'render_old_santee_programs', display)
    calls = []
    monkeypatch.setattr(worker, 'supabase_rpc', lambda name, payload: calls.append((name, payload)))
    result = worker._process_claimed_source(sources.source_payload(key))
    assert (result['complete'], result['failed'], result['staged']) == (0, 1, 0)
    assert len(calls) == 1 and calls[0][0] == 'community_collector_record_preview_v3'
    assert calls[0][1]['p_error'] == 'robots_denied'
    if key == parser.OLD_SANTEE:
        get.assert_not_called()
    else:
        display.assert_not_called()


def test_fixed_recdesk_post_gets_the_same_shorter_parent_deadline(monkeypatch):
    monkeypatch.setattr(worker, 'monotonic', lambda: 100.0)
    monkeypatch.setattr(parser, 'monotonic', lambda: 100.0)
    get, display = transport(monkeypatch, parser.OLD_SANTEE)
    worker.preview_source(sources.source_payload(parser.OLD_SANTEE), deadline_at=120)
    display.assert_called_once_with(deadline_at=112.0)
    assert all(call.kwargs['deadline_at'] == 112.0 for call in get.call_args_list)


def test_recovery_evidence_identity_and_artwork_cannot_cross_sources():
    recdesk = 'https://oldsanteecanal.recdesk.com/Community/Program/Detail?programId=100'
    ymca = 'https://columbiaymca.org/2026/11/03/create-with-us-holiday-craft-event-at-orangeburg-y/'
    photo = ('https://columbiaymca.org/wp-content/uploads/sites/22/2026/11/'
             'ChatGPT-Image-Aug-19-2026-01_44_15-PM-1024x541.png')
    assert evidence.family(parser.OLD_SANTEE, ymca) is None
    assert evidence.family(parser.ORANGEBURG_YMCA, recdesk) is None
    assert evidence.image_url(photo, 'holly_hill:' + parser.OLD_SANTEE) is None
    with pytest.raises(ValueError, match='publisher_evidence_identity_mismatch'):
        evidence.attach({'event_url': recdesk}, parser.ORANGEBURG_YMCA, candidate=photo)
