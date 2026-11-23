"""Source-scoped RPDE limit and terminal cursor semantics for Better."""
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from roomquest import openactive

BETTER_SERIES = openactive.BETTER + '/session-series'


def test_better_requests_a_documented_bounded_page_without_losing_cursor():
    original = BETTER_SERIES + '?afterTimestamp=123&afterId=abc'
    result = openactive.bounded_request_url(original, BETTER_SERIES)
    assert urlsplit(result).path == urlsplit(original).path
    assert parse_qs(urlsplit(result).query) == {
        'afterTimestamp': ['123'], 'afterId': ['abc'], 'limit': ['100']}
    assert openactive.bounded_request_url(result, BETTER_SERIES) == result
    assert openactive.page_url(result, BETTER_SERIES)


def test_limit_applies_only_to_reviewed_better_session_series():
    for stream in (openactive.BETTER + '/scheduled-sessions',
                   openactive.BOOKWHEN + 'sessionseries',
                   openactive.BOOKWHEN + 'scheduledsessions',
                   openactive.ORIENTEERING):
        assert openactive.bounded_request_url(stream, stream) == stream
    with pytest.raises(ValueError, match='openactive_cursor_scope'):
        openactive.bounded_request_url('https://example.net/other', BETTER_SERIES)


def test_bounded_terminal_page_with_or_without_limit():
    request = openactive.bounded_request_url(
        BETTER_SERIES + '?afterTimestamp=123&afterId=abc', BETTER_SERIES)
    for next_url in (request, BETTER_SERIES + '?afterTimestamp=123&afterId=abc'):
        body = json.dumps({'items': [], 'next': next_url,
                           'license': 'https://creativecommons.org/licenses/by/4.0/'})
        assert openactive.parse_page(body, request, BETTER_SERIES)['tail'] is True


def test_changed_cursor_cannot_be_mistaken_for_terminal_page():
    request = openactive.bounded_request_url(
        BETTER_SERIES + '?afterTimestamp=123&afterId=abc', BETTER_SERIES)
    changed = BETTER_SERIES + '?afterTimestamp=124&afterId=def'
    body = json.dumps({'items': [], 'next': changed,
                       'license': 'https://creativecommons.org/licenses/by/4.0/'})
    result = openactive.parse_page(body, request, BETTER_SERIES)
    assert result['tail'] is False


def test_nonempty_self_next_never_certifies_a_complete_capture():
    request = openactive.bounded_request_url(BETTER_SERIES, BETTER_SERIES)
    body = json.dumps({'items': [{'id': 1, 'modified': 1, 'kind': 'SessionSeries',
                                   'state': 'deleted'}], 'next': BETTER_SERIES,
                       'license': 'https://creativecommons.org/licenses/by/4.0/'})
    with pytest.raises(ValueError, match='openactive_cursor_stalled'):
        openactive.parse_page(body, request, BETTER_SERIES)
