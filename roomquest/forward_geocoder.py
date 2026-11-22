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

from roomquest.preview_worker import PreviewError, supabase_rpc

ENDPOINT = "https://api.geocod.io/v2/geocode"
RPC = "community_collector_geocoder"
TIMEOUT = 8
MAX_RESPONSE = 30_000
SUPPORTED_COUNTRIES = frozenset({"US", "GB"})
GB_POSTCODE = re.compile(r"(?:GIR0AA|[A-Z]{1,2}[0-9][A-Z0-9]?[0-9][A-Z]{2})")
GB_STREET_WORDS = {
    "street": "st", "road": "rd", "avenue": "ave", "lane": "ln",
    "drive": "dr", "close": "cl", "court": "ct", "place": "pl", "terrace": "ter",
}
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


def normalize_gb_postcode(value: str) -> str:
    """Validate a full postcode's shape; never infer one from an outward code."""
    compact = re.sub(r"\s+", "", str(value or "")).upper()
    return compact[:-3] + " " + compact[-3:] if GB_POSTCODE.fullmatch(compact) else ""


def gb_address_part(value: str, *, street: bool = False) -> str:
    """Mirror the database's bounded reviewed GB street/town normalization."""
    value = str(value or "")
    if (len(value) > 180 or re.search(r"[\x00-\x1f\x7f,/<>]", value)
            or re.search(r"https?:|www\.", value, re.I)):
        return ""
    value = re.sub(r"\s+", " ", value).strip().lower()
    if len(value) < 2 or not re.search(r"[a-z]", value):
        return ""
    if street:
        value = value.replace(".", "")
        value = re.sub(r"\b(" + "|".join(GB_STREET_WORDS) + r")\b",
                       lambda match: GB_STREET_WORDS[match.group()], value)
    if (re.search(r"\b(online|virtual|zoom|unknown|tbd)\b", value)
            or re.search(r"\bp\.?o\.? box\b", value)):
        return ""
    return value


def result_address_parts(item: dict, country_code: str = "US") -> tuple[str, str, str, str]:
    """Return normalized street, city, state, and postal code separately."""
    c = item.get("address_components") or {}
    street = " ".join(str(c.get(k) or "") for k in
                      ("number", "predirectional", "street", "suffix", "postdirectional",
                       "unit_type", "unit_number"))
    city = str(c.get("city") or "")
    state = str(c.get("nation" if country_code == "GB" else "state_province") or "")
    postal = (normalize_gb_postcode(c.get("postal_code")) if country_code == "GB" else
              re.sub(r"[^0-9-]", "", str(c.get("zip") or c.get("postal_code") or "")))
    if country_code == "GB":
        return gb_address_part(street, street=True), gb_address_part(city), gb_address_part(state), postal
    return canonical(street), canonical(city), canonical(state), postal


def expected_address_parts(address: str, country_code: str = "US") -> tuple[str, str, str, str]:
    parts = [part.strip() for part in str(address or "").split(",")]
    if country_code == "GB":
        # Admin reviews an exact venue identity and supplies these three fields.
        # A free-form fourth field must not be silently dropped or become a state.
        return ((gb_address_part(parts[0], street=True), gb_address_part(parts[1]),
                 "", normalize_gb_postcode(parts[2])) if len(parts) == 3 and len(address) <= 400
                else ("", "", "", ""))
    street = canonical(parts[0] if parts else "")
    city = canonical(parts[1] if len(parts) > 1 else "")
    state_zip = parts[2] if len(parts) > 2 else ""
    state_match = re.match(r"\s*([A-Za-z]{2})(?:\s+(\d{5}(?:-\d{4})?))?\s*$", state_zip)
    state = canonical(state_match.group(1) if state_match else state_zip)
    postal = state_match.group(2) if state_match and state_match.group(2) else ""
    return street, city, state, postal


# Only a county/state centroid is too broad to represent a physical event.
# Geocodio's other documented tiers are its coordinates, not fabricated pins.
ACCEPTED_ACCURACY_TYPES = frozenset({
    "rooftop", "point", "range_interpolation", "nearest_rooftop_match",
    "intersection", "street_center", "place",
})


def _street_without_number_and_unit(value: str) -> str:
    """Compare the publisher and Geocodio street even when a suite is absent."""
    main = re.sub(r"^[0-9][a-z0-9-]*\s+", "", canonical(value))
    return re.sub(
        r"\s+(?:ste|suite|unit|apt|apartment|#)\s+[a-z0-9-]+$", "", main
    )


