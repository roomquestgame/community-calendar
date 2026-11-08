"""Reviewed local sources keep the existing guarded preview/staging contracts."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from unittest.mock import MagicMock, Mock
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
import pytest

from roomquest import holly_hill_businesses as businesses
from roomquest import holly_hill_civic as civic
from roomquest import holly_hill_institutions as institutions
from roomquest import holly_hill_sources as sources
from roomquest import ics_adapter, preview_worker as worker

FIXTURES = Path(__file__).parent / 'fixtures'
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
KEYS = tuple(sorted(sources.SOURCES))
MEDIA_KEYS = {civic.SANTEE, civic.BEIDLER, civic.SC250, civic.EUTAWVILLE,
              civic.ELLOREE, businesses.D_AND_G, businesses.OUTSIDE_INN}
V2_KEYS = {institutions.OCTECH, institutions.CANE_BAY}


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    class ClockMeta(type):
        def __instancecheck__(cls, value):
            return isinstance(value, datetime)

    class Frozen(datetime, metaclass=ClockMeta):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    for module in (businesses, civic, institutions, ics_adapter, worker):
        monkeypatch.setattr(module, 'datetime', Frozen)


def fixture(group, name):
    return (FIXTURES / ('holly_hill_' + group) / name).read_text()


def mock_publisher_transport(monkeypatch, source_key, *, full_octech=False):
    """Replay captured publisher bodies at the normal guarded-fetch interface.

    Orangeburg's small calendar is synthetic contract data. Elloree's discovery
    markup is a minimal endpoint witness; its returned JSON is a live capture.
    OCTech success isolates its one captured eligible detail. The unmodified
    listing's unavailable second detail is covered separately as a failure.
    """
    bodies = {item['url']: fixture('businesses', item['file'])
              for item in json.loads(fixture('businesses', 'manifest.json'))}
    bodies.update({
        civic.SOURCES[civic.SANTEE]['url']: fixture('civic', 'santee_calendar.html'),
        civic.BEIDLER_ROOT + 'night-exploration': fixture('civic', 'beidler_night.html'),
        civic.BEIDLER_ROOT + 'nocturnal-family-forays': fixture('civic', 'beidler_family.html'),
        civic.BEIDLER_ROOT + 'boo-swamp': fixture('civic', 'beidler_boo.html'),
        civic.SOURCES[civic.SC250]['url']: fixture('civic', 'sc250_calendar.ics'),
        'https://southcarolina250.com/events/list/page/2/?ical=1': fixture('civic', 'ics_page2.ics'),
        'https://southcarolina250.com/events/list/page/3/?ical=1': fixture('civic', 'sc250_ics_page3.ics'),
        civic.SOURCES[civic.ELLOREE]['url']: '<script>fetch("' + civic.ELLOREE_API + '")</script>',
        institutions.ICS[institutions.ST_GEORGE]: fixture('institutions', 'st_george.ics'),
        institutions.ICS[institutions.MONCKS]: fixture('institutions', 'moncks_corner.ics'),
        institutions.HTML[institutions.CANE_BAY]: fixture('institutions', 'cane_bay_events.html'),
        'https://octech.coursestorm.com/course/defensive-driving17': fixture('institutions', 'defensive-driving17.html'),
        'https://octech.coursestorm.com/course/defensive-driving18': '',
        sources.SOURCES[sources.ORANGEBURG_LIBRARY]['url']:
            'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:synthetic-pipeline-contract\r\n'
            'SUMMARY:Synthetic library program\r\nDTSTART:20261110T160000Z\r\n'
            'DTEND:20261110T170000Z\r\nLOCATION:Library room\r\n'
            'URL:https://www.orangeburgcounty.org/Calendar.aspx?EID=123\r\n'
            'END:VEVENT\r\nEND:VCALENDAR\r\n',
    })
    browse = BeautifulSoup(fixture('institutions', 'octech_browse.html'), 'html.parser')
    if not full_octech:
        browse.select('.course-item')[1].decompose()
    bodies[institutions.HTML[institutions.OCTECH]] = str(browse)
    calls = []

    def fetch(url, accept, **kwargs):
        calls.append((url, accept, kwargs))
        assert kwargs['respect_robots'] is True
        assert kwargs['allowed_hosts'] == sources.SOURCES[source_key]['hosts']
        assert kwargs['deadline_at'] is not None
        assert urlsplit(url).hostname in kwargs['allowed_hosts']
        if url.startswith(civic.SOURCES[civic.EUTAWVILLE]['url'] + '?'):
            return fixture('civic', 'eutawville.json')
        return bodies[url]

    fetch_mock = Mock(side_effect=fetch)
    render = Mock(return_value=fixture('civic', 'elloree.json'))
    monkeypatch.setattr(worker, 'fetch_publisher', fetch_mock)
    monkeypatch.setattr(worker, 'render_elloree_calendar', render)
    return calls, fetch_mock, render


@pytest.mark.parametrize('key', KEYS)
@pytest.mark.parametrize('field,value', [
    ('feed_url', 'http://127.0.0.1/unreviewed'), ('timezone', 'UTC'),
    ('kind', 'unreviewed'), ('platform_adapter', 'unreviewed'),
])
def test_central_identity_guard_rejects_changed_tuple_before_any_transport(monkeypatch, key, field, value):
    source = sources.source_payload(key)
    source[field] = value
    fetch, render, collect = Mock(), Mock(), Mock()
    monkeypatch.setattr(worker, 'fetch_publisher', fetch)
    monkeypatch.setattr(worker, 'render_elloree_calendar', render)
    monkeypatch.setattr(sources, 'collect', collect)
    with pytest.raises(worker.PreviewError, match='unregistered_holly_hill_source'):
        worker.preview_source(source)
    fetch.assert_not_called()
    render.assert_not_called()
    collect.assert_not_called()


def test_unknown_source_cannot_enter_the_central_dispatcher():
    source = sources.source_payload(businesses.D_AND_G)
    source['source_key'] = 'unreviewed_holly_hill_source'
    fetch = Mock()
    with pytest.raises(ValueError, match='unregistered_holly_hill_source'):
        sources.collect(source, fetch)
    fetch.assert_not_called()


@pytest.mark.parametrize('key', KEYS)
def test_captured_publishers_reach_preview_through_normal_host_and_deadline_guards(monkeypatch, caplog, key):
    calls, fetch, render = mock_publisher_transport(monkeypatch, key)
    output = worker.preview_source(sources.source_payload(key))
    assert output['p_source_key'] == key and output['p_error'] is None
    assert output['p_future_count'] == len(output['p_events'])
    assert len(output['p_samples']) <= worker.MAX_PREVIEWS
    assert ('p_parser_capability' in output) == (key in MEDIA_KEYS)
    if key in MEDIA_KEYS:
        assert output['p_parser_capability'] == 'publisher_event_candidates_v1'
    expected_counts = {
        businesses.D_AND_G: 1, businesses.OUTSIDE_INN: 0, civic.SANTEE: 46,
        civic.BEIDLER: 1, civic.SC250: 29, civic.EUTAWVILLE: 0, civic.ELLOREE: 2,
        institutions.ST_GEORGE: 3, institutions.MONCKS: 3,
        institutions.OCTECH: 2, institutions.CANE_BAY: 0, sources.ORANGEBURG_LIBRARY: 1,
    }
    if key in expected_counts:
        assert output['p_future_count'] == expected_counts[key]
    if key == civic.SC250:
        assert len(calls) == 3
        screenings = [row for row in output['p_events'] if row['title'] == 'Screening: Ken Burns The Revolutionary War']
        assert screenings == []
        assert caplog.text.count('publisher_series_month_conflict') == 9
        assert all(accept == 'text/calendar' for _, accept, _ in calls)
    if key == civic.ELLOREE:
        render.assert_called_once_with(deadline_at=calls[0][2]['deadline_at'])
    else:
        render.assert_not_called()
    assert fetch.called


def test_central_deadline_keeps_worker_reserve_and_transport_failure_is_not_empty(monkeypatch):
    source = sources.source_payload(businesses.D_AND_G)
    monkeypatch.setattr(worker, 'monotonic', lambda: 100.0)
    seen = []

    def collect(config, fetch, *, deadline_at, fetch_elloree):
        assert config == source and deadline_at == 112.0
        fetch(source['feed_url'], 'text/html')
        return []

    def blocked(url, accept, **kwargs):
        seen.append(kwargs)
        raise worker.PreviewError('robots_denied')

    monkeypatch.setattr(sources, 'collect', collect)
    monkeypatch.setattr(worker, 'fetch_publisher', blocked)
    with pytest.raises(worker.PreviewError, match='robots_denied'):
        worker.preview_source(source, deadline_at=120.0)
    assert seen == [{'respect_robots': True, 'deadline_at': 112.0,
                     'allowed_hosts': businesses.HOSTS[businesses.D_AND_G]}]


def expected_rpc(key):
    if key in MEDIA_KEYS:
        return 'community_collector_record_preview_v3'
    if key in V2_KEYS:
        return 'community_collector_record_preview_v2'
    return 'community_collector_record_preview'


@pytest.mark.parametrize('key', KEYS)
def test_real_fixture_preview_stages_exact_records_before_correct_recording_contract(monkeypatch, key):
    mock_publisher_transport(monkeypatch, key)
    source = sources.source_payload(key)
    expected = worker.preview_source(source)
    calls = []

    def rpc(name, payload):
        calls.append((name, deepcopy(payload)))
        return len(payload.get('p_events', []))

    monkeypatch.setattr(worker, 'supabase_rpc', rpc)
    result = worker._process_claimed_source(source)
    assert result == {'complete': 1, 'failed': 0, 'staged': len(expected['p_events'])}
    assert calls[-1][0] == expected_rpc(key)
    assert all(name == 'community_collector_record_staged_events' for name, _ in calls[:-1])
    assert [event for _, payload in calls[:-1] for event in payload['p_events']] == expected['p_events']
    status = calls[-1][1]
    assert status['p_error'] is None and status['p_future_count'] == expected['p_future_count']
    assert 'p_events' not in status
    assert ('p_parser_capability' in status) == (key in MEDIA_KEYS)
    if key in MEDIA_KEYS:
        assert status['p_parser_capability'] == 'publisher_event_candidates_v1'


@pytest.mark.parametrize('key', KEYS)
def test_collection_failure_records_hold_on_correct_contract_without_staging(monkeypatch, key):
    monkeypatch.setattr(worker, 'fetch_publisher', Mock(side_effect=worker.PreviewError('robots_denied')))
    calls = []
    monkeypatch.setattr(worker, 'supabase_rpc', lambda name, payload: calls.append((name, deepcopy(payload))))
    result = worker._process_claimed_source(sources.source_payload(key))
    assert result['failed'] == 1 and result['complete'] == 0 and result['staged'] == 0
    assert len(calls) == 1 and calls[0][0] == expected_rpc(key)
    assert calls[0][1]['p_error'] == 'robots_denied'
    assert calls[0][1]['p_samples'] == [] and 'p_parser_capability' not in calls[0][1]


def test_octech_missing_second_detail_never_stages_the_partial_first_course(monkeypatch):
    key = institutions.OCTECH
    mock_publisher_transport(monkeypatch, key, full_octech=True)
    calls = []
    monkeypatch.setattr(worker, 'supabase_rpc', lambda name, payload: calls.append((name, deepcopy(payload))))
    result = worker._process_claimed_source(sources.source_payload(key))
    assert result['complete'] == 0 and result['failed'] == 1 and result['staged'] == 0
    assert len(calls) == 1 and calls[0][0] == 'community_collector_record_preview_v2'
    assert calls[0][1]['p_error'] == 'octech_document_invalid'


def elloree_transport(monkeypatch, *, status=200, content_type='application/json', body=b'[]'):
    reply = MagicMock(status_code=status, headers={'Content-Type': content_type}, encoding='utf-8')
    reply.iter_content.return_value = [body]
    session = MagicMock()
    session.__enter__.return_value = session
    session.post.return_value = reply
    monkeypatch.setattr(worker.requests, 'Session', lambda: session)
    dns, robots, pace = Mock(), Mock(return_value=True), Mock()
    monkeypatch.setattr(worker, 'validate_public_dns', dns)
    monkeypatch.setattr(worker, 'robots_allowed', robots)
    monkeypatch.setattr(worker, 'pace_publisher', pace)
    monkeypatch.setattr(worker, '_observe_retry_after', Mock())
    return session, reply, dns, robots, pace


def test_elloree_render_posts_only_exact_empty_json_under_normal_guards(monkeypatch):
    session, reply, dns, robots, pace = elloree_transport(monkeypatch)
    assert worker.render_elloree_calendar() == '[]'
    session.get.assert_not_called()
    session.post.assert_called_once()
    args, kwargs = session.post.call_args
    assert args == (civic.ELLOREE_API,)
    assert kwargs['json'] == {} and 'data' not in kwargs
    assert kwargs['allow_redirects'] is False and kwargs['stream'] is True
    assert kwargs['headers']['Accept'] == kwargs['headers']['Content-Type'] == 'application/json'
    assert kwargs['headers']['Referer'] == civic.SOURCES[civic.ELLOREE]['url']
    assert 'Authorization' not in kwargs['headers'] and 'Cookie' not in kwargs['headers']
    dns.assert_called_once_with('connect.elloreesc.com')
    robots.assert_called_once_with('connect.elloreesc.com', '/api/functions/getPublicCalendarEvents')
    pace.assert_called_once()
    reply.close.assert_called_once()


@pytest.mark.parametrize('changed', [
    {'url': 'https://connect.elloreesc.com/api/functions/deleteEvent'},
    {'url': 'https://other.example/api/functions/getPublicCalendarEvents'},
    {'accept': 'text/html'}, {'respect_robots': False},
    {'allowed_hosts': ('connect.elloreesc.com', 'other.example')},
    {'calendar_json': {'id': '123'}}, {'calendar_json': []}, {'calendar_json': ''},
    {'calendar_form': {'action': 'anything'}},
])
def test_elloree_post_boundary_rejects_arbitrary_urls_bodies_and_weaker_guards(monkeypatch, changed):
    request = dict(url=civic.ELLOREE_API, accept='application/json', respect_robots=True,
                   allowed_hosts=('connect.elloreesc.com',), calendar_json={})
    request.update(changed)
    session, dns = Mock(), Mock()
    monkeypatch.setattr(worker.requests, 'Session', session)
    monkeypatch.setattr(worker, 'validate_public_dns', dns)
    with pytest.raises(worker.PreviewError, match='invalid_calendar_render_parameters'):
        worker._fetch_publisher_request(**request)
    session.assert_not_called()
    dns.assert_not_called()


@pytest.mark.parametrize('status', [301, 302, 303, 307, 308])
def test_elloree_post_is_never_replayed_on_redirect(monkeypatch, status):
    session, reply, _, _, _ = elloree_transport(monkeypatch, status=status)
    reply.headers['Location'] = 'https://other.example/redirect'
    with pytest.raises(worker.PreviewError, match='calendar_render_redirect_blocked'):
        worker.render_elloree_calendar()
    session.post.assert_called_once()
    session.get.assert_not_called()
    reply.close.assert_called_once()


def test_elloree_wrong_content_type_and_robots_denial_never_claim_empty(monkeypatch):
    session, reply, _, _, _ = elloree_transport(monkeypatch, content_type='text/html')
    with pytest.raises(worker.PreviewError, match='invalid_calendar_render_content_type'):
        worker.render_elloree_calendar()
    reply.close.assert_called_once()
    session, _, _, robots, _ = elloree_transport(monkeypatch)
    robots.return_value = False
    with pytest.raises(worker.PreviewError, match='robots_denied'):
        worker.render_elloree_calendar()
    session.post.assert_not_called()
