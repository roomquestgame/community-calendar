"""Budgeted, search-only discovery. Publisher content is never card evidence here.

The database reserves each request before network I/O and never refunds an
ambiguous attempt. No automatic retries, provider upgrades, or billing changes.
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
from urllib.parse import urlsplit, urlunsplit

import requests

TEMPLATE_VERSION = "evergreen-v1"
FAMILIES = ("playgrounds parks", "walking hiking trails", "dog parks",
            "nature centers", "museums")
BENCHMARK_LOCATIONS = ("Fairfax County, Virginia", "Arlington, Virginia",
                       "Chase City, Virginia", "South Hill, Virginia")


def canonical_url(value):
    if not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        u = urlsplit(value)
        if (u.scheme != "https" or not u.hostname or u.username or u.password
                or u.port not in (None, 443) or any(c.isspace() for c in value)
                or any(c in value for c in "<>\\") or "%" in u.netloc):
            return None
        # DNS/public-address validation still occurs immediately before fetching.
        import ipaddress
        try:
            if not ipaddress.ip_address(u.hostname).is_global:
                return None
        except ValueError:
            if "." not in u.hostname or u.hostname.endswith((".local", ".localhost", ".internal")):
                return None
        return urlunsplit(("https", u.hostname.lower(), u.path or "/", u.query, ""))
    except ValueError:
        return None


def query_identity(location, family, cycle):
    if family not in FAMILIES or not isinstance(location, str) or not location.strip():
        raise ValueError("invalid_query")
    if not isinstance(cycle, str) or not cycle:
        raise ValueError("invalid_cycle")
    return sha256(json.dumps([TEMPLATE_VERSION, location.casefold().strip(), family, cycle],
                             separators=(",", ":")).encode()).hexdigest()


def benchmark_queries():
    return [{"location": place, "family": family, "query": f"{family} {place}",
             "identity": query_identity(place, family, "benchmark-v1")}
            for place in BENCHMARK_LOCATIONS for family in FAMILIES]


def free_allowance(usage, *, reviewed_benchmark=False, reviewed_until=None):
    """Require an account-wide free plan AND a zero paid-overage limit.

    A key-specific quota or one-time remaining balance is not a billing fence.
    Unknown schemas and paid accounts fail closed; never alter account settings.
    """
    a = usage.get("account") if isinstance(usage, dict) else None
    if not isinstance(a, dict) or str(a.get("current_plan", "")).strip().lower() not in {"free", "researcher"}:
        return None
    # Owner billing screenshots, 2026-11-16: Researcher, PAYG Off,
    # requests stop at plan limit. Narrow, expiring benchmark-only evidence.
    if a.get('paygo_limit', 'missing') is None:
        from datetime import datetime, timezone
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        reviewed = reviewed_benchmark and now < datetime(2026, 11, 17, 8, 15, tzinfo=timezone.utc)
        # Only the authenticated job gateway supplies this fixed owner-evidence
        # expiry. Never extend it on each run or accept an unbounded timestamp.
        if isinstance(reviewed_until, str):
            try:
                expiry = datetime.fromisoformat(reviewed_until.replace('Z', '+00:00'))
                reviewed = reviewed or now < expiry <= now + timedelta(hours=72)
            except (ValueError, TypeError):
                pass
        if reviewed:
            a = {**a, 'paygo_limit': 0}
    if any(type(a.get(k)) not in (int, float) or not math.isfinite(a[k]) or a[k] < 0
           for k in ("plan_usage", "plan_limit", "paygo_usage", "paygo_limit")):
        return None
    if a["paygo_limit"] != 0 or a["paygo_usage"] != 0 or a["plan_limit"] > 1000:
        return None
    return max(0, int(min(950, a["plan_limit"]) - a["plan_usage"]))


def account_fence_reason(usage):
    """Diagnostic codes only; never return provider content or account details."""
    a = usage.get('account') if isinstance(usage, dict) else None
    if not isinstance(a, dict):
        return 'account_schema_unknown'
    if str(a.get('current_plan', '')).strip().lower() not in {'free', 'researcher'}:
        return 'free_plan_unconfirmed'
    if any(type(a.get(k)) not in (int, float) or not math.isfinite(a[k]) or a[k] < 0
           for k in ('plan_usage', 'plan_limit', 'paygo_usage', 'paygo_limit')):
        return 'account_limits_unconfirmed'
    if a['paygo_limit'] != 0 or a['paygo_usage'] != 0:
        return 'zero_paid_overage_unconfirmed'
    if a['plan_limit'] > 1000:
        return 'free_plan_limit_unconfirmed'
    return 'free_allowance_exhausted'


def _request(key, endpoint, payload=None):
    # Fixed provider origin; redirects are prohibited, including for credentials.
    with requests.Session() as session:
        with session.request("POST" if payload is not None else "GET",
                             "https://api.tavily.com/" + endpoint,
                             headers={"Authorization": "Bearer " + key},
                             json=payload, timeout=(3, 12), stream=True,
                             allow_redirects=False) as response:
            if response.status_code != 200:
                raise ValueError("search_http_failure")
            raw = bytearray()
            for chunk in response.iter_content(16384):
                raw.extend(chunk)
                if len(raw) > 1_000_000:
                    raise ValueError("search_response_limit")
            return json.loads(raw)


def run_search(*, key, job, database, request=None):
    """One request; reserve/reconcile are short durable database transactions.

    `job` must come from the durable planner, not a public request. The budget
    gateway also verifies its query identity and the account allowance receipt.
    """
    if not key:
        return {"status": "search_credentials_missing"}
    request = request or _request
    query = job.get("query")
    if not isinstance(query, str) or not 1 <= len(query) <= 400:
        return {"status": "invalid_query"}
    allowance = None
    reason = 'usage_request_failed'
    try:
        usage = request(key, "usage")
        allowance = free_allowance(usage, reviewed_benchmark=job.get("planner") == "benchmark",
                                   reviewed_until=job.get("billing_review_until"))
        reason = account_fence_reason(usage)
        status = "free_only_verified" if allowance is not None and allowance >= 1 else "account_free_only_blocked"
    except Exception:
        status = "account_allowance_unavailable"
    # Only a non-secret outcome and bounded allowance enter operational receipts.
    try:
        database('record_search_preflight', {'status': status, 'free_allowance': allowance})
    except Exception:
        return {'status': 'preflight_receipt_unavailable'}
    if status != 'free_only_verified':
        return {'status': status, 'reason': reason}
    admission = database("reserve_search", {"query_id": job["id"],
                                             "free_allowance": allowance})
    if not isinstance(admission, dict) or admission.get("status") != "reserved":
        return admission
    receipt = {"reservation_id": admission["reservation_id"],
               "lease_token": admission["lease_token"], "outcome": "uncertain"}
    try:
        response = request(key, "search", {
            "query": query, "topic": "general", "search_depth": "basic",
            "auto_parameters": False, "include_answer": False,
            "include_raw_content": False, "max_results": 10, "include_usage": True,
            "exclude_domains": admission.get("exclude_domains", []),
        })
        usage = response.get("usage", {}).get("credits")
        if type(usage) not in (int, float) or not math.isfinite(usage) or usage < 0:
            raise ValueError("search_usage_missing")
        receipt.update(credits=usage, provider_request_id=response.get("request_id"))
        candidates, seen = [], set()
        results = response.get("results")
        if not isinstance(results, list) or len(results) > 10:
            raise ValueError("search_results_invalid")
        for rank, item in enumerate(results, 1):
            if not isinstance(item, dict):
                continue
            url = canonical_url(item.get("url"))
            if url is None or url in seen:
                continue
            seen.add(url)
            score = item.get("score")
            candidates.append({"url": url, "rank": rank,
                               "title": str(item.get("title", ""))[:300],
                               "score": score if type(score) in (int, float) and math.isfinite(score) else None})
        receipt.update(outcome="success", candidates=candidates)
    except Exception:
        # Request may have been charged. Keep its reservation, including if the
        # response was malformed; do not retry or print provider/error content.
        pass
    try:
        return database("finish_search", receipt)
    except Exception:
        return {"status": "search_reconciliation_unavailable"}
