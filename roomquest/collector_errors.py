"""Safe diagnostic metadata for source failures versus collector failures.

This classification never turns an unsuccessful collection into a success.
Source dispositions and retry budgets remain in the database; only HTML uses
the source_error finish outcome to avoid cooling an unrelated publisher's lane.
"""
import re

_WORKER_ERRORS = frozenset({
    "database_unavailable", "staging_deadline", "collector_not_configured",
    "unsupported_collector_rpc",
})
_TRANSIENT_ERRORS = frozenset({
    "dns_unavailable", "robots_unavailable", "source_network_error",
    "source_fetch_deadline", "collection_deadline", "publisher_rate_limited",
})
_ACCESS_ERRORS = frozenset({
    "robots_denied", "invalid_source_url", "invalid_redirect_url", "non_public_dns",
    "redirect_blocked", "redirect_host_not_approved", "redirect_missing_location",
    "too_many_redirects", "publisher_wait_requires_review",
})
_CONFIGURATION_ERRORS = frozenset({
    "adapter_requires_configuration", "source_timezone_required", "park_code_missing",
    "park_catalog_incomplete", "unverified_park_calendar_identifier",
})


def safe_error_code(value):
    text = str(value)
    return text if re.fullmatch(r"[a-z][a-z0-9_]{2,119}", text) else "source_parse_error"


def failure_details(error_code, *, expected_source_error, phase):
    """Classify only bounded codes; raw exceptions and payloads never escape."""
    code = safe_error_code(error_code)
    scope, kind = "source", "parse"
    if code in _WORKER_ERRORS:
        scope, kind = "worker", "infrastructure"
    elif phase != "collection" or not expected_source_error:
        scope, kind = "worker", "unexpected"
    elif code in _TRANSIENT_ERRORS:
        kind = "transient"
    elif code in _ACCESS_ERRORS:
        kind = "access"
    elif code in _CONFIGURATION_ERRORS or code.startswith("unregistered_"):
        kind = "configuration"
    elif match := re.fullmatch(r"publisher_http_(\d{3})", code):
        status = int(match.group(1))
        kind = "transient" if status in (408, 425, 429) or 500 <= status <= 599 else "access"
    return {"failure_scope": scope, "error_kind": kind, "error_code": code}
