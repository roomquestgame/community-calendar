"""Registration, recurring collection, and detail-page content share one parser."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch

import pytest

from roomquest import feed_registration, preview_worker
from roomquest import registered_native_content as native
from roomquest.registration_formats import source_key


ROOT = 'https://venue.example.org'
FEED = ROOT + '/events'
DETAILS = [ROOT + '/events/detail/reading', ROOT + '/events/detail/concert']


def source():
    return {'source_key': source_key(FEED), 'feed_url': FEED, 'kind': 'html',
            'platform_adapter': 'html', native.CAPABILITY: 1,
            native.HTML_CAPABILITY: 1}


def pages():
    at = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)
    listing = '<html><head><title>Upcoming Events</title></head><body><main><h1>Upcoming Events</h1>'
    listing += ''.join('<article><a href="' + url + '">Public event</a></article>' for url in DETAILS)
    listing += '</main></body></html>'
    result = {FEED: listing}
    for index, url in enumerate(DETAILS):
        event = {'@context': 'https://schema.org', '@type': 'Event', '@id': url + '#event',
                 'url': url, 'name': 'Public event ' + str(index),
                 'startDate': (at + timedelta(days=index)).isoformat(),
                 'endDate': (at + timedelta(days=index, hours=2)).isoformat(),
                 'description': '<p>Meet the artists and explore their work.</p>',
                 'image': '/images/poster-' + str(index) + '.jpg',
                 'location': {'@type': 'Place', 'name': 'Community Hall',
                              'address': {'@type': 'PostalAddress', 'streetAddress': '12 Main St',
                                          'addressLocality': 'Richmond', 'addressRegion': 'VA',
                                          'postalCode': '23220'}}}
        result[url] = '<html><head><link rel="canonical" href="' + url + '">' + \
            '<script type="application/ld+json">' + json.dumps(event) + '</script></head></html>'
    return result


def test_registration_probes_details_before_certifying_generic_html():
    responses = pages()
    with patch.object(feed_registration, 'fetch_publisher',
                      side_effect=lambda url, *_args, **_kwargs: responses[url]) as fetch, \
            patch.object(feed_registration, 'supabase_rpc',
                         side_effect=[{'url': FEED, native.HTML_CAPABILITY: 1}, True]) as rpc:
        assert feed_registration.register('fixture-ticket') == {'outcome': 'verified'}
    receipt = rpc.call_args.args[1]
    assert (receipt['p_type'], receipt['p_reason'], receipt['p_endpoint']) == (
        'html', native.HTML_VERSION, FEED)
    assert {call.args[0] for call in fetch.call_args_list} == {FEED, *DETAILS}
    assert all(call.kwargs['respect_robots'] for call in fetch.call_args_list)
    assert all(call.kwargs['allowed_hosts'] == ('venue.example.org',)
               for call in fetch.call_args_list if call.args[0] != FEED)


def test_html_registration_follows_the_actual_full_calendar_from_homepage():
    responses = pages()
    responses[ROOT + '/'] = ('<html><body><main><h1>Upcoming Events</h1>'
        '<a href="/events">See our full schedule</a>'
        '<a href="/events/">Event Calendar</a>'
        '<a href="/events/detail/reading">Featured reading</a></main></body></html>')
    with patch.object(feed_registration, 'fetch_publisher',
                      side_effect=lambda url, *_args, **_kwargs: responses[url]) as fetch, \
            patch.object(feed_registration, 'supabase_rpc', side_effect=[
                {'url': ROOT + '/', native.HTML_CAPABILITY: 1}, True]) as rpc:
        assert feed_registration.register('fixture-ticket') == {'outcome': 'discovered'}
    receipt = rpc.call_args.args[1]
    assert receipt['p_endpoint'] == FEED
    assert receipt['p_type'] == 'html' and receipt['p_reason'] == native.HTML_VERSION
    assert {call.args[0] for call in fetch.call_args_list} == {ROOT + '/', FEED, *DETAILS}


@pytest.mark.parametrize('destination', ['/events', '/events?venue=other', '/events?venue=a'])
def test_full_calendar_navigation_preserves_every_original_selector(destination):
    original = ROOT + '/?venue=a&venue=b'
    body = ('<html><body><main><h1>Upcoming Events</h1><a href="' + destination
            + '">See our full schedule</a><a href="/events/detail/reading">Featured reading</a>'
            '<a href="/events/detail/concert">Featured concert</a></main></body></html>')
    with patch.object(feed_registration, 'fetch_publisher', return_value=body) as fetch, \
            patch.object(feed_registration, 'recover_html_feed', return_value=None), \
            patch.object(feed_registration, 'supabase_rpc', side_effect=[
                {'url': original, native.HTML_CAPABILITY: 1}, True]) as rpc:
        assert feed_registration.register('fixture-ticket') == {'outcome': 'review'}
    assert fetch.call_count == 1
    assert rpc.call_args.args[1].get('p_endpoint') is None


def test_verified_venue_path_does_not_expand_into_an_operator_wide_calendar():
    original = ROOT + '/venue/main-hall'
    body = ('<html><body><main><h1>Upcoming Events</h1>'
            '<a href="/events">All venues</a><a href="/events/detail/reading">Reading</a>'
            '<a href="/events/detail/concert">Concert</a></main></body></html>')
    assert 'calendar_page' not in feed_registration.classify(original, body, venue_website=True)
    with patch.object(feed_registration, 'fetch_publisher', return_value=body) as fetch, \
            patch.object(feed_registration, 'recover_html_feed', return_value=None), \
            patch.object(feed_registration, 'supabase_rpc', side_effect=[
                {'url': original, 'verified_venue_website': True, native.HTML_CAPABILITY: 1}, True]) as rpc:
        assert feed_registration.register('fixture-ticket') == {'outcome': 'review'}
    assert fetch.call_count == 1
    assert rpc.call_args.args[1].get('p_endpoint') is None


@pytest.mark.parametrize('path,body', [
    ('/boulder-theater-venue', '<html><a href="/events">All events</a></html>'),
    ('/venues/east/events', '<html><link rel="https://api.w.org/" href="/wp-json/">'
                          '<script src="/wp-content/plugins/the-events-calendar/calendar.js"></script></html>'),
])
def test_exploratory_feed_recovery_cannot_discard_path_scoped_venues(path, body):
    with patch.object(feed_registration, 'fetch_publisher') as fetch:
        assert feed_registration.recover_html_feed(ROOT + path, body, 999999999) is None
    fetch.assert_not_called()


def test_recurring_worker_stages_detail_content_with_actual_evidence():
    responses = pages()
    def rpc(name, args):
        if name == 'community_collector_record_staged_events':
            return len(args['p_events'])
    with patch.object(preview_worker, 'fetch_publisher',
                      side_effect=lambda url, *_args, **_kwargs: responses[url]), \
            patch.object(preview_worker, 'supabase_rpc', side_effect=rpc) as database:
        result = preview_worker._process_claimed_source(source())
    assert result == {'complete': 1, 'failed': 0, 'staged': 2}
    staged = next(call.args[1] for call in database.call_args_list
                  if call.args[0] == 'community_collector_record_staged_events')
    assert staged['p_registered_native_content_version'] == 1
    for row in staged['p_events']:
        assert row['description'] == 'Meet the artists and explore their work.'
        assert row['event_url'] in DETAILS
        assert row['image_evidence_url'] == row['event_url']
        assert row['registered_native_content']['evidence_url'] == row['event_url']
        assert row['registered_native_content']['extraction'] == native.HTML_VERSION
    completed = database.call_args_list[-1].args[1]
    assert completed['p_error'] is None
    assert completed['p_parser_capability'] == native.VERSION


def test_checked_html_capability_keeps_its_parser_if_a_legacy_adapter_is_added():
    from roomquest import registered_listings
    responses = pages()
    with patch.object(registered_listings, 'URLS', (*registered_listings.URLS, FEED)), \
            patch.object(registered_listings, 'collect', side_effect=AssertionError('native proof required')), \
            patch.object(preview_worker, 'fetch_publisher',
                         side_effect=lambda url, *_args, **_kwargs: responses[url]):
        result = preview_worker.preview_source(source())
    assert result['p_parser_capability'] == native.VERSION
    assert len(result['p_events']) == 2
    assert all(row['registered_native_content']['extraction'] == native.HTML_VERSION
               for row in result['p_events'])


def test_detail_native_content_cannot_claim_the_listing_as_its_evidence():
    row = {'id': 'reading', 'event_url': DETAILS[0]}
    with pytest.raises(ValueError, match='registered_native_evidence_invalid'):
        native.attach(row, source(), description_value='Reading', evidence_url=FEED)
    native.attach(row, source(), description_value='Reading', image_value='/images/reading.jpg',
                  evidence_url=DETAILS[0])
    native.validate_record(row, source())
    for mutate in (
        lambda r: r.update(image_evidence_url=FEED),
        lambda r: r['registered_native_content'].update(evidence_url=FEED),
        lambda r: r['registered_native_content'].pop('extraction'),
    ):
        forged = deepcopy(row)
        mutate(forged)
        with pytest.raises(ValueError, match='registered_native_evidence_invalid'):
            native.validate_record(forged, source())


def test_scoped_html_narrative_has_an_explicit_description_origin():
    row = {'id': 'reading', 'event_url': DETAILS[0]}
    narrative = '<p>' + ('Publisher narrative. ' * 170) + '</p>'
    native.attach(row, source(), description_value=narrative,
                  description_field=native.HTML_DESCRIPTION_FIELD, evidence_url=DETAILS[0])
    native.validate_record(row, source())
    assert len(row['description']) > 2000
    assert row['registered_native_content']['description_field'] == native.HTML_DESCRIPTION_FIELD
    forged = deepcopy(row)
    forged['registered_native_content']['description_field'] = 'page_text'
    with pytest.raises(ValueError, match='registered_native_evidence_invalid'):
        native.validate_record(forged, source())


def test_json_native_contract_does_not_accept_html_narrative_proof():
    claim = {**source(), 'kind': 'json', 'platform_adapter': 'jsonld'}
    row = {'id': 'reading', 'event_url': DETAILS[0]}
    with pytest.raises(ValueError, match='registered_native_evidence_invalid'):
        native.attach(row, claim, description_value='Published text',
                      description_field=native.HTML_DESCRIPTION_FIELD)
    native.attach(row, claim, description_value='Published text')
    row['registered_native_content']['description_field'] = native.HTML_DESCRIPTION_FIELD
    with pytest.raises(ValueError, match='registered_native_evidence_invalid'):
        native.validate_record(row, claim)


@pytest.mark.parametrize('capability', [None, True, '1', 0, 2])
def test_generic_html_requires_the_exact_backend_capability(capability):
    claim = {**source(), native.HTML_CAPABILITY: capability}
    with pytest.raises(ValueError, match='registered_native_source_invalid'):
        native.attach({'id': 'reading', 'event_url': DETAILS[0]}, claim,
                      evidence_url=DETAILS[0])


def test_detail_media_claim_remains_candidate_only_and_bound_to_its_event():
    claim = {**source(), 'candidate_only': True, 'event_url': DETAILS[0],
             'extraction_url': DETAILS[0]}
    assert native.media_claim(claim)
    assert not native.media_claim({**claim, 'candidate_only': False})
    assert not native.media_claim({**claim, 'extraction_url': FEED})
    assert not native.media_claim({**claim, 'event_url': DETAILS[1]})
    assert not native.media_claim({**claim, 'event_url': 'https://other.example.org/event',
                                  'extraction_url': 'https://other.example.org/event'})
    assert not native.media_claim({**claim, 'event_url': FEED, 'extraction_url': FEED})
    uppercase = DETAILS[0].replace('venue.example.org', 'VENUE.example.org')
    assert not native.media_claim({**claim, 'event_url': uppercase, 'extraction_url': uppercase})


def test_generic_html_transport_denial_cannot_be_recorded_as_success():
    with patch.object(feed_registration, 'fetch_publisher',
                      side_effect=[pages()[FEED], preview_worker.PreviewError('robots_denied')]), \
            patch.object(feed_registration, 'supabase_rpc',
                         side_effect=[{'url': FEED, native.HTML_CAPABILITY: 1}, True]) as rpc:
        assert feed_registration.register('fixture-ticket') == {'outcome': 'disabled'}
    assert rpc.call_args.args[1]['p_reason'] == 'robots_denied'


@pytest.mark.parametrize('capability', [None, True, '1', 0, 2])
def test_older_registration_backend_does_not_receive_new_html_verification(capability):
    with patch.object(feed_registration, 'fetch_publisher', return_value=pages()[FEED]) as fetch, \
            patch.object(feed_registration, 'supabase_rpc', side_effect=[
                {'url': FEED, native.HTML_CAPABILITY: capability}, True]) as rpc:
        assert feed_registration.register('fixture-ticket') == {'outcome': 'review'}
    assert rpc.call_args.args[1]['p_reason'] == 'html_adapter_needed'
    assert fetch.call_count == 1
