"""Reviewed external navigation still uses the normal registration gates."""
from unittest.mock import patch

import pytest

from roomquest.feed_registration import classify, register
from roomquest.preview_worker import PreviewError

HOME = 'https://www.morgan.edu/'
CALENDAR = 'https://events.morgan.edu/'
LINK = '<a href="https://events.morgan.edu/" title="Events">Events</a>'
LOCALIST = '<script src="https://localist-images.azureedge.net/assets/app.js"></script>'


def test_reviewed_link_requires_exact_source_and_published_destination():
    assert classify(HOME, LINK) == {'calendar_page': CALENDAR}
    for source in [HOME + '?venue=East', HOME + 'department',
                   'https://unrelated.edu/', 'http://www.morgan.edu/',
                   'https://www.morgan.edu.attacker.example/']:
        assert 'calendar_page' not in classify(source, LINK)
    for body in ['<p>No link</p>', LINK.replace('events.morgan.edu', 'events.morgan.edu.attacker.example'),
                 LINK.replace('events.morgan.edu/', 'events.morgan.edu/event/one'),
                 LINK.replace('events.morgan.edu/', 'events.morgan.edu/?venue=East'),
                 '<script>var calendar="https://events.morgan.edu/";</script>']:
        assert 'calendar_page' not in classify(HOME, body)
    assert 'calendar_page' not in classify(HOME, LINK, endpoint_only=True)


def test_navigation_records_api_endpoint_for_independent_existing_workflow_check():
    with patch('roomquest.feed_registration.supabase_rpc', side_effect=[{'url': HOME}, True]) as rpc, \
         patch('roomquest.feed_registration.fetch_publisher', side_effect=[LINK, LOCALIST]) as fetch:
        assert register('ticket') == {'outcome': 'discovered'}
    result = rpc.call_args.args[1]
    assert result['p_endpoint'] == CALENDAR + 'api/2/events'
    assert result['p_type'] == 'localist'
    assert [c.args[0] for c in fetch.call_args_list] == [HOME, CALENDAR]
    assert all(c.kwargs['respect_robots'] for c in fetch.call_args_list)
    assert fetch.call_args_list[1].kwargs['allowed_hosts'] == ('events.morgan.edu',)
    assert fetch.call_args_list[0].kwargs['deadline_at'] == fetch.call_args_list[1].kwargs['deadline_at']


@pytest.mark.parametrize('reason,outcome', [('robots_denied', 'disabled'),
    ('publisher_http_403', 'disabled'), ('publisher_rate_limited', 'retry')])
def test_destination_access_restrictions_are_preserved(reason, outcome):
    with patch('roomquest.feed_registration.supabase_rpc', side_effect=[{'url': HOME}, True]) as rpc, \
         patch('roomquest.feed_registration.fetch_publisher', side_effect=[LINK, PreviewError(reason)]) as fetch:
        assert register('ticket') == {'outcome': outcome}
    assert fetch.call_count == 2
    assert rpc.call_args.args[1]['p_reason'] == reason


def test_destination_is_not_accepted_without_calendar_evidence():
    with patch('roomquest.feed_registration.supabase_rpc', side_effect=[{'url': HOME}, True]), \
         patch('roomquest.feed_registration.fetch_publisher', side_effect=[LINK, '<p>Welcome</p>']) as fetch:
        assert register('ticket') == {'outcome': 'review'}
    assert fetch.call_count == 2


def test_existing_explicit_feed_precedes_reviewed_navigation():
    body = LINK + '<link type="text/calendar" href="https://www.morgan.edu/calendar.ics">'
    assert classify(HOME, body)['p_endpoint'] == HOME + 'calendar.ics'
