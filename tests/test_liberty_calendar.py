"""Sanitized public facts plus synthetic transport replies; no publisher I/O."""
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

import pytest

from roomquest import liberty_calendar as c
from roomquest import preview_worker as w

NOW = datetime(2026, 11, 22, 9, tzinfo=timezone.utc)
DAY = NOW.date()
TOKEN = 'eyJhbGciOiJIUzI1NiJ9.eyJndWVzdCI6dHJ1ZX0.' + 's' * 43
SCRIPT_URL = c.ORIGINAL + '_next/static/chunks/' + 'b' * 16 + '.js'
IDS = {'getApiUrl': '00' + 'a' * 40, 'getApiToken': '00' + 'b' * 40}
SCRIPT = ';'.join('(0,h.createServerReference)("' + value + '",h.callServer,void 0,h.findSourceMapURL,"' + name + '")'
                  for name, value in IDS.items())
FIXTURE = Path(__file__).parent / 'fixtures/liberty/public-events.json'


def listing(chunks=None, *, included=None, export='AuthProvider'):
    chunks = chunks or ['/_next/static/chunks/' + value * 16 + '.js' for value in 'abc']
    frame = '5:I' + json.dumps([27232, chunks, export]) + '\n'
    return ''.join('<script src="' + value + '"></script>' for value in (chunks if included is None else included)) + (
        '<script>self.__next_f.push(' + json.dumps([1, frame]) + ')</script>')


def action(value, *, long=False):
    head = '0:{"a":"$@1","f":"","b":"public-build"}\n'
    if long:
        return head + '2:T' + format(len(value.encode('utf-8')), 'x') + ',' + value + '1:"$2"\n'
    return head + '1:' + json.dumps(value) + '\n'


def packet(events):
    return json.dumps({'queryInfo': {'totalResults': len(events), 'totalPages': 1, 'pageIndex': 1}, 'events': events})


def native():
    return json.loads(FIXTURE.read_text())['events']


def preview(title, start, end, venue, street, city, url, identity, **kwargs):
    return dict(id=identity, title=title, starts_at=start.astimezone(timezone.utc).isoformat(),
        ends_at=end.astimezone(timezone.utc).isoformat(), venue_name=venue, venue_address=street,
        venue_city=city, event_url=url, lat=None, lng=None)


@pytest.fixture(autouse=True)
def clock_and_normalizer():
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
    with patch.object(c, 'datetime', Clock), patch.object(c, 'record', side_effect=preview):
        yield


def callbacks(events=None):
    fetch = Mock(side_effect=lambda url, accept: SCRIPT if url == SCRIPT_URL else '/* unrelated public app chunk */')
    getter = Mock(side_effect=lambda **args: action(c.API_ORIGIN) if args['getter'] == 'getApiUrl' else action(TOKEN, long=True))
    api = Mock(return_value=packet(native() if events is None else events))
    return fetch, getter, api


def collect(events=None, **changes):
    fetch, getter, api = callbacks(events)
    options = dict(listing=listing(), fetch_action=getter, fetch_events=api)
    options.update(changes)
    rows = c.collect({'feed_url': c.ORIGINAL, 'source_key': c.SOURCE_KEY}, fetch, **options)
    return rows, fetch, getter, api


def test_exact_source_bootstrap_dynamic_ids_public_facts_and_occurrence_identity():
    rows, fetch, getter, api = collect()
    assert len(rows) == 4
    assert fetch.call_count == 2
    assert [call.args[1] for call in fetch.call_args_list] == ['application/javascript'] * 2
    assert [call.kwargs['getter'] for call in getter.call_args_list] == list(c.GETTERS)
    assert all(call.kwargs['script_url'] == SCRIPT_URL and call.kwargs['script'] == SCRIPT for call in getter.call_args_list)
    api.assert_called_once_with(page=1, window_start=DAY, public_token=TOKEN, deadline_at=None)
    assert not any('Hockey' in row['title'] for row in rows)  # Native/description time contradiction.
    montview = next(row for row in rows if row['title'] == 'Bestie BOGO')
    assert montview['venue_name'] == 'Montview Student Union'
    assert montview['venue_address'] == '1410 Regents Pkwy, Lynchburg, VA 24515'
    assert all(row['description'] and row['timezone'] == c.ZONE
               and row['lat'] is None and row['lng'] is None for row in rows)
    assert TOKEN not in json.dumps(rows)
    assert 'creatorUser' not in FIXTURE.read_text() and 'metadata' not in FIXTURE.read_text()