def _gb_address_matches(item: dict, address: str) -> bool:
    """Keep the reviewed street/town identity while retaining provider precision."""
    expected_street, expected_city, _, expected_postal = expected_address_parts(address, "GB")
    if not expected_street or not expected_city or not expected_postal:
        return False
    _, result_city, _, result_postal = result_address_parts(item, "GB")
    kind = item.get("accuracy_type")
    same_town = bool(result_city and result_city == expected_city)
    if kind in {"place", "intersection"}:
        return same_town
    if kind not in ACCEPTED_ACCURACY_TYPES:
        return False
    components = item.get("address_components") or {}
    provider_core = gb_address_part(" ".join(
        str(components.get(k) or "") for k in
        ("predirectional", "street", "suffix", "postdirectional")
    ).strip(), street=True)
    expected_core = re.sub(r"^[0-9][a-z0-9-]*\s+", "", expected_street)
    expected_core = re.sub(r"\s+(?:ste|suite|unit|apt|apartment|#)\s+[a-z0-9-]+$", "", expected_core)
    if not provider_core or provider_core != expected_core:
        return False
    # A full postcode can disambiguate a postal-town alias, never a different
    # street or venue. Street approximations can fall elsewhere on that street.
    if not same_town and result_postal != expected_postal:
        return False
    if kind in {"rooftop", "point"}:
        raw_postal = str(components.get("postal_code") or "").strip()
        if raw_postal and result_postal != expected_postal:
            return False
        number = re.match(r"^([0-9][a-z0-9-]*)\s+", expected_street)
        if number and str(components.get("number") or "").strip().lower() != number.group(1):
            return False
    return True


def address_matches(item: dict, address: str, country_code: str = "US") -> bool:
    """Trust provider-ranked coordinates while preventing wrong-state/area pins.

    Exact addresses remain valid across postal-city names. For approximate
    street matches, the city must agree, but house number/unit detail may be
    absent or interpolated. Geocodio's 'place' means an approximate city pin.
    """
    if country_code == "GB":
        return _gb_address_matches(item, address)
    if country_code != "US":
        return False
    result_street, result_city, result_state, result_postal = result_address_parts(item)
    expected_street, expected_city, expected_state, expected_postal = expected_address_parts(address)
    if not expected_street or not expected_city or not expected_state:
        return False
    if not result_state or result_state != expected_state:
        return False

    # Preserve the old exact-address path and its caller-supplied ZIP check.
    if result_street == expected_street:
        return not (expected_postal and result_postal and expected_postal != result_postal)

    kind = item.get("accuracy_type")
    if kind in {"place", "intersection"}:
        return bool(result_city and result_city == expected_city)
    if kind not in ACCEPTED_ACCURACY_TYPES:
        return False
    if not result_city or result_city != expected_city:
        return False

    # Compare the physical building street fields, not a provider's optional
    # unit fragments. Geocodio sometimes returns a unit_type without a number
    # (or vice versa); neither changes which building was geocoded.
    components = item.get("address_components") or {}
    provider_core = canonical(" ".join(
        str(components.get(k) or "") for k in
        ("predirectional", "street", "suffix", "postdirectional")
    ).strip())
    return bool(
        provider_core
        and provider_core == _street_without_number_and_unit(expected_street)
        and (kind not in {"rooftop", "point"}
             or result_street.split(" ", 1)[0] == expected_street.split(" ", 1)[0])
    )


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


def country_matches(value: str, country_code: str) -> bool:
    return (value == "GB" if country_code == "GB" else
            value in ("US", "USA") if country_code == "US" else False)


def verify(payload: dict, address: str, country_code: str = "US") -> dict | None:
    """Accept Geocodio's ranked usable point, retaining its precision label.

    We no longer require 0.9+ rooftop/point accuracy or reject the top result
    because a second, lower-ranked candidate exists. Country/state and street
    or city evidence still stop obviously misplaced coordinates. Never treat
    county/state centroids as a local venue.
    """
    try:
        rows = payload.get("results")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 2:
            return None
        first = rows[0]
        coordinates(first)
        score = float(first.get("accuracy"))
        if (not math.isfinite(score) or not 0 <= score <= 1
                or first.get("accuracy_type") not in ACCEPTED_ACCURACY_TYPES
                or not country_matches(first.get("address_components", {}).get("country"), country_code)
                or not address_matches(first, address, country_code)):
            return None

        # Geocodio orders these by confidence. Keep the first valid coordinate,
        # not a fabricated midpoint or a different, lower-ranked address.
        fields = {"address_components", "location", "accuracy", "accuracy_type",
                  "formatted_address", "source", "stable_address_key", "match_type"}
        return {"results": [{k: v for k, v in first.items() if k in fields}]}
    except (TypeError, ValueError, AttributeError, GeocodeFailure, OverflowError):
        return None


