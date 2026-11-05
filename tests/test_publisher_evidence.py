"""Publisher evidence survives normalization, staging payloads and image probes."""
from pathlib import Path
from unittest.mock import Mock

import pytest

from roomquest.publisher_evidence import attach, family, image_url, IMAGE_VERSION
from roomquest.event_media import resolve_photo
from roomquest.south_carolina_parks import details

FIXTURES = Path(__file__).parent / 'fixtures' / 'south_carolina_parks'


@pytest.mark.parametrize('key,url,picture,publisher', [
    ('mycountyparks_ia_mahaska', 'https://www.mycountyparks.com/County/Mahaska/Park/Caldwell-Park/Events/29678/Coffee-Club',
     'https://content.mycountyparks.com/Production/RelatedItem/Content/coffee.jpg', 'mycountyparks'),
    ('bellevue_times_ne', 'https://bellevuetimes.com/events/stem-cart/?occurrence=20261114T100000',
     'https://bellevuetimes.com/wp-content/uploads/2026/11/cart.png', 'bellevue_times'),
    ('south_carolina_parks_1831', 'https://southcarolinaparks.com/products/10012259',
     'https://southcarolinaparks.com/assets/event-birding.jpg', 'south_carolina_parks'),
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
