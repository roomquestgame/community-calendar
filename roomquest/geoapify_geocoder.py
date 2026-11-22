"""Country-bound Geoapify lookups for reviewed UK venue addresses.

The existing database owns request budgets, leases, backoff and saved results.
This adapter makes exactly one reserved request and retains Geoapify's native
precision and attribution. It never labels a Geoapify result as Geocodio.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener

from roomquest.forward_geocoder import (
    GeocodeFailure, MAX_ERROR_RESPONSE, MAX_RESPONSE, NoRedirects, TIMEOUT,
    expected_address_parts, gb_address_part, normalize_gb_postcode,
    reservation_matches, sanitize_diagnostic,
)

PROVIDER = "geoapify"
ENDPOINT = "https://api.geoapify.com/v1/geocode/search"
ACCEPTED_RESULT_TYPES = frozenset({"building", "amenity", "street"})
MIN_CONFIDENCE = 0.8
MATCH_TYPES = frozenset({"full_match", "inner_part", "match_by_building", "match_by_street"})
TEXT_LIMITS = {
    "country": 100, "country_code": 2, "state": 180, "county": 180,
    "city": 180, "town": 180, "village": 180, "municipality": 180,
    "street": 180, "housenumber": 40, "postcode": 12, "name": 200,
    "formatted": 600, "address_line1": 300, "address_line2": 300,
    "result_type": 20,
}
RANK_FIELDS = ("confidence", "confidence_city_level", "confidence_street_level",
               "confidence_building_level")
DATASOURCE_LIMITS = {"sourcename": 100, "attribution": 400, "license": 200, "url": 500}


def _text(value, maximum: int) -> str | None:
    if (not isinstance(value, str) or not value.strip() or len(value) > maximum
            or re.search(r"[\x00-\x1f\x7f]", value)):
        return None
    return value


def _score(value) -> bool:
    return type(value) in (int, float) and 0 <= value <= 1 and math.isfinite(value)


def valid_coordinates(item: dict) -> bool:
    lat, lon = item.get("lat"), item.get("lon")
    return (type(lat) in (int, float) and type(lon) in (int, float)
            and -90 <= lat <= 90 and -180 <= lon <= 180
            and math.isfinite(lat) and math.isfinite(lon))


def address_matches(item: dict, address: str) -> bool:
    """Verify the reviewed street or named amenity, never a postcode alone."""
    street, town, _, postcode = expected_address_parts(address, "GB")
    if not street or not town or not postcode:
        return False
    provider_postcode = normalize_gb_postcode(item.get("postcode"))
    number = re.match(r"^([0-9][a-z0-9-]*)\s+", street)
    # Some reviewed park addresses identify a named site rather than a road.
    # Permit only the same full name (optionally followed by a parenthetical
    # description) at the exact postcode; never a nearby peak or partial name.
    name = _text(item.get("name"), TEXT_LIMITS["name"])
    if (item.get("result_type") == "amenity" and not number and name
            and provider_postcode == postcode
            and gb_address_part(re.sub(r"\s+\([^()]*\)\s*$", "", name), street=True) == street):
        return True
    provider_street = gb_address_part(item.get("street"), street=True)
    expected_core = re.sub(r"^[0-9][a-z0-9-]*\s+", "", street)
    expected_core = re.sub(r"\s+(?:ste|suite|unit|apt|apartment|#)\s+[a-z0-9-]+$", "", expected_core)
    if not provider_street or provider_street != expected_core:
        return False
    same_town = any(gb_address_part(item.get(field)) == town
                    for field in ("city", "town", "village", "municipality"))
    if not same_town and provider_postcode != postcode:
        return False
    if item.get("result_type") in {"building", "amenity"}:
        raw_postcode = item.get("postcode")
        if raw_postcode and provider_postcode != postcode:
            return False
        if number and str(item.get("housenumber") or "").strip().lower() != number.group(1):
            return False
    return True


def _datasource(value) -> dict | None:
    """Keep the source's licence and attribution with every reusable result."""
    if not isinstance(value, dict):
        return None
    clean = {name: _text(value.get(name), maximum)
             for name, maximum in DATASOURCE_LIMITS.items()}
    if not all(clean.values()):
        return None
    try:
        url = urlsplit(clean["url"])
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            return None
    except ValueError:
        return None
    return clean


