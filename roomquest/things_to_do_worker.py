"""One bounded, privately staged evergreen page per autonomous pilot tick.

The database owns the inventory, lease, admission checks and spending limits.
This module never writes events, publishes cards, or accepts a URL from HTTP.
"""
from __future__ import annotations

from hashlib import sha256
import os
import re
from time import monotonic
from uuid import UUID
from urllib.parse import urlsplit
from contextlib import nullcontext

from roomquest.collector_errors import failure_details, safe_error_code
from roomquest.preview_worker import PreviewError, fetch_publisher, supabase_rpc
from roomquest.publisher_pacing import capture_publisher_pacing
from roomquest.activity_request_admission import admitted_requests

RPC = "community_collector_things_to_do"
PARKS = frozenset({
    "potomac-overlook-regional-park", "upton-hill-regional-park",
    "meadowlark-botanical-gardens",
})
HOST = "www.novaparks.com"
PARENT_EVIDENCE_PARK = "meadowlark-botanical-gardens"
PARENT_EVIDENCE_URL = "https://" + HOST + "/parks/" + PARENT_EVIDENCE_PARK
MAX_RECORDS = 40
MAX_CLAIM_SECONDS = 1.5
IDLE_STATUSES = frozenset({
    "busy", "cooldown", "paused_load", "paused_telemetry", "publisher_hold",
    "budget_exhausted", "expired", "disabled", "idle",
})


def _rpc(action, payload):
    return supabase_rpc(RPC, {"p_action": action, "p_payload": payload}, timeout=4)


def _valid_claim(claim):
    if not isinstance(claim, dict) or claim.get("status") != "claimed":
        return False
    try:
        UUID(claim["job_id"])
        UUID(claim["lease_token"])
    except (KeyError, ValueError, TypeError, AttributeError):
        return False
    if claim.get('policy_version') == 'evergreen-v1':
        scope = claim.get('scope')
        if not isinstance(scope, dict) or scope.get('source_key') != claim.get('source_key'):
            return False
        if scope.get('parser') == 'general':
            from roomquest.things_to_do_extract import in_scope
            return (bool(re.fullmatch(r'web:[a-f0-9]{64}', claim.get('source_key', '')))
                    and all(isinstance(scope.get(k), str) and scope[k].strip() for k in ('city', 'state'))
                    and in_scope(claim.get('page_url', ''), scope))
        if scope.get('parser') != 'nova':
            return False
    key = claim.get("source_key")
    if key not in PARKS:
        return False
    url = claim.get("page_url")
    if not isinstance(url, str) or not (
            re.fullmatch(r"https://www\.novaparks\.com/parks/" + re.escape(key)
                         + r"/things-to-do(?:/[a-z0-9-]+)?", url)
            or key == PARENT_EVIDENCE_PARK and url == PARENT_EVIDENCE_URL):
        return False
    context = claim.get("park_context")
    return (isinstance(context, dict) and context.get("park_slug") == key
            and all(isinstance(context.get(k), str) and context[k].strip()
                    for k in ("park_name", "city", "state", "location_text",
                              "location_source_url")))


def _fetch(url, *, deadline_at):
    # Redirects are disabled for this tiny pilot. A new target is a separately
    # admitted page; it cannot expand one budgeted page into several requests.
    return fetch_publisher(url, "text/html", respect_robots=True,
                           allowed_hosts=(HOST,), deadline_at=deadline_at,
                           follow_redirects=False)


def _finish(database, claim, outcome, *, pacing=None, activities=None, links=None,
            content_hash=None, error_code=None):
    pacing = pacing or {}
    payload = {
        "job_id": claim["job_id"], "lease_token": claim["lease_token"],
        "status": outcome, "content_hash": content_hash,
        "activities": activities or [], "discovered_urls": links or [],
        "error_code": error_code,
        "publisher_crawl_delay_seconds": pacing.get("crawl_delay_seconds", 0),
        "publisher_retry_after_seconds": pacing.get("retry_after_seconds", 0),
        "publisher_wait_unbounded": pacing.get("wait_unbounded", False),
    }
    try:
        result = database("finish", payload)
    except Exception:
        # The durable lease expires; a later scheduled tick may retry the page.
        # Never refetch or retry writes inside this invocation.
        return {"status": "finish_unavailable", "job_id": claim["job_id"]}
    if isinstance(result, dict) and result.get("status") == "lease_expired":
        return {"status": "lease_expired", "job_id": claim["job_id"]}
    if (not isinstance(result, dict) or result.get("status") != "finished"
            or result.get("outcome") not in {"success", "retry", "held", "paused", "lease_expired"}):
        return {"status": "finish_unavailable", "job_id": claim["job_id"]}
    response = {"status": "finished", "outcome": result["outcome"],
                "job_id": claim["job_id"]}
    for key in ("accepted", "inserted", "updated", "unchanged", "skipped", "enqueued"):
        value = result.get(key)
        if type(value) is int and 0 <= value <= MAX_RECORDS:
            response[key] = value
    if error_code and result["outcome"] == outcome:
        response["error_code"] = error_code
    return response


