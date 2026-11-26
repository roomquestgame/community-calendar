"""Exercise submitted URL -> provider receipt -> ordinary collection."""
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch

import pytest
from roomquest import (feed_registration, preview_worker, tickera_provider,
                       ticketweb_event_discovery, tockify_provider)
from roomquest.registration_formats import source_key
from test_tickera_ticketweb_providers import tickera_page, event_discovery_page, event_discovery_payload


def seo(url):
    day = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    return '<script type="application/ld+json">' + json.dumps([
        {'@type': 'Event', 'name': 'Summary ' + slug, 'startDate': day,
         'url': url + '/event/' + slug, 'location': {'name': 'Hall'}}
        for slug in ('one', 'two')]) + '</script>'


@pytest.mark.parametrize('path', ['events/', 'shows/', 'whats-on/', 'upcoming-events/'])
@pytest.mark.parametrize('adapter,module,page,extra', [
    ('tickera', tickera_provider, tickera_page(), {'wp-json/': '{"timezone_string":"America/New_York"}'}),
    ('event_discovery', ticketweb_event_discovery, event_discovery_page(),
     {'wp-admin/admin-ajax.php': event_discovery_payload()}),
])
def test_url_navigation_keeps_native_provider_even_with_seo(path, adapter, module, page, extra):
    root = 'https://venue.example.org/'
    listing = root + path
    home = '<html><script src="' + module.PLUGIN + 'main.js"></script><a href="/' + path + '">Events</a>' + seo(root) + '</html>'
    receipts = []
    responses = {root: home, listing: page, **{root + k: v for k, v in extra.items()}}
    def rpc(method, args, **kwargs):
        if method.endswith('claim_registration'):
            return {'url': root}
        if method.endswith('feed_profile'):
            return {}
        receipts.append(args)
        return True
    def fetch(url, accept, **kwargs):
        assert kwargs['respect_robots']
        return responses[url]
    with patch.object(feed_registration, 'supabase_rpc', rpc), patch.object(feed_registration, 'fetch_publisher', fetch):
        assert feed_registration.register('ticket') == {'outcome': 'discovered'}
    assert receipts[-1]['p_type'] == adapter
    assert receipts[-1]['p_endpoint'] == listing
    # Use the exact returned identity in the ordinary collector, not a parser-only assertion.
    source = {'feed_url': listing, 'source_key': source_key(listing), 'kind': 'json', 'platform_adapter': adapter}
    with patch.object(preview_worker, 'supabase_rpc', rpc), patch.object(preview_worker, 'fetch_publisher', fetch):
        result = preview_worker.preview_source(source)
    assert result['p_future_count'] == 1 and result['p_error'] is None


@pytest.mark.parametrize('module', [tickera_provider, ticketweb_event_discovery])
def test_provider_navigation_keeps_scope_and_requires_unambiguous_advertised_link(module):
    marker = '<script src="' + module.PLUGIN + 'main.js"></script>'
    root = 'https://venue.example.org/'
    assert module.calendar_destination(root, marker + '<a href="/shows/">Shows</a>') == root + 'shows/'
    assert module.calendar_destination(root, marker + '<a href="/shows/">Shows</a><a href="/events/">Events</a>') is None
    assert module.calendar_destination(root, marker + '<a href="https://foreign.example/events/">Events</a>') is None
    assert module.calendar_destination(root + 'events?venue=East', marker + '<a href="/calendar/">All</a>') is None
    assert module.calendar_destination(root + 'venues/east', marker + '<a href="/events/">All</a>') is None
    assert module.calendar_destination(root + 'events?venue=East', marker + '<a href="/calendar/?venue=East">East</a>') == root + 'calendar/?venue=East'