def verify(payload: dict, address: str) -> dict | None:
    """Retain only the first provider-ranked, validated street/building result."""
    try:
        rows = payload.get("results")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 2:
            return None
        first = rows[0]
        if not isinstance(first, dict):
            return None
        rank = first.get("rank")
        if (first.get("country_code") != "gb" or not valid_coordinates(first)
                or first.get("result_type") not in ACCEPTED_RESULT_TYPES
                or not isinstance(rank, dict) or not _score(rank.get("confidence"))
                or rank["confidence"] < MIN_CONFIDENCE
                or rank.get("match_type") not in MATCH_TYPES
                or any(name in rank and not _score(rank[name]) for name in RANK_FIELDS)
                or not address_matches(first, address)):
            return None
        datasource = _datasource(first.get("datasource"))
        if datasource is None:
            return None
        clean = {name: value for name, maximum in TEXT_LIMITS.items()
                 if (value := _text(first.get(name), maximum)) is not None}
        # The fields used for validation must survive bounding unchanged.
        if any(first.get(name) not in (None, "") and clean.get(name) != first[name]
               for name in ("country_code", "street", "result_type", "housenumber", "postcode",
                            "city", "town", "village", "municipality", "name")):
            return None
        clean.update(lat=first["lat"], lon=first["lon"], datasource=datasource,
                     rank={name: rank[name] for name in (*RANK_FIELDS, "match_type") if name in rank})
        return {"provider": PROVIDER, "results": [clean]}
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def result_diagnostic(payload, address: str, http_status=None) -> dict:
    """No raw query, response body, URL or credential enters diagnostics."""
    rows = payload.get("results") if isinstance(payload, dict) else None
    is_array = isinstance(rows, list)
    first = rows[0] if is_array and rows and isinstance(rows[0], dict) else {}
    rank = first.get("rank") if isinstance(first.get("rank"), dict) else {}
    try:
        address_match = address_matches(first, address)
    except (AttributeError, TypeError, ValueError, OverflowError):
        address_match = False
    return sanitize_diagnostic({
        "version": 1, "cause": "empty_results" if is_array and not rows else "result_mismatch",
        "http_status": http_status, "result_count": min(len(rows), 3) if is_array else 0,
        "results_array": is_array, "candidate_object": bool(first),
        "coordinates_valid": valid_coordinates(first),
        "score_valid": _score(rank.get("confidence")) and rank.get("confidence", 0) >= MIN_CONFIDENCE,
        "accuracy_type_valid": isinstance(first.get("result_type"), str)
                               and first["result_type"] in ACCEPTED_RESULT_TYPES,
        "country_valid": first.get("country_code") == "gb", "address_match": address_match,
    })


def _http_diagnostic(error: HTTPError) -> dict:
    # Do not parse provider text: Geoapify can echo the API-key-bearing URL.
    try:
        error.read(MAX_ERROR_RESPONSE + 1)
    except (AttributeError, OSError, TypeError, ValueError):
        pass
    finally:
        try:
            error.close()
        except (AttributeError, OSError, ValueError):
            pass
    return sanitize_diagnostic({"version": 1, "cause": "http_rejected",
                                "http_status": error.code, "error_class": "unclassified"})


def geocode(address: str, key: str, *, reservation: dict, country_code: str = "GB",
            opener=None) -> dict:
    """One request, bound to SQL's provider/country/query reservation."""
    try:
        valid = datetime.fromisoformat(str(reservation["valid_until"]).replace("Z", "+00:00"))
        if (country_code != "GB" or not reservation_matches(reservation, address, country_code)
                or reservation.get("provider") != PROVIDER or not reservation.get("allowed")
                or not reservation.get("request_id")
                or (valid - datetime.now(timezone.utc)).total_seconds() < TIMEOUT + 1):
            raise GeocodeFailure("invalid_reservation")
    except (KeyError, ValueError, TypeError):
        raise GeocodeFailure("invalid_reservation") from None
    street, city, _, postcode = expected_address_parts(address, "GB")
    if not street or not city or not postcode:
        raise GeocodeFailure("invalid_request")
    if not key:
        raise GeocodeFailure("provider_auth")
    request = Request(ENDPOINT + "?" + urlencode({
        "text": address, "filter": "countrycode:gb", "bias": "countrycode:none",
        "format": "json", "lang": "en", "limit": 2, "apiKey": key,
    }), headers={"User-Agent": "RoomQuest-Forward-Geocoder/1.0", "Accept": "application/json"})
    http_status = None
    try:
        with (opener or build_opener(NoRedirects()).open)(request, timeout=TIMEOUT) as response:
            http_status = getattr(response, "status", None)
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise GeocodeFailure("invalid_response", diagnostic={
                    "version": 1, "cause": "response_too_large", "http_status": http_status})
            payload = json.loads(raw)
            match = verify(payload, address)
            if match is None:
                raise GeocodeFailure("ambiguous", diagnostic=result_diagnostic(payload, address, http_status))
            return match
    except HTTPError as exc:
        reason = ("rate_limited" if exc.code == 429 else "provider_auth" if exc.code in (401, 403)
                  else "ambiguous" if exc.code in (400, 422) else "provider_error")
        raise GeocodeFailure(reason, diagnostic=_http_diagnostic(exc)) from None
    except (URLError, TimeoutError, OSError):
        raise GeocodeFailure("provider_error", diagnostic={"version": 1, "cause": "transport_error"}) from None
    except (ValueError, UnicodeError):
        raise GeocodeFailure("invalid_response", diagnostic={
            "version": 1, "cause": "invalid_json", "http_status": http_status}) from None
