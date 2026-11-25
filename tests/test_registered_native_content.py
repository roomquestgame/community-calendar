"""Negotiated native facts/candidates, with real adapters and controlled RPCs.

These tests do not emulate SQL publication, source approval, or media leasing.
The matching backend fixture tests those private-stage/publication boundaries.
"""
from copy import deepcopy
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import pytest

from roomquest import event_media, jsonld_adapter, registered_native_content as native
from roomquest import preview_worker, wordpress_adapter
from roomquest.registration_formats import source_key


ROOT = 'https://venue.example.org'
FEED = ROOT + '/wp-json/tribe/events/v1/events?venue=7&search=Workshop'
PHOTO = 'https://cdn.example.org/workshop-poster.jpg'


def source(adapter='wordpress', capability=1):
    feed = FEED if adapter == 'wordpress' else ROOT + '/events/category/workshops/'
    return {'source_key': source_key(feed), 'feed_url': feed, 'kind': 'json',
            'platform_adapter': adapter, 'timezone': 'Europe/London',
            native.CAPABILITY: capability}


def item(index=1, *, blank_venue=False, description='<p>Make a basket.</p>'):
    at = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)
    return {'id': index, 'title': 'Public workshop', 'status': 'publish',
            'url': ROOT + '/event/workshop-' + str(index), 'timezone': 'Europe/London',
            'utc_start_date': at.isoformat(), 'utc_end_date': (at + timedelta(hours=2)).isoformat(),
            'description': description, 'image': {'url': PHOTO, 'width': 800, 'height': 600},
            'venue': [] if blank_venue else {'venue': 'Actual Hall', 'address': '12 Main St',
                'city': 'Cambridge', 'state': 'Cambridgeshire', 'zip': 'CB1 1AA'},
            'categories': [{'name': 'Workshop'}]}


def payload(items):
    return json.dumps({'events': items, 'total': len(items), 'total_pages': 1})


def jsonld_item():
    e = item()
    return {'@type': 'Event', '@id': 'workshop-1', 'name': e['title'], 'url': e['url'],
            'startDate': e['utc_start_date'], 'endDate': e['utc_end_date'],
            'description': e['description'], 'image': e['image'], 'keywords': 'Workshop',
            'location': {'@type': 'Place', 'name': 'Actual Hall', 'address': {
                'streetAddress': '12 Main St', 'addressLocality': 'Cambridge',
                'addressRegion': 'Cambridgeshire', 'postalCode': 'CB1 1AA'}}}


def collect(items, claim=None):
    return wordpress_adapter.collect(claim or source(), lambda *_: payload(items))


def run_worker(body, claim=None, *, stage_failure=False):
    def rpc(name, args):
        if name == 'community_collector_record_staged_events':
            if stage_failure:
                raise preview_worker.PreviewError('database_unavailable')
            return len(args['p_events'])
    with patch.object(preview_worker, 'fetch_publisher', return_value=body) as fetch, \
            patch.object(preview_worker, 'supabase_rpc', side_effect=rpc) as database:
        result = preview_worker._process_claimed_source(claim or source())
    return result, fetch, database


@pytest.mark.parametrize('value', [None, False, True, '1', 1.0, 0, 2])
def test_no_exact_capability_preserves_the_legacy_contract(value):
    claim = source(capability=value)
    row = collect([item(description='x' * 3000)], claim)[0]
    assert len(row['description']) == 3000
    assert 'registered_native_content' not in row
    assert 'image_extractor_version' not in row and 'image_url' not in row


def test_absent_capability_preserves_legacy_staging_and_receipt():
    claim = source()
    del claim[native.CAPABILITY]
    result, _, db = run_worker(payload([item()]), claim)
    assert result == {'complete': 1, 'failed': 0, 'staged': 1}
    assert len(db.call_args_list) == 2
    assert native.CAPABILITY not in db.call_args_list[0].args[1]
    assert 'p_registered_native_content_version' not in db.call_args_list[0].args[1]
    assert db.call_args_list[-1].args[0] == 'community_collector_record_preview'
    assert 'p_parser_capability' not in db.call_args_list[-1].args[1]


