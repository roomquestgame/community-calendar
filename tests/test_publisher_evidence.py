"""Publisher evidence survives normalization, staging payloads and image probes."""
from pathlib import Path
from unittest.mock import Mock

import pytest

from roomquest.publisher_evidence import attach, family, image_url, IMAGE_VERSION
from roomquest import event_media
from roomquest.event_media import resolve_photo
from roomquest.south_carolina_parks import details

FIXTURES = Path(__file__).parent / 'fixtures' / 'south_carolina_parks'
ROSEMONT_IMAGE = 'https://rosemontofvirginia.com/wp-content/uploads/2026/04/ShortStacked-Logo.jpg'
ROSEMONT_EVENT = 'https://rosemontofvirginia.com/event/wine-dine-w-short-stacked-2/'


@pytest.mark.parametrize('key,url,picture,publisher', [
    ('mycountyparks_ia_mahaska', 'https://www.mycountyparks.com/County/Mahaska/Park/Caldwell-Park/Events/29678/Coffee-Club',
     'https://content.mycountyparks.com/Production/RelatedItem/Content/coffee.jpg', 'mycountyparks'),
    ('bellevue_times_ne', 'https://bellevuetimes.com/events/stem-cart/?occurrence=20261114T100000',
     'https://bellevuetimes.com/wp-content/uploads/2026/11/cart.png', 'bellevue_times'),
    ('south_carolina_parks_1831', 'https://southcarolinaparks.com/products/10012259',
     'https://southcarolinaparks.com/assets/event-birding.jpg', 'south_carolina_parks'),
    ('rosemont_of_virginia', ROSEMONT_EVENT, ROSEMONT_IMAGE, 'rosemont'),
])
def test_selected_candidates_use_probe_only_and_reject_off_publisher_redirects(key, url, picture, publisher):
    item = attach({'event_url': url}, key, candidate=picture, facts={'cost': '$10'})
    assert family(key, url) == publisher
    assert item['image_evidence_url'] == url
    assert item['image_extractor_version'] == IMAGE_VERSION
    fetch = Mock(side_effect=AssertionError('Must never fetch an event detail page'))
    claim = {'source_key': key, 'event_url': url, 'title': 'Event', 'candidate_only': True,
             'candidate_url': picture}
    assert resolve_photo(claim, fetcher=fetch, probe=lambda _: (picture, 'image/jpeg'))['image_url'] == picture
    assert resolve_photo(claim, fetcher=fetch, probe=lambda _: ('https://unrelated.example/photo.jpg', 'image/jpeg')) is None
    fetch.assert_not_called()


@pytest.mark.parametrize('publisher', [
    'mycountyparks', 'bellevue_times', 'madison', 'chase_city_chamber',
    'south_carolina_parks', 'think_iowa_city', 'unleashcb', 'mason_city', None,
])
def test_rosemont_reviewed_image_exception_does_not_apply_to_other_families(publisher):
    assert image_url(ROSEMONT_IMAGE, publisher) is None


@pytest.mark.parametrize('key,url', [
    ('unrelated_wordpress', ROSEMONT_EVENT),
    ('rosemont_of_virginia', 'https://other.example/event/wine-dine/'),
    ('rosemont_of_virginia', 'https://rosemontofvirginia.com/'),
])
def test_rosemont_reviewed_image_still_requires_publisher_event_identity(key, url):
    with pytest.raises(ValueError, match='publisher_evidence_identity_mismatch'):
        attach({'event_url': url}, key, candidate=ROSEMONT_IMAGE)