def reservation_matches(reservation: dict, address: str, country_code: str) -> bool:
    """GB needs an echoed, exact query/country binding; legacy US remains valid."""
    if (not isinstance(reservation, dict) or not isinstance(country_code, str)
            or country_code not in SUPPORTED_COUNTRIES):
        return False
    if country_code == "GB" or "country_code" in reservation or "query_text" in reservation:
        return (reservation.get("country_code") == country_code
                and reservation.get("query_text") == address)
    return True


def geocode(address: str, key: str, *, reservation: dict, country_code: str = "US",
            opener=None) -> dict | None:
    """A fresh SQL reservation is mandatory; never resend on a network failure."""
    try:
        valid = datetime.fromisoformat(str(reservation["valid_until"]).replace("Z", "+00:00"))
        if (not reservation_matches(reservation, address, country_code)
                or not reservation.get("allowed") or not reservation.get("request_id") or (
                valid - datetime.now(timezone.utc)).total_seconds() < TIMEOUT + 1):
            raise GeocodeFailure("invalid_reservation")
    except (KeyError, ValueError, TypeError):
        raise GeocodeFailure("invalid_reservation") from None
    if not key:
        raise GeocodeFailure("provider_auth")
    query = address
    if country_code == "GB":
        street, city, _, postal = expected_address_parts(address, country_code)
        if not street or not city or not postal:
            raise GeocodeFailure("invalid_request")
        parts = address.split(",")
        query = ",".join((parts[0].strip(), parts[1].strip(), postal))
    request = Request(ENDPOINT + "?" + urlencode({
        "q": query, "country": "GB" if country_code == "GB" else "USA", "limit": 2}),
                      headers={"Authorization": "Bearer " + key,
                               "User-Agent": "RoomQuest-Forward-Geocoder/1.0",
                               "Accept": "application/json"})
    try:
        with (opener or build_opener(NoRedirects()).open)(request, timeout=TIMEOUT) as response:
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise GeocodeFailure("invalid_response")
            return verify(json.loads(raw), address, country_code)
    except HTTPError as exc:
        reason = ("rate_limited" if exc.code == 429 else
                  ("provider_country_access" if country_code == "GB" and exc.code == 403 else "provider_auth")
                  if exc.code in (401, 403) else
                  "ambiguous" if exc.code in (400, 422) else "provider_error")
        raise GeocodeFailure(reason) from None
    except (URLError, TimeoutError, OSError):
        raise GeocodeFailure("provider_error") from None
    except (ValueError, UnicodeError):
        raise GeocodeFailure("invalid_response") from None


def rpc(action: str, payload: dict | None = None):
    try:
        if action == "claim":
            result = supabase_rpc("community_collector_geocoder_claim_v2",
                                  {"p_limit": (payload or {}).get("limit", 1)},
                                  timeout=12)
        else:
            result = supabase_rpc(RPC, {"p_action": action, "p_payload": payload or {}}, timeout=12)
        print("geocoder_rpc_ok", action)
        return result
    except Exception as exc:
        # Submit failures get one bounded diagnostic from run_batch, where the
        # already-returned match is available. Never print RPC exception text.
        if action != "submit":
            print("geocoder_rpc_failed", action, type(exc).__name__)
        raise