@pytest.mark.parametrize('mutation', [
    {'source_key': 'municipal_' + '0' * 24}, {'kind': 'html'},
    {'platform_adapter': 'squarespace'}, {'feed_url': FEED + '&venue=8'},
    {'feed_url': ROOT + '/events#private'}, {'feed_url': 'http://venue.example.org/events'},
    {'feed_url': 'https://127.0.0.1/events'}, {'feed_url': 'https://u:p@venue.example.org/events'},
])
def test_positive_capability_with_wrong_identity_fails_before_fetch(mutation):
    claim = {**source(), **mutation}
    fetch = MagicMock()
    with pytest.raises(ValueError, match='registered_native_source_invalid'):
        wordpress_adapter.collect(claim, fetch)
    fetch.assert_not_called()


def test_positive_capability_cannot_enter_the_other_adapter():
    fetch = MagicMock()
    with pytest.raises(ValueError, match='registered_native_source_invalid'):
        wordpress_adapter.collect(source('jsonld'), fetch)
    with pytest.raises(ValueError, match='registered_native_source_invalid'):
        jsonld_adapter.collect(source(), fetch)
    fetch.assert_not_called()


@pytest.mark.parametrize('feed_host,event_host,accepted', [
    ('venue.example.org', 'www.venue.example.org', True),
    ('www.venue.example.org', 'venue.example.org', True),
    ('WWW.VENUE.EXAMPLE.ORG', 'Venue.Example.Org', True),
    ('www.venue.example.org', 'www.venue.example.org', True),
    ('venue.example.org', 'events.venue.example.org', False),
    ('events.venue.example.org', 'venue.example.org', False),
    ('venue.example.org', 'other.example.org', False),
    ('venue.example.org', 'www.www.venue.example.org', False),
])
def test_native_event_host_matches_backend_publisher_normalization(feed_host, event_host, accepted):
    claim = source()
    claim['feed_url'] = FEED.replace('venue.example.org', feed_host)
    claim['source_key'] = source_key(claim['feed_url'])
    original_feed, original_key = claim['feed_url'], claim['source_key']
    raw = item()
    raw['url'] = raw['url'].replace('venue.example.org', event_host)
    if not accepted:
        with pytest.raises(ValueError, match='registered_native_event_identity_invalid'):
            collect([raw], claim)
        assert not native.media_claim({**claim, 'candidate_only': True,
            'extraction_url': claim['feed_url'], 'event_url': raw['url']})
        return
    row = collect([raw], claim)[0]
    native.validate_record(row, claim)
    assert row['event_url'] == raw['url']
    assert row['registered_native_content']['feed_url'] == original_feed
    assert row['registered_native_content']['source_key'] == original_key
    assert claim['feed_url'] == original_feed and claim['source_key'] == original_key
    assert native.media_claim({**claim, 'candidate_only': True,
        'extraction_url': claim['feed_url'], 'event_url': raw['url']})


def test_native_wordpress_keeps_full_sanitized_unicode_narrative_and_facts():
    prose = '🎨' * 5000
    raw = item(description='<nav>Menu</nav>[vc_row][vc_column_text]<p>' + prose
        + '</p><script>secret()</script><p>Bring tools &amp; gloves.</p>[/vc_column_text][/vc_row]')
    legacy = collect([deepcopy(raw)], source(capability=None))[0]
    row = collect([raw])[0]
    assert row['description'] == prose + '\nBring tools & gloves.'
    assert row['image_url'] == PHOTO
    assert row['image_evidence_url'] == FEED
    assert row['image_provenance'] == native.VERSION
    assert row['image_extractor_version'] == native.VERSION
    for key in legacy.keys() - {'description'}:
        assert row[key] == legacy[key]
    native.validate_record(row, source())


def test_twelve_thousand_unicode_characters_are_preserved():
    row = collect([item(description='🎨' * 12000)])[0]
    assert row['description'] == '🎨' * 12000
    native.validate_record(row, source())


def test_oversize_narrative_is_bounded_without_rejecting_other_events():
    rows = collect([item(1), item(99, description='🎨' * 12001)])
    assert len(rows) == 2
    assert rows[1]['description'] == '🎨' * 12000
    for row in rows:
        native.validate_record(row, source())