def test_native_wall_clock_timezone_is_preserved_when_public_times_agree():
    event = native()[0]
    event['eventDescription'] = '<p>Public hockey game at 3PM.</p>'
    rows, *_ = collect([event])
    ice = rows[0]
    assert ice['id'] == 'liberty-occurrence:36303'
    assert ice['starts_at'] == '2026-11-22T20:00:00+00:00'
    assert ice['timezone'] == 'America/New_York'
    assert ice['event_url'] == c.ORIGINAL + 'event/md3-hockey-vs-university-of-virginia'


def test_conflicting_description_is_held_without_moving_the_public_start():
    with pytest.raises(ValueError, match='^no_extractable_events$'):
        collect([native()[0]])


def test_ancillary_door_and_registration_times_are_not_event_start_claims():
    event = native()[0]
    event['eventDescription'] = '<p>Doors open at 2PM. Registration closes at 1:30PM. Public hockey game at 3PM.</p>'
    rows, *_ = collect([event])
    assert rows[0]['starts_at'] == '2026-11-22T20:00:00+00:00'


def test_repeated_event_with_distinct_explicit_occurrences_is_retained():
    first = next(event for event in native() if event['eventId'] == 17249)
    second = deepcopy(first)
    second['occurrences'][0]['occurrenceId'] = 34147
    for field in ('startTime', 'endTime'):
        value = second['occurrences'][0][field]
        value.update(month=12, day=2, timeString=value['timeString'].replace('2026-11-30', '2026-12-02'))
    rows, *_ = collect([first, second])
    assert [row['id'] for row in rows] == ['liberty-occurrence:34143', 'liberty-occurrence:34147']


@pytest.mark.parametrize('change', ['url', 'key'])
def test_source_gate_runs_before_fetch(change):
    source = {'feed_url': c.ORIGINAL, 'source_key': c.SOURCE_KEY}
    source['feed_url' if change == 'url' else 'source_key'] += 'other'
    fetch = Mock()
    with pytest.raises(ValueError, match='^unregistered_liberty_calendar$'):
        c.collect(source, fetch)
    fetch.assert_not_called()


def test_rotated_script_hash_and_action_ids_are_read_as_data():
    url = SCRIPT_URL.replace('b' * 16, 'd' * 16)
    script = SCRIPT.replace('00' + 'a' * 40, '00' + 'c' * 40)
    assert c.bootstrap_scripts(listing([url])) == (url,)
    assert c.action_reference(url, script, 'getApiUrl') == '00' + 'c' * 40


@pytest.mark.parametrize('html', [listing(export='OtherProvider'), listing(included=[]),
    listing(['https://unreviewed.example/_next/static/chunks/' + 'a' * 16 + '.js']),
    listing(['/private/' + 'a' * 16 + '.js']),
    listing(['/_next/static/chunks/' + value * 16 + '.js' for value in 'abcd']),
    listing() + listing(['/_next/static/chunks/' + 'd' * 16 + '.js'])])
def test_missing_conflicting_unreferenced_foreign_and_unbounded_bootstrap_is_held(html):
    with pytest.raises(ValueError, match='liberty_bootstrap_changed'):
        c.bootstrap_scripts(html)


def test_no_matching_helper_stops_after_three_observed_scripts():
    fetch, getter, api = callbacks()
    fetch.side_effect = None
    fetch.return_value = '/* no getters */'
    with pytest.raises(ValueError, match='liberty_bootstrap_changed'):
        c.collect({'feed_url': c.ORIGINAL, 'source_key': c.SOURCE_KEY}, fetch,
            listing=listing(), fetch_action=getter, fetch_events=api)
    assert fetch.call_count == 3
    getter.assert_not_called()
    api.assert_not_called()


def test_next_text_frame_is_byte_counted_and_never_executed():
    assert c.action_result(action(TOKEN, long=True)) == TOKEN
    assert c.action_result(action('public calendar ☃', long=True)) == 'public calendar ☃'
    assert c.action_result(action(c.API_ORIGIN)) == c.API_ORIGIN


@pytest.mark.parametrize('payload', ['1:"value"\n', '0:{"a":"$@1"}\n1:"$9"\n',
    '0:{"a":"$@1"}\n1:"$2"\n2:"$1"\n', '0:{"a":"$@1"}\n1:"a"\n1:"b"\n',
    '0:{"a":"$@1"}\n1:E{"message":"secret must not appear"}\n',
    '0:{"a":"$@1"}\n2:Tfffff,short1:"$2"\n', 'x' * (c.MAX_ACTION_BYTES + 1)])