def test_squarespace_json_beats_seo_and_keeps_selectors():
    url = 'https://venue.example.org/events?tag=A&tag=B'
    page = '<html class="collection-type-events"><script src="https://static.squarespace.com/main.js"></script>' + seo(url) + '</html>'
    assert feed_registration.classify(url, page) == {
        'p_outcome': 'discovered', 'p_type': 'squarespace', 'p_endpoint': url + '&format=json'}


def test_tec_native_api_beats_seo_through_registration():
    url = 'https://venue.example.org/events'
    endpoint = 'https://venue.example.org/wp-json/tribe/events/v1/events'
    day = (datetime.now(timezone.utc) + timedelta(days=3)).strftime('%Y-%m-%d %H:%M:%S')
    payload = json.dumps({'events': [{'id': 1, 'title': 'Actual native event', 'start_date': day,
        'utc_start_date': (datetime.strptime(day, '%Y-%m-%d %H:%M:%S') + timedelta(hours=5)).strftime('%Y-%m-%d %H:%M:%S'), 'timezone': 'America/New_York', 'url': url + '/actual', 'status': 'publish'}], 'total': 1})
    page = '<html><div class="tribe-events"></div>' + seo(url) + '</html>'
    with patch.object(feed_registration, 'supabase_rpc', side_effect=[{'url': url}, True]) as rpc, \
         patch.object(feed_registration, 'fetch_publisher', side_effect=[page, payload]) as fetch:
        assert feed_registration.register('ticket') == {'outcome': 'discovered'}
    assert rpc.call_args.args[1]['p_type'] == 'wordpress'
    assert rpc.call_args.args[1]['p_endpoint'] == endpoint
    assert [call.args[0] for call in fetch.call_args_list] == [url, endpoint]


def test_valid_empty_provider_refreshes_are_not_parser_failures():
    page = tickera_page()
    start = page.index('events: [') + len('events: [')
    end = page.index('], eventDidMount', start)
    empty = page[:start] + page[end:]
    assert tickera_provider.parse(empty, url='https://venue.example.org/calendar/', zone='UTC') == []
    assert ticketweb_event_discovery.parse('{"events":[]}', url='https://venue.example.org/calendar/', zone='UTC') == []
    with pytest.raises(ValueError):
        ticketweb_event_discovery.parse('{"events":[{}]}', url='https://venue.example.org/calendar/', zone='UTC')


def test_growthzone_native_xml_beats_seo():
    from test_growthzone_calendar_registration import PAGE, LISTING, _run
    with patch('test_growthzone_calendar_registration.LISTING', LISTING + seo(PAGE)):
        status, receipts, urls, calls = _run()
    assert status == {'outcome': 'discovered'}
    assert receipts[0]['p_type'] == 'growthzone'
    assert calls == 1


@pytest.mark.parametrize('adapter,page,extra', [
    ('tickera', tickera_page(), '{"timezone_string":"America/New_York"}'),
    ('event_discovery', event_discovery_page(), '{"events":[]}'),
])
def test_valid_empty_calendar_does_not_create_a_new_source(adapter, page, extra):
    if adapter == 'tickera':
        start = page.index('events: [') + len('events: [')
        end = page.index('], eventDidMount', start)
        page = page[:start] + page[end:]
    def rpc(method, args, **kwargs):
        if method.endswith('claim_registration'):
            return {'url': 'https://venue.example.org/calendar/'}
        if method.endswith('feed_profile'):
            return {}
        assert args['p_outcome'] == 'retry'
        assert args['p_reason'] == 'no_extractable_events'
        return True
    with patch.object(feed_registration, 'supabase_rpc', rpc), \
         patch.object(feed_registration, 'fetch_publisher', side_effect=[page, extra]):
        assert feed_registration.register('ticket') == {'outcome': 'retry'}