@pytest.mark.parametrize('value', [None, '', 'https://venue.example.org/more'])
def test_absent_or_url_only_narrative_is_empty_without_excerpt_fallback(value):
    e = item(description=value)
    e['excerpt'] = 'Do not substitute this excerpt.'
    row = collect([e])[0]
    assert row['description'] == ''
    assert row['registered_native_content']['description_field'] is None


@pytest.mark.parametrize('value', [{}, ['invalid'], 7])
def test_malformed_description_stays_an_error(value):
    with pytest.raises(ValueError, match='invalid_event_description'):
        collect([item(description=value)])


@pytest.mark.parametrize('value', [
    None, '', '  ', '#unresolved', {'@id': '#unresolved'},
    'http://cdn.example.org/x.jpg', 'https://127.0.0.1/x.jpg',
    'https://user:secret@cdn.example.org/x.jpg', 'https://cdn.example.org:8443/x.jpg',
    PHOTO + '#fragment', 'https://cdn.example.org:443/x.jpg',
    'https://cdn.example.org/path with spaces.jpg', 'https://123.example.org/x.jpg',
    'https://cdn.example.org/logo.png', 'https://cdn.example.org/picture.svg',
    {'url': PHOTO, 'width': 1}, {'url': PHOTO, 'height': 1},
    {'url': PHOTO, 'width': True}, {'url': PHOTO, 'height': 'unknown'},
])
def test_optional_missing_unsafe_or_tiny_image_does_not_lose_facts(value):
    row = collect([{**item(), 'image': value}])[0]
    assert row['title'] == 'Public workshop'
    assert row['registered_native_content']['image_field'] is None
    assert row['image_extractor_version'] == native.VERSION
    assert 'image_url' not in row and 'image_evidence_url' not in row
    native.validate_record(row, source())


@pytest.mark.parametrize('value,expected', [
    (PHOTO, PHOTO), ({'contentUrl': PHOTO}, PHOTO),
    ({'url': '/uploads/poster.jpg', 'width': 160, 'height': 90}, ROOT + '/uploads/poster.jpg'),
    ([{'url': PHOTO, 'width': 1}, PHOTO], PHOTO),
    ([None] * 5 + [PHOTO], None),
])
def test_native_candidate_selection_is_bounded(value, expected):
    row = collect([{**item(), 'image': value}])[0]
    assert row.get('image_url') == expected


def test_jsonld_full_narrative_and_local_image_reference_use_same_contract():
    e = jsonld_item()
    e.update(description='x' * 3500, image={'@id': '#poster'})
    graph = {'@graph': [e, {'@type': 'ImageObject', '@id': '#poster',
                          'contentUrl': PHOTO, 'width': 800, 'height': 600}]}
    fetch = MagicMock(return_value=json.dumps(graph))
    row = jsonld_adapter.collect(source('jsonld'), fetch)[0]
    assert row['description'] == 'x' * 3500 and row['image_url'] == PHOTO
    assert row['registered_native_content']['adapter'] == 'jsonld'
    assert row['image_evidence_url'] == source('jsonld')['feed_url']
    native.validate_record(row, source('jsonld'))
    fetch.assert_called_once_with(source('jsonld')['feed_url'], 'text/html,application/ld+json')


def test_jsonld_oversize_uses_common_bound():
    e = jsonld_item()
    e['description'] = 'x' * 12001
    row = jsonld_adapter.collect(source('jsonld'), MagicMock(return_value=json.dumps(e)))[0]
    assert row['description'] == 'x' * 12000
    native.validate_record(row, source('jsonld'))


def test_wordpress_empty_native_venue_reaches_private_stage_unchanged():
    claim = {**source(), 'publisher_default_venue': 'Must not be inferred',
             'publisher_default_lat': 52.2, 'publisher_default_lng': .1,
             'publisher_venue_evidence': 'An unrelated source default'}
    e = item(blank_venue=True, description='<p>Join us in our Workshop Barn.</p>')
    row = collect([e], claim)[0]
    assert row['id'] == '1' and row['event_url'] == e['url']
    assert row['venue_name'] == '' and row['venue_address'] == ''
    assert row['lat'] is None and row['lng'] is None
    assert row['description'] == 'Join us in our Workshop Barn.'
    assert not any(key.startswith('override_') for key in row)
    result, _, db = run_worker(payload([e]), claim)
    assert result == {'complete': 1, 'failed': 0, 'staged': 1}
    staged = db.call_args_list[0].args[1]['p_events'][0]
    assert staged['venue_name'] == '' and staged['venue_address'] == ''
    assert staged['lat'] is None and staged['lng'] is None
    assert db.call_args_list[-1].args[1]['p_venue_count'] == 0