def test_bad_return_frames_have_only_static_safe_errors(payload):
    with pytest.raises(ValueError, match='^liberty_bootstrap_changed$'):
        c.action_result(payload)


def test_unreviewed_api_origin_stops_before_getting_a_token():
    getter = Mock(return_value=action('https://another.example'))
    api = Mock()
    with pytest.raises(ValueError, match='^liberty_api_origin_changed$'):
        collect(fetch_action=getter, fetch_events=api)
    getter.assert_called_once()
    api.assert_not_called()


@pytest.mark.parametrize('visibility,published', [('Private', 1), ('Public', 0), ('Public', True), (None, 1), ('public', 1)])
def test_public_and_published_are_both_required(visibility, published):
    event = native()[0]
    event.update(visibility=visibility, published=published)
    with pytest.raises(ValueError, match='^no_extractable_events$'):
        collect([event])


@pytest.mark.parametrize('label', ['Liberty University', 'Events Placeholder Location', 'LaHaye Event Space',
    'Montview Student Union - Parking Lot', 'School of Business - All', 'JF Library Online Classroom'])
def test_unknown_generic_placeholder_virtual_and_parking_venues_are_held(label):
    event = native()[0]
    event['locations'] = [{'locationId': 1, 'locationFormalName': label}]
    with pytest.raises(ValueError, match='^no_extractable_events$'):
        collect([event])


def test_mixed_buildings_and_holiday_only_are_held_even_with_a_known_address():
    ambiguous = next(event for event in native() if event['eventId'] == 16218)
    holiday = next(event for event in native() if event['eventId'] == 8675)
    holiday['locations'] = native()[0]['locations']
    with pytest.raises(ValueError, match='^no_extractable_events$'):
        collect([ambiguous, holiday])


def test_only_visitor_facing_description_is_retained():
    event = native()[0]
    event['creatorUser'] = {'email': 'never-copy@example.test'}
    event['metadata'] = [{'metadataName': 'private-note', 'metadataValue': 'do not persist'}]
    event['eventDescription'] = '<p>Public game details.</p><script>do not execute</script>'
    rows, *_ = collect([event])
    assert rows[0]['description'] == 'Public game details.'
    assert 'never-copy' not in json.dumps(rows) and 'do not persist' not in json.dumps(rows)


@pytest.mark.parametrize('change', ['timezone', 'bool_zone', 'timeString', 'end', 'occurrences', 'duplicate'])
def test_changed_times_occurrence_shape_and_duplicate_page_rows_fail_closed(change):
    event = native()[0]
    events = [event]
    if change == 'timezone': event['occurrences'][0]['startTime']['timezone'] = 5
    elif change == 'bool_zone': event['occurrences'][0]['startTime']['timezone'] = False
    elif change == 'timeString': event['occurrences'][0]['startTime']['timeString'] = '2026-11-22T17:45'
    elif change == 'end': event['occurrences'][0]['endTime'] = deepcopy(event['occurrences'][0]['startTime'])
    elif change == 'occurrences': event['occurrences'].append(deepcopy(event['occurrences'][0]))
    elif change == 'duplicate': events.append(deepcopy(event))
    with pytest.raises(ValueError, match='^liberty_(?:event_time_changed|occurrences_changed|calendar_incomplete)$'):
        collect(events)


@pytest.mark.parametrize('info', [dict(totalResults=101, totalPages=2, pageIndex=1),
    dict(totalResults=7, totalPages=2, pageIndex=1), dict(totalResults=8, totalPages=1, pageIndex=1),
    dict(totalResults=7, totalPages=1, pageIndex=2), dict(totalResults=True, totalPages=1, pageIndex=1)])
def test_oversized_incomplete_or_changed_pagination_never_follows_another_page(info):
    api = Mock(return_value=json.dumps({'queryInfo': info, 'events': native()}))
    with pytest.raises(ValueError, match='^liberty_calendar_(?:limit|incomplete|changed)$'):
        collect(fetch_events=api)
    api.assert_called_once()


def test_deadline_stops_before_any_discovery_or_token_request():
    fetch, getter, api = callbacks()
    with patch.object(c, 'monotonic', return_value=100), pytest.raises(ValueError, match='^collection_deadline$'):
        c.collect({'feed_url': c.ORIGINAL, 'source_key': c.SOURCE_KEY}, fetch,
            listing=listing(), deadline_at=99, fetch_action=getter, fetch_events=api)
    fetch.assert_not_called()
    getter.assert_not_called()
    api.assert_not_called()


