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


def test_production_entrypoint_dispatches_registration_before_preview():
    import importlib.util
    from pathlib import Path
    from types import ModuleType
    from unittest.mock import Mock

    modules = {}
    for name in ('geocode', 'preview', 'chambermaster', 'provider_pilot', 'category_demand',
                 'html_demand', 'media_demand', 'things_to_do', 'timezones', 'feed_registration'):
        module = ModuleType('api.' + name)
        module.handler = type(name + 'Handler', (), {'do_GET': Mock(), 'do_POST': Mock()})
        modules[module.__name__] = module
    spec = importlib.util.spec_from_file_location('registration_index', Path(__file__).parents[1] / 'api/index.py')
    entry = importlib.util.module_from_spec(spec)
    with patch.dict('sys.modules', modules):
        spec.loader.exec_module(entry)
    handler = object.__new__(entry.handler)
    handler.path = '/api/feed-registration'
    handler.do_POST()
    modules['api.feed_registration'].handler.do_POST.assert_called_once_with(handler)
    modules['api.preview'].handler.do_POST.assert_not_called()


def test_verified_venue_follows_one_same_publisher_calendar_then_registers_its_feed():
    venue = 'https://venue.example.org/'
    page = '<a href="/events/">Events</a><a href="https://other.example.org/calendar">Partner</a>'
    assert classify(venue, page)['p_outcome'] == 'review'
    with patch('roomquest.feed_registration.supabase_rpc', side_effect=[{'url': venue, 'verified_venue_website': True}, True]) as rpc, \
         patch('roomquest.feed_registration.fetch_publisher', side_effect=[page, '<a href="/music.ics">Subscribe</a>']) as fetch:
        assert register('ticket')['outcome'] == 'discovered'
        assert rpc.call_args.args[1]['p_endpoint'] == venue + 'music.ics'
        assert [call.args[0] for call in fetch.call_args_list] == [venue, venue + 'events/']
        assert all(call.kwargs['respect_robots'] for call in fetch.call_args_list)

def test_wordpress_collection_requires_endpoint_and_event_evidence():
    import json
    payload = json.dumps({'events': [{'id': 71, 'title': 'Public reading', 'start_date': '2027-01-04 10:00:00'}]})
    for url in (URL + '/wp-json/tribe/events/v1/events', URL + '/?rest_route=%2Ftribe%2Fevents%2Fv1%2Fevents'):
        assert classify(url, payload) == {'p_outcome': 'verified', 'p_endpoint': url, 'p_type': 'wordpress'}
        assert classify(url, '{"events":[],"total":0}')['p_outcome'] == 'verified'
        assert classify(url, '{"events":[{}]}')['p_reason'] == 'invalid_wordpress_calendar'
        assert classify(url, '{"events":[]}')['p_outcome'] == 'review'
    assert classify(URL + '/arbitrary', payload)['p_outcome'] == 'review'
