"""RoomQuest Forward Geocoder: one reserved request per unique physical address.

No Google fallback, provider batching, field appends, secret logging, or automatic
HTTP retries. Transient errors use the durable SQL queue's bounded retry/backoff.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
import re
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from roomquest.preview_worker import supabase_rpc

ENDPOINT = "https://api.geocod.io/v2/geocode"
RPC = "community_collector_geocoder"
TIMEOUT = 8
MAX_RESPONSE = 30_000
WORDS = {
    "street": "st", "road": "rd", "avenue": "ave", "boulevard": "blvd",
    "drive": "dr", "lane": "ln", "court": "ct", "parkway": "pkwy",
    "place": "pl", "circle": "cir", "highway": "hwy", "terrace": "ter",
    "trail": "trl", "north": "n", "south": "s", "east": "e", "west": "w",
}


class GeocodeFailure(Exception):
    """Only fixed reason codes may leave the provider boundary."""


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise GeocodeFailure("provider_error")


def canonical(value: str) -> str:
    value = value.lower().replace(".", "")
    value = re.sub(r"\b(" + "|".join(WORDS) + r")\b",
                   lambda m: WORDS[m.group()], value)
    return ",".join(re.sub(r"\s+", " ", x.strip()) for x in value.split(","))


def result_address(item: dict) -> str:
    c = item.get("address_components") or {}
    street = " ".join(str(c.get(k) or "") for k in
                      ("number", "predirectional", "street", "suffix", "postdirectional"))
    return canonical(street + "," + str(c.get("city") or "") +
                     "," + str(c.get("state_province") or ""))


def coordinates(item: dict) -> tuple[float, float]:
    loc = item.get("location") or {}
    lat, lng = loc.get("lat"), loc.get("lng")
    if (type(lat) not in (int, float) or type(lng) not in (int, float)
            or not math.isfinite(lat) or not math.isfinite(lng)
            or not -90 <= lat <= 90 or not -180 <= lng <= 180):
        raise GeocodeFailure("invalid_response")
    return float(lat), float(lng)


def distance_m(a: dict, b: dict) -> float:
    lat1, lng1 = map(math.radians, coordinates(a))
    lat2, lng2 = map(math.radians, coordinates(b))
    h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lng2-lng1)/2)**2
    return 12_742_000 * math.asin(min(1, math.sqrt(h)))


def verify(payload: dict, address: str) -> dict | None:
    """Compare exact street/city/state, not substrings or publisher geography."""
    try:
        rows = payload.get("results")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 2:
            return None
        first = rows[0]
        coordinates(first)
        score = float(first.get("accuracy") or 0)
        if (not math.isfinite(score) or not 0.9 <= score <= 1
                or first.get("accuracy_type") not in {"rooftop", "point"}
                or first.get("address_components", {}).get("country") not in {"US", "USA"}
                or result_address(first) != canonical(address)):
            return None
        for other in rows[1:]:
            if float(other.get("accuracy") or 0) > score - 0.2:
                if result_address(other) != canonical(address) or distance_m(first, other) > 50:
                    return None
        # Only provider evidence needed for verification is retained.
        fields = {"address_components", "location", "accuracy", "accuracy_type",
                  "formatted_address", "source", "stable_address_key", "match_type"}
        return {"results": [{k: v for k, v in row.items() if k in fields} for row in rows]}
    except (TypeError, ValueError, AttributeError, GeocodeFailure, OverflowError):
        return None


def geocode(address: str, key: str, *, reservation: dict, opener=None) -> dict | None:
    """A fresh SQL reservation is mandatory; never resend on a network failure."""
    try:
        valid = datetime.fromisoformat(str(reservation["valid_until"]).replace("Z", "+00:00"))
        if not reservation.get("allowed") or not reservation.get("request_id") or (
                valid - datetime.now(timezone.utc)).total_seconds() < TIMEOUT + 1:
            raise GeocodeFailure("invalid_reservation")
    except (KeyError, ValueError, TypeError):
        raise GeocodeFailure("invalid_reservation") from None
    if not key:
        raise GeocodeFailure("provider_auth")
    request = Request(ENDPOINT + "?" + urlencode({"q": address, "country": "USA", "limit": 2}),
                      headers={"Authorization": "Bearer " + key,
                               "User-Agent": "RoomQuest-Forward-Geocoder/1.0",
                               "Accept": "application/json"})
    try:
        with (opener or build_opener(NoRedirects()).open)(request, timeout=TIMEOUT) as response:
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise GeocodeFailure("invalid_response")
            return verify(json.loads(raw), address)
    except HTTPError as exc:
        reason = ("rate_limited" if exc.code == 429 else
                  "provider_auth" if exc.code in (401, 403) else
                  "ambiguous" if exc.code in (400, 422) else "provider_error")
        raise GeocodeFailure(reason) from None
    except (URLError, TimeoutError, OSError):
        raise GeocodeFailure("provider_error") from None
    except (ValueError, UnicodeError):
        raise GeocodeFailure("invalid_response") from None


def rpc(action: str, payload: dict | None = None):
    return supabase_rpc(RPC, {"p_action": action, "p_payload": payload or {}}, timeout=12)


def run_batch(*, max_requests: int = 10, deadline_seconds: int = 45,
              database=None, provider=None, clock=None) -> dict:
    """Claim one at a time and leave 20 seconds for reserve/provider/result I/O."""
    database, provider, clock = database or rpc, provider or geocode, clock or monotonic
    stats = dict(attempted=0, resolved=0, ambiguous=0, errors=0,
                 events_updated=0, quota_exhausted=False, stop_reason="batch_complete")
    key = os.environ.get("GEOCODIO_API_KEY", "")
    if (os.environ.get("FORWARD_GEOCODER_ENABLED") != "true"
            or os.environ.get("VERCEL_ENV") != "production" or not key):
        return {**stats, "stop_reason": "disabled"}
    deadline = clock() + min(45, max(1, deadline_seconds))
    for _ in range(min(10, max(1, max_requests))):
        if clock() + 20 > deadline:
            stats["stop_reason"] = "deadline"
            break
        claims = database("claim", {"limit": 1}) or []
        if not claims:
            stats["stop_reason"] = "queue_empty_or_paused"
            break
        claim = claims[0]
        identity = {k: claim[k] for k in ("venue_key", "lease_id")}
        reserved = database("reserve", identity)
        if not reserved.get("allowed"):
            stats["quota_exhausted"] = reserved.get("reason") == "quota_exhausted"
            stats["stop_reason"] = reserved.get("reason", "paused")
            break
        stats["attempted"] += 1
        identity["request_id"] = reserved["request_id"]
        try:
            match = provider(claim["query_text"], key, reservation=reserved)
        except GeocodeFailure as exc:
            reason = str(exc)
            if reason not in {"provider_error", "provider_auth", "rate_limited",
                              "invalid_response", "ambiguous"}:
                reason = "provider_error"
            database("fail", {**identity, "reason": reason})
            stats["ambiguous" if reason == "ambiguous" else "errors"] += 1
            if reason in {"provider_auth", "rate_limited"}:
                stats["stop_reason"] = reason
                break
            continue
        if match is None:
            database("fail", {**identity, "reason": "ambiguous"})
            stats["ambiguous"] += 1
        else:
            result = database("submit", {**identity, "response": match})
            stats["resolved"] += 1
            stats["events_updated"] += int(result.get("events_updated", 0))
    return stats