def reply(*, action_mode=False, status=200, headers=None, chunks=None):
    response = Mock(status_code=status, encoding='utf-8')
    response.headers = {'Content-Type': 'text/x-component' if action_mode else 'application/json', **(headers or {})}
    response.iter_content.return_value = chunks if chunks is not None else [b'{}']
    return response


def network(response, *, allowed=True):
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.get.return_value = session.post.return_value = response
    return session, [patch.object(w.requests, 'Session', return_value=session),
        patch.object(w, 'validate_public_dns'), patch.object(w, 'robots_allowed', return_value=allowed),
        patch.object(w, 'pace_publisher'), patch.object(w, 'activity_before_request'),
        patch.object(w, 'current_snapshot')]


def read(action_mode=False):
    if action_mode:
        return w.read_liberty_public_action(script_url=SCRIPT_URL, script=SCRIPT, getter='getApiToken')
    return w.read_liberty_events(page=1, window_start=DAY, public_token=TOKEN)


@pytest.mark.parametrize('action_mode', [False, True])
def test_guarded_public_transport_exact_method_headers_and_no_checkpoint(action_mode, caplog):
    session, patches = network(reply(action_mode=action_mode))
    with ExitStack() as stack:
        mocks = [stack.enter_context(item) for item in patches]
        assert read(action_mode) == '{}'
    url = c.ORIGINAL if action_mode else c.events_url(page=1, window_start=DAY)
    parts = urlsplit(url)
    mocks[1].assert_called_once_with(parts.hostname)
    assert mocks[2].call_args.args == (parts.netloc, parts.path + ('?' + parts.query if parts.query else ''))
    mocks[3].assert_called_once()
    mocks[4].assert_called_once_with(url, redirect=False)
    mocks[5].assert_not_called()
    method, other = (session.post, session.get) if action_mode else (session.get, session.post)
    method.assert_called_once()
    other.assert_not_called()
    args, kwargs = method.call_args
    assert args == (url,) and kwargs['stream'] is True and kwargs['allow_redirects'] is False
    expected = {'User-Agent': w.robots_checkpoint.PUBLISHER_USER_AGENT,
        'Accept': 'text/x-component' if action_mode else 'application/json'}
    if action_mode:
        expected.update({'Content-Type': 'text/plain;charset=UTF-8', 'Next-Action': IDS['getApiToken'],
            'Origin': 'https://events.liberty.edu'})
        assert kwargs['data'] == b'[]' and 'json' not in kwargs
    else:
        expected['Authorization'] = 'Bearer ' + TOKEN
        assert 'data' not in kwargs and 'json' not in kwargs
    assert kwargs['headers'] == expected
    assert TOKEN not in caplog.text


@pytest.mark.parametrize('action_mode', [False, True])
def test_robots_denial_stops_before_any_getter_or_events_request(action_mode):
    session, patches = network(reply(action_mode=action_mode), allowed=False)
    with ExitStack() as stack:
        for item in patches: stack.enter_context(item)
        with pytest.raises(w.PreviewError, match='^robots_denied$'): read(action_mode)
    session.get.assert_not_called()
    session.post.assert_not_called()


@pytest.mark.parametrize('action_mode', [False, True])
@pytest.mark.parametrize('status,headers,chunks,reason', [
    (403, {}, None, 'publisher_http_403'), (401, {}, None, 'publisher_http_401'),
    (302, {'Location': 'https://another.example/collect-token'}, None, 'redirect_blocked'),
    (200, {'Content-Type': 'text/html'}, None, 'invalid_liberty_content_type'),
    (200, {'Content-Length': '3000001'}, None, 'source_unavailable_or_oversized'),
    (200, {}, [b'x' * 3_000_001], 'source_too_large'),
])
def test_denials_redirects_types_and_size_have_no_retry_or_response_leak(action_mode, status, headers, chunks, reason, caplog):
    response = reply(action_mode=action_mode, status=status, headers=headers, chunks=chunks)
    session, patches = network(response)
    with ExitStack() as stack:
        for item in patches: stack.enter_context(item)
        with pytest.raises(w.PreviewError, match='^' + reason + '$'): read(action_mode)
    assert session.get.call_count + session.post.call_count == 1
    response.close.assert_called_once()
    assert TOKEN not in caplog.text


@pytest.mark.parametrize('mutation', ['host', 'route', 'getter', 'script_host', 'script_path', 'script_body',
    'robots', 'accept', 'hosts', 'redirects', 'post_body', 'other_key', 'token'])