def run_batch(*, database=None, fetch=None, parse=None, discover=None, clock=None, request_database=None):
    """Claim/fetch/finish once. Injected dependencies support offline checks."""
    if database is None and os.environ.get("VERCEL_ENV") != "production":
        return {"status": "disabled_environment"}
    database = database or _rpc
    supplied_fetch = fetch
    fetch = fetch or _fetch
    clock = clock or monotonic
    started = clock()
    deadline = started + 45
    try:
        claim = database("claim", {})
    except Exception:
        return {"status": "paused_telemetry"}
    elapsed = clock() - started
    if isinstance(claim, dict) and claim.get("status") in IDLE_STATUSES:
        return {"status": claim["status"]}
    if not _valid_claim(claim):
        # A malformed admission is not permission to fetch. Its lease, if any,
        # is recovered server-side; never echo the response or its token.
        return {"status": "invalid_claim"}
    if elapsed > MAX_CLAIM_SECONDS:
        return _finish(database, claim, "paused", error_code="slow_database_admission")

    autonomous = claim.get('policy_version') == 'evergreen-v1'
    context = claim['park_context']
    if autonomous and claim['scope']['parser'] == 'general':
        from roomquest.things_to_do_extract import parse_page, discover_links
        parse = parse or parse_page
        discover = discover or discover_links
        context = claim['scope']
        if supplied_fetch is None:
            def fetch(url, *, deadline_at):
                return fetch_publisher(url, 'text/html', respect_robots=True,
                                       allowed_hosts=(urlsplit(claim['page_url']).hostname,),
                                       follow_redirects=False, deadline_at=deadline_at)
    def reserve(kind, url):
        payload = {'job_id': claim['job_id'], 'lease_token': claim['lease_token'],
                   'kind': kind, 'url': url}
        if request_database is not None:
            return request_database('reserve_publisher', payload)
        return supabase_rpc('community_collector_activity_discovery',
                            {'p_action': 'reserve_publisher', 'p_payload': payload}, timeout=4)

    if parse is None or discover is None:
        from roomquest.things_to_do_nova import parse_page, discover_links
        parse = parse or parse_page
        discover = discover or discover_links
    with capture_publisher_pacing() as pacing, (admitted_requests(reserve) if autonomous else nullcontext()):
        try:
            raw = fetch(claim["page_url"], deadline_at=deadline)
            if not isinstance(raw, str) or not raw or len(raw.encode("utf-8")) > 3_000_000:
                raise PreviewError("invalid_things_to_do_page")
            activities = parse(raw, claim["page_url"], context)
            links = discover(raw, claim["page_url"], context)
            if autonomous and not activities and not links:
                raise PreviewError('unusable_activity_page')
            if (not isinstance(activities, list) or len(activities) > MAX_RECORDS
                    or any(not isinstance(x, dict) for x in activities)
                    or not isinstance(links, list) or len(links) > MAX_RECORDS
                    or any(not isinstance(x, str) for x in links)):
                raise PreviewError("things_to_do_page_limit")
            if clock() >= deadline:
                raise PreviewError("collection_deadline")
            if pacing["wait_unbounded"]:
                raise PreviewError("publisher_wait_requires_review")
        except (PreviewError, ValueError) as exc:
            code = safe_error_code(exc)
            details = failure_details(code, expected_source_error=True, phase="collection")
            outcome = "retry" if details["error_kind"] == "transient" else "held"
            if code == 'activity_request_not_admitted':
                outcome = 'paused'
            if details["error_kind"] == "pacing":
                outcome = "paused"
            return _finish(database, claim, outcome, pacing=pacing, error_code=code)
        except Exception:
            return _finish(database, claim, "held", pacing=pacing,
                           error_code="things_to_do_parser_unexpected")
        return _finish(database, claim, "success", pacing=pacing,
                       activities=activities, links=links,
                       content_hash=sha256(raw.encode("utf-8")).hexdigest())
