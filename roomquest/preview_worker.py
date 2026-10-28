"""Bounded, curator-only preview processor using Udell's actual Python adapters.

The upstream scraper, recurrence, combine and ICS/JSON-LD code remain in this fork.
This processor *previews* publisher events only. It never writes external_events.
Production publish/approval stays behind RoomQuest's audited Supabase gates.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
from time import monotonic
from time import sleep
from threading import Lock
from urllib.robotparser import RobotFileParser
import ipaddress
import json
import os
import re
import socket
import requests
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.parse import urljoin
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

MAX_BODY = 3_000_000
MAX_PREVIEWS = 10
LOOKAHEAD_DAYS = 60
ROOMQUEST_DB = "https://drpqjuqghpjivtwznfdj.supabase.co"
_robots_delays = {}
_publisher_next = {}
_publisher_lock = Lock()


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
    _robots_delays[host] = parser.crawl_delay("RoomQuestCommunityCalendar") or parser.crawl_delay("*") or 1
    return parser.can_fetch("RoomQuestCommunityCalendar", "https://" + host + path)


def pace_publisher(host: str, deadline: float) -> None:
    """Honor advertised delay within this worker; DB leases serialize publishers."""
    with _publisher_lock:
        now = monotonic()
        wait = max(0, _publisher_next.get(host, now) - now)
        delay = max(1, float(_robots_delays.get(host, 1)))
        if now + wait + 0.2 >= deadline:
            raise PreviewError("publisher_rate_limited")
        _publisher_next[host] = now + wait + delay
    if wait:
        sleep(wait)


def fetch_publisher(url: str, accept: str, *, respect_robots: bool = False,
                    deadline_at: float | None = None) -> str:
    """Use Udell's requests GET and its redirect behavior for approved HTTPS feeds.

    Keep URL/DNS validation and bounded downloads. As in upstream Udell,
    fetch registered calendar endpoints directly without a robots preflight;
    destination URLs still pass public-network checks before each redirect.
    """
    if not public_source_url(url):
        raise PreviewError("invalid_source_url")
    headers = {
        "User-Agent": ("RoomQuestCommunityCalendar/0.2 (+https://roomquestapp.vercel.app/)" if respect_robots
                       else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"),
        "Accept": accept,
    }
    current = url
    deadline = min(deadline_at or float("inf"), monotonic() + 18)
    with requests.Session() as session:
        for _ in range(5):
            parsed = urlparse(current)
            if not public_source_url(current):
                raise PreviewError("invalid_redirect_url")
            validate_public_dns(parsed.hostname or "")
            if respect_robots and not robots_allowed(parsed.netloc, parsed.path + ("?" + parsed.query if parsed.query else "")):
                raise PreviewError("robots_denied")
            if respect_robots and monotonic() >= deadline:
                raise PreviewError("source_fetch_deadline")
            if respect_robots:
                pace_publisher(parsed.netloc, deadline)
            try:
                remaining = max(0.1, deadline - monotonic())
                timeout = (min(3,remaining/2), min(7,remaining/2)) if respect_robots else (5,12)
                response = session.get(current, headers=headers, timeout=timeout,
                                       stream=True, allow_redirects=False)
                if response.status_code in (301, 302, 303, 307, 308):
                    from urllib.parse import urljoin
                    location = response.headers.get("Location")
                    response.close()
                    if not location:
                        raise PreviewError("redirect_missing_location")
                    current = urljoin(current, location)
                    continue
                if response.status_code != 200:
                    code = response.status_code
                    response.close()
                    raise PreviewError("publisher_http_" + str(code))
                length = int(response.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    response.close()
                    raise PreviewError("source_unavailable_or_oversized")
                chunks, size = [], 0
                for chunk in response.iter_content(chunk_size=32768):
                    if respect_robots and monotonic() >= deadline:
                        response.close()
                        raise PreviewError("source_fetch_deadline")
                    size += len(chunk)
                    if size > MAX_BODY:
                        response.close()
                        raise PreviewError("source_too_large")
                    chunks.append(chunk)
                encoding = response.encoding or "utf-8-sig"
                if respect_robots and "charset=" not in response.headers.get("Content-Type", "").lower():
                    encoding = "utf-8-sig"
                response.close()
                try:
                    return b"".join(chunks).decode(encoding, errors="strict" if respect_robots else "replace")
                except UnicodeError as exc:
                    raise PreviewError("invalid_source_encoding") from exc
            except requests.RequestException as exc:
                raise PreviewError("source_network_error") from exc
    raise PreviewError("too_many_redirects")

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


def _preview(title, start, end, venue, lat, lng, url, identity="",
             category="", address="", city="", image=None, *, allow_ongoing=False):
    future = _future_datetime(start)
    if future is None and allow_ongoing and isinstance(start, datetime) and start.tzinfo and isinstance(end, datetime) and end.tzinfo:
        now = datetime.now(timezone.utc)
        if now-timedelta(hours=24) <= start <= now and end >= now+timedelta(minutes=60):
            future = start.astimezone(timezone.utc)
    if not future or not isinstance(title, str) or not title.strip():
        return None
    name, latitude, longitude = _location(venue, lat, lng)
    end_value = end.astimezone(timezone.utc).isoformat() if isinstance(end, datetime) and end.tzinfo else None
    return {
        "id": str(identity)[:180], "title": title.strip()[:180],
        "starts_at": future.isoformat(), "ends_at": end_value,
        "venue_name": name, "lat": latitude, "lng": longitude,
        "event_url": url if isinstance(url, str) and public_source_url(url) else None,
        "category": str(category or "")[:80],
        "venue_address": str(address or "")[:400],
        "venue_city": str(city or "")[:120],
        **({"image_url": event_image(image, url if isinstance(url, str) else "")} if image is not None else {}),
        "reason": None if latitude is not None else "missing_verified_venue_geo",
    }


def parse_ics_preview(payload: str, *, allow_ongoing=False, include_images=True) -> list[dict]:
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
                              str(item.get("UID", "")),
                              calendar_categories(item), image=calendar_image(item) if include_images else None,
                              allow_ongoing=allow_ongoing)
            if record:
                results.append(record)
        except (KeyError, ValueError, TypeError):
            continue
    return results


def event_image(value, base_url="") -> str | None:
    """Select a public event image candidate; the media worker validates its bytes."""
    if isinstance(value, list):
        return next((u for x in value[:5] if (u := event_image(x, base_url))), None)
    if isinstance(value, dict):
        value = value.get("contentUrl") or value.get("url") or value.get("@id")
    if not isinstance(value, str):
        return None
    value = urljoin(base_url, value.strip())
    if not public_source_url(value):
        return None
    path = urlparse(value).path.lower()
    if path.endswith(('.svg', '.pdf', '.ics', '.html')) or re.search(r'(^|/)(favicon|logo|avatar|pixel|tracking)[._/-]', path):
        return None
    return value


def calendar_image(item) -> str | None:
    base = str(item.get("URL", ""))
    for field in ("IMAGE", "X-IMAGE", "X-WP-IMAGES-URL", "ATTACH"):
        values = item.get(field, [])
        for value in values if isinstance(values, list) else [values]:
            mime = str(getattr(value, 'params', {}).get('FMTTYPE', '')).lower()
            if field == 'ATTACH' and not (mime.startswith('image/') or re.search(r'\.(png|jpe?g|webp|gif|avif)(\?|$)', str(value), re.I)):
                continue
            if candidate := event_image(str(value), base):
                return candidate
    from bs4 import BeautifulSoup
    for field in ("X-ALT-DESC", "DESCRIPTION"):
        html = str(item.get(field, ""))[:50_000]
        if '<img' in html.lower():
            for image in BeautifulSoup(html, 'html.parser').select('img[src]')[:5]:
                if candidate := event_image(image.get('src'), base):
                    return candidate
    return None


def calendar_categories(item) -> str:
    """Decode vCategory values rather than storing their Python object repr."""
    values = item.get("CATEGORIES", [])
    values = values if isinstance(values, list) else [values]
    labels = []
    for value in values:
        for label in getattr(value, "cats", [value]):
            text = str(label).strip()
            if text and text not in labels:
                labels.append(text)
    return ", ".join(labels)[:80]


def postal_address(address: dict) -> str:
    """Keep locality/state/postcode from structured publisher venue addresses."""
    return ", ".join(str(address.get(k) or "").strip() for k in
                     ("streetAddress", "addressLocality", "addressRegion", "postalCode")
                     if address.get(k))[:400]


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
        address = venue.get("address") or {}
        if not isinstance(address, dict):
            address = {}
        record = _preview(str(item.get("name", "")), start, end,
                          venue.get("name"), geo.get("latitude"), geo.get("longitude"),
                          item.get("url"), item.get("@id", ""),
                          item.get("keywords", ""),
                          postal_address(address), address.get("addressLocality", ""), image=item.get("image"))
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
                          item.get("location"), None, None, item.get("url"),
                          category=item.get("category", ""),
                          address=item.get("address", ""), city=item.get("city", ""))
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
        categories = item.get("categories") or []
        label = ", ".join(str(x.get("name", "")) for x in categories[:3]
                          if isinstance(x, dict)) if isinstance(categories, list) else ""
        preview = _preview(record.get("title"), record.get("dtstart"), record.get("dtend"),
                           venue.get("venue"), venue.get("geo_lat"), venue.get("geo_lng"),
                           record.get("url"), item.get("id", ""), label,
                           ", ".join(str(venue.get(k) or "").strip() for k in
                                     ("address", "city", "state", "zip") if venue.get(k)),
                           venue.get("city", ""), image=item.get("image"))
        if preview:
            results.append(preview)
    return results


SUPPORTED = {"ical", "jsonld", "growthzone", "wordpress"}


def preview_source(source: dict, *, deadline_at=None) -> dict:
    if source.get("source_key", "").startswith("municipal_mapsee_"):
        from roomquest.mapsee_adapter import profiles, collect
        profile = profiles().get(source["source_key"])
        if not profile or profile["url"] != source.get("feed_url"):
            raise PreviewError("unregistered_mapsee_source")
        try:
            deadline = min(monotonic() + 20, deadline_at - 8 if deadline_at is not None else float("inf"))
            if monotonic() >= deadline:
                raise PreviewError("collection_deadline")
            records = collect(source, profile, lambda url, accept: fetch_publisher(
                url, accept, respect_robots=True, deadline_at=deadline))
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            if re.fullmatch(r"[a-z_]{3,100}", reason):
                raise PreviewError(reason) from exc
            raise PreviewError("invalid_calendar_payload") from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {
            "p_source_key": source["source_key"], "p_samples": samples,
            "p_future_count": len(records),
            "p_venue_count": sum(1 for row in records if row["lat"] is not None),
            "p_error": None, "p_events": records,
        }
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
               "community_collector_record_staged_events", "community_collector_geocoder",
               "community_collector_venues", "community_collector_media"}
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
        with urllib.request.urlopen(request, timeout=4) as response:
            raw = response.read(150_000)
            return json.loads(raw.decode()) if raw else None
    except (HTTPError, URLError, ValueError) as exc:
        raise PreviewError("database_unavailable") from exc


def _process_claimed_source(source: dict, *, deadline_at=None) -> dict:
    """Process a single claimed feed with the existing private staging contract."""
    try:
        deadline = min(monotonic() + 43, deadline_at or float("inf"))
        output = (preview_source(source, deadline_at=deadline - 4)
                  if source.get("source_key", "").startswith("municipal_mapsee_") else preview_source(source))
        events = output.pop("p_events", [])
        staged = 0
        # Existing token/RPC accepts at most 100 facts. Large Mapsee sources use
        # several bounded calls; only a wholly completed source becomes healthy.
        batches, batch, size = [], [], 2
        for event in events:
            event_size = len(json.dumps(event, ensure_ascii=False)) + 2
            if batch and (len(batch) >= 100 or size + event_size > 150_000):
                batches.append(batch)
                batch, size = [], 2
            batch.append(event)
            size += event_size
        batches.append(batch)
        for batch in batches:
            if monotonic() > deadline - 4:
                raise PreviewError("staging_deadline")
            written = supabase_rpc("community_collector_record_staged_events", {
                "p_source_key": source["source_key"], "p_events": batch
            })
            staged += int(written or 0)
    except (PreviewError, OSError, ValueError) as exc:
        output = {
            "p_source_key": source["source_key"], "p_samples": [],
            "p_future_count": 0, "p_venue_count": 0,
            "p_error": str(exc)[:120] if isinstance(exc, PreviewError) else "source_parse_error",
        }
        staged = 0
    supabase_rpc("community_collector_record_preview", output)
    return {"complete": int(output["p_error"] is None),
            "failed": int(output["p_error"] is not None), "staged": staged}


def collect_previews(limit=4) -> dict:
    """Legacy single collector invocation; no behavior change for manual preview."""
    claimed = supabase_rpc("community_collector_claim_previews",
                           {"p_limit": min(4, max(1, int(limit)))})
    result = {"claimed": len(claimed or []), "complete": 0, "failed": 0, "staged": 0}
    for source in claimed or []:
        item = _process_claimed_source(source)
        for key in ("complete", "failed", "staged"):
            result[key] += item[key]
    return result


def collect_bulk_previews(max_sources=15, concurrency=3, deadline_seconds=48) -> dict:
    """Five independently scheduled workers * fifteen = up to 75 / interval.

    Supabase's existing scoped RPC still atomically claims <=4 at a time.
    No schema/grant/migration changes, URL input, service key, or CI scraper.
    The hard deadline is below Vercel's function maxDuration=60s.
    """
    maximum = min(15, max(1, int(max_sources)))
    workers = min(3, max(1, int(concurrency)))
    deadline = monotonic() + max(1, min(48, deadline_seconds))
    result = {"claimed": 0, "complete": 0, "failed": 0, "staged": 0}
    mapsee_batch = False
    retried_cooldown = False
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while result["claimed"] < maximum and monotonic() < deadline:
            claim_limit = min(workers, 4, maximum - result["claimed"])
            claimed = supabase_rpc("community_collector_claim_previews",
                                   {"p_limit": claim_limit}) or []
            if not claimed:
                # A completed Mapsee publisher lease has a short DB cooldown.
                # Give it one bounded chance before ending this scheduled slot.
                if mapsee_batch and not retried_cooldown and monotonic() + 2 < deadline:
                    sleep(1.1)
                    retried_cooldown = True
                    continue
                break
            mapsee_batch = any(s.get("source_key", "").startswith("municipal_mapsee_") for s in claimed)
            retried_cooldown = False
            result["claimed"] += len(claimed)
            for item in pool.map(lambda source: _process_claimed_source(source, deadline_at=deadline + 3), claimed):
                for key in ("complete", "failed", "staged"):
                    result[key] += item[key]
    return result


