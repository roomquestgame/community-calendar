"""Both venue pages publish the same existing, two-venue calendar."""
from unittest.mock import patch

import pytest

from roomquest.feed_registration import classify, register
from roomquest.preview_worker import PreviewError

CALENDAR = 'https://www.boplex.com/events'
VENUES = ['https://www.boplex.com/our-venues/bojangles-coliseum',
          'https://www.boplex.com/our-venues/ovens-auditorium']
LINK = '<a href="/events">Events</a>'


@pytest.mark.parametrize('venue', VENUES)
def test_only_publisher_link_on_exact_reviewed_venue_is_followed(venue):
    assert classify(venue, LINK) == {'calendar_page': CALENDAR}
    for source in [venue + '?room=private', venue + '/other', venue.replace('.com/', '.com.attacker.test/')]:
        assert 'calendar_page' not in classify(source, LINK)
    assert 'calendar_page' not in classify(venue, '<p>No calendar link</p>')
    assert 'calendar_page' not in classify(venue, LINK, endpoint_only=True)


@pytest.mark.parametrize('venue', VENUES)
def test_registration_validates_existing_adapter_before_endpoint_alias(venue):
    with patch('roomquest.feed_registration.supabase_rpc', side_effect=[{'url': venue}, True]) as rpc, \
         patch('roomquest.feed_registration.fetch_publisher', side_effect=[LINK, '<p>Calendar</p>']) as fetch, \
         patch('roomquest.registered_listings.collect', return_value=[{'id': 'real-occurrence'}]) as collect:
        assert register('ticket') == {'outcome': 'discovered'}
    assert rpc.call_args.args[1]['p_endpoint'] == CALENDAR
    assert rpc.call_args.args[1]['p_type'] == 'html'
    assert collect.call_args.args[0]['feed_url'] == CALENDAR
    assert [c.args[0] for c in fetch.call_args_list] == [venue, CALENDAR]
    assert all(c.kwargs['respect_robots'] for c in fetch.call_args_list)


@pytest.mark.parametrize('reason,outcome', [('robots_denied', 'disabled'), ('publisher_http_403', 'disabled')])
def test_calendar_restriction_is_not_bypassed(reason, outcome):
    with patch('roomquest.feed_registration.supabase_rpc', side_effect=[{'url': VENUES[0]}, True]), \
         patch('roomquest.feed_registration.fetch_publisher', side_effect=[LINK, PreviewError(reason)]):
        assert register('ticket') == {'outcome': outcome}