def test_blank_venue_exception_is_not_granted_to_legacy_or_jsonld():
    with pytest.raises(ValueError, match='venue_extraction_unavailable'):
        collect([item(blank_venue=True)], source(capability=None))
    e = jsonld_item()
    e['location'] = {}
    with pytest.raises(ValueError, match='venue_extraction_unavailable'):
        jsonld_adapter.collect(source('jsonld'), lambda *_: json.dumps(e))


@pytest.mark.parametrize('event_url', [
    'https://another.example.org/event/one', 'http://venue.example.org/event/one',
    'https://u:p@venue.example.org/event/one', 'https://127.0.0.1/event/one',
    ROOT + '/event/one#fragment', 'https://venue.example.org:443/event/one',
    ROOT + '/event/one two', ROOT + '/event/one\ntwo',
])
def test_native_event_proof_requires_same_public_publisher(event_url):
    with pytest.raises(ValueError, match='registered_native_event_identity_invalid|event_link_missing'):
        collect([{**item(), 'url': event_url}])


def test_scoped_endpoint_and_all_pages_keep_existing_filters():
    calls = []
    def fetch(url, _):
        calls.append(url)
        page = int(parse_qs(urlsplit(url).query)['page'][0])
        return json.dumps({'events': [item(page)], 'total_pages': 2,
                           'next_rest_url': 'https://unrelated.example.org/ignored' if page == 1 else None})
    rows = wordpress_adapter.collect(source(), fetch)
    assert len(rows) == 2 and len(calls) == 2
    for url in calls:
        assert urlsplit(url).hostname == 'venue.example.org'
        assert parse_qs(urlsplit(url).query)['venue'] == ['7']
        assert parse_qs(urlsplit(url).query)['search'] == ['Workshop']
    assert all(row['image_evidence_url'] == FEED for row in rows)


@pytest.mark.parametrize('code', [
    'robots_denied', 'publisher_http_403', 'publisher_http_429',
    'source_network_error', 'publisher_pacing_deferred',
])
def test_native_path_preserves_transport_access_and_pacing_errors(code):
    with patch.object(preview_worker, 'fetch_publisher',
                      side_effect=preview_worker.PreviewError(code)), \
            patch.object(preview_worker, 'supabase_rpc') as db:
        result = preview_worker._process_claimed_source(source())
    assert result['complete'] == 0 and result['failed'] == 1 and result['staged'] == 0
    db.assert_called_once()
    assert db.call_args.args[1]['p_error'] == code
    assert db.call_args.args[1]['p_parser_capability'] == native.VERSION


def test_partial_staging_failure_never_certifies_snapshot():
    result, _, db = run_worker(payload([item()]), stage_failure=True)
    assert result['complete'] == 0 and result['failed'] == 1
    assert db.call_args_list[0].args[1]['p_registered_native_content_version'] == 1
    assert db.call_args_list[-1].args[1]['p_error'] == 'database_unavailable'
    assert db.call_args_list[-1].args[1]['p_parser_capability'] == native.VERSION


@pytest.mark.parametrize('adapter', ['wordpress', 'jsonld'])
def test_empty_collection_explicitly_negotiates_staging_and_completion(adapter):
    body = payload([]) if adapter == 'wordpress' else json.dumps({
        '@type': 'ItemList', 'numberOfItems': 0, 'itemListElement': []})
    result, _, db = run_worker(body, source(adapter))
    assert result == {'complete': 1, 'failed': 0, 'staged': 0}
    assert db.call_args_list[0].args[0] == 'community_collector_record_staged_events'
    assert db.call_args_list[0].args[1]['p_events'] == []
    assert db.call_args_list[0].args[1]['p_registered_native_content_version'] == 1
    assert db.call_args_list[-1].args[0] == 'community_collector_record_preview_v3'
    assert db.call_args_list[-1].args[1]['p_parser_capability'] == native.VERSION


