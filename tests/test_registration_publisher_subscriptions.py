"""Publisher-linked subscription discovery without calendar-scope broadening."""
from unittest.mock import patch
from urllib.parse import quote

import pytest

from roomquest.feed_registration import classify, register, _wrapped_ical_subscription


FARMVILLE_PAGE = 'https://www.farmvilleareachamber.org/events'
FARMVILLE_FEED = 'https://www.farmvilleareachamber.org/calendar.ics'
LCVA_PAGE = 'https://lcva.longwood.edu/events-calendar/'
LCVA_DIRECT = 'https://lcva.longwood.edu/events/month/?shortcode=c5cb6fd5&ical=1'


def google_link(feed):
    return ('https://calendar.google.com/calendar/render?cid='
            + quote(feed.replace('https://', 'webcal://'), safe=''))


def test_farmville_google_calendar_wrapper_recovers_same_host_ical():
    html = '<h1>Events</h1><a href="' + google_link(FARMVILLE_FEED) + '">Subscribe</a>'
    assert classify(FARMVILLE_PAGE, html) == {
        'p_outcome': 'discovered', 'p_endpoint': FARMVILLE_FEED, 'p_type': 'ical'}


def test_month_scoped_ics_does_not_register_as_complete_calendar():
    # Publisher observations: the LCVA calendar's month export contained only
    # three older VEVENTs, despite the listing exposing many dated entries.
    html = ('<a href="' + google_link('https://lcva.longwood.edu/?post_type=tribe_events&ical=1')
            + '">Google</a>'
            '<a href="' + LCVA_DIRECT + '">Export Events</a>')
    assert classify(LCVA_PAGE, html) == {
        'p_outcome': 'review',
        'p_reason': 'calendar_period_scope_unverified',
        'p_type': 'ical'}


def test_www_google_com_calendar_wrapper_has_same_strict_scope():
    wrapper = google_link(FARMVILLE_FEED).replace('calendar.google.com', 'www.google.com')
    assert _wrapped_ical_subscription(FARMVILLE_PAGE, wrapper) == FARMVILLE_FEED


def test_one_full_first_party_ics_wins_over_google_wrapper():
    page = 'https://publisher.example/events'
    full = 'https://publisher.example/calendar.ics'
    html = ('<a href="' + google_link('https://publisher.example/alternative.ics')
            + '">Google</a><a href="/calendar.ics">Calendar</a>')
    assert classify(page, html) == {
        'p_outcome': 'discovered', 'p_endpoint': full, 'p_type': 'ical'}


@pytest.mark.parametrize('feed', [
    'https://other.example.org/all.ics',
    'https://www.farmvilleareachamber.org/events/123?ical=1',
    'https://user:pass@www.farmvilleareachamber.org/calendar.ics',
])
def test_wrapped_urls_cannot_escape_publisher_or_choose_one_event(feed):
    assert _wrapped_ical_subscription(FARMVILLE_PAGE, google_link(feed)) is None


def test_multiple_wrapped_sources_remain_reviewable():
    first = google_link(FARMVILLE_FEED)
    second = google_link('https://www.farmvilleareachamber.org/another.ics')
    result = classify(FARMVILLE_PAGE,
                      '<a href="' + first + '">A</a><a href="' + second + '">B</a>')
    assert result['p_reason'] == 'multiple_calendar_links'


def test_filtered_page_does_not_lose_scope():
    url = FARMVILLE_PAGE + '?venue=East'
    html = '<a href="' + google_link(FARMVILLE_FEED) + '">Subscribe</a>'
    result = classify(url, html)
    assert result['p_outcome'] == 'review'
    assert result.get('p_endpoint') is None


def test_unfiltered_upcoming_events_page_follows_one_linked_calendar_page():
    url = 'https://www.farmvilleareachamber.org/upcoming-events'
    html = '<h2>Upcoming events</h2><a href="/events">All events</a>'
    assert classify(url, html) == {'calendar_page': FARMVILLE_PAGE}
    assert classify(url + '?venue=East', html)['p_outcome'] == 'review'
    assert classify(url, html.replace('/events', '/events/venue/East')) != {
        'calendar_page': FARMVILLE_PAGE}


def test_registration_handoff_follows_page_then_submits_discovered_feed():
    start = 'https://www.farmvilleareachamber.org/upcoming-events'
    first = '<h2>Upcoming events</h2><a href="/events">All events</a>'
    second = '<a href="' + google_link(FARMVILLE_FEED) + '">Subscribe</a>'
    with patch('roomquest.feed_registration.supabase_rpc',
               side_effect=[{'url': start}, True]) as rpc, \
         patch('roomquest.feed_registration.fetch_publisher',
               side_effect=[first, second]) as fetch:
        assert register('ticket') == {'outcome': 'discovered'}
    payload = rpc.call_args.args[1]
    assert payload['p_outcome'] == 'discovered'
    assert payload['p_endpoint'] == FARMVILLE_FEED
    assert payload['p_type'] == 'ical'
    assert fetch.call_count == 2
    for call in fetch.call_args_list:
        assert call.kwargs['respect_robots'] is True
