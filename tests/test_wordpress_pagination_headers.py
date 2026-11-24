"""Header-driven WordPress manifest receipts are authoritative for completeness."""
import pytest
from roomquest import wordpress_custom_events as wp
from test_wordpress_custom_events import post, profile


def response(rows, total, pages):
    return rows, {'X-WP-Total': str(total), 'X-WP-TotalPages': str(pages)}


def test_one_page_success_and_all_occurrences():
    found = wp.extract_from_responses(profile(),
        [response([post()], 1, 1)], '2026-12-01', '2026-12-30')
    assert found['complete'] and len(found['events']) == 1


def test_two_page_complete_snapshot_only_with_both_pages():
    first = post()
    second = post(id=124, link='https://venue.example.org/events/second-talk/')
    collection = [response([first], 2, 2), response([second], 2, 2)]
    rows, count = wp.complete_response_pages(collection, per_page=1)
    assert count == 2 and len(rows) == 2
    assert len(wp.extract_from_responses(profile(), collection,
        '2026-12-01', '2026-12-30', per_page=1)['events']) == 2


@pytest.mark.parametrize('responses,code,per_page', [
    ([([post()], {})], 'pagination_headers_missing', 100),
    ([response([post()], 2, 2)], 'pagination_incomplete', 1),
    ([response([post()], 2, 2), response([post(id=124)], 3, 3)],
     'pagination_changed', 1),
    ([response([post()], 2, 2), response([post()], 2, 2)],
     'pagination_duplicate', 1),
    ([response([post()], 3, 1)], 'pagination_incomplete', 100),
    ([response([post()], 1, 2)], 'pagination_total_invalid', 100),
    ([response([post()], 0, 0)], 'pagination_total_invalid', 100),
])
def test_unverified_headers_dont_certify_prefix(responses,code,per_page):
    with pytest.raises(ValueError, match='wordpress_custom_' + code):
        wp.complete_response_pages(responses,per_page=per_page)


def test_direct_page_extractor_rejects_same_id_on_two_pages():
    with pytest.raises(ValueError, match='wordpress_custom_pagination_duplicate'):
        wp.extract(profile(), [[post()],[post()]], 2,
                   '2026-12-01','2026-12-30')


def receipt(number, rows, total, pages, *, route=None, per_page=1):
    url = wp.page_url(route or profile()['route_url'], number, per_page=per_page)
    return {'url': url, 'rows': rows, 'headers': response(rows, total, pages)[1]}


def test_provider_prefix_resumes_exact_next_url_then_returns_complete_projection():
    route = profile()['route_url']
    first = receipt(1, [post()], 2, 2)
    second = receipt(2, [post(id=124)], 2, 2)
    assert wp.next_page_url(route, [], per_page=1) == first['url']
    assert wp.next_page_url(route, [first], per_page=1) == second['url']
    with pytest.raises(ValueError, match='pagination_incomplete'):
        wp.extract_from_page_receipts(profile(), [first], '2026-12-01', '2026-12-30', per_page=1)
    restored = [first, second]
    assert wp.next_page_url(route, restored, per_page=1) is None
    found = wp.extract_from_page_receipts(profile(), restored, '2026-12-01', '2026-12-30', per_page=1)
    assert found['complete'] and found['post_count'] == 2 and len(found['events']) == 2


@pytest.mark.parametrize('scope', ['other_page', 'other_route', 'other_host', 'wrong_page_size'])
def test_restored_page_receipt_must_match_exact_ordered_request(scope):
    route = profile()['route_url']
    first = receipt(1, [post()], 2, 2)
    if scope == 'other_page':
        first['url'] = wp.page_url(route, 2, per_page=1)
    elif scope == 'other_route':
        first['url'] = wp.page_url(route.replace('/events', '/shows'), 1, per_page=1)
    elif scope == 'other_host':
        first['url'] = wp.page_url(route.replace('venue.example.org', 'another.example.org'), 1, per_page=1)
    else:
        first['url'] = wp.page_url(route, 1, per_page=2)
    with pytest.raises(ValueError, match='pagination_receipt_scope'):
        wp.next_page_url(route, [first], per_page=1)


def test_duplicate_headers_disagreeing_and_short_first_page_are_held():
    first = receipt(1, [post()], 2, 2)
    first['headers']['x-wp-total'] = '3'
    with pytest.raises(ValueError, match='pagination_headers_conflict'):
        wp.next_page_url(profile()['route_url'], [first], per_page=1)
    short = receipt(1, [post()], 3, 2, per_page=2)
    with pytest.raises(ValueError, match='pagination_incomplete'):
        wp.next_page_url(profile()['route_url'], [short], per_page=2)


def test_legacy_permalinks_resume_exact_route_without_filters():
    route = 'https://venue.example.org/?rest_route=/wp/v2/events'
    first = receipt(1, [post()], 2, 2, route=route)
    assert wp.next_page_url(route, [first], per_page=1) == route + '&page=2&per_page=1'
    for invalid in (route+'&search=music', profile()['route_url']+'?status=draft',
                    profile()['route_url']+'?exclude=123', route+'&rest_route=/wp/v2/posts'):
        with pytest.raises(ValueError, match='route_invalid'):
            wp.next_page_url(invalid, [], per_page=1)