def change_identity(row, field, value):
    row[field] = value
    row['registered_native_content']['event_id' if field == 'id' else field] = value


@pytest.mark.parametrize('mutation', [
    lambda row: row.pop('registered_native_content'),
    lambda row: row['registered_native_content'].update(version=True),
    lambda row: row['registered_native_content'].update(feed_url=FEED + '&scope=other'),
    lambda row: row['registered_native_content'].update(event_id='wrong'),
    lambda row: row.update(image_evidence_url=ROOT),
    lambda row: row.update(image_provenance='publisher_event_candidates_v1'),
    lambda row: row.update(description='x' * 12001),
    lambda row: row.update(description='<b>Unstripped markup</b>'),
    lambda row: change_identity(row, 'id', ' padded-id '),
    lambda row: change_identity(row, 'event_url', ROOT + '/event/one#fragment'),
    lambda row: change_identity(row, 'event_url', 'https://venue.example.org:443/event/one'),
    lambda row: change_identity(row, 'event_url', ROOT + '/event/one two'),
    lambda row: change_identity(row, 'event_url', ROOT + '/event/one\ntwo'),
    lambda row: row.update(image_url=PHOTO + '#fragment'),
    lambda row: row.update(image_url='https://cdn.example.org:443/workshop.jpg'),
])
def test_all_records_are_validated_before_first_staging_batch(mutation):
    rows = collect([item(i) for i in range(1, 22)])
    mutation(rows[-1])
    output = {'p_source_key': source()['source_key'], 'p_events': rows,
              'p_samples': [], 'p_future_count': len(rows), 'p_venue_count': 0,
              'p_error': None, 'p_parser_capability': native.VERSION}
    with patch.object(preview_worker, 'preview_source', return_value=output), \
            patch.object(preview_worker, 'supabase_rpc') as db:
        result = preview_worker._process_claimed_source(source())
    assert result['complete'] == 0 and result['staged'] == 0 and result['failed'] == 1
    db.assert_called_once()
    assert db.call_args.args[0] == 'community_collector_record_preview_v3'


def media_claim(**changes):
    return {**source(), 'candidate_only': True, 'candidate_url': PHOTO,
            'event_url': ROOT + '/event/workshop-1', 'extraction_url': FEED,
            'title': 'Public workshop', **changes}


def test_native_media_probes_only_the_candidate_and_uses_feed_evidence():
    fetch = MagicMock()
    probe = MagicMock(return_value=(PHOTO, 'image/jpeg'))
    result = event_media.resolve_photo(media_claim(), fetcher=fetch, probe=probe,
                                      clock=lambda: 0, deadline=30)
    fetch.assert_not_called()
    probe.assert_called_once_with(PHOTO)
    assert result == {'image_url': PHOTO, 'mime_type': 'image/jpeg', 'evidence_url': FEED}


@pytest.mark.parametrize('changes', [
    {native.CAPABILITY: value} for value in [None, False, True, '1', 1.0, 2]
] + [
    {'candidate_only': False}, {'kind': 'ical'}, {'platform_adapter': 'squarespace'},
    {'source_key': 'forged'}, {'extraction_url': ROOT}, {'feed_url': FEED + '&scope=other'},
    {'event_url': 'https://another.example.org/event/one'},
    {'candidate_url': None}, {'candidate_url': ''}, {'candidate_url': 'http://cdn.example.org/a.jpg'},
    {'candidate_url': 'https://127.0.0.1/a.jpg'},
])
def test_invalid_native_media_claim_never_fetches_or_probes(changes):
    fetch, probe = MagicMock(), MagicMock()
    result = event_media.resolve_photo(media_claim(**changes), fetcher=fetch, probe=probe,
                                      clock=lambda: 0, deadline=30)
    assert result is None
    fetch.assert_not_called()
    probe.assert_not_called()


def test_native_media_still_requires_validated_final_redirect_target():
    fetch = MagicMock()
    result = event_media.resolve_photo(media_claim(), fetcher=fetch,
        probe=lambda _: ('https://cdn.example.org/logo.png', 'image/jpeg'),
        clock=lambda: 0, deadline=30)
    assert result is None
    fetch.assert_not_called()


