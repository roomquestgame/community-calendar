"""Recognition signals must never auto-admit publisher calendars."""
from roomquest.calendar_profile_signals import unsupported_calendar_profile
from roomquest.registration_auto_defer import auto_defer_nonactionable, MONTH_SECONDS


def test_embedded_profiles_require_strong_two_part_signals():
    assert unsupported_calendar_profile('''<html><script src="https://elfsightcdn.com/platform.js"></script>
      <div class="elfsight-app-example"></div></html>''') == 'elfsight_adapter_needed'
    assert unsupported_calendar_profile('''<html><script src="https://system.spektrix.com/example/api/v3/events"></script></html>''') == 'spektrix_adapter_needed'
    assert unsupported_calendar_profile('''<html><div data-tockify-calendar="spirited"></div><script src="https://public.tockify.com/browser/embed.js"></script></html>''') == 'tockify_adapter_needed'
    assert unsupported_calendar_profile('''<html><script>new FullCalendar.Calendar(el, {events: '/events-feed'})</script></html>''') == 'fullcalendar_adapter_needed'


def test_marketing_mentions_and_json_do_not_create_adapter_claims():
    assert unsupported_calendar_profile('<html><p>Spektrix ticketing partner</p></html>') is None
    assert unsupported_calendar_profile('<html><script src="/fullcalendar.js"></script></html>') is None
    assert unsupported_calendar_profile('<html><div class="elfsight-app-example"></div></html>') is None
    assert unsupported_calendar_profile('{"events":[]}') is None


def test_footer_signals_in_large_documents():
    html = '<html>' + 'x' * 1_100_000 + '<script src="https://elfsightcdn.com/platform.js"></script><div class="elfsight-app-example"></div></html>'
    assert unsupported_calendar_profile(html) == 'elfsight_adapter_needed'


def test_new_signals_stay_on_existing_monthly_auto_defer_path():
    for reason in ('elfsight_adapter_needed', 'spektrix_adapter_needed', 'fullcalendar_adapter_needed', 'tockify_adapter_needed'):
        assert auto_defer_nonactionable({'p_outcome': 'review', 'p_reason': reason, 'p_type': 'html'}) == {
            'p_outcome': 'retry', 'p_reason': reason, 'p_retry_seconds': MONTH_SECONDS,
        }
