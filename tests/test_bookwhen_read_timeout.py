"""Source-scoped Bookwhen RPDE read-timeout regression tests.

The total transport deadline, robots checks, pacing and response size limit are
still enforced by fetch_publisher. These tests do not call the publisher.
"""
import pytest
from roomquest import preview_worker as worker, openactive


@pytest.mark.parametrize('stream', openactive.PROFILES['bookwhen']['streams'])
def test_only_reviewed_bookwhen_streams_get_extra_read_budget(stream):
    for candidate in (stream, stream + '?afterTimestamp=123&afterId=x'):
        assert worker._read_timeout_for_publisher(
            candidate, 'application/json', ('bookwhen.com',), True, 17) == 11
        assert worker._read_timeout_for_publisher(
            candidate, 'application/json', ('bookwhen.com',), True, 6) == 5


def test_unreviewed_hosts_paths_and_formats_keep_existing_timeout():
    url = openactive.BOOKWHEN + 'sessionseries'
    for candidate, accept, hosts, robots in (
        (url, 'text/html', ('bookwhen.com',), True),
        (url, 'application/json', ('bookwhen.com',), False),
        (url, 'application/json', ('evil.example',), True),
        ('https://bookwhen.com/unreviewed', 'application/json', ('bookwhen.com',), True),
        (openactive.BETTER + '/session-series', 'application/json', ('better-admin.org.uk',), True),
    ):
        assert worker._read_timeout_for_publisher(candidate, accept, hosts, robots, 17) == 7
    assert worker._read_timeout_for_publisher(url, 'application/json', ('bookwhen.com',), True, 2) == 1


def test_bookwhen_timeout_does_not_override_deadline():
    url = openactive.BOOKWHEN + 'scheduledsessions'
    for remaining in (0.2, 1.0, 6.0, 17.0):
        timeout = worker._read_timeout_for_publisher(
            url, 'application/json', ('bookwhen.com',), True, remaining)
        assert 0.1 <= timeout <= 11
        assert timeout < remaining or remaining <= 1
