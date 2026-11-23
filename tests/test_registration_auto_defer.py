"""Decision tests: review queue is only for actionable ambiguity/policy."""
from roomquest.registration_auto_defer import auto_defer_nonactionable, MONTH_SECONDS
import pytest


@pytest.mark.parametrize("reason", [
    "no_reusable_calendar", "html_adapter_needed",
    "no_extractable_events", "xml_adapter_needed",
])
def test_ordinary_missing_calendar_is_automatically_deferred(reason):
    result = auto_defer_nonactionable({
        "p_outcome": "review", "p_reason": reason, "p_type": "html"})
    assert result == {
        "p_outcome": "retry", "p_reason": reason,
        "p_retry_seconds": MONTH_SECONDS,
    }


@pytest.mark.parametrize("reason", [
    "robots_denied", "robots_unavailable", "publisher_http_403",
    "conflicting_jsonld_reference", "html_calendar_rockhouse_scope_unverified",
    "calendar_filter_unverified", "multiple_calendar_links",
    "single_event_page", "publisher_wait_requires_review",
])
def test_access_and_identity_are_never_automatically_overridden(reason):
    original = {"p_outcome": "review", "p_reason": reason}
    assert auto_defer_nonactionable(original) is original


@pytest.mark.parametrize("state", ["verified", "discovered", "disabled", "retry"])
def test_already_decided_outcomes_never_change(state):
    original = {"p_outcome": state, "p_reason": "no_reusable_calendar"}
    assert auto_defer_nonactionable(original) is original
