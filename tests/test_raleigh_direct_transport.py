"""Exact public read operations retain robots, DNS, pacing and redirect guards."""
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import pytest

from roomquest import preview_worker as w
from roomquest import raleigh_direct_arts as arts, raleigh_direct_community as community


PUBLIC_KEY = 'sb_publishable_' + 'x'*24  # Synthetic public key; never a live credential.


def dates():
    day = datetime.now(ZoneInfo(community.ZONE)).date()
    return day, day+timedelta(days=60)


def response(status=200, **headers):
    result = Mock(status_code=status, encoding='utf-8')
    result.headers = {'Content-Type': 'application/json', **headers}
    result.iter_content.return_value = [b'[]']
    return result


def network(reply, allowed=True):
    session = Mock(); session.__enter__ = Mock(return_value=session); session.__exit__ = Mock(return_value=False)
    session.get.return_value = reply; session.post.return_value = reply
    patches = [patch.object(w.requests, 'Session', return_value=session),
               patch.object(w, 'validate_public_dns'), patch.object(w, 'robots_allowed', return_value=allowed),
               patch.object(w, 'pace_publisher')]
    return session, patches


def game_read():
    first, last = dates()
    return w.read_game_theory_events(public_key=PUBLIC_KEY, window_start=first.isoformat(), window_end=last.isoformat())


def art_read():
    first, _ = dates()
    return w.render_artspace_calendar(year=first.year, month=first.month, atts=arts.ARTSPACE_ATTS, window_start=first.isoformat())


def test_public_key_get_is_exact_read_only_host_route_query_and_headers():
    session, patches = network(response())
    with patches[0], patches[1] as dns, patches[2] as robots, patches[3] as pace:
        assert game_read() == '[]'
    dns.assert_called_once_with(community.GAME_API_HOST)
    robots.assert_called_once(); pace.assert_called_once(); session.post.assert_not_called()
    args, kwargs = session.get.call_args
    assert community.valid_game_theory_request(args[0], PUBLIC_KEY)
    assert kwargs['headers']['apikey'] == PUBLIC_KEY and kwargs['headers']['Authorization'] == 'Bearer ' + PUBLIC_KEY
    assert kwargs['allow_redirects'] is False and kwargs['stream'] is True
    assert kwargs['headers']['User-Agent'] == w.robots_checkpoint.PUBLISHER_USER_AGENT


@pytest.mark.parametrize('mutation', ['host', 'route', 'query', 'secret', 'jwt', 'post', 'robots', 'media', 'window'])
def test_game_read_rejects_arbitrary_requests_before_network(mutation):
    first, last = dates()
    url = community.game_theory_request(PUBLIC_KEY, first.isoformat(), last.isoformat())
    options = dict(respect_robots=True, allowed_hosts=(community.GAME_API_HOST,), game_theory_key=PUBLIC_KEY)
    accept = 'application/json'
    if mutation == 'host': url = url.replace(community.GAME_API_HOST, 'other.supabase.co')
    elif mutation == 'route': url = url.replace('/rest/v1/events', '/rest/v1/private_users')
    elif mutation == 'query': url += '&select=private_column'
    elif mutation == 'secret': options['game_theory_key'] = 'sb_secret_'+'x'*30
    elif mutation == 'jwt': options['game_theory_key'] = 'eyJhbGciOiJIUzI1NiJ9.fake.signature'
    elif mutation == 'post': options['calendar_json'] = {'action': 'write'}
    elif mutation == 'robots': options['respect_robots'] = False
    elif mutation == 'media': accept = 'text/html'
    elif mutation == 'window': url = url.replace(first.isoformat(), '2099-01-01')
    with patch.object(w.requests, 'Session') as session:
        with pytest.raises(w.PreviewError, match='^invalid_game_theory_request$'):
            w._fetch_publisher_request(url, accept, **options)
        session.assert_not_called()


def test_artspace_posts_only_native_month_display_fields():
    session, patches = network(response())
    with patches[0], patches[1] as dns, patches[2] as robots, patches[3] as pace:
        assert art_read() == '[]'
    dns.assert_called_once_with('artspacenc.org'); robots.assert_called_once(); pace.assert_called_once()
    args, kwargs = session.post.call_args
    assert args == (arts.ARTSPACE_API,)
    assert arts.valid_artspace_calendar_form(kwargs['data'])
    assert kwargs['data']['action'] == 'mec_tile_load_month'
    assert len(urlencode(kwargs['data']).encode()) < 8192
    assert kwargs['headers']['Referer'] == 'https://artspacenc.org/calendar/'
    assert 'apikey' not in kwargs['headers'] and 'Authorization' not in kwargs['headers']
    assert kwargs['allow_redirects'] is False
    session.get.assert_not_called()


def test_artspace_native_json_body_may_use_its_observed_html_content_type():
    session, patches = network(response(**{'Content-Type': 'text/html; charset=UTF-8'}))
    with patches[0], patches[1], patches[2], patches[3]:
        assert art_read() == '[]'
    assert session.post.call_count == 1


@pytest.mark.parametrize('mutation', [{'action': 'delete_event'}, {'atts[id]': '1'}, {'extra': 'x'}, {'mec_year': '2099'}])
def test_artspace_rejects_arbitrary_post_fields_before_network(mutation):
    day, _ = dates()
    form = {**arts.artspace_calendar_form(day.year, day.month, arts.ARTSPACE_ATTS, day.isoformat()), **mutation}
    with patch.object(w.requests, 'Session') as session:
        with pytest.raises(w.PreviewError, match='invalid_calendar_render_parameters'):
            w._fetch_publisher_request(arts.ARTSPACE_API, 'application/json', respect_robots=True,
                                       allowed_hosts=('artspacenc.org',), calendar_form=form)
        session.assert_not_called()


@pytest.mark.parametrize('read,method', [(game_read, 'get'), (art_read, 'post')])
def test_public_reads_respect_robots_and_never_replay_redirects(read, method):
    session, patches = network(response(), allowed=False)
    with patches[0], patches[1], patches[2], patches[3]:
        with pytest.raises(w.PreviewError, match='^robots_denied$'):
            read()
    session.get.assert_not_called(); session.post.assert_not_called()
    session, patches = network(response(302, Location='https://example.com/elsewhere'))
    with patches[0], patches[1], patches[2], patches[3]:
        with pytest.raises(w.PreviewError, match='calendar_render_redirect_blocked'):
            read()
    assert getattr(session, method).call_count == 1


@pytest.mark.parametrize('read', [game_read, art_read])
def test_403_and_non_json_responses_remain_failures(read):
    for reply, reason in [(response(403), 'publisher_http_403'),
                          (response(**{'Content-Type': 'application/xml'}), 'invalid_calendar_render_content_type')]:
        session, patches = network(reply)
        with patches[0], patches[1], patches[2], patches[3]:
            with pytest.raises(w.PreviewError, match=reason): read()
        assert session.get.call_count + session.post.call_count == 1
