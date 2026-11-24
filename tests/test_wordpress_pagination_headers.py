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
