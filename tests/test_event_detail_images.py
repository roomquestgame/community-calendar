"""Negotiated one-page image enrichment, using real extraction and media flow."""
import json
from time import monotonic
from unittest.mock import MagicMock

import pytest

from roomquest import event_media as media
from roomquest import media_worker as worker
from roomquest import preview_worker as publisher
from roomquest.publisher_pacing import observe_retry_after
from test_media_demand import Database, TICKET


EVENT = 'https://calendar.example.org/event/workshop'
PHOTO = 'https://cdn.example.org/workshop.jpg'
TITLE = 'Community workshop'


def detail_claim(**updates):
    return {'media_key': 'detail:fixture', 'lease_id': 'leased-fixture',
            'source_key': 'approved-native-source', 'event_url': EVENT,
            'title': TITLE, 'candidate_url': None, 'candidate_only': False,
            'extraction_url': EVENT, 'event_detail_image_version': 1, **updates}


def photo_page():
    return ('<h1>' + TITLE + '</h1><div class="tribe-events-event-image">'
            '<img src="' + PHOTO + '" width="1200" height="800"></div>')


@pytest.fixture(autouse=True)
def no_live_requests(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('No publisher network calls in fixture tests')
    monkeypatch.setattr('requests.sessions.Session.request', forbidden)
    monkeypatch.setattr('socket.getaddrinfo', forbidden)
    monkeypatch.setenv('VERCEL_ENV', 'production')


@pytest.mark.parametrize('version', [None, False, True, '1', 0, 2])
def test_missing_or_inexact_detail_capability_never_fetches(version):
    claim = detail_claim(event_detail_image_version=version)
    fetch, probe = MagicMock(), MagicMock()
    assert media.resolve_photo(claim, fetcher=fetch, probe=probe, clock=lambda: 0, deadline=30) is None
    fetch.assert_not_called()
    probe.assert_not_called()


@pytest.mark.parametrize('change', [
    {'candidate_only': True}, {'candidate_url': PHOTO},
    {'extraction_url': EVENT + '/other'}, {'event_url': 'https://127.0.0.1/event'},
    {'source_key': ''}, {'title': ''},
])
def test_detail_claim_requires_exact_leased_page_and_missing_native_image(change):
    claim = detail_claim(**change)
    fetch = MagicMock()
    assert not media.detail_image_claim(claim)
    assert media.resolve_photo(claim, fetcher=fetch, clock=lambda: 0, deadline=30) is None
    fetch.assert_not_called()


def test_featured_event_photo_precedes_generic_open_graph_artwork():
    html = photo_page() + '<meta property="og:image" content="https://cdn.example.org/park-aerial.jpg">'
    assert media.extract_photo(html, EVENT, TITLE) == PHOTO


@pytest.mark.parametrize('attribute', ['data-src', 'data-lazy-src'])
def test_lazy_event_photo_uses_only_existing_event_owned_selectors(attribute):
    html = '<h1>' + TITLE + '</h1><img class="wp-post-image" src="" ' + attribute + '="' + PHOTO + '">'
    assert media.extract_photo(html, EVENT, TITLE) == PHOTO
    assert media.extract_photo(html.replace(' class="wp-post-image"', ''), EVENT, TITLE) is None


@pytest.mark.parametrize('image', ['', '#poster', False, {'url': ''}])
def test_empty_page_image_does_not_resolve_to_the_event_url(image):
    html = '<script type="application/ld+json">' + json.dumps({
        '@type': 'Event', 'name': TITLE, 'url': EVENT, 'image': image,
    }) + '</script>'
    assert media.extract_photo(html, EVENT, TITLE) is None


def test_jsonld_image_must_belong_to_the_exact_event_url_if_declared():
    html = '<script type="application/ld+json">' + json.dumps({
        '@type': 'Event', 'name': TITLE, 'url': EVENT + '-different', 'image': PHOTO,
    }) + '</script>'
    assert media.extract_photo(html, EVENT, TITLE) is None
    assert media.extract_photo(html.replace(EVENT + '-different', EVENT + '#event'), EVENT, TITLE) == PHOTO


def test_conflicting_featured_photos_are_not_chosen_arbitrarily():
    html = photo_page() + '<div class="tribe-events-event-image"><img src="/other.jpg"></div>'
    assert media.extract_photo(html, EVENT, TITLE) is None


def test_specific_shorter_publisher_heading_can_identify_unique_primary_artwork():
    title = 'Downtown Silver Spring FRESHFARM Market'
    html = ('<h1>Downtown Silver Spring</h1>'
            '<img class="wp-post-image" src="' + PHOTO + '">')
    assert media.extract_photo(html, EVENT, title) is None
    assert media.extract_photo(html, EVENT, title, allow_heading_prefix=True) == PHOTO


def test_shorter_heading_does_not_authorize_generic_social_or_unscoped_images():
    title = 'Downtown Silver Spring FRESHFARM Market'
    html = ('<h1>Downtown Silver Spring</h1><img src="' + PHOTO + '">'
            '<meta property="og:image" content="' + PHOTO + '">')
    assert media.extract_photo(html, EVENT, title, allow_heading_prefix=True) is None
    assert media.extract_photo('<h1>Community Market</h1><img class="wp-post-image" src="' + PHOTO + '">',
                               EVENT, 'Community Market Summer Opening', allow_heading_prefix=True) is None


def test_unique_heading_hero_background_is_owned_by_the_specific_primary_page():
    html = ('<main><div class="market-hero"><div class="market-hero-background" '
            'style="background-image: url(\'/photos/market-banner.jpg\');"></div>'
            '<div class="market-hero-inner"><nav><img src="/logo.png"></nav>'
            '<div><h1>Downtown Silver Spring</h1></div></div></div>'
            '<aside><img class="wp-post-image" src="/related.jpg"></aside>'
            '<div style="background-image:url(/unrelated.jpg)"></div></main>')
    assert media.extract_photo(html, EVENT, 'Downtown Silver Spring FRESHFARM Market',
                               allow_heading_prefix=True) == 'https://calendar.example.org/photos/market-banner.jpg'
    assert media.extract_photo(html.replace('market-hero', 'page-content'), EVENT,
                               'Downtown Silver Spring FRESHFARM Market', allow_heading_prefix=True) is None


@pytest.mark.parametrize('extra', [
    '<div style="background-image:url(/another-photo.jpg)"></div>',
    '<h1>Another market</h1>',
])
def test_ambiguous_hero_never_selects_a_background(extra):
    html = ('<div class="event-hero"><h1>' + TITLE + '</h1>'
            '<div style="background-image:url(/poster.jpg)"></div>' + extra + '</div>')
    assert media.extract_photo(html, EVENT, TITLE, allow_heading_prefix=True) is None


@pytest.mark.parametrize('filename', ['OG-Image.jpg', 'default-event-image.png',
                                     'social-thumbnail-1200x630-v01.png', 'logo.png',
                                     'site-logo.png', 'site-logo-white.png', 'og-default.jpg', 'location-map.png'])
def test_full_title_does_not_authorize_generic_default_or_logo_artwork(filename):
    html = '<h1>' + TITLE + '</h1><meta property="og:image" content="/uploads/' + filename + '">'
    assert media.extract_photo(html, EVENT, TITLE, allow_heading_prefix=True) is None


@pytest.mark.parametrize('wrapper', [
    '<aside aria-label="Related events">{}</aside>',
    '<aside>' + '<div>' * 8 + '{}' + '</div>' * 8 + '</aside>',
    '<div class="related-events">{}</div>',
    '<section id="related-events">{}</section>',
    '<section aria-label="Recommended events">{}</section>',
    '<main><article><h2>Unrelated market</h2>{}</article></main>',
    '<footer>{}</footer>',
])
def test_another_event_or_navigation_photo_is_not_primary_artwork(wrapper):
    html = '<h1>' + TITLE + '</h1>' + wrapper.format('<img class="wp-post-image" src="' + PHOTO + '">')
    assert media.extract_photo(html, EVENT, TITLE, allow_heading_prefix=True) is None


def test_primary_hero_container_can_own_its_background_directly():
    html = '<div class="event-hero" style="background-image:url(' + PHOTO + ')"><h1>' + TITLE + '</h1></div>'
    assert media.extract_photo(html, EVENT, TITLE, allow_heading_prefix=True) == PHOTO


@pytest.mark.parametrize('level', range(1, 7))
def test_related_article_heading_level_does_not_change_image_ownership(level):
    html = ('<h1>' + TITLE + '</h1><main><article><h' + str(level) + '>Another event</h' + str(level)
            + '><img class="wp-post-image" src="' + PHOTO + '"></article></main>')
    assert media.extract_photo(html, EVENT, TITLE, allow_heading_prefix=True) is None


@pytest.mark.parametrize('structured', [True, False])
def test_library_event_poster_schema_and_social_fields_use_exact_page_identity(structured):
    # Synthetic library/Communico-style text blocks plus supported schema/meta
    # fields. This is not a captured Yarn Storm page or a claim about its DOM.
    url = 'https://library.example.org/event/17666145'
    poster = 'https://images.example.org/events/yarn-storm.jpg'
    html = ('<title>Yarn Storm - Library</title><meta property="og:title" content="Yarn Storm">'
            '<div class="amh-block amh-text"><div class="amh-content">Yarn Storm</div></div>')
    if structured:
        html += '<script type="application/ld+json">' + json.dumps({
            '@type': 'Event', 'name': 'Yarn Storm', 'url': url,
            'image': {'@type': 'ImageObject', 'url': poster, 'width': 900, 'height': 1200},
        }) + '</script>'
    else:
        html += '<meta property="og:image" content="' + poster + '">'
    assert media.extract_photo(html, url, 'Yarn Storm', allow_heading_prefix=True) == poster
    assert media.extract_photo(html, url, 'Another craft event', allow_heading_prefix=True) is None


def test_detail_fetch_uses_publisher_policy_exact_host_and_bounded_deadline(monkeypatch):
    fetch = MagicMock(return_value=photo_page())
    monkeypatch.setattr(media, 'fetch_publisher', fetch)
    result = media.resolve_photo(detail_claim(), probe=lambda image: (image, 'image/jpeg'),
                                 clock=lambda: 0, deadline=30, strict_deadline=True)
    assert result == {'image_url': PHOTO, 'mime_type': 'image/jpeg', 'evidence_url': EVENT}
    fetch.assert_called_once_with(EVENT, 'text/html', respect_robots=True, deadline_at=10,
                                  allowed_hosts=('calendar.example.org', 'www.calendar.example.org'))


def response(status, body=b'', content_type='text/html'):
    item = MagicMock(status_code=status, encoding='utf-8')
    item.headers = {'Content-Type': content_type}
    item.iter_content.side_effect = lambda *args, **kwargs: iter([body])
    item.__enter__.return_value = item
    return item


def prepare_transport(monkeypatch, responses):
    session = MagicMock()
    session.get.side_effect = responses
    session.__enter__.return_value = session
    monkeypatch.setattr(media.requests, 'Session', lambda: session)
    monkeypatch.setattr(publisher, 'validate_public_dns', lambda host: None)
    monkeypatch.setattr(media, 'validate_public_dns', lambda host: None)
    monkeypatch.setattr(publisher, 'robots_allowed', lambda *args, **kwargs: True)
    monkeypatch.setattr(media, 'robots_allowed', lambda *args, **kwargs: True)
    monkeypatch.setattr(publisher, 'pace_publisher', lambda *args: None)
    monkeypatch.setattr(media, 'pace_publisher', lambda *args: None)
    monkeypatch.setattr(publisher, 'activity_before_request', lambda *args, **kwargs: None)
    return session


def test_real_transport_extracts_one_page_then_checks_image_bytes(monkeypatch):
    session = prepare_transport(monkeypatch, [
        response(200, photo_page().encode()), response(200, b'\xff\xd8\xff\xe0jpeg', 'image/jpeg'),
    ])
    result = media.resolve_photo(detail_claim(), strict_deadline=True, deadline=monotonic() + 30)
    assert result == {'image_url': PHOTO, 'mime_type': 'image/jpeg', 'evidence_url': EVENT}
    assert [call.args[0] for call in session.get.call_args_list] == [EVENT, PHOTO]


def test_real_403_is_not_bypassed_or_retried_as_another_url(monkeypatch):
    session = prepare_transport(monkeypatch, [response(403)])
    with pytest.raises(media.MediaPageUnavailable, match='page_unavailable'):
        media.resolve_photo(detail_claim(), strict_deadline=True, deadline=monotonic() + 30)
    assert [call.args[0] for call in session.get.call_args_list] == [EVENT]


def test_real_redirect_cannot_leave_the_claimed_publisher(monkeypatch):
    redirected = response(302)
    redirected.headers['Location'] = 'https://different.example.org/event/workshop'
    session = prepare_transport(monkeypatch, [redirected])
    with pytest.raises(media.MediaPageUnavailable):
        media.resolve_photo(detail_claim(), strict_deadline=True, deadline=monotonic() + 30)
    assert [call.args[0] for call in session.get.call_args_list] == [EVENT]


def test_page_rate_limit_preserves_retry_after_without_probing(monkeypatch):
    def limited(*args, **kwargs):
        observe_retry_after('120')
        raise publisher.PreviewError('publisher_rate_limited')
    monkeypatch.setattr(media, 'fetch_publisher', limited)
    probe = MagicMock()
    with pytest.raises(media.MediaDeferred) as raised:
        media.resolve_photo(detail_claim(), probe=probe, clock=lambda: 0, deadline=30, strict_deadline=True)
    assert raised.value.reason == 'transient_http'
    assert raised.value.retry_after_seconds == 120
    assert raised.value.host == 'calendar.example.org'
    probe.assert_not_called()


def test_negotiated_worker_submits_only_its_leased_page_evidence(monkeypatch):
    db = Database(count=1)
    db.pending[0] = detail_claim()
    fetch = MagicMock(return_value=photo_page())
    monkeypatch.setattr(media, 'fetch_publisher', fetch)
    monkeypatch.setattr(media, 'probe_image', lambda image, **kwargs: (image, 'image/jpeg'))
    stats = worker.collect_media(TICKET, database=db, clock=lambda: 0)
    assert stats['ready'] == 1 and stats['outcome'] == 'complete'
    assert db.calls[0][1]['event_detail_image_version'] == 1
    assert all(payload['event_detail_image_version'] == 1
               for action, payload, _ in db.calls if action == 'claim')
    submitted = next(payload for action, payload, _ in db.calls if action == 'submit')
    assert submitted['media_key'] == 'detail:fixture' and submitted['lease_id'] == 'leased-fixture'
    assert submitted['image_url'] == PHOTO and submitted['evidence_url'] == EVENT
    fetch.assert_called_once()


@pytest.mark.parametrize('reason', ['publisher_http_403', 'robots_denied'])
def test_blocked_page_records_unavailability_without_a_transient_retry_loop(monkeypatch, reason):
    db = Database(count=1)
    db.pending[0] = detail_claim()
    fetch = MagicMock(side_effect=publisher.PreviewError(reason))
    monkeypatch.setattr(media, 'fetch_publisher', fetch)
    stats = worker.collect_media(TICKET, database=db, clock=lambda: 0)
    assert stats['unavailable'] == 1 and stats['deferred'] == 0
    failed = next(payload for action, payload, _ in db.calls if action == 'fail')
    assert failed['reason'] == 'page_unavailable'
    fetch.assert_called_once()


def test_detail_admission_reserves_page_and_probe_time():
    db = Database(count=0, budget_seconds=25)
    worker.collect_media(TICKET, database=db, clock=lambda: 0)
    claims = [payload for action, payload, _ in db.calls if action == 'claim']
    assert claims and claims[0]['event_detail_image_version'] == 0


def test_claim_delay_defers_detail_without_starting_a_page_request():
    now = [0]
    db = Database(count=1)
    db.pending[0] = detail_claim()
    db.after_claim = lambda: now.__setitem__(0, 20)
    resolve = MagicMock()
    stats = worker.collect_media(TICKET, database=db, resolver=resolve, clock=lambda: now[0])
    assert stats['deferred'] == 1
    assert next(payload for action, payload, _ in db.calls if action == 'defer')['reason'] == 'deadline'
    resolve.assert_not_called()