def _submit_failure_diagnostic(identity: dict, address: str, match: dict,
                               error: Exception) -> dict:
    """Report only fixed validation flags and well-formed queue identifiers."""
    rows = match.get("results") if isinstance(match, dict) else None
    rows = rows if isinstance(rows, list) else []
    first = rows[0] if rows and isinstance(rows[0], dict) else {}
    components = first.get("address_components")
    components = components if isinstance(components, dict) else {}
    country_code = identity.get("country_code", "US")
    actual_street, actual_city, actual_state, actual_postal = result_address_parts(
        {"address_components": components}, country_code)
    expected_street, expected_city, expected_state, expected_postal = expected_address_parts(address, country_code)
    try:
        score = float(first.get("accuracy") or 0)
        score_valid = math.isfinite(score) and 0 <= score <= 1
    except (TypeError, ValueError, OverflowError):
        score_valid = False

    def identifier(name: str, pattern: str):
        value = identity.get(name)
        return value if isinstance(value, str) and re.fullmatch(pattern, value) else None

    def empty_component(name: str) -> bool:
        value = components.get(name)
        return isinstance(value, str) and not value.strip()

    error_type = next((kind.__name__ for kind in
                       (PreviewError, HTTPError, URLError, TimeoutError, ConnectionError)
                       if isinstance(error, kind)), "unknown")
    return {
        "event": "geocoder_submit_failed",
        "venue_key": identifier("venue_key", r"[0-9a-f]{32}"),
        "request_id": identifier("request_id", r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"),
        "error_type": error_type,
        "result_count": min(len(rows), 3),
        "city_present": bool(actual_city),
        "city_exact_match": bool(actual_city and expected_city and actual_city == expected_city),
        "city_space_insensitive_match": bool(actual_city and expected_city and
                                             actual_city.replace(" ", "") == expected_city.replace(" ", "")),
        "street_match": bool(actual_street and expected_street and actual_street == expected_street),
        "state_match": bool(actual_state and expected_state and actual_state == expected_state),
        "postal_match": bool(actual_postal and expected_postal and actual_postal == expected_postal),
        "empty_predirectional_component": empty_component("predirectional"),
        "empty_postdirectional_component": empty_component("postdirectional"),
        "score_valid": score_valid,
        "accuracy_type_valid": first.get("accuracy_type") in ACCEPTED_ACCURACY_TYPES,
        "country_valid": country_matches(components.get("country"), country_code),
    }


def valid_claim(claim: dict) -> bool:
    """Only the explicit v2 contract can authorize this country's request."""
    if not isinstance(claim, dict):
        return False
    if not all(isinstance(claim.get(k), str) and claim[k].strip()
               for k in ("venue_key", "lease_id", "query_text", "country_code")):
        return False
    country_code = claim["country_code"]
    if country_code not in SUPPORTED_COUNTRIES:
        return False
    street, city, state, postal = expected_address_parts(claim["query_text"], country_code)
    if country_code == "GB":
        return bool(street and city and postal)
    # Do not reinterpret a postcode-bearing GB query as a legacy US address.
    return bool(street and city and re.fullmatch(r"[a-z]{2}", state))


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
        if not valid_claim(claim):
            # No reservation or provider request; leave this malformed lease for
            # operational review rather than guessing a country or address.
            stats["errors"] += 1
            stats["stop_reason"] = "invalid_claim"
            break
        country_code = claim["country_code"]
        identity = {k: claim[k] for k in ("venue_key", "lease_id", "country_code")}
        if country_code == "GB":
            identity["query_text"] = claim["query_text"]
        reserved = database("reserve", identity)
        if not reserved.get("allowed"):
            stats["quota_exhausted"] = reserved.get("reason") == "quota_exhausted"
            stats["stop_reason"] = reserved.get("reason", "paused")
            break
        if not reservation_matches(reserved, claim["query_text"], country_code):
            stats["errors"] += 1
            stats["stop_reason"] = "invalid_reservation"
            break
        stats["attempted"] += 1
        identity["request_id"] = reserved["request_id"]
        try:
            match = provider(claim["query_text"], key, reservation=reserved,
                             country_code=country_code)
        except GeocodeFailure as exc:
            reason = str(exc)
            if reason not in {"provider_error", "provider_auth", "provider_country_access", "rate_limited",
                              "invalid_response", "ambiguous"}:
                reason = "provider_error"
            database("fail", {**identity, "reason": reason})
            stats["ambiguous" if reason == "ambiguous" else "errors"] += 1
            if reason in {"provider_auth", "provider_country_access", "rate_limited"}:
                stats["stop_reason"] = reason
                break
            continue
        if match is None:
            database("fail", {**identity, "reason": "ambiguous"})
            stats["ambiguous"] += 1
        else:
            try:
                result = database("submit", {**identity, "response": match})
            except (PreviewError, URLError, TimeoutError, ConnectionError) as exc:
                # The database may have committed despite a transport failure.
                # Keep the lease/outcome and consumed reservation intact: never
                # replay submit, call fail, or repeat this provider request here.
                stats["errors"] += 1
                print(json.dumps(_submit_failure_diagnostic(
                    identity, claim["query_text"], match, exc), sort_keys=True,
                    separators=(",", ":")))
                continue
            stats["resolved"] += 1
            stats["events_updated"] += int(result.get("events_updated", 0))
    return stats
