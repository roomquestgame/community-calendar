"""Bounded, curator-only preview processor using Udell's actual Python adapters.

The upstream scraper, recurrence, combine and ICS/JSON-LD code remain in this fork.
This processor *previews* publisher events only. It never writes external_events.
Production publish/approval stays behind RoomQuest's audited Supabase gates.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from urllib.robotparser import RobotFileParser
import ipaddress
import json
import os
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

MAX_BODY = 700_000
MAX_PREVIEWS = 10
LOOKAHEAD_DAYS = 60
ROOMQUEST_DB = "https://drpqjuqghpjivtwznfdj.supabase.co"


class PreviewError(ValueError):
    """Expected, safely reportable source failure."""


class RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise PreviewError("redirect_blocked")


def public_source_url(value: str) -> bool:
    """Reject direct private endpoints, credentials, ports and ambiguous hostnames.

    This gate is in addition to server-side source registration and a separate
    operator secret; it is not an arbitrary browser-facing URL-fetch endpoint.
    """
    try:
        parsed = urlparse(value)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or not host or parsed.username or parsed.password:
            return False
        if parsed.port not in (None, 443):
            return False
        if len(value) > 1000 or len(host) > 253:
            return False
        if host.lower().endswith((".local", ".internal", ".localhost")) or host == "localhost":
            return False
        if host.endswith(".") or ".." in host or not re.fullmatch(r"[a-zA-Z0-9.-]+", host):
            return False
        if "." not in host or any(len(part) > 63 or not part for part in host.split(".")):
            return False
        try:
            ipaddress.ip_address(host)
            return False
        except ValueError:
            pass
        return True
    except (ValueError, TypeError):
        return False


def validate_public_dns(host: str) -> None:
    """All resolved addresses must be public, otherwise fail closed."""
    try:
        info = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        addresses = {record[4][0] for record in info}
        if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
            raise PreviewError("non_public_dns")
    except (OSError, ValueError) as exc:
        raise PreviewError("dns_unavailable") from exc


@lru_cache(maxsize=256)
def robots_allowed(host: str, path: str) -> bool:
    """Respect publisher crawl restrictions, fail closed on ambiguous responses.

    Never redirect robots requests or fetch private-network destinations.
    404/410 mean no robots rules; 401/403, 429, network failures deny.
    """
    robots_url = "https://" + host + "/robots.txt"
    try:
        validate_public_dns(host)
        opener = build_opener(RejectRedirects())
        request = Request(robots_url, headers={
            "User-Agent": "RoomQuestCommunityCalendar/0.1 (community-event research)"
        })
        with opener.open(request, timeout=5) as response:
            raw = response.read(128_001)
            if response.status != 200 or len(raw) > 128_000:
                raise PreviewError("robots_unavailable")
    except HTTPError as exc:
        if exc.code in (404, 410):
            return True
        raise PreviewError("robots_denied") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise PreviewError("robots_unavailable") from exc
    parser = RobotFileParser()
    parser.parse(raw.decode("utf-8", errors="replace").splitlines())
    return parser.can_fetch("RoomQuestCommunityCalendar", "https://" + host + path)


def fetch_publisher(url: str, accept: str) -> str:
    if not public_source_url(url):
        raise PreviewError("invalid_source_url")
    parsed = urlparse(url)
    validate_public_dns(parsed.hostname or "")
    if not robots_allowed(parsed.hostname or "", parsed.path or "/"):
        raise PreviewError("robots_denied")
    opener = build_opener(RejectRedirects())
    request = Request(url, headers={
        "User-Agent": "RoomQuestCommunityCalendar/0.1 (source-review; bounded)",
        "Accept": accept,
    })
    try:
        with opener.open(request, timeout=7) as response:
            if response.status != 200 or int(response.headers.get("Content-Length") or 0) > MAX_BODY:
                raise PreviewError("source_unavailable_or_oversized")
            raw = response.read(MAX_BODY + 1)
            if len(raw) > MAX_BODY:
                raise PreviewError("source_too_large")
            return raw.decode("utf-8-sig", errors="replace")
    except HTTPError as exc:
        raise PreviewError("publisher_http_" + str(exc.code)) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise PreviewError("source_network_error") from exc


def _location(venue_name, lat, lng) -> tuple[str, float | None, float | None]:
    name = str(venue_name or "").strip()[:160]
    try:
        latitude = float(lat)
        longitude = float(lng)
        if -90 <= latitude <= 90 and -180 <= longitude <= 180 and name:
            return name, latitude, longitude
    except (ValueError, TypeError, OverflowError):
        pass
    return name, None, None


def _future_datetime(value) -> datetime | None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return None
    utc_value = value.astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    if now <= utc_value <= now + timedelta(days=LOOKAHEAD_DAYS):
        return utc_value
    return None


def _preview(title, start, end, venue, lat, lng, url, identity=""):
    future = _future_datetime(start)
    if not future or not isinstance(title, str) or not title.strip():
        return None
    name, latitude, longitude = _location(venue, lat, lng)
    end_value = end.astimezone(timezone.utc).isoformat() if isinstance(end, datetime) and end.tzinfo else None
    return {
        "id": str(identity)[:180], "title": title.strip()[:180],
        "starts_at": future.isoformat(), "ends_at": end_value,
        "venue_name": name, "lat": latitude, "lng": longitude,
        "event_url": url if isinstance(url, str) and public_source_url(url) else None,
        "reason": None if latitude is not None else "missing_verified_venue_geo",
    }


def parse_ics_preview(payload: str) -> list[dict]:
    """Use upstream combine_ics recurrence expansion and icalendar VEVENT parsing."""
    from icalendar import Calendar
    from scripts.combine_ics import expand_rrules

    original = Calendar.from_ical(payload)
    expanded = expand_rrules(payload, window_days=LOOKAHEAD_DAYS)
    items = []
    if expanded is None:
        items = original.walk("VEVENT")
    else:
        for item in expanded:
            try:
                sub = Calendar.from_ical("BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\n" + item +
                                        "\nEND:VEVENT\nEND:VCALENDAR")
                items.extend(sub.walk("VEVENT"))
            except ValueError:
                continue

    results = []
    for item in items[:1000]:
        if str(item.get("STATUS", "")).upper() in ("CANCELLED", "CANCELED"):
            continue
        try:
            started = item.decoded("DTSTART")
            ended = item.decoded("DTEND") if item.get("DTEND") else None
            geo = item.get("GEO")
            lat = getattr(geo, "latitude", None) if geo is not None else None
            lng = getattr(geo, "longitude", None) if geo is not None else None
            if geo is not None and isinstance(geo, (tuple, list)) and len(geo) == 2:
                lat, lng = geo
            record = _preview(str(item.get("SUMMARY", "")), started, ended,
                              str(item.get("LOCATION", "")), lat, lng,
                              str(item.get("URL", "")),
                              str(item.get("UID", "")))
            if record:
                results.append(record)
        except (KeyError, ValueError, TypeError):
            continue
    return results


def parse_jsonld_preview(payload: str) -> list[dict]:
    """Use Udell's JSON-LD/BeautifulSoup-compatible Event extraction library."""
    from scrapers.lib.jsonld import extract_jsonld_blocks, extract_events_from_blocks
    events = extract_events_from_blocks(extract_jsonld_blocks(payload))
    results = []
    for item in events[:500]:
        if not isinstance(item, dict) or item.get("eventStatus", "").endswith("/EventCancelled"):
            continue
        try:
            start = datetime.fromisoformat(str(item.get("startDate", "")).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(item["endDate"]).replace("Z", "+00:00")) if item.get("endDate") else None
        except ValueError:
            continue
        venue = item.get("location", {})
        if isinstance(venue, list):
            venue = next((v for v in venue if isinstance(v, dict)), {})
        if not isinstance(venue, dict):
            venue = {}
        geo = venue.get("geo", {}) or {}
        if not isinstance(geo, dict):
            geo = {}
        record = _preview(str(item.get("name", "")), start, end,
                          venue.get("name"), geo.get("latitude"), geo.get("longitude"),
                          item.get("url"), item.get("@id", ""))
        if record:
            results.append(record)
    return results


