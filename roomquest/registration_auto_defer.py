"""Automatic non-actionable registration outcomes.

A missing reusable calendar or currently empty event collection is not an
ambiguous publisher decision. Keep the canonical URL eligible for a bounded
future registration probe, instead of filling the human review queue.

This never changes access-denial, source-scope, conflicting identity, rights,
or caller-verified publication decisions. Existing publisher transport still
rechecks robots, redirect, pacing and HTTP permissions on every future probe.
"""

MONTH_SECONDS = 30 * 24 * 60 * 60
AUTO_DEFER_REASONS = frozenset({
    "html_adapter_needed",
    "xml_adapter_needed",
    "no_reusable_calendar",
    "spektrix_adapter_needed",
    "fullcalendar_adapter_needed",
    "elfsight_adapter_needed",
    "tockify_adapter_needed",
    "venuepilot_adapter_needed",
    "webtrac_adapter_needed",
    "ticketweb_linked_events_adapter_needed",
    "wix_events_adapter_needed",
    "wix_custom_page_adapter_needed",
    "wordpress_calendar_adapter_needed",
    "the_events_calendar_adapter_needed",
    "events_manager_adapter_needed",
    "event_organiser_adapter_needed",
    "mec_adapter_needed",
    "eventon_adapter_needed",
    "eventon_nonce_unavailable",
    "wp_event_manager_adapter_needed",
    "ai1ec_adapter_needed",
    "wordpress_legacy_json_adapter_needed",
    "no_extractable_events",
})


def auto_defer_nonactionable(result):
    """Convert only content absence/unsupported-format review to future retry."""
    if not isinstance(result, dict):
        return result
    if (result.get("p_outcome") != "review"
            or result.get("p_reason") not in AUTO_DEFER_REASONS):
        return result
    return {
        "p_outcome": "retry",
        "p_reason": result["p_reason"],
        "p_retry_seconds": MONTH_SECONDS,
    }