def image_response(status=200, headers=None):
    response = MagicMock()
    response.status_code = status
    response.headers = headers or {'Content-Type': 'image/jpeg', 'Content-Length': '1000'}
    response.iter_content.return_value = iter([b'\xff\xd8\xff\xe0image'])
    response.__enter__.return_value = response
    return response


@pytest.mark.parametrize('policy', [False, 'robots_denied', 'publisher_wait_requires_review'])
def test_native_image_policy_denial_precedes_get_without_page_fallback(policy):
    fetch, session = MagicMock(), MagicMock()
    effect = preview_worker.PreviewError(policy) if isinstance(policy, str) else None
    with patch.object(event_media, 'validate_public_dns'), \
            patch.object(event_media, 'robots_allowed', return_value=False, side_effect=effect) as robots, \
            patch.object(event_media, 'pace_publisher') as pace:
        assert event_media.resolve_photo(media_claim(), fetcher=fetch, session=session,
            clock=lambda: 0, deadline=30, strict_deadline=True) is None
    robots.assert_called_once_with('cdn.example.org', '/workshop-poster.jpg', deadline_at=8)
    session.get.assert_not_called()
    fetch.assert_not_called()
    pace.assert_not_called()


def test_native_image_checks_exact_query_and_each_redirect_under_host_permit():
    from roomquest.media_worker import HostLimiter
    first = PHOTO + '?size=large&version=2'
    second = 'https://images.example.net/private/poster.jpg?license=none'
    limiter = HostLimiter(1, clock=lambda: 0)
    seen = []
    def policy(host, path, *, deadline_at):
        assert limiter._active[event_media.canonical_host(host)] == 1
        seen.append((host, path, deadline_at))
        return host == 'cdn.example.org'
    session = MagicMock()
    session.get.return_value = image_response(302, {'Location': second})
    fetch = MagicMock()
    with patch.object(event_media, 'validate_public_dns') as dns, \
            patch.object(event_media, 'robots_allowed', side_effect=policy), \
            patch.object(event_media, 'pace_publisher') as pace:
        assert event_media.resolve_photo(media_claim(candidate_url=first), fetcher=fetch,
            session=session, host_limiter=limiter, clock=lambda: 0, deadline=30,
            strict_deadline=True) is None
    assert seen == [('cdn.example.org', '/workshop-poster.jpg?size=large&version=2', 8),
                    ('images.example.net', '/private/poster.jpg?license=none', 8)]
    assert [call.args[0] for call in dns.call_args_list] == ['cdn.example.org', 'images.example.net']
    session.get.assert_called_once()
    assert session.get.call_args.args[0] == first
    pace.assert_called_once_with('cdn.example.org', 8)
    assert not limiter._active
    fetch.assert_not_called()


@pytest.mark.parametrize('code,reason', [
    ('robots_unavailable', 'network_error'), ('publisher_rate_limited', 'transient_http'),
    ('publisher_pacing_deferred', 'host_busy'), ('source_fetch_deadline', 'deadline'),
])
def test_native_temporary_policy_errors_use_existing_closed_defer_outcomes(code, reason):
    session = MagicMock()
    with patch.object(event_media, 'validate_public_dns'), \
            patch.object(event_media, 'robots_allowed', side_effect=preview_worker.PreviewError(code)):
        with pytest.raises(event_media.MediaDeferred) as caught:
            event_media.resolve_photo(media_claim(), session=session, clock=lambda: 0,
                deadline=30, strict_deadline=True)
    assert caught.value.reason == reason
    assert caught.value.host == 'cdn.example.org'
    assert caught.value.attempted is False
    session.get.assert_not_called()


