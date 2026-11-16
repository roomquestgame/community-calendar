"""Offline, persistent coordinate enrichment. Never parse or rewrite event times."""
from functools import lru_cache
import math
from time import monotonic
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

RESOLVER_VERSION = "timezonefinder-9.2.0-data-4.2026.6"


@lru_cache(maxsize=1)
def finder():
    from timezonefinder import TimezoneFinder
    return TimezoneFinder()


def resolve(lat, lng):
    """No nearest-zone guesses, rounding, geocoding, network, or fixed offsets."""
    if isinstance(lat, bool) or isinstance(lng, bool):
        return None
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError, OverflowError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lng)
            and -90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    if lat == 0 and lng == 0:
        return None
    zone = finder().timezone_at_land(lat=lat, lng=lng)
    if not zone or zone.startswith("Etc/"):
        return None
    # Do not select arbitrarily in overlapping jurisdictional boundary data.
    if finder().timezones_at(lat=lat, lng=lng) != [zone]:
        return None
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return zone


def run_batch(*, rpc=None, deadline_seconds=45):
    if rpc is None:
        from roomquest.preview_worker import supabase_rpc
        rpc = supabase_rpc
    deadline = monotonic() + deadline_seconds

    def call(action, payload):
        return rpc("community_collector_timezones", {
            "p_action": action, "p_payload": payload,
        })

    # Initializing dependencies before claiming prevents import failures from
    # taking a lease. Existing venue and event results live in Postgres.
    finder()
    claims = call("claim", {"version": RESOLVER_VERSION})
    stats = {"resolved": 0, "unresolved": 0, "applied": 0}
    for claim in claims:
        if monotonic() > deadline - 8:
            break  # Unfinished leases expire; no false negative cache entry.
        zone = resolve(claim["lat"], claim["lng"])
        call("finish", {**claim, "zone": zone, "version": RESOLVER_VERSION})
        stats["resolved" if zone else "unresolved"] += 1
    if monotonic() < deadline - 4:
        stats["applied"] = call("apply", {})
    return stats