def parse_growthzone_preview(payload: str, source: dict) -> list[dict]:
    """Call Udell's GrowthZone/ChamberMaster XML parser, without its unrestricted fetch."""
    if not source.get("timezone"):
        raise PreviewError("source_timezone_required")
    from scrapers.growthzone import GrowthZoneScraper
    scraper = GrowthZoneScraper({"api_url": source["feed_url"],
                                 "timezone": source["timezone"], "name": "RoomQuest source"})
    results = []
    for item in scraper._parse_xml(payload)[:500]:
        record = _preview(item.get("title"), item.get("dtstart"), item.get("dtend"),
                          item.get("location"), None, None, item.get("url"))
        if record:
            results.append(record)
    return results


def parse_wordpress_preview(payload: str, source: dict) -> list[dict]:
    """Use upstream Tribe Events REST record parser; preserve explicit venue GEO only."""
    if not source.get("timezone"):
        raise PreviewError("source_timezone_required")
    from scrapers.lib.tribe_events import TribeEventsScraper
    parser = TribeEventsScraper()
    tz = ZoneInfo(source["timezone"])
    parsed = json.loads(payload)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("events"), list):
        raise PreviewError("not_wordpress_events_api")
    results = []
    for item in parsed["events"][:500]:
        record = parser._parse_event(item, tz)
        if not record:
            continue
        venue = item.get("venue") or {}
        if not isinstance(venue, dict):
            venue = {}
        preview = _preview(record.get("title"), record.get("dtstart"), record.get("dtend"),
                           venue.get("venue"), venue.get("geo_lat"), venue.get("geo_lng"),
                           record.get("url"), item.get("id", ""))
        if preview:
            results.append(preview)
    return results


