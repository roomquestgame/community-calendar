"""Publisher-linked historical WordPress subscriptions must remain real ICS."""
from roomquest.feed_registration import classify
from roomquest.venue_calendar_locator import _feed_type
from roomquest.wordpress_capabilities import publisher_linked_ical_subscription

CAL = 'https://events.example.org/events/'
TIMELY = ('https://events.example.org/?plugin=all-in-one-event-calendar'
          '&controller=ai1ec_exporter_controller&action=export_events&no_html=true')
SIMPLE = 'https://events.example.org/events/ical-feed'


def test_linked_native_and_legacy_export_urls_are_recognized():
    for url in (TIMELY,SIMPLE):
        assert publisher_linked_ical_subscription(url)
        assert _feed_type(url, {}, 'Calendar subscription') == 'ical'
        result = classify(CAL, '<html><main><h1>Events</h1>'
                          '<a href="' + url + '">Subscribe to calendar</a>'
                          '</main></html>')
        assert result == {'p_outcome':'discovered','p_endpoint':url,'p_type':'ical'}


def test_legacy_export_identity_requires_exact_publisher_query():
    for url in (
        'https://events.example.org/?plugin=all-in-one-event-calendar'
        '&controller=ai1ec_exporter_controller&action=export_events'
        '&ai1ec_cat_ids=4',
        'https://events.example.org/?plugin=all-in-one-event-calendar'
        '&controller=ai1ec_exporter_controller&action=export_events'
        '&ai1ec_post_ids=22',
        'https://events.example.org/?plugin=all-in-one-event-calendar'
        '&controller=ai1ec_exporter_controller&action=export_event',
        'https://events.example.org/event/matinee/ical-feed',
        'https://events.example.org/events/ical-feed?event_id=1',
        'https://events.example.org/events/feed',
        'http://events.example.org/events/ical-feed',
    ):
        assert not publisher_linked_ical_subscription(url)


def test_no_unlinked_or_non_ics_promotion():
    assert classify(CAL,'<main><h1>Events</h1><p>Timely plugin installed</p></main>')['p_outcome']=='review'
    # Even a real exporter URL must prove an actual VCALENDAR before admission.
    assert classify(TIMELY,'<html>Not a calendar</html>', endpoint_only=True)['p_outcome']=='review'
