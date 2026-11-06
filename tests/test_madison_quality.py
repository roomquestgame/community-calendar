"""Madison-only candidate evidence and conflicting publisher prose."""
import copy
import json
from unittest.mock import Mock, patch

import pytest

from roomquest.wordpress_adapter import collect
from roomquest.preview_worker import preview_source, _process_claimed_source
from roomquest.publisher_evidence import family, image_url
from roomquest.event_media import resolve_photo

SOURCE = {'source_key': 'madison_county_parks_ia', 'kind': 'json',
          'platform_adapter': 'wordpress', 'timezone': 'America/Chicago',
          'feed_url': 'https://www.madisoncountyparks.org/wp-json/tribe/events/v1/events'}
URL = 'https://www.madisoncountyparks.org/calendar/basket/'
IMAGE = 'https://www.madisoncountyparks.org/wp-content/uploads/2026/01/aurora.jpg'


def event():
    return {'id': 4867, 'title': 'Traditional Basket Weaving', 'status': 'publish',
            'url': URL, 'start_date': '2026-11-17 18:00:00', 'end_date': '2026-11-17 19:00:00',
            'utc_start_date': '2026-11-18 00:00:00', 'utc_end_date': '2026-11-18 01:00:00',
            'timezone': 'America/Chicago', 'cost': 'Free',
            'venue': {'venue': 'Conservation Center', 'address': '2508 Pammel Park Trail',
                      'city': 'Winterset', 'state': 'IA', 'zip': '50273'},
            'description': '<p>Join us at the Center on Oct 6 from 6-7PM. Learn basket weaving.</p>'}


def collected(item):
    return collect(SOURCE, lambda *_: json.dumps({'events': [item]}))[0]


def test_conflicting_intro_keeps_publisher_prose_with_explicit_warning_and_no_schedule_change():
    row = collected(event())
    assert row['description'].startswith('Schedule note:')
    assert 'on Oct 6 from 6-7PM' in row['description']
    assert row['starts_at'] == '2026-11-18T00:00:00+00:00'
    assert row['publisher_details'] == {'cost': 'Free'}
    assert 'image_url' not in row


@pytest.mark.parametrize('text', ['Join us on Nov 17 for weaving.',
                                 'A presentation about the storm on October 6.',
                                 'Join us for a talk about October 6.', 'Join us on Foobar 6.'])
def test_matching_or_historical_dates_do_not_add_warning(text):
    item = event(); item['description'] = text
    assert collected(item)['description'] == text


def test_single_inline_image_keeps_event_evidence_and_does_not_fetch_it():
    item = event(); item['description'] = '<p>Aurora science.</p><img src="' + IMAGE + '">'
    fetch = Mock(return_value=json.dumps({'events': [item]}))
    row = collect(SOURCE, fetch)[0]
    assert fetch.call_count == 1
    assert row['image_url'] == IMAGE
    assert row['image_evidence_url'] == URL
    assert row['image_extractor_version'] == 'publisher_event_candidates_v1'
    claim = {'source_key': SOURCE['source_key'], 'event_url': URL, 'title': item['title'],
             'candidate_url': IMAGE, 'candidate_only': True}
    forbidden_fetch = Mock(side_effect=AssertionError('No page re-fetch'))
    assert resolve_photo(claim, fetcher=forbidden_fetch, probe=lambda _: (IMAGE, 'image/jpeg'))
    assert resolve_photo(claim, fetcher=forbidden_fetch,
                         probe=lambda _: ('https://other.example/photo.jpg', 'image/jpeg')) is None
    forbidden_fetch.assert_not_called()


def test_multiple_images_fail_closed_and_featured_image_is_supported():
    item = event(); item['description'] = '<img src="' + IMAGE + '"><img src="' + IMAGE.replace('aurora', 'other') + '">'
    assert 'image_url' not in collected(item)
    item['description'] = 'Learn weaving.'; item['image'] = {'url': IMAGE}
    assert collected(item)['image_url'] == IMAGE


@pytest.mark.parametrize('url', ['http://www.madisoncountyparks.org/wp-content/uploads/a.jpg',
    'https://www.madisoncountyparks.org.evil.test/wp-content/uploads/a.jpg',
    'https://www.madisoncountyparks.org/wp-content/uploads/../a.jpg',
    'https://user@www.madisoncountyparks.org/wp-content/uploads/a.jpg',
    'https://www.madisoncountyparks.org/wp-content/uploads/a.jpg?key=abc',
    'https://www.madisoncountyparks.org/logo.png'])
def test_unqualified_image_urls_are_rejected(url):
    assert image_url(url, 'madison') is None


def test_worker_stages_evidence_and_uses_versioned_completion_contract():
    item = event(); item['description'] = 'A talk.<img src="' + IMAGE + '">'
    def rpc(name, payload):
        return len(payload['p_events']) if name.endswith('record_staged_events') else None
    with patch('roomquest.preview_worker.fetch_publisher', return_value=json.dumps({'events': [item]})), \
         patch('roomquest.preview_worker.supabase_rpc', side_effect=rpc) as db:
        assert _process_claimed_source(SOURCE)['complete'] == 1
    assert db.call_args_list[0].args[1]['p_events'][0]['image_url'] == IMAGE
    assert db.call_args_list[-1].args[0] == 'community_collector_record_preview_v3'
    assert db.call_args_list[-1].args[1]['p_parser_capability'] == 'publisher_event_candidates_v1'


def test_ordinary_wordpress_source_does_not_get_madison_evidence_or_rpc_capability():
    item = event(); item['description'] += '<img src="' + IMAGE + '">'
    other = {**SOURCE, 'source_key': 'nebraska_game_parks'}
    with patch('roomquest.preview_worker.fetch_publisher', return_value=json.dumps({'events': [item]})):
        result = preview_source(other)
    assert 'p_parser_capability' not in result
    assert 'image_url' not in result['p_events'][0]
    assert 'publisher_details' not in result['p_events'][0]


def test_warning_and_narrative_remain_within_staging_bound():
    item = event(); item['description'] += 'a' * 4000
    assert len(collected(item)['description']) == 2000