SUPPORTED = {"ical", "jsonld", "growthzone", "wordpress"}


def preview_source(source: dict) -> dict:
    adapter = source.get("platform_adapter") or "unknown"
    if adapter not in SUPPORTED:
        raise PreviewError("adapter_requires_configuration")
    url = source.get("feed_url", "")
    accept = "text/calendar" if adapter == "ical" else (
        "application/json" if adapter == "wordpress" else "text/html,application/xml"
    )
    payload = fetch_publisher(url, accept)
    try:
        if adapter == "ical":
            events = parse_ics_preview(payload)
        elif adapter == "jsonld":
            events = parse_jsonld_preview(payload)
        elif adapter == "growthzone":
            events = parse_growthzone_preview(payload, source)
        else:
            events = parse_wordpress_preview(payload, source)
    except (ValueError, TypeError, KeyError) as exc:
        raise PreviewError("invalid_calendar_payload") from exc
    unique = {((row.get("id") or row.get("title") or ""), row["starts_at"]): row for row in events}
    records = sorted(unique.values(), key=lambda row: (row["starts_at"], row["title"]))[:500]
    return {
        "p_source_key": source["source_key"], "p_samples": records[:MAX_PREVIEWS],
        "p_future_count": len(records),
        "p_venue_count": sum(1 for row in records if row["lat"] is not None),
        "p_error": None,
        "p_events": records[:100],  # private metadata-only staging; not part of the preview RPC
    }


def supabase_rpc(path: str, payload: dict):
    """Call ONLY the preview-scoped RPCs. The service_role key never leaves Supabase.

    Supabase's publishable API key identifies the project but grants no privileged
    role. A separate 256-bit, rotated collector token authorizes only these two
    security-definer RPCs. The token must never enter a public client or log.
    """
    import urllib.request
    allowed = {"community_collector_claim_previews", "community_collector_record_preview",
               "community_collector_record_staged_events"}
    if path not in allowed:
        raise PreviewError("unsupported_collector_rpc")
    root = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")
    token = os.environ.get("ROOMQUEST_COLLECTOR_TOKEN", "")
    if root != ROOMQUEST_DB or not key or len(token) != 64:
        raise PreviewError("collector_not_configured")
    request = urllib.request.Request(root + "/rest/v1/rpc/" + path,
        data=json.dumps({"p_token": token, **payload}).encode("utf-8"),
        headers={"apikey": key, "Content-Type": "application/json",
                 "Accept": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(request, timeout=9) as response:
            raw = response.read(150_000)
            return json.loads(raw.decode()) if raw else None
    except (HTTPError, URLError, ValueError) as exc:
        raise PreviewError("database_unavailable") from exc


def collect_previews(limit=4) -> dict:
    claimed = supabase_rpc("community_collector_claim_previews", {"p_limit": min(4, max(1, int(limit)))})
    result = {"claimed": len(claimed or []), "complete": 0, "failed": 0,
              "staged": 0}
    for source in claimed or []:
        try:
            output = preview_source(source)
            events = output.pop("p_events", [])
            # Stage privately before closing the claim. This RPC can write ONLY
            # to community_staged_events; it never approves or publishes events.
            written = supabase_rpc("community_collector_record_staged_events", {
                "p_source_key": source["source_key"], "p_events": events
            })
            result["staged"] += int(written or 0)
        except (PreviewError, OSError, ValueError) as exc:
            output = {
                "p_source_key": source["source_key"], "p_samples": [],
                "p_future_count": 0, "p_venue_count": 0,
                "p_error": str(exc)[:120] if isinstance(exc, PreviewError) else "source_parse_error",
            }
        supabase_rpc("community_collector_record_preview", output)
        if output["p_error"] is None:
            result["complete"] += 1
        else:
            result["failed"] += 1
    return result
