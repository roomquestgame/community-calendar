"""Synthetic publisher-controlled WordPress CPT schemas, never post dates."""
import pytest
from roomquest import wordpress_custom_events as wp

SITE = 'https://venue.example.org'
ROUTE = SITE + '/wp-json/wp/v2/events'
FIELDS = {'start': 'meta.eventStart', 'end': 'meta.eventEnd',
          'venue': 'meta.venue', 'address': 'meta.street'}


def profile(**overrides):
    return {'route_url': ROUTE, 'publisher_url': SITE + '/events/',
            'post_type': 'events', 'country': 'GB', 'timezone': 'Europe/London',
            'home_city': 'London', 'fields': FIELDS, **overrides}


def post(**overrides):
    return {'id': 123, 'type': 'events', 'status': 'publish',
            'link': SITE + '/events/evening-talk/',
            'title': {'rendered': 'Evening Talk'},
            # WordPress post publication timestamps MUST NOT supply event date.
            'date': '2025-08-09T12:00:00', 'date_gmt': '2025-08-09T12:00:00',
            'meta': {'eventStart': '2026-12-05T19:00:00',
                     'eventEnd': '2026-12-05T20:00:00',
                     'venue': 'Publisher Hall',
                     'street': '12 Kingsland Road, London E2 8EA'},
            'content': {'rendered': '<p>A thoughtful conversation.</p>'},
            **overrides}


def test_rest_discovered_route_and_retained_query_scope_page_urls():
    assert wp.page_url(ROUTE, 2).endswith('/wp-json/wp/v2/events?page=2&per_page=100')
    assert wp.page_url(SITE + '/?rest_route=/wp/v2/events', 2).endswith(
        '?rest_route=/wp/v2/events&page=2&per_page=100')
    for route in (SITE + '/wp-json/wp/v2/posts', SITE + '/wp-json/users',
                  'http://venue.example.org/wp-json/wp/v2/events'):
        if route.endswith('/posts'):
            # Posts may be a legitimate WP type but are not calendar sources
            # without an independently reviewed event field mapping.
            continue
        with pytest.raises(ValueError, match='wordpress_custom_route_invalid'):
            wp.page_url(route, 1)


def test_complete_custom_post_type_extracts_actual_future_event_date():
    result = wp.extract(profile(), [[post()]], 1, '2026-12-01', '2026-12-30')
    assert result['complete'] is True
    assert result['post_count'] == 1
    [row] = result['events']
    assert row['title'] == 'Evening Talk'
    assert row['starts_at'] == '2026-12-05T19:00:00+00:00'
    assert row['venue_name'] == 'Publisher Hall'
    assert row['description'] == 'A thoughtful conversation.'
    assert row['id'].startswith('wordpress:events:123:')


def test_two_dated_occurrences_retained_under_one_wordpress_post():
    orig = post(meta={'performances': [
        {'start': '2026-12-05T19:00:00', 'venue': 'Publisher Hall',
         'street': '12 Kingsland Road, London E2 8EA'},
        {'start': '2026-12-06T15:00:00', 'venue': 'Publisher Hall',
         'street': '12 Kingsland Road, London E2 8EA'},
    ]})
    fields = {'occurrences': 'meta.performances', 'start': 'start',
              'venue': 'venue', 'address': 'street'}
    result = wp.extract(profile(fields=fields), [[orig]], 1,
                        '2026-12-01', '2026-12-30')
    assert len(result['events']) == 2
    assert result['events'][0]['id'] != result['events'][1]['id']


def test_missing_date_does_not_fall_back_to_wordpress_post_date():
    bad = post(meta={'venue': 'Publisher Hall',
                     'street': '12 Kingsland Road, London E2 8EA'})
    with pytest.raises(ValueError, match='wordpress_custom_event_time_missing'):
        wp.extract(profile(), [[bad]], 1, '2026-12-01', '2026-12-30')


def test_full_pagination_required_even_when_first_page_has_real_events():
    with pytest.raises(ValueError, match='wordpress_custom_source_or_pagination_invalid'):
        wp.extract(profile(), [[post()]], 2, '2026-12-01', '2026-12-30')
    with pytest.raises(ValueError, match='wordpress_custom_post_invalid'):
        wp.extract(profile(), [['not a publisher post']], 1,
                   '2026-12-01', '2026-12-30')


def test_untrusted_event_link_location_and_dst_dont_publish_prefixes():
    for invalid in (
        post(link='https://other.example.com/show'),
        post(meta={'eventStart': '2026-12-05T19:00:00',
                   'eventEnd': '2026-12-05T20:00:00',
                   'venue': 'Publisher Hall', 'street': ''}),
    ):
        with pytest.raises(ValueError):
            wp.extract(profile(), [[invalid]], 1, '2026-12-01', '2026-12-30')
    bad_dst = post(meta={'eventStart': '2026-10-25T01:30:00',
                         'venue': 'Publisher Hall',
                         'street': '12 Kingsland Road, London E2 8EA'})
    with pytest.raises(ValueError, match='wordpress_custom_time_ambiguous'):
        wp.extract(profile(), [[bad_dst]], 1, '2026-10-24', '2026-10-28')


def test_public_authorized_legacy_custom_route_requires_separate_mapping():
    invalid = profile(fields={**FIELDS, 'start':'date'})
    with pytest.raises(ValueError, match='wordpress_custom_mapping_invalid'):
        wp.extract(invalid, [[post()]], 1, '2026-12-01', '2026-12-30')
