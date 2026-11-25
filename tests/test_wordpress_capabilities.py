"""Native-first WordPress capability recognition, without inventing feeds."""
import json
from unittest.mock import patch

import pytest

from roomquest.wordpress_capabilities import (
    advertised_rest_root, inspect_rest_index, rest_route_url, wordpress_fingerprints,
)
from roomquest.feed_registration import register
from roomquest.venue_calendar_locator import find_calendar

ROOT = 'https://theatre.example.org/whats-on/'


@pytest.mark.parametrize(('html', 'expected'), [
    ('<link rel="https://api.w.org/" href="https://theatre.example.org/wp-json/">',
     'https://theatre.example.org/wp-json/'),
    ('<link href="/?rest_route=%2F" rel="https://api.w.org/">',
     'https://theatre.example.org/?rest_route=%2F'),
    ('<link rel="https://api.w.org/" href="https://theatre.example.org/wordpress/wp-json/">',
     'https://theatre.example.org/wordpress/wp-json/'),
    ('<link rel="https://api.w.org/" href="https://elsewhere.example.org/wp-json/">', None),
    ('<link rel="https://api.w.org/" href="http://theatre.example.org/wp-json/">', None),
    ('<link rel="https://api.w.org/" href="/wp-json/?foo=bar">', None),
    ('<a href="/wp-json/">Not publisher-advertised</a>', None),
    ('<link rel="https://api.w.org/" href="/wp-json/">'
     '<link rel="https://api.w.org/" href="/wordpress/wp-json/">', None),
])
def test_publisher_advertised_rest_root_only(html, expected):
    assert advertised_rest_root(ROOT, '<html><head>' + html + '</head></html>') == expected


def test_plugin_and_legacy_fingerprints_do_not_imply_a_feed():
    assert 'the-events-calendar' in wordpress_fingerprints(
        '<link href="/wp-content/plugins/the-events-calendar/style.css">')
    assert 'events-manager' in wordpress_fingerprints(
        '<script src="/wp-content/plugins/events-manager/events.js"></script>')
    assert 'legacy-json-api' in wordpress_fingerprints(
        '<a href="/?json=get_recent_posts">Old JSON plugin</a>')
    assert 'tickera' in wordpress_fingerprints(
        '<script src="/wp-content/plugins/tickera-events-listing/events.js"></script>')
    assert 'event-discovery' in wordpress_fingerprints(
        '<script src="/wp-content/plugins/event-discovery/calendar.js"></script>')
    assert wordpress_fingerprints('<p>Ordinary blog</p>') == ()


def test_wix_bootstrap_text_cannot_impersonate_a_wordpress_plugin():
    html = '''<html><script id="wix-warmup-data" type="application/json">
      {"componentName":"eo-event","asset":"/event-organiser/card.js"}
      </script><script src="https://static.wixstatic.com/services/wix-thunderbolt.js"></script></html>'''
    assert wordpress_fingerprints(html) == ()


def test_both_wp_rest_route_styles_and_subdirectory_installation():
    assert rest_route_url('https://theatre.example.org/wp-json/', '/tribe/events/v1/events') == (
        'https://theatre.example.org/wp-json/tribe/events/v1/events')
    assert rest_route_url('https://theatre.example.org/wordpress/wp-json/', '/tribe/events/v1/events') == (
        'https://theatre.example.org/wordpress/wp-json/tribe/events/v1/events')
    assert rest_route_url('https://theatre.example.org/?rest_route=%2F', '/tribe/events/v1/events') == (
        'https://theatre.example.org/?rest_route=/tribe/events/v1/events')
    assert rest_route_url('http://theatre.example.org/wp-json/', '/tribe/events/v1/events') is None


def test_tec_get_route_required_and_custom_cpt_not_auto_registered():
    root = 'https://theatre.example.org/wp-json/'
    index = {'namespaces': ['wp/v2', 'tribe/events/v1'], 'routes': {
        '/wp/v2/types': {'endpoints': [{'methods': ['GET']}]},
        '/tribe/events/v1/events': {'endpoints': [{'methods': ['GET', 'POST']}]},
        '/wp/v2/events': {'endpoints': [{'methods': ['GET']}]}}}
    result = inspect_rest_index(root, json.dumps(index))
    assert result['endpoint'] == root + 'tribe/events/v1/events'
    assert result['collector'] == 'wordpress'
    assert result['custom_event_routes'] == ('/wp/v2/events',)
    assert result['types_route'] is True
    index['routes']['/tribe/events/v1/events']['endpoints'][0]['methods'] = ['POST']
    assert inspect_rest_index(root, json.dumps(index))['endpoint'] is None
    del index['routes']['/tribe/events/v1/events']
    assert inspect_rest_index(root, json.dumps(index))['endpoint'] is None