@pytest.mark.parametrize('body,mime,accepted', [
    (b'\xff\xd8\xff\xe0jpeg', 'image/jpeg', True),
    (b'<html>not an image</html>', 'image/jpeg', False),
    (b'<svg></svg>', 'image/svg+xml', False),
])
def test_rosemont_reviewed_candidate_still_requires_normal_byte_probe(monkeypatch, body, mime, accepted):
    response = Mock()
    response.status_code = 200
    response.headers = {'Content-Type': mime, 'Content-Length': str(len(body))}
    response.iter_content.return_value = iter([body])
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    session = Mock()
    session.get.return_value = response
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(event_media.requests, 'Session', lambda: session)
    monkeypatch.setattr(event_media, 'validate_public_dns', lambda _: None)
    fetch = Mock(side_effect=AssertionError('No event-page fetch'))
    claim = {'source_key': 'rosemont_of_virginia', 'event_url': ROSEMONT_EVENT,
             'title': 'Wine + Dine', 'candidate_only': True, 'candidate_url': ROSEMONT_IMAGE}
    result = resolve_photo(claim, fetcher=fetch)
    assert bool(result) is accepted
    if accepted:
        assert result == {'image_url': ROSEMONT_IMAGE, 'mime_type': 'image/jpeg',
                          'evidence_url': ROSEMONT_EVENT}
    session.get.assert_called_once()
    assert session.get.call_args.args == (ROSEMONT_IMAGE,)
    assert session.get.call_args.kwargs['allow_redirects'] is False
    assert session.get.call_args.kwargs['headers']['Range'] == 'bytes=0-4095'
    fetch.assert_not_called()


@pytest.mark.parametrize('url', [
    'https://content.mycountyparks.com.evil.test/Production/RelatedItem/Content/a.jpg',
    'https://user@content.mycountyparks.com/Production/RelatedItem/Content/a.jpg',
    'https://content.mycountyparks.com/Production/RelatedItem/Content/../a.jpg',
    'https://content.mycountyparks.com/Production/RelatedItem/Content/a.jpg?token=secret',
    'http://content.mycountyparks.com/Production/RelatedItem/Content/a.jpg',
])
def test_image_candidates_do_not_admit_unsafe_or_unrelated_urls(url):
    assert image_url(url, 'mycountyparks') is None


def test_missing_candidate_never_falls_back_to_generic_site_artwork():
    fetch = Mock(side_effect=AssertionError('No new request'))
    assert resolve_photo({'source_key': 'bellevue_times_ne', 'candidate_only': True,
                          'event_url': 'https://bellevuetimes.com/events/cart/?occurrence=20261114T100000',
                          'title': 'Cart'}, fetcher=fetch) is None
    fetch.assert_not_called()


def test_real_south_carolina_page_keeps_narrative_price_meeting_point_and_topic():
    desc, facts, topics, candidate = details({'name': 'Tour of Redcliffe', 'description': 'Catalog summary'},
                                           (FIXTURES/'redcliffe.html').read_text())
    assert desc.startswith('Join us as we explore the complicated history')
    assert 'Adults $10, Children $5, SC Seniors $6' in desc
    assert facts['cost'] == 'Adults $10, Children $5, SC Seniors $6'
    assert facts['meeting_location'].startswith('Check in at Visitor Center')
    assert topics == ['Civil War']
    assert candidate is None


def test_real_birding_page_keeps_age_evidence_and_rejects_generic_site_photo():
    desc, facts, topics, candidate = details({'name': 'Birding Walk With A Ranger'},
                                           (FIXTURES/'birding.html').read_text())
    assert 'Appropriate for ages 12 and up.' in desc
    assert facts['cost'] == '$10 per person'
    assert topics == [] and candidate is None
    assert image_url('https://southcarolinaparks.com/images/og/south-carolina-parks.jpg', 'south_carolina_parks') is None


def test_json_catalog_description_is_preserved_without_html_narrative():
    assert details({'name': 'Program', 'description': '<p>Learn about birds.</p>'}, '<h3>DETAILS</h3>')[0] == 'Learn about birds.'


def test_event_specific_sc_narrative_image_is_supported_without_a_new_fetch():
    html = '<div class="copy"><h1 class="event-heading__title">Birding</h1><p class="description">Join us<img src="/assets/bird.jpg"></p></div>'
    assert details({'name': 'Birding'}, html)[3] == 'https://southcarolinaparks.com/assets/bird.jpg'
    with pytest.raises(ValueError, match='identity_mismatch'):
        details({'name': 'Different Event'}, html)
