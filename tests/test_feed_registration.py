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


def test_direct_spektrix_client_website_keeps_provider_identity():
    url = 'https://tickets.foxtucson.com/foxtucsontheatre/website/'
    assert classify(url, '<html><title>Fox Tucson Theatre</title></html>') == {
        'p_outcome': 'discovered',
        'p_endpoint': 'https://tickets.foxtucson.com/foxtucsontheatre/api/v3/events',
        'p_type': 'spektrix',
    }


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


def test_html_listing_keeps_filter_and_single_events_out_of_registration():
    url = URL + '/events?venue=East'
    page = '<a href="/event/play">Play</a><a href="/event/music">Music</a>'
    assert classify(url, page)['p_reason'] == 'html_adapter_needed'
    assert classify(url, page + '<a href="/all.ics">All venues</a>')['p_outcome'] == 'review'
    assert classify(url, page + '<a href="/feed.ics?venue=East">East</a>')['p_endpoint'].endswith('venue=East')
    assert classify(URL + '/events/detail/a-play', page)['p_reason'] == 'single_event_page'


def test_jsonld_collection_runs_normalizer_before_verification():
    import json
    from datetime import datetime, timedelta, timezone
    url = URL + '/events'
    future = (datetime.now(timezone.utc) + timedelta(days=4)).isoformat()
    base = {'@type': 'MusicEvent', 'startDate': future, 'name': 'Concert', 'location': {'name': 'Concert Hall'}}
    def wrap(events):
        return '<script type="application/ld+json">' + json.dumps(events) + '</script>'
    assert classify(url, wrap([dict(base, url=url + '/one'), dict(base, url=url + '/two')]))['p_type'] == 'jsonld'
    assert classify(url, wrap([dict(base, url=url + '/one'), dict(base, url=url + '/two')]))['p_outcome'] == 'verified'
    assert classify(url, wrap(dict(base,url=url)))['p_reason'] == 'single_event_page'


def test_squarespace_listing_preserves_all_selectors_for_probe():
    listing = 'https://calendar.example.org/events?tag=A&tag=B'
    html = '<html class="collection-type-events"><script src="https://static.squarespace.com/site.js"></script></html>'
    assert classify(listing, html)['p_endpoint'] == listing + '&format=json'


def test_empty_calendar_cannot_activate_without_a_collected_event():
    with patch('roomquest.feed_registration.supabase_rpc', side_effect=[{'url': URL}, True]) as rpc, \
         patch('roomquest.feed_registration.fetch_publisher', return_value=EMPTY):
        assert register('ticket')['outcome'] == 'retry'
        assert rpc.call_args.args[1]['p_reason'] == 'no_extractable_events'


def test_squarespace_hold_preserves_the_collector_reason():
    import json
    data = {'upcoming': [], 'pagination': {'nextPage': True}}
    result = classify(URL + '?format=json', json.dumps(data))
    assert result == {'p_outcome': 'review', 'p_type': 'squarespace', 'p_reason': 'pagination_requires_review'}


def test_reviewed_html_follows_a_verified_tec_collection_once_not_ambiguous_ical_links():
    import json
    page = 'https://calendar.example.org/events'
    endpoint = 'https://calendar.example.org/wp-json/tribe/events/v1/events'
    html = ('<div class="tribe-events"><a href="/first.ics">Calendar A</a>'
            '<a href="/second.ics">Calendar B</a></div>')
    payload = json.dumps({'events': [{'id': 71, 'title': 'Public reading',
                                       'start_date': '2027-03-04 10:00:00'}], 'total': 1})
    with patch('roomquest.feed_registration.supabase_rpc',
               side_effect=[{'url': page}, True]) as rpc, \
         patch('roomquest.feed_registration.fetch_publisher',
               side_effect=[html, payload]) as fetch, \
         patch('roomquest.feed_registration.probe', return_value=True) as parse:
        assert register('ticket') == {'outcome': 'discovered'}
    receipt = rpc.call_args.args[1]
    assert (receipt['p_outcome'], receipt['p_endpoint'], receipt['p_type']) == (
        'discovered', endpoint, 'wordpress')
    assert rpc.call_count == 2  # One claim and one finish; no per-link database reads.
    assert fetch.call_count == 2  # Original HTML and one verified provider response.
    assert [call.args[0] for call in fetch.call_args_list] == [page, endpoint]
    assert all(call.kwargs['respect_robots'] for call in fetch.call_args_list)
    assert fetch.call_args_list[1].kwargs['allowed_hosts'] == ('calendar.example.org',)
    parse.assert_called_once_with(endpoint, payload, 'wordpress')


def test_html_registration_does_not_select_arbitrary_calendar_or_parent_page():
    page = 'https://calendar.example.org/'
    html = ('<a href="/events">Upcoming events</a>'
            '<a href="/calendar">Event calendar</a>')
    with patch('roomquest.feed_registration.supabase_rpc',
               side_effect=[{'url': page}, True]) as rpc, \
         patch('roomquest.feed_registration.fetch_publisher', return_value=html) as fetch:
        assert register('ticket') == {'outcome': 'retry'}
    assert rpc.call_args.args[1]['p_reason'] == 'no_reusable_calendar'
    assert fetch.call_count == 1  # Conflicting index links do not trigger exploration.