def test_tockify_embed_discovers_and_verifies_standard_ics_subscription():
    day = datetime.now(timezone.utc) + timedelta(days=7)
    root = 'https://publisher.example.org/'
    feed = 'https://tockify.com/api/feeds/ics/community.events'
    page = '''<html><div data-tockify-calendar="community.events"></div>
    <script src="https://public.tockify.com/browser/embed.js"></script></html>'''
    ical = f'''BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
UID:tockify-1\r
DTSTART:{day.strftime('%Y%m%d')}T190000Z\r
SUMMARY:Community show\r
URL:https://publisher.example.org/events/community-show\r
END:VEVENT\r
END:VCALENDAR\r
'''
    assert tockify_provider.subscription(page) == feed
    receipts = []
    def rpc(method, args, **kwargs):
        if method.endswith('claim_registration'):
            return {'url': root}
        receipts.append(args)
        return True
    def fetch(url, accept, **kwargs):
        return page if url == root else ical if url == feed else pytest.fail(url)
    with patch.object(feed_registration, 'supabase_rpc', rpc), patch.object(
            feed_registration, 'fetch_publisher', fetch):
        assert feed_registration.register('ticket')['outcome'] == 'discovered'
    assert receipts[-1]['p_outcome'] == 'discovered'
    assert receipts[-1]['p_endpoint'] == feed
    assert receipts[-1]['p_type'] == 'ical'


def test_tockify_multiple_or_unproved_embeds_are_not_guessed():
    marker = '<script src="https://public.tockify.com/browser/embed.js"></script>'
    assert tockify_provider.subscription('<div data-tockify-calendar="one"></div>') is None
    assert tockify_provider.subscription(
        marker + '<div data-tockify-calendar="one"></div><div data-tockify-calendar="two"></div>') is None


@pytest.mark.parametrize('adapter,module', [
    ('event_discovery', ticketweb_event_discovery), ('tickera', tickera_provider),
])
def test_native_navigation_defers_endpoint_verification_to_its_existing_child_claim(adapter, module):
    root = 'https://venue.example.org/'
    destination = root + 'calendar/'
    home = '<script src="' + module.PLUGIN + 'front.js"></script><a href="/calendar/">Calendar</a>'
    with patch.object(feed_registration, 'supabase_rpc', side_effect=[{'url': root}, True]) as rpc, \
         patch.object(feed_registration, 'fetch_publisher', return_value=home) as fetch:
        assert feed_registration.register('parent-ticket') == {'outcome': 'discovered'}
    assert fetch.call_count == 1 and fetch.call_args.args[0] == root
    assert fetch.call_args.kwargs['respect_robots'] is True
    result = rpc.call_args.args[1]
    assert (result['p_outcome'], result['p_type'], result['p_endpoint']) == ('discovered', adapter, destination)
    # An advertised endpoint is not itself verification, source creation or
    # permission to bypass the independently claimed endpoint's robots rules.
    with patch.object(feed_registration, 'supabase_rpc', side_effect=[{'url': destination, 'type_hint': adapter, 'endpoint_only': True}, True]) as rpc, \
         patch.object(feed_registration, 'fetch_publisher', side_effect=preview_worker.PreviewError('robots_denied')) as fetch:
        assert feed_registration.register('child-ticket') == {'outcome': 'disabled'}
    assert rpc.call_args.args[1]['p_reason'] == 'robots_denied'
    assert rpc.call_args.args[1]['p_type'] == adapter
    assert rpc.call_args.args[1]['p_endpoint'] == destination
    assert fetch.call_count == 1 and fetch.call_args.kwargs['respect_robots'] is True


def test_unverified_user_hint_does_not_supply_detected_identity_on_failed_fetch():
    with patch.object(feed_registration, 'supabase_rpc', side_effect=[
            {'url': 'https://venue.example.org/', 'type_hint': 'event_discovery'}, True]) as rpc, \
         patch.object(feed_registration, 'fetch_publisher', side_effect=preview_worker.PreviewError('robots_denied')):
        assert feed_registration.register('ticket') == {'outcome': 'disabled'}
    assert rpc.call_args.args[1].get('p_type') is None
