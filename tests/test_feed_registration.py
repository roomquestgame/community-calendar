from unittest.mock import patch

import pytest

from roomquest.feed_registration import classify, register
from roomquest.preview_worker import PreviewError

URL = 'https://calendar.example.org/list'
EMPTY = 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Fixture//EN\r\nEND:VCALENDAR\r\n'


def test_calendar_content_wins_over_hint_and_supports_empty_feed():
    assert classify(URL, EMPTY, 'wordpress') == {'p_outcome': 'verified', 'p_endpoint': URL, 'p_type': 'ical'}
    assert classify(URL, EMPTY.rsplit('END:', 1)[0])['p_outcome'] == 'review'
    assert classify(URL + '?eventID=12', EMPTY)['p_reason'] == 'single_event_page'


def test_follow_only_an_unambiguous_calendar_subscription():
    html = '<link rel="alternate" type="text/calendar" href="/classes.ics?group=Yoga">'
    assert classify(URL, html)['p_endpoint'].endswith('/classes.ics?group=Yoga')
    assert classify(URL, html + '<a href="/other.ics">Other</a>')['p_reason'] == 'multiple_calendar_links'
    assert classify(URL, '<a href="/event/one/?ical=1">Add to calendar</a>')['p_outcome'] == 'review'
    assert classify(URL, html, endpoint_only=True)['p_outcome'] == 'review'
    assert classify(URL, '{"events": []}')['p_type'] is None
    assert classify(URL + '/wp-json/tribe/events/v1/events', '{"events": []}')['p_type'] == 'wordpress'


@pytest.mark.parametrize(('reason','outcome'), [('robots_denied','disabled'),('publisher_http_403','disabled'),
    ('publisher_http_503','retry'),('source_network_error','retry'),('publisher_http_429','retry'),
    ('non_public_dns','review')])
def test_worker_uses_robots_and_retains_access_result(reason, outcome):
    with patch('roomquest.feed_registration.supabase_rpc', side_effect=[{'url': URL},True]) as rpc, \
         patch('roomquest.feed_registration.fetch_publisher', side_effect=PreviewError(reason)) as fetch:
        assert register('ticket') == {'outcome':outcome}
    assert fetch.call_args.kwargs['respect_robots'] is True
    result = rpc.call_args.args[1]
    assert (result['p_outcome'], result['p_reason'], result['p_ticket']) == (outcome, reason, 'ticket')


def test_no_publisher_request_for_unknown_or_used_ticket():
    with patch('roomquest.feed_registration.supabase_rpc', return_value=None), \
         patch('roomquest.feed_registration.fetch_publisher') as fetch:
        assert register('old') == {'outcome':'idle'}
        fetch.assert_not_called()