def test_legacy_and_unsupported_plugin_routes_are_recognition_only():
    older = inspect_rest_index('https://theatre.example.org/wp-json/', json.dumps({
        'namespaces': ['oembed/1.0'], 'routes': {}}))
    assert older['rest_generation'] == 'pre_core_or_restricted'
    assert older['endpoint'] is None
    modern = inspect_rest_index('https://theatre.example.org/wp-json/', json.dumps({
        'namespaces': ['wp/v2', 'mec/v1.0', 'events-manager/v1', 'eventon/v2'],
        'routes': {'/wp/v2/events': {'methods': ['GET']},
                   '/mec/v1.0/events': {'methods': ['GET']}}}))
    assert modern['endpoint'] is None
    assert set(modern['plugin_families']) == {
        'modern-events-calendar', 'events-manager', 'eventon'}
    assert modern['custom_event_routes'] == ('/wp/v2/events',)


@pytest.mark.parametrize('payload', [
    'not json', '[]', '{}', '{"namespaces":[], "routes":[]}',
    '{"namespaces":"wp/v2", "routes":{}}',
])
def test_invalid_rest_index_cannot_enable_calendar(payload):
    assert inspect_rest_index('https://theatre.example.org/wp-json/', payload) is None


def test_an_unhinted_tec_api_is_discovered_via_the_publisher_index():
    page = 'https://theatre.example.org/whats-on/'
    root = 'https://theatre.example.org/wp-json/'
    endpoint = root + 'tribe/events/v1/events'
    listing = ('<html><head><link rel="https://api.w.org/" href="/wp-json/"></head>'
               '<body><h1>Upcoming events</h1><a href="/event/first">First</a>'
               '<a href="/event/second">Second</a></body></html>')
    index = json.dumps({'namespaces': ['wp/v2', 'tribe/events/v1'],
                        'routes': {'/tribe/events/v1/events':
                                   {'endpoints': [{'methods': ['GET']}]}}})
    events = json.dumps({'events': [{'id': 31, 'title': 'London workshop',
                                    'start_date': '2027-04-03 19:00:00'}],
                         'total': 1, 'total_pages': 1})
    responses = {page: listing, root: index, endpoint: events}
    def fetch(url, accept, **kwargs):
        assert kwargs.get('respect_robots') is True
        if url != page:
            assert kwargs.get('allowed_hosts') == ('theatre.example.org',)
        return responses[url]
    with patch('roomquest.feed_registration.supabase_rpc',
               side_effect=[{'url': page}, True]) as rpc, \
         patch('roomquest.feed_registration.fetch_publisher', side_effect=fetch) as get, \
         patch('roomquest.feed_registration.probe', return_value=True) as probe:
        assert register('original-ticket') == {'outcome': 'discovered'}
    receipt = rpc.call_args.args[1]
    assert (receipt['p_outcome'], receipt['p_type'], receipt['p_endpoint']) == (
        'discovered', 'wordpress', endpoint)
    assert [item.args[0] for item in get.call_args_list] == [page, root, endpoint]
    probe.assert_called_once_with(endpoint, events, 'wordpress')


def test_tec_hint_uses_advertised_legacy_root_before_guessing_modern_path():
    page = 'https://theatre.example.org/events/'
    endpoint = 'https://theatre.example.org/?rest_route=/tribe/events/v1/events'
    html = ('<link rel="https://api.w.org/" href="/?rest_route=%2F">'
            '<div class="tribe-events">A real TEC calendar</div>')
    events = '{"events":[{"id":1,"title":"Museum night","start_date":"2027-01-01"}],"total":1}'
    responses = {endpoint: events}
    def fetch(url, accept, **kwargs):
        assert kwargs['allowed_hosts'] == ('theatre.example.org',)
        return responses[url]
    with patch('roomquest.venue_calendar_locator.classify',
               return_value={'p_outcome': 'verified', 'p_type': 'wordpress'}):
        assert find_calendar(html, page, None, fetch, float('inf'),
                             require_unique_calendar_page=True) == (endpoint, 'wordpress')


def test_custom_post_type_does_not_register_without_event_facts():
    page = 'https://theatre.example.org/events/'
    root = 'https://theatre.example.org/wp-json/'
    html = '<link rel="https://api.w.org/" href="/wp-json/">'
    index = json.dumps({'namespaces': ['wp/v2'],
                        'routes': {'/wp/v2/types': {'methods': ['GET']},
                                   '/wp/v2/events': {'methods': ['GET']}}})
    seen = []
    def fetch(url, accept, **kwargs):
        seen.append(url)
        assert url == root
        return index
    result = find_calendar(html, page, None, fetch, float('inf'))
    assert result != ('https://theatre.example.org/wp-json/wp/v2/events', 'wordpress')
    assert seen == [root]


def test_location_filter_does_not_open_an_unfiltered_wp_api():
    page = 'https://theatre.example.org/events/?venue=one'
    html = '<link rel="https://api.w.org/" href="/wp-json/">'
    def unexpected(*args, **kwargs):
        raise AssertionError('Filtered source must not fetch an unfiltered API')
    find_calendar(html, page, None, unexpected, float('inf'))