@pytest.mark.parametrize('wait,terminal', [(120, False), (3601, True), (86401, True)])
def test_native_robots_retry_after_is_retained_or_stops_without_shorter_wait(wait, terminal):
    from roomquest.publisher_pacing import observe_retry_after
    def policy(*args, **kwargs):
        observe_retry_after(str(wait))
        raise preview_worker.PreviewError('publisher_rate_limited')
    session = MagicMock()
    with patch.object(event_media, 'validate_public_dns'), \
            patch.object(event_media, 'robots_allowed', side_effect=policy):
        if terminal:
            assert event_media.resolve_photo(media_claim(), session=session,
                clock=lambda: 0, deadline=30, strict_deadline=True) is None
        else:
            with pytest.raises(event_media.MediaDeferred) as caught:
                event_media.resolve_photo(media_claim(), session=session,
                    clock=lambda: 0, deadline=30, strict_deadline=True)
            assert caught.value.reason == 'transient_http'
            assert caught.value.retry_after_seconds == 120
    session.get.assert_not_called()


def test_native_image_cached_robots_still_checks_each_path_and_honors_crawl_delay():
    now = [0]
    clock = lambda: now[0]
    sleeps = []
    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds
    robots_response = MagicMock()
    robots_response.status = 200
    robots_response.headers = {}
    robots_response.read.return_value = b'User-agent: *\nDisallow: /private/\nCrawl-delay: 2\n'
    robots_response.__enter__.return_value = robots_response
    opener = MagicMock()
    opener.open.return_value = robots_response
    session = MagicMock()
    session.get.return_value = image_response(302, {'Location': 'https://cdn.example.org/private/image.jpg'})
    with patch.object(event_media, 'validate_public_dns'), patch.object(preview_worker, 'validate_public_dns'), \
            patch.object(preview_worker, 'build_opener', return_value=opener), \
            patch.object(preview_worker, 'monotonic', clock), patch.object(preview_worker, 'sleep', sleep), \
            patch.object(preview_worker, '_robots_cache', OrderedDict()), \
            patch.object(preview_worker, '_robots_delays', {}), \
            patch.object(preview_worker, '_publisher_next', {}), \
            patch.object(preview_worker, '_publisher_retry_after', {}):
        assert event_media.resolve_photo(media_claim(), session=session, clock=clock,
            deadline=30, strict_deadline=True) is None
    opener.open.assert_called_once()
    assert opener.open.call_args.args[0].full_url == 'https://cdn.example.org/robots.txt'
    assert opener.open.call_args.kwargs['timeout'] <= 5
    robots_response.read.assert_called_once_with(128001)
    assert sleeps == [2]
    session.get.assert_called_once()
    assert now[0] == 2


@pytest.mark.parametrize('spent', [7, 8])
def test_native_robots_lookup_shares_existing_eight_second_probe_budget(spent):
    now = [0]
    def policy(host, path, *, deadline_at):
        assert deadline_at == 8
        now[0] = spent
        return True
    session = MagicMock()
    session.get.return_value = image_response()
    with patch.object(event_media, 'validate_public_dns'), \
            patch.object(event_media, 'robots_allowed', side_effect=policy), \
            patch.object(event_media, 'pace_publisher'):
        if spent == 8:
            with pytest.raises(event_media.MediaDeferred, match='deadline'):
                event_media.resolve_photo(media_claim(), session=session, clock=lambda: now[0],
                    deadline=30, strict_deadline=True)
            session.get.assert_not_called()
        else:
            assert event_media.resolve_photo(media_claim(), session=session, clock=lambda: now[0],
                deadline=30, strict_deadline=True)['image_url'] == PHOTO
            assert sum(session.get.call_args.kwargs['timeout']) <= 1


def test_legacy_image_probe_does_not_enter_native_policy_gate():
    session = MagicMock()
    session.get.return_value = image_response()
    with patch.object(event_media, 'validate_public_dns'), \
            patch.object(event_media, 'robots_allowed') as robots:
        assert event_media.probe_image(PHOTO, session=session, clock=lambda: 0) == (PHOTO, 'image/jpeg')
    robots.assert_not_called()


@pytest.mark.parametrize('code', [
    'registered_native_source_invalid', 'registered_native_capability_required',
    'registered_native_event_identity_invalid', 'registered_native_description_too_long',
    'registered_native_evidence_invalid',
])
def test_native_failure_diagnostics_remain_closed_codes(code):
    from roomquest.category_worker import _error_code
    assert _error_code(preview_worker.PreviewError(code)) == code
    assert _error_code(preview_worker.PreviewError(code + '_private_payload')) == 'unclassified_preview_error'