def test_html_registration_preserves_scope_instead_of_deriving_unfiltered_tec():
    page = 'https://calendar.example.org/events?venue=East'
    html = '<div class="tribe-events">Venue-specific dated events</div>'
    with patch('roomquest.feed_registration.supabase_rpc',
               side_effect=[{'url': page}, True]) as rpc, \
         patch('roomquest.feed_registration.fetch_publisher', return_value=html) as fetch:
        assert register('ticket') == {'outcome': 'retry'}
    assert rpc.call_args.args[1]['p_reason'] == 'the_events_calendar_adapter_needed'
    assert fetch.call_count == 1  # A generic TEC API would drop the venue selector.


def test_html_registration_does_not_register_a_zero_event_collection():
    page = 'https://calendar.example.org/events'
    html = '<div class="tribe-events">This venue has a calendar</div>'
    empty = '{"events":[],"total":0}'
    with patch('roomquest.feed_registration.supabase_rpc',
               side_effect=[{'url': page}, True]) as rpc, \
         patch('roomquest.feed_registration.fetch_publisher',
               side_effect=[html, empty]) as fetch, \
         patch('roomquest.feed_registration.probe', return_value=False):
        assert register('ticket') == {'outcome': 'retry'}
    assert rpc.call_args.args[1]['p_reason'] == 'the_events_calendar_adapter_needed'
    assert fetch.call_count == 2


def test_html_registration_keeps_robots_denial_of_new_endpoint_on_hold():
    page = 'https://calendar.example.org/events'
    html = '<div class="tribe-events">Public calendar</div>'
    with patch('roomquest.feed_registration.supabase_rpc',
               side_effect=[{'url': page}, True]) as rpc, \
         patch('roomquest.feed_registration.fetch_publisher',
               side_effect=[html, PreviewError('robots_denied')]) as fetch:
        assert register('ticket') == {'outcome': 'retry'}
    assert rpc.call_args.args[1]['p_reason'] == 'the_events_calendar_adapter_needed'
    assert fetch.call_count == 2
    assert fetch.call_args_list[1].kwargs['respect_robots'] is True


def test_venue_locator_unique_page_guard_is_opt_in():
    from roomquest.venue_calendar_locator import find_calendar
    page = 'https://calendar.example.org/'
    html = ('<a href="/events">Upcoming events</a>'
            '<a href="/calendar">Event calendar</a>')
    fetch = lambda *args, **kwargs: ''
    assert find_calendar(html, page, None, fetch, 10, require_unique_calendar_page=True) == (
        None, 'multiple_pages')
    assert find_calendar(html, page, None, fetch, 10) == (None, 'none')



def test_verified_venue_linked_html_calendar_can_recover_without_new_registration():
    import json
    venue = 'https://calendar.example.org/'
    listing = 'https://calendar.example.org/events/'
    endpoint = 'https://calendar.example.org/wp-json/tribe/events/v1/events'
    root_html = '<a href="/events/">Upcoming events</a>'
    listing_html = '<div class="tribe-events"><h1>Events</h1></div>'
    payload = json.dumps({'events': [{'id': 72, 'title': 'Library workshop',
                                       'start_date': '2027-03-09 12:00:00'}], 'total': 1})
    with patch('roomquest.feed_registration.supabase_rpc',
               side_effect=[{'url': venue, 'verified_venue_website': True}, True]) as rpc, \
         patch('roomquest.feed_registration.fetch_publisher',
               side_effect=[root_html, listing_html, payload]) as fetch, \
         patch('roomquest.feed_registration.probe', return_value=True):
        assert register('ticket') == {'outcome': 'discovered'}
    receipt = rpc.call_args.args[1]
    assert (receipt['p_outcome'], receipt['p_endpoint'], receipt['p_type']) == (
        'discovered', endpoint, 'wordpress')
    assert fetch.call_count == 3
    assert [call.args[0] for call in fetch.call_args_list] == [venue, listing, endpoint]
    assert rpc.call_count == 2
    assert all(call.kwargs['respect_robots'] for call in fetch.call_args_list)


def test_verified_venue_linked_html_without_verified_feed_does_not_promote_endpoint():
    venue = 'https://calendar.example.org/'
    listing = 'https://calendar.example.org/events/'
    html = '<a href="/events/">Upcoming events</a>'
    details = '<h1>Events</h1><a href="/events/first">First event</a>'
    with patch('roomquest.feed_registration.supabase_rpc',
               side_effect=[{'url': venue, 'verified_venue_website': True}, True]) as rpc, \
         patch('roomquest.feed_registration.fetch_publisher',
               side_effect=[html, details]) as fetch:
        assert register('ticket') == {'outcome': 'retry'}
    result = rpc.call_args.args[1]
    assert result['p_reason'] == 'html_adapter_needed'
    assert 'p_endpoint' not in result  # Never persist an unverified child URL as a feed.
    assert fetch.call_count == 2




def test_publisher_meta_charset_does_not_require_lossy_decoding():
    from roomquest.preview_worker import _html_declared_charset
    html = b'<html><head><meta charset="windows-1252"></head><body>caf\xe9</body></html>'
    assert _html_declared_charset(html) == 'windows-1252'
    assert 'café' in html.decode(_html_declared_charset(html), errors='strict')
    assert _html_declared_charset(b'<meta charset="utf-8">') == 'utf-8'
    assert _html_declared_charset(b'<meta charset="unknown-charset">') is None
    assert _html_declared_charset(b'<html>no charset</html>') is None
    assert _html_declared_charset(b' ' * 4096 + b'<meta charset="windows-1252">') is None
