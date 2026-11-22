"""Reviewed public captures through the real registration and recurring paths.

Only publisher I/O and the registration RPC are stubbed. These tests do not
contact Battersea Bloem, Square, a geocoder, or the database.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from unittest.mock import Mock, patch
from urllib.parse import urlencode, urlsplit

import pytest

from roomquest import battersea_bloem as calendar
from roomquest import feed_registration as registration
from roomquest import preview_worker as worker
from roomquest import registered_listings as listings
from roomquest import uk_registered_listings as uk
from roomquest.registration_formats import source_key


FIXTURES = Path(__file__).parent / 'fixtures/battersea_bloem'
MANIFEST = json.loads((FIXTURES / 'manifest.json').read_text())
API_URL = next(row['url'] for row in MANIFEST['source_files']
               if row['name'] == 'square-featured-events.json')
IDS = ['2THLH7MU7MK7SV2IZFY3XMHY', '88', '6Q6UA5W3CUQ3KJQVKJNAAPJB',
       '130', 'ULW5X4F6ILEIXBVG2E7GNYCO', '2CJYQ7RO4GNPZDDOBVBGXIYZ', '90']
HOSTS = ('www.batterseabloem.com', 'battersea-bloem.square.site')
CELL = ('siteData', 'page', 'properties', 'contentAreas', 'userContent', 'content', 'cells', 0)


class FrozenMeta(type):
    def __instancecheck__(cls, value):
        return isinstance(value, datetime)


class FrozenDateTime(datetime, metaclass=FrozenMeta):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 11, 22, 12, tzinfo=timezone.utc)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def freeze_clock(monkeypatch):
    # Keep the actual shared normalizer/date horizon running against the
    # capture date; do not replace record(), timestamp(), or description().
    for module in (calendar, worker, listings, uk):
        monkeypatch.setattr(module, 'datetime', FrozenDateTime)


def fixture(name):
    return (FIXTURES / name).read_text()


def source():
    return dict(feed_url=calendar.URL, source_key=source_key(calendar.URL),
                kind='html', platform_adapter='html', timezone='Europe/London')


def change(value, path, replacement):
    for part in path[:-1]:
        value = value[part]
    value[path[-1]] = replacement


def home_with(path, value):
    raw = fixture('square-home.html')
    match = re.search(r'window\.__BOOTSTRAP_STATE__ = (.*);</script>', raw)
    state = json.loads(match[1])
    change(state, path, value)
    return raw[:match.start(1)] + json.dumps(state) + raw[match.end(1):]


def products_with(path, value):
    data = json.loads(fixture('square-events.json'))
    change(data, path, value)
    return json.dumps(data)


def network(*, listing=None, home=None, products=None):
    responses = {
        calendar.URL: listing if listing is not None else fixture('workshop-envelope.json'),
        calendar.STORE: home if home is not None else fixture('square-home.html'),
        API_URL: products if products is not None else fixture('square-events.json'),
    }

    def fetch(url, accept, **options):
        assert url in responses, 'Unexpected publisher request: ' + url
        if url == calendar.STORE:
            assert accept == 'text/html'
        if url == API_URL:
            assert accept == 'application/json'
        return responses[url]
    return Mock(side_effect=fetch)


def collect(**options):
    return listings.collect(source(), network(**options))


def assert_transport(fetch, *, first_accept, initial_scoped):
    assert [call.args[0] for call in fetch.call_args_list] == [calendar.URL, calendar.STORE, API_URL]
    first = fetch.call_args_list[0]
    assert first.args[1] == first_accept
    deadline = first.kwargs['deadline_at']
    assert deadline > 0
    expected = dict(respect_robots=True, deadline_at=deadline)
    assert first.kwargs == ({**expected, 'allowed_hosts': HOSTS} if initial_scoped else expected)
    assert all(call.kwargs == {**expected, 'allowed_hosts': HOSTS}
               for call in fetch.call_args_list[1:])


def test_captured_html_and_duda_envelope_produce_same_seven_actual_sessions():
    rows = collect()
    assert rows == collect(listing=fixture('workshop.html'))
    expected = [
        ('2026-11-27T20:00:00+00:00', '2026-11-27T22:30:00+00:00'),
        ('2026-11-28T15:00:00+00:00', '2026-11-28T17:30:00+00:00'),
        ('2026-11-29T10:30:00+00:00', '2026-11-29T13:00:00+00:00'),
        ('2026-11-29T15:00:00+00:00', '2026-11-29T17:30:00+00:00'),
        ('2026-12-04T20:00:00+00:00', '2026-12-04T22:30:00+00:00'),
        ('2026-12-05T15:00:00+00:00', '2026-12-05T17:30:00+00:00'),
        ('2026-12-17T20:00:00+00:00', '2026-12-17T22:00:00+00:00'),
    ]
    assert [(row['starts_at'], row['ends_at']) for row in rows] == expected
    assert [row['id'] for row in rows] == ['battersea-square:' + identity for identity in IDS]
    products = json.loads(fixture('square-events.json'))['data']
    assert [row['event_url'] for row in rows] == [item['absolute_site_link'] for item in products]
    assert all(row['venue_name'] == 'Battersea Bloem' and row['venue_address'] ==
               '10 Hamilton Road, Cambridge CB4 1BP, United Kingdom' for row in rows)
    assert all(row['timezone'] == 'Europe/London' and row['lat'] is None and row['lng'] is None
               and row['reason'] == 'missing_verified_venue_geo' for row in rows)
    assert all('Price: £48.50.' in row['description'] for row in rows[:6])
    assert 'Price: £37.50.' in rows[-1]['description']
    assert [row['id'] for row in rows if 'Tickets sold out.' in row['description']] == [
        'battersea-square:' + identity for identity in ('88', '130', IDS[4], IDS[5])]
    assert all('cancel' not in str(row).lower() for row in rows)
    assert [row['image_url'] for row in rows] == [item['thumbnail']['data']['absolute_url'] for item in products]
    assert not any('native' in key or 'evidence' in key for row in rows for key in row)


@pytest.mark.parametrize('hint', [None, 'ical'])
def test_registration_verifies_original_receipt_through_existing_html_dispatch(hint):
    fetch = network()
    with patch.object(registration, 'fetch_publisher', fetch), patch.object(
            registration, 'supabase_rpc', side_effect=[
                {'id': 877, 'url': calendar.URL, 'type_hint': hint}, True]) as rpc:
        assert registration.register('receipt-ticket') == {'outcome': 'verified'}
    assert_transport(fetch, first_accept=registration.ACCEPT, initial_scoped=False)
    assert [call.args[0] for call in rpc.call_args_list] == [
        'community_collector_claim_registration', 'community_collector_finish_registration']
    assert rpc.call_args.args[1] == dict(p_ticket='receipt-ticket', p_outcome='verified',
                                      p_type='html', p_endpoint=calendar.URL)


def test_recurring_collection_uses_same_exact_adapter_and_existing_candidate_contract():
    fetch = network(listing=fixture('workshop.html'))
    with patch.object(worker, 'fetch_publisher', fetch), patch.object(worker, 'supabase_rpc') as rpc:
        result = worker.preview_source(source(), deadline_at=worker.monotonic() + 45)
    assert_transport(fetch, first_accept='text/html', initial_scoped=True)
    rpc.assert_not_called()
    assert result['p_source_key'] == source_key(calendar.URL)
    assert result['p_future_count'] == 7 and result['p_venue_count'] == 0 and result['p_error'] is None
    assert result['p_parser_capability'] == 'publisher_event_candidates_v1'
    assert result['p_events'] == collect()


def test_featured_selection_is_read_each_time_and_unfeatured_products_are_never_queried():
    featured = ['90', '88']
    home = home_with(CELL + ('content', 'properties', 'featuredEventIds'), featured)
    payload = json.loads(fixture('square-events.json'))
    payload['data'] = [item for item in payload['data'] if item['site_product_id'] in featured]
    payload['meta']['pagination'].update(total=2, count=2, per_page=2)
    target = API_URL.split('?')[0] + '?' + urlencode([
        ('page', 1), ('per_page', 2), ('product_type', 'event'), ('ids[]', '90'), ('ids[]', '88')])
    responses = {calendar.URL: fixture('workshop.html'), calendar.STORE: home,
                 target: json.dumps(payload)}
    fetch = Mock(side_effect=lambda url, accept: responses[url])
    rows = listings.collect(source(), fetch)
    assert [row['id'] for row in rows] == ['battersea-square:88', 'battersea-square:90']
    assert [call.args[0] for call in fetch.call_args_list] == [calendar.URL, calendar.STORE, target]


@pytest.mark.parametrize('changed', [
    {'source_key': 'municipal_' + '0' * 24},
    {'feed_url': calendar.URL + '/'},
    {'feed_url': calendar.URL + '?format=json'},
    {'feed_url': 'https://www.batterseabloem.com/wreath-workshop'},
    {'feed_url': calendar.STORE},
])
def test_other_source_keys_paths_and_stores_never_start_network(changed):
    fetch = network()
    with pytest.raises(ValueError, match='^unregistered_html_source$'):
        listings.collect({**source(), **changed}, fetch)
    with patch.object(worker, 'fetch_publisher', fetch), pytest.raises(
            worker.PreviewError, match='^unregistered_html_source$'):
        worker.preview_source({**source(), **changed})
    fetch.assert_not_called()


@pytest.mark.parametrize('listing', ['{"content":', '{"alias":"workshop","alias":"workshop"}',
                                      '[]', '{"content":"<h1>Botanical Workshops</h1>"}',
                                      '<html><h1>Botanical Workshops</h1></html>'])
def test_malformed_or_unidentified_page_cannot_authorize_linked_reads(listing):
    fetch = network(listing=listing)
    with pytest.raises(ValueError, match='^battersea_'):
        listings.collect(source(), fetch)
    assert fetch.call_count == 1


@pytest.mark.parametrize('path,value', [
    (('alias',), 'another-page'),
    (('parameters', 'InitialPageAlias'), 'another-page'),
    (('isHomePage',), True),
    (('headsection',), '<meta property="og:url" content="https://example.test/workshop">'),
    (('content',), '<div class="dmBody"><h1>Botanical Workshops</h1><a href="https://another-store.square.site/">Book</a></div>'),
])
def test_duda_identity_and_actual_official_booking_link_are_required(path, value):
    envelope = json.loads(fixture('workshop-envelope.json'))
    change(envelope, path, value)
    fetch = network(listing=json.dumps(envelope))
    with pytest.raises(ValueError, match='^battersea_'):
        listings.collect(source(), fetch)
    assert fetch.call_count == 1


@pytest.mark.parametrize('path,value', [
    (('cmsContentDraftId',), 'unpublished-draft'),
    (('siteData', 'user', 'id'), 1),
    (('siteData', 'site', 'properties', 'catalogSiteId'), '123'),
    (('siteData', 'site', 'properties', 'domain', 'subdomain'), 'other.square.site'),
    (('storeInfo', 'merchant_id'), 'another-merchant'),
    (('storeInfo', 'currency'), 'USD'),
    (('siteData', 'page', 'properties', 'hidden'), True),
    (CELL + ('hidden',), True),
    (CELL + ('content', 'properties', 'hidden'), 'true'),
    (CELL + ('content', 'properties', 'featuredEventIds'), IDS + [IDS[0]]),
    (CELL + ('content', 'properties', 'featuredEventIds'), []),
    (CELL + ('content', 'properties', 'featuredEventIds'), [str(i) for i in range(1, 22)]),
    (CELL + ('content', 'properties', 'featuredEventIds'), ['../../another-store']),
])
def test_only_published_featured_ids_from_exact_store_can_authorize_product_request(path, value):
    fetch = network(home=home_with(path, value))
    with pytest.raises(ValueError, match='^battersea_'):
        listings.collect(source(), fetch)
    assert fetch.call_count == 2


def test_bootstrap_is_data_only_and_oversized_featured_request_is_held_before_products():
    raw = fixture('square-home.html').replace(';</script>', '; window.runAnything();</script>')
    fetch = network(home=raw)
    with pytest.raises(ValueError, match='^battersea_square_bootstrap_unverified$'):
        listings.collect(source(), fetch)
    assert fetch.call_count == 2
    ids = [str(i).zfill(32) for i in range(1, 21)]
    fetch = network(home=home_with(CELL + ('content', 'properties', 'featuredEventIds'), ids))
    with pytest.raises(ValueError, match='^battersea_square_featured_ids_limit$'):
        listings.collect(source(), fetch)
    assert fetch.call_count == 2


@pytest.mark.parametrize('path,value', [
    (('meta', 'pagination', 'count'), 6),
    (('meta', 'pagination', 'total_pages'), 2),
    (('meta', 'pagination', 'links'), ['next']),
    (('data', 0, 'site_product_id'), '999'),
    (('data', 0, 'site_product_id'), '88'),
    (('data', 0, 'owner_id'), 'another-owner'),
    (('data', 0, 'site_id'), 'another-site'),
    (('data', 0, 'merchant_id'), 'another-merchant'),
    (('data', 0, 'product_type'), 'physical'),
    (('data', 0, 'visibility'), 'hidden'),
    (('data', 0, 'absolute_site_link'), 'https://another-store.square.site/product/flowers/88'),
    (('data', 0, 'site_link'), '/product/another-event/88'),
])
def test_partial_wrong_store_non_event_and_extra_products_cannot_complete_collection(path, value):
    with pytest.raises(ValueError, match='^battersea_'):
        collect(products=products_with(path, value))


def test_missing_featured_product_cannot_verify_registration_or_complete_recurring_collection():
    data = json.loads(fixture('square-events.json'))
    data['data'].pop()
    # Even a self-consistent shorter API page must match the featured ID list.
    data['meta']['pagination'].update(total=6, count=6, per_page=6)
    fetch = network(products=json.dumps(data))
    with patch.object(registration, 'fetch_publisher', fetch), patch.object(
            registration, 'supabase_rpc', side_effect=[{'id': 877, 'url': calendar.URL}, True]) as rpc:
        assert registration.register('receipt-ticket') == {'outcome': 'review'}
    assert rpc.call_args.args[1]['p_reason'] == 'battersea_square_incomplete_collection'
    assert fetch.call_count == 3
    with patch.object(worker, 'fetch_publisher', network(products=json.dumps(data))), pytest.raises(
            worker.PreviewError, match='^battersea_square_incomplete_collection$'):
        worker.preview_source(source())


@pytest.mark.parametrize('field,value', [
    ('start_date', '27 November'), ('start_date', '2026-02-30'),
    ('start_time', '8 PM'), ('start_time', '20:00 PM'),
    ('end_date', '2026-11-26'), ('end_time', '7:00 PM'),
    ('timezone', 'America/New_York'), ('has_no_end_time', True),
])
def test_schedule_requires_explicit_year_valid_wall_times_and_london_zone(field, value):
    with pytest.raises(ValueError, match='^battersea_square_schedule_unverified$'):
        collect(products=products_with(('data', 0, 'product_type_details', field), value))


def test_string_no_end_flag_and_cached_editor_offset_do_not_change_occurrence_time():
    rows = collect(products=products_with(('data', 0, 'product_type_details', 'has_no_end_time'), '1'))
    assert rows[0]['starts_at'] == '2026-11-27T20:00:00+00:00' and rows[0]['ends_at'] is None
    rows = collect(products=products_with(
        ('data', 0, 'product_type_details', 'timezone_info'),
        {'name': 'Europe/London', 'utc_offset_seconds': 3600, 'utc_offset_string': '+01:00'}))
    assert rows[0]['starts_at'] == '2026-11-27T20:00:00+00:00'
    assert rows[0]['ends_at'] == '2026-11-27T22:30:00+00:00'


@pytest.mark.parametrize('path,value', [
    (('location_name',), 'West Hub'),
    (('location_types',), ['ONLINE']),
    (('join_event_online_link',), 'https://example.test/join'),
    (('address', 'street2'), '11 Hamilton Road'),
    (('address', 'city'), 'London'),
    (('address', 'postal_code'), 'SW1A 1AA'),
    (('address', 'country_code'), 'US'),
])
def test_other_venues_are_never_assigned_the_cambridge_studio(path, value):
    with pytest.raises(ValueError, match='^battersea_square_venue_unverified$'):
        collect(products=products_with(('data', 0, 'product_type_details') + path, value))


def test_public_narrative_uses_existing_sanitizer_and_never_imports_admin_fields():
    data = json.loads(fixture('square-events.json'))
    data['data'][0]['short_description'] = '<nav>Navigation only</nav><p>Materials &amp; refreshments.</p><script>privateMarker()</script>'
    data['data'][0]['internal_notes'] = 'Never copy this field'
    rows = collect(products=json.dumps(data))
    assert rows[0]['description'] == 'Materials & refreshments.\n\nPrice: £48.50.'
    assert not any(value in json.dumps(rows) for value in ('Navigation only', 'privateMarker', 'Never copy'))


@pytest.mark.parametrize('path,value,reason', [
    (('short_description',), 'x' * 2001, 'description_too_long'),
    (('badges', 'out_of_stock'), 'false', 'availability_unverified'),
    (('price', 'low_subunits'), 1, 'price_unverified'),
    (('price', 'low'), -1, 'price_unverified'),
    (('thumbnail', 'data', 'absolute_url'), 'https://example.test/photo.jpg', 'image_unverified'),
    (('thumbnail', 'data', 'owner_id'), 'other-owner', 'image_unverified'),
])
def test_unverified_optional_content_cannot_bypass_existing_event_contract(path, value, reason):
    with pytest.raises(ValueError, match='^battersea_square_' + reason + '$'):
        collect(products=products_with(('data', 0) + path, value))


def test_missing_thumbnail_does_not_require_a_fallback_image_or_extra_request():
    fetch = network(products=products_with(('data', 0, 'thumbnail'), None))
    rows = listings.collect(source(), fetch)
    assert 'image_url' not in rows[0] and len(rows) == 7
    assert fetch.call_count == 3


@pytest.mark.parametrize('reason', ['robots_denied', 'publisher_http_401', 'publisher_http_403'])
@pytest.mark.parametrize('target', [calendar.URL, calendar.STORE, API_URL])
def test_denial_at_each_read_stops_registration_without_transport_fallback(reason, target):
    fetch = network()
    read = fetch.side_effect

    def denied(url, accept, **options):
        if url == target:
            raise worker.PreviewError(reason)
        return read(url, accept, **options)
    fetch.side_effect = denied
    with patch.object(registration, 'fetch_publisher', fetch), patch.object(
            registration, 'supabase_rpc', side_effect=[{'id': 877, 'url': calendar.URL}, True]) as rpc:
        assert registration.register('receipt-ticket') == {'outcome': 'disabled'}
    assert rpc.call_args.args[1] == dict(p_ticket='receipt-ticket', p_outcome='disabled', p_reason=reason)
    assert [call.args[0] for call in fetch.call_args_list] == [calendar.URL, calendar.STORE, API_URL][
        :[calendar.URL, calendar.STORE, API_URL].index(target) + 1]


def test_real_pacing_allows_cold_square_robots_then_home_and_products_within_registration_budget(monkeypatch):
    clock, reads = [0.0], []
    monkeypatch.setattr(worker, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(calendar, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(uk, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(worker, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(worker, '_robots_delays', {HOSTS[0]: 1, HOSTS[1]: 5})
    monkeypatch.setattr(worker, '_publisher_next', {})
    monkeypatch.setattr(worker, '_publisher_retry_after', {})
    raw_fetch, robots_seen = network(), set()

    def paced(url, accept):
        host = urlsplit(url).hostname
        if host not in robots_seen:
            robots_seen.add(host)
            # Model the existing reservation after a newly read robots policy.
            worker._reserve_known_crawl_delay(host)
        worker.pace_publisher(host, 35)
        reads.append((url, clock[0]))
        return raw_fetch(url, accept)
    rows = listings.collect(source(), paced, deadline_at=35)
    assert len(rows) == 7 and [row[0] for row in reads] == [calendar.URL, calendar.STORE, API_URL]
    assert reads[2][1] - reads[1][1] == 5
    assert 10 <= clock[0] < 35 and raw_fetch.call_count == 3


def test_deadline_exhaustion_stops_without_restarting_store_home(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(calendar, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(uk, 'monotonic', lambda: clock[0])
    fetch = network()
    read = fetch.side_effect

    def slow(url, accept):
        if url == calendar.STORE:
            clock[0] = 35
        return read(url, accept)
    fetch.side_effect = slow
    with pytest.raises(ValueError, match='^collection_deadline$'):
        listings.collect(source(), fetch, deadline_at=35)
    assert [call.args[0] for call in fetch.call_args_list] == [calendar.URL, calendar.STORE]


def test_generic_json_classification_is_unchanged_and_west_hub_is_not_registered():
    for url in (calendar.URL, 'https://another.example/workshop'):
        result = registration.classify(url, fixture('workshop-envelope.json'))
        assert result['p_outcome'] == 'review' and result['p_reason'] == 'unrecognized_json'
    assert not any('onlinesales.admin.cam.ac.uk' in url for url in listings.URLS)