def test_bootstrap_transport_cannot_become_an_arbitrary_action(mutation):
    url, accept = c.ORIGINAL, 'text/x-component'
    script_url, script, getter = SCRIPT_URL, SCRIPT, 'getApiToken'
    options = dict(respect_robots=True, allowed_hosts=(c.HOST,), follow_redirects=False)
    if mutation == 'host': url = url.replace(c.HOST, 'another.example')
    elif mutation == 'route': url += 'admin'
    elif mutation == 'getter': getter = 'deleteEvent'
    elif mutation == 'script_host': script_url = script_url.replace(c.HOST, 'another.example')
    elif mutation == 'script_path': script_url = script_url.replace('/_next/static/', '/admin/')
    elif mutation == 'script_body': script = '"getApiToken":"' + IDS['getApiToken'] + '"'
    elif mutation == 'robots': options['respect_robots'] = False
    elif mutation == 'accept': accept = 'application/json'
    elif mutation == 'hosts': options['allowed_hosts'] = (c.HOST, c.API_HOST)
    elif mutation == 'redirects': options['follow_redirects'] = True
    elif mutation == 'post_body': options['calendar_json'] = {'write': True}
    elif mutation == 'other_key': options['game_theory_key'] = 'not-anonymous'
    elif mutation == 'token': options['liberty_token'] = TOKEN
    options['liberty_action'] = (script_url, script, getter)
    with patch.object(w.requests, 'Session') as session, pytest.raises(w.PreviewError, match='^invalid_liberty_action_request$'):
        w._fetch_publisher_request(url, accept, **options)
    session.assert_not_called()


@pytest.mark.parametrize('mutation', ['host', 'route', 'page', 'limit', 'published', 'grouped', 'extra_query',
    'window', 'fragment', 'token', 'injection', 'robots', 'accept', 'hosts', 'redirects', 'post_body', 'other_key'])
def test_anonymous_token_cannot_cross_origin_or_read_another_view(mutation):
    url, accept = c.events_url(page=1, window_start=DAY), 'application/json'
    options = dict(respect_robots=True, allowed_hosts=(c.API_HOST,), follow_redirects=False, liberty_token=TOKEN)
    if mutation == 'host': url = url.replace(c.API_HOST, 'another.example')
    elif mutation == 'route': url = url.replace('/events?', '/users?')
    elif mutation == 'page': url = url.replace('page=1', 'page=2')
    elif mutation == 'limit': url = url.replace('resultsPerPage=100', 'resultsPerPage=1000')
    elif mutation == 'published': url = url.replace('published=1', 'published=0')
    elif mutation == 'grouped': url = url.replace('groupOccurrences=false', 'groupOccurrences=true')
    elif mutation == 'extra_query': url += '&visibility=Private'
    elif mutation == 'window': url = url.replace('2026-12-21', '2027-12-21')
    elif mutation == 'fragment': url += '#anything'
    elif mutation == 'token': options['liberty_token'] = 'an-account-token'
    elif mutation == 'injection': options['liberty_token'] += '\r\nX-Other: value'
    elif mutation == 'robots': options['respect_robots'] = False
    elif mutation == 'accept': accept = 'text/html'
    elif mutation == 'hosts': options['allowed_hosts'] = (c.HOST, c.API_HOST)
    elif mutation == 'redirects': options['follow_redirects'] = True
    elif mutation == 'post_body': options['calendar_json'] = {'write': True}
    elif mutation == 'other_key': options['brewing_instance'] = 'unrelated'
    with patch.object(w.requests, 'Session') as session, pytest.raises(w.PreviewError, match='^invalid_liberty_events_request$'):
        w._fetch_publisher_request(url, accept, **options)
    session.assert_not_called()


def test_action_response_has_a_smaller_body_cap():
    session, patches = network(reply(action_mode=True, chunks=[b'x' * (c.MAX_ACTION_BYTES + 1)]))
    with ExitStack() as stack:
        for item in patches: stack.enter_context(item)
        with pytest.raises(w.PreviewError, match='^source_too_large$'): read(True)
    session.post.assert_called_once()


def test_request_budget_and_source_deadline_remain_authoritative():
    session, patches = network(reply())
    with ExitStack() as stack:
        mocks = [stack.enter_context(item) for item in patches]
        mocks[4].side_effect = w.PreviewError('source_request_limit')
        with pytest.raises(w.PreviewError, match='^source_request_limit$'): read()
    session.get.assert_not_called()
    with patch.object(w, 'monotonic', return_value=100), patch.object(w, 'validate_public_dns') as dns:
        with pytest.raises(w.PreviewError, match='^source_fetch_deadline$'):
            w.read_liberty_events(page=1, window_start=DAY, public_token=TOKEN, deadline_at=99)
    dns.assert_not_called()
