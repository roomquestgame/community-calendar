"""Bounded, curator-only preview processor using Udell's actual Python adapters.

The upstream scraper, recurrence, combine and ICS/JSON-LD code remain in this fork.
This processor *previews* publisher events only. It never writes external_events.
Production publish/approval stays behind RoomQuest's audited Supabase gates.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from collections import OrderedDict
from pathlib import Path
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

from roomquest.collector_errors import failure_details
from roomquest.publisher_pacing import (capture_publisher_pacing, observe_crawl_delay,
                                       observe_retry_after, pacing_rpc_fields, robots_crawl_delay)

MAX_BODY = 3_000_000
MAX_PREVIEWS = 10
STAGING_BATCH_SIZE = 20
LOOKAHEAD_DAYS = 60
ROOMQUEST_DB = "https://drpqjuqghpjivtwznfdj.supabase.co"
RALEIGH_CATALOG_ICS = {
    "municipal_3ed0f050cdcddf0d03f1b6d5": "https://triangleland.org/events/list/?ical=1",
    "municipal_78278a6e98fb935c1bade8f8": "https://unitedarts.org/events/?ical=1",
    "municipal_mapsee_a2a584b18340c80504149da8": "https://durhamcountylibrary.libcal.com/ical_subscribe.php?src=p&cid=14288&cam=1752",
    "municipal_mapsee_16481cc7b70b0bedc4014223": "https://www.lib.ncsu.edu/api/calendar/events",
    "municipal_mapsee_232075b2bde6371f2a6b0bf4": "https://www.apexnc.org/common/modules/iCalendar/iCalendar.aspx?catID=23&feed=calendar",
    "municipal_mapsee_71f780dc81d6d3b9097db7c0": "https://www.hollyspringsnc.gov/common/modules/iCalendar/iCalendar.aspx?catID=24&feed=calendar",
    "municipal_mapsee_915fd84e82585dad00e9ffba": "https://www.fuquay-varina.org/common/modules/iCalendar/iCalendar.aspx?catID=45&feed=calendar",
}
RALEIGH_UDELL_ICS = json.loads(Path(__file__).with_name("raleigh_udell_ics.json").read_text(encoding="utf-8"))
VIRGINIA_CIVIC_ICS = {
    "farmville_parks_rec_va": "https://farmvilleva.com/common/modules/iCalendar/iCalendar.aspx?catID=23&feed=calendar",
    "halifax_county_main_va": "https://www.halifaxcountyva.gov/common/modules/iCalendar/iCalendar.aspx?catID=14&feed=calendar",
}
_robots_delays = {}
ROBOTS_CACHE_SECONDS = 300
MAX_ROBOTS_HOSTS = 128
_robots_cache = OrderedDict()
_robots_cache_lock = Lock()
_publisher_next = {}
_publisher_retry_after = {}
_publisher_lock = Lock()


class PreviewError(ValueError):
    """Expected, safely reportable source failure."""


class RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise PreviewError("redirect_blocked")


class ReviewedRobotsRedirects(RejectRedirects):
    """One reviewed vendor route; no general robots redirect permission."""
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # Observed November 6: this API host routes a nonexistent robots file
        # to its vendor's explicit 404 endpoint. Recheck the original each
        # cache window so newly published rules are still authoritative.
        if (request.full_url == 'https://eyqhj2iy2m-dsn.algolia.net/robots.txt'
                and newurl == 'https://algolia.net/1/404'
                and code in (301, 302, 307, 308)):
            validate_public_dns('algolia.net')
            return Request(newurl, headers={
                'User-Agent': 'RoomQuestCommunityCalendar/0.1 (community-event research)'
            }, method='GET')
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def _observe_retry_after(host, headers):
    wait, unbounded = observe_retry_after(headers.get("Retry-After") if headers else None)
    if unbounded:
        raise PreviewError("publisher_wait_requires_review")
    if wait:
        with _publisher_lock:
            until = monotonic() + wait
            _publisher_retry_after[host] = max(_publisher_retry_after.get(host, 0), until)
            _publisher_next[host] = max(_publisher_next.get(host, 0), until)


def _reserve_known_crawl_delay(host):
    wait, unbounded = observe_crawl_delay(_robots_delays.get(host, 1))
    if not unbounded:
        with _publisher_lock:
            _publisher_next[host] = max(_publisher_next.get(host, 0), monotonic() + max(1, wait))


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
    except PreviewError:
        # PreviewError subclasses ValueError; do not relabel a policy block as
        # a transient DNS outage and make it eligible for transport retries.
        raise
    except (OSError, ValueError) as exc:
        raise PreviewError("dns_unavailable") from exc


def _cache_robots(host, parser):
    # Age a policy from its completed response, not a shared wall-clock bucket.
    # A policy fetched just before a five-minute boundary must not expire a
    # moment later while that same publisher's crawl delay is still running.
    with _robots_cache_lock:
        _robots_cache[host] = (monotonic() + ROBOTS_CACHE_SECONDS, parser)
        _robots_cache.move_to_end(host)
        while len(_robots_cache) > MAX_ROBOTS_HOSTS:
            _robots_cache.popitem(last=False)
    return parser


def _robots_rules(host: str, *, deadline_at: float | None = None):
    """Cache each publisher's rules for five minutes after a valid response.

    Only the exact reviewed API-vendor robots redirect is permitted; every
    other redirect and every private-network destination remains blocked.
    404/410 mean no robots rules; all other HTTP/network failures fail closed.
    Actual denial and temporary unavailability retain distinct error codes.
    Cache the rules, not a path's decision: every event path is still checked.
    """
    with _robots_cache_lock:
        cached = _robots_cache.get(host)
        if cached is not None:
            if cached[0] > monotonic():
                _robots_cache.move_to_end(host)
                return cached[1]
            del _robots_cache[host]
    deadline = deadline_at if deadline_at is not None else monotonic() + 18
    if monotonic() >= deadline:
        raise PreviewError("source_fetch_deadline")
    robots_url = "https://" + host + "/robots.txt"
    attempted = False
    try:
        validate_public_dns(host)
        # A failed robots response is not cached. Its Retry-After must still
        # protect another robots GET, not only later calendar requests.
        # Publisher admission uses the enclosing source budget. The robots
        # network operation remains capped at five seconds after that wait.
        pace_publisher(host, deadline, reserve=False)
        opener = build_opener(ReviewedRobotsRedirects())
        request = Request(robots_url, headers={
            "User-Agent": "RoomQuestCommunityCalendar/0.1 (community-event research)"
        })
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise PreviewError("source_fetch_deadline")
        attempted = True
        with opener.open(request, timeout=min(5, remaining)) as response:
            _observe_retry_after(host, getattr(response, "headers", {}))
            raw = response.read(128_001)
            if response.status != 200 or len(raw) > 128_000:
                raise PreviewError("robots_unavailable")
    except HTTPError as exc:
        _observe_retry_after(host, exc.headers)
        if exc.code in (404, 410):
            _robots_delays[host] = 1
            return _cache_robots(host, None)
        if exc.code in (401, 403):
            raise PreviewError("robots_denied") from exc
        if exc.code == 429:
            raise PreviewError("publisher_rate_limited") from exc
        raise PreviewError("robots_unavailable") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise PreviewError("robots_unavailable") from exc
    finally:
        if attempted:
            _reserve_known_crawl_delay(host)
    parser = RobotFileParser()
    lines = raw.decode("utf-8-sig", errors="replace").splitlines()
    parser.parse(lines)
    _robots_delays[host] = robots_crawl_delay(lines, "RoomQuestCommunityCalendar")
    # The newly learned delay also separates this robots response from the
    # first calendar request. An oversized value is held before that request.
    _reserve_known_crawl_delay(host)
    return _cache_robots(host, parser)


def robots_allowed(host: str, path: str, *, deadline_at: float | None = None) -> bool:
    """Evaluate the current path against cached, publisher-specific rules."""
    parser = _robots_rules(host, deadline_at=deadline_at)
    _, unbounded = observe_crawl_delay(_robots_delays.get(host, 1))
    if unbounded:
        raise PreviewError("publisher_wait_requires_review")
    return parser is None or parser.can_fetch("RoomQuestCommunityCalendar", "https://" + host + path)


def pace_publisher(host: str, deadline: float, *, reserve=True) -> None:
    """Honor advertised delay within this worker; DB leases serialize publishers."""
    with _publisher_lock:
        now = monotonic()
        if host in _publisher_retry_after:
            _, unbounded = observe_retry_after(max(0, _publisher_retry_after[host] - now))
            if unbounded:
                raise PreviewError("publisher_wait_requires_review")
        wait = max(0, _publisher_next.get(host, now) - now)
        if now + wait + 0.2 >= deadline:
            # This is a local scheduling decision; no publisher rejected a
            # request. Keep real HTTP 429 codes distinct in records and logs.
            if wait:
                raise PreviewError("publisher_pacing_deferred")
            raise PreviewError("source_fetch_deadline")
        if reserve:
            delay = max(1, float(_robots_delays.get(host, 1)))
            _publisher_next[host] = now + wait + delay
    if wait:
        sleep(wait)


def fetch_publisher(url: str, accept: str, *, respect_robots: bool = False,
                    deadline_at: float | None = None, allowed_hosts=None) -> str | bytes:
    """Fetch an approved public source with the existing bounded GET transport."""
    return _fetch_publisher_request(url, accept, respect_robots=respect_robots,
                                    deadline_at=deadline_at, allowed_hosts=allowed_hosts)


def render_good_shepherd_calendar(*, nonce: str, args: str,
                                  deadline_at: float | None = None) -> str:
    """Read the one public calendar render action observed in publisher markup.

    The parser cannot supply a URL, action, arbitrary form fields or credentials.
    This display-only POST uses the ordinary shared publisher protections; no
    registration, account, subscription or other WordPress action is supported.
    """
    if (not isinstance(nonce, str) or not re.fullmatch(r'[0-9a-f]{10}', nonce)
            or not isinstance(args, str) or not re.fullmatch(r'[0-9a-f]{40}', args)):
        raise PreviewError('invalid_calendar_render_parameters')
    return _fetch_publisher_request(
        'https://goodshepherdsouthhill.org/wp-admin/admin-ajax.php', 'text/html',
        respect_robots=True, deadline_at=deadline_at,
        allowed_hosts=('goodshepherdsouthhill.org',),
        calendar_form={'action': 'r34ics_ajax', 'r34ics_nonce': nonce,
                       'subaction': 'display_calendar', 'args': args,
                       'js_args[debug]': 'false'})


def render_elloree_calendar(*, deadline_at: float | None = None) -> str:
    """Read Elloree's exact public calendar action with no caller-supplied body."""
    return _fetch_publisher_request(
        'https://connect.elloreesc.com/api/functions/getPublicCalendarEvents',
        'application/json', respect_robots=True, deadline_at=deadline_at,
        allowed_hosts=('connect.elloreesc.com',), calendar_json={})


def render_old_santee_programs(*, deadline_at: float | None = None) -> str:
    """Read the exact anonymous RecDesk program-list display operation.

    All filter fields and the first page are fixed to the reviewed public UI.
    No caller-supplied URL, account, cart, registration or payment data is
    accepted. The adapter checks the returned total before accepting a snapshot.
    """
    return _fetch_publisher_request(
        'https://oldsanteecanal.recdesk.com/Community/Program/FilterPrograms',
        'text/html', respect_robots=True, deadline_at=deadline_at,
        allowed_hosts=('oldsanteecanal.recdesk.com',), calendar_json={
            'ProgramName': '', 'Code': '', 'ProgramNameXS': '',
            'DateRangeSelection': '', 'DateRangeFrom': '', 'DateRangeTo': '',
            'ProgramType': '0', 'Age': '', 'Facility': '0', 'Days': '0',
            'Pagination': {'CurrentPageIndex': 1, 'LoadMore': False}})


def _fetch_publisher_request(url: str, accept: str, *, respect_robots: bool = False,
                             deadline_at: float | None = None, allowed_hosts=None,
                             calendar_form=None, calendar_json=None) -> str | bytes:
    """Use the shared bounded transport for approved HTTPS publisher content.

    Keep URL/DNS validation and bounded downloads. As in upstream Udell,
    fetch registered calendar endpoints directly without a robots preflight;
    destination URLs still pass public-network checks before each GET redirect.
    Reviewed display-only POSTs are source scoped and never redirected.
    """
    render_content_type = None
    json_content_type = 'application/json'
    json_referer = None
    if calendar_json is not None:
        elloree = (url == 'https://connect.elloreesc.com/api/functions/getPublicCalendarEvents'
                   and accept == 'application/json' and allowed_hosts == ('connect.elloreesc.com',)
                   and isinstance(calendar_json, dict) and not calendar_json)
        recdesk = (url == 'https://oldsanteecanal.recdesk.com/Community/Program/FilterPrograms'
                   and accept == 'text/html' and allowed_hosts == ('oldsanteecanal.recdesk.com',)
                   and isinstance(calendar_json, dict) and calendar_json == {
                       'ProgramName': '', 'Code': '', 'ProgramNameXS': '',
                       'DateRangeSelection': '', 'DateRangeFrom': '', 'DateRangeTo': '',
                       'ProgramType': '0', 'Age': '', 'Facility': '0', 'Days': '0',
                       'Pagination': {'CurrentPageIndex': 1, 'LoadMore': False}}
                   and type(calendar_json['Pagination']['CurrentPageIndex']) is int
                   and calendar_json['Pagination']['LoadMore'] is False)
        if calendar_form is not None or not respect_robots or not (elloree or recdesk):
            raise PreviewError('invalid_calendar_render_parameters')
        render_content_type = 'application/json' if elloree else 'text/html'
        json_referer = ('https://elloreesc.com/elloree-town-calendar/' if elloree
                        else 'https://oldsanteecanal.recdesk.com/Community/Program')
        if recdesk:
            json_content_type = 'application/json; charset=utf-8'
    if calendar_form is not None:
        # A second boundary keeps internal callers from turning this into an
        # arbitrary write-capable transport. Never replay a POST on redirect.
        if (url != 'https://goodshepherdsouthhill.org/wp-admin/admin-ajax.php'
                or accept != 'text/html' or not respect_robots
                or allowed_hosts != ('goodshepherdsouthhill.org',)
                or not isinstance(calendar_form, dict)
                or set(calendar_form) != {'action', 'r34ics_nonce', 'subaction', 'args', 'js_args[debug]'}
                or calendar_form.get('action') != 'r34ics_ajax'
                or calendar_form.get('subaction') != 'display_calendar'
                or calendar_form.get('js_args[debug]') != 'false'
                or not isinstance(calendar_form.get('r34ics_nonce'), str)
                or not isinstance(calendar_form.get('args'), str)
                or not re.fullmatch(r'[0-9a-f]{10}', str(calendar_form.get('r34ics_nonce', '')))
                or not re.fullmatch(r'[0-9a-f]{40}', str(calendar_form.get('args', '')))):
            raise PreviewError('invalid_calendar_render_parameters')
    if not public_source_url(url):
        raise PreviewError("invalid_source_url")
    headers = {
        "User-Agent": ("RoomQuestCommunityCalendar/0.2 (+https://roomquestapp.vercel.app/)" if respect_robots
                       else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"),
        "Accept": accept,
    }
    if calendar_form is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8'
        headers['Referer'] = 'https://goodshepherdsouthhill.org/welcome/calendar/'
    elif calendar_json is not None:
        headers['Content-Type'] = json_content_type
        headers['Referer'] = json_referer
    current = url
    admission_deadline = deadline_at if deadline_at is not None else monotonic() + 18
    deadline = min(admission_deadline, monotonic() + 18)
    network_started = False
    with requests.Session() as session:
        for _ in range(5):
            parsed = urlparse(current)
            if allowed_hosts is not None and parsed.hostname not in allowed_hosts:
                raise PreviewError("redirect_host_not_approved")
            if not public_source_url(current):
                raise PreviewError("invalid_redirect_url")
            current_deadline = deadline if network_started else admission_deadline
            if respect_robots and monotonic() >= current_deadline:
                raise PreviewError("source_fetch_deadline")
            validate_public_dns(parsed.hostname or "")
            if respect_robots and not robots_allowed(
                    parsed.netloc, parsed.path + ("?" + parsed.query if parsed.query else ""),
                    deadline_at=current_deadline):
                raise PreviewError("robots_denied")
            if respect_robots and monotonic() >= current_deadline:
                raise PreviewError("source_fetch_deadline")
            if respect_robots:
                pace_publisher(parsed.netloc, current_deadline)
                if monotonic() >= current_deadline:
                    raise PreviewError("source_fetch_deadline")
            if not network_started:
                # Admission can consume a valid part of the source budget;
                # preserve the 18-second network cap after admission. Redirects
                # share that cap and never restart the enclosing deadline.
                deadline = min(admission_deadline, monotonic() + 18)
                network_started = True
            try:
                remaining = max(0.1, deadline - monotonic())
                timeout = (min(3,remaining/2), min(7,remaining/2)) if respect_robots else (5,12)
                if calendar_form is None and calendar_json is None:
                    response = session.get(current, headers=headers, timeout=timeout,
                                           stream=True, allow_redirects=False)
                elif calendar_json is not None:
                    response = session.post(current, json=calendar_json, headers=headers,
                                            timeout=timeout, stream=True, allow_redirects=False)
                else:
                    response = session.post(current, data=calendar_form, headers=headers,
                                            timeout=timeout, stream=True, allow_redirects=False)
                if respect_robots:
                    try:
                        _observe_retry_after(parsed.netloc, response.headers)
                    except PreviewError:
                        response.close()
                        raise
                if response.status_code in (301, 302, 303, 307, 308):
                    if calendar_form is not None or calendar_json is not None:
                        response.close()
                        raise PreviewError('calendar_render_redirect_blocked')
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
                if (calendar_form is not None and
                        response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
                        != 'text/html'):
                    response.close()
                    raise PreviewError('invalid_calendar_render_content_type')
                if (calendar_json is not None and
                        response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
                        != render_content_type):
                    response.close()
                    raise PreviewError('invalid_calendar_render_content_type')
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
                if accept == 'application/pdf':
                    payload = b"".join(chunks)
                    if not payload.startswith(b'%PDF-'):
                        raise PreviewError('invalid_publisher_pdf')
                    return payload
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
             category="", address="", city="", image=None, *, allow_ongoing=False,
             retain_until_end=False):
    future = _future_datetime(start)
    if future is None and allow_ongoing and retain_until_end and isinstance(start, datetime) and start.tzinfo:
        now = datetime.now(timezone.utc)
        expires = end if isinstance(end, datetime) and end.tzinfo else start + timedelta(hours=3)
        if start <= now < expires:
            future = start.astimezone(timezone.utc)
    elif future is None and allow_ongoing and isinstance(start, datetime) and start.tzinfo and isinstance(end, datetime) and end.tzinfo:
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


def parse_ics_preview(payload: str, *, allow_ongoing=False, include_images=True, include_description=False) -> list[dict]:
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
                # Retain the occurrence's own narrative after recurrence expansion.
                # Do not look up by UID: recurrence overrides can have different text.
                if include_description:
                    record["description"] = str(item.get("DESCRIPTION", "")).strip()[:12000]
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
    import xml.etree.ElementTree as ET
    from urllib.parse import quote
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise PreviewError("invalid_calendar_payload") from exc
    if root.tag != "ArrayOfEventDisplay":
        raise PreviewError("not_growthzone_events_api")
    parsed_url = urlparse(source["feed_url"])
    base_url = f"https://{parsed_url.netloc}"
    results = []
    for element in root.findall("EventDisplay")[:500]:
        # The public XML schedule does not supply precise locations. Leave them
        # unresolved; never use the chamber's address or city as a default.
        if (element.findtext("Status") or "").upper() != "APPROVED":
            continue
        if (element.findtext("IsAllDayEvent") or "").lower() == "true":
            continue  # this pathway requires a genuine timed start
        event_id = element.findtext("EventID") or ""
        slug = element.findtext("Slug") or ""
        if not re.fullmatch(r"[0-9]{1,20}", event_id) or not slug:
            continue
        item = scraper._parse_event(element)
        if not item:
            continue
        from roomquest.mapsee_adapter import timestamp
        item["dtstart"] = timestamp(element.findtext("StartDate"), source["timezone"])
        item["dtend"] = timestamp(element.findtext("EndDate"), source["timezone"])
        if item["dtend"] is not None and item["dtend"] <= item["dtstart"]:
            continue
        # Some API slugs already end in EventID, others do not. The public
        # detail route requires it; a year suffix alone must not become an ID.
        suffix = slug if slug.endswith("-" + event_id) else slug + "-" + event_id
        item["url"] = base_url + "/events/details/" + quote(suffix, safe="-")
        record = _preview(item.get("title"), item.get("dtstart"), item.get("dtend"),
                          item.get("location"), None, None, item.get("url"), event_id,
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


SUPPORTED = {"ical", "jsonld", "growthzone", "wordpress", "squarespace"}


def preview_source(source: dict, *, deadline_at=None) -> dict:
    from roomquest import maryland_sources, nebraska_library_ics
    from roomquest import holly_hill_sources, omaha_lincoln
    from roomquest import civic_local_calendars, civic_schedule, legistar, municipal_notices, virginia_civic
    source_key = source.get('source_key')
    from roomquest import chesapeake_library, visit_norfolk
    if source_key in (chesapeake_library.KEY, visit_norfolk.KEY):
        adapter = chesapeake_library if source_key == chesapeake_library.KEY else visit_norfolk
        deadline = min(monotonic() + 32, deadline_at - 8 if deadline_at is not None else float('inf'))
        try:
            records = adapter.collect(source, lambda url, accept: fetch_publisher(
                url, accept, respect_robots=True, deadline_at=deadline,
                allowed_hosts=(adapter.HOST,)))
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}', reason) else 'invalid_calendar_payload') from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {'p_source_key': source_key, 'p_samples': samples, 'p_future_count': len(records),
                'p_venue_count': sum(row['lat'] is not None for row in records),
                'p_error': None, 'p_events': records}
    if (source_key in legistar.SOURCES or source_key in virginia_civic.SOURCES
            or source_key in municipal_notices.SOURCES or source_key in civic_local_calendars.SOURCES
            or source_key == civic_schedule.PUBLIC_WORKS_KEY):
        try:
            if source_key == civic_schedule.PUBLIC_WORKS_KEY:
                expected = civic_schedule.public_works_source()
                if (type(source.get('civic_contract_version')) is not int
                        or any(source.get(key) != value for key, value in expected.items()
                               if key != 'civic_jurisdiction_name')):
                    raise ValueError('unregistered_public_works_source')
                hosts = (urlparse(expected['feed_url']).hostname,)
                collect = civic_schedule.collect_public_works
            else:
                module = next(adapter for adapter in (legistar, municipal_notices, virginia_civic, civic_local_calendars)
                              if source_key in adapter.SOURCES)
                spec = module.validate(source)
                hosts = (legistar.HOST,) if module is legistar else spec['hosts']
                collect = module.collect
            # DMV's fixed first page has at most ten rows (one staging batch)
            # and advertises a 30-second robots delay. Use the available caller
            # budget for that normal admission wait; never extend its deadline.
            # The ordinary category lane still reserves its outer four seconds.
            source_seconds, reserve_seconds = (36, 2) if source_key == virginia_civic.DMV else (25, 8)
            deadline = min(monotonic() + source_seconds,
                           deadline_at - reserve_seconds if deadline_at is not None else float('inf'))
            records = collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=hosts), deadline_at=deadline)
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}', reason) else 'invalid_civic_payload') from exc
        if len(records) > 500:
            raise PreviewError('source_record_limit')
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {'p_source_key': source_key, 'p_samples': samples,
                'p_future_count': len(records),
                'p_venue_count': sum(row.get('lat') is not None for row in records),
                'p_error': None, 'p_events': records}
    if source_key in holly_hill_sources.SOURCES:
        try:
            spec = holly_hill_sources.validate(source)
            deadline = min(monotonic() + 36, deadline_at - 8 if deadline_at is not None else float('inf'))
            records = holly_hill_sources.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=spec['hosts']), deadline_at=deadline,
                fetch_elloree=lambda: render_elloree_calendar(deadline_at=deadline),
                fetch_programs=lambda: render_old_santee_programs(deadline_at=deadline))
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}', reason) else 'invalid_holly_hill_payload') from exc
        if len(records) > 500:
            raise PreviewError('holly_hill_record_limit')
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        result = {'p_source_key': source_key, 'p_samples': samples,
                  'p_future_count': len(records),
                  'p_venue_count': sum(row.get('lat') is not None for row in records),
                  'p_error': None, 'p_events': records}
        if holly_hill_sources.publisher_media(source):
            result['p_parser_capability'] = 'publisher_event_candidates_v1'
        return result
    if source_key in nebraska_library_ics.SOURCES:
        try:
            nebraska_library_ics.validate(source)
        except ValueError as exc:
            raise PreviewError(str(exc)) from exc
    if source.get("kind", "ical") == "ical" and source.get("platform_adapter") == "ical":
        from roomquest.ics_adapter import parse
        source_key = source.get("source_key", "")
        civic_ics = source_key in VIRGINIA_CIVIC_ICS
        raleigh_ics = source_key in RALEIGH_CATALOG_ICS
        raleigh_url = RALEIGH_CATALOG_ICS.get(source_key) or RALEIGH_UDELL_ICS.get(source_key)
        if raleigh_url and source.get("feed_url") != raleigh_url:
            raise PreviewError("unregistered_raleigh_catalog_ics")
        if civic_ics and (source.get("feed_url") != VIRGINIA_CIVIC_ICS[source_key]
                          or source.get("timezone") != "America/New_York"):
            raise PreviewError("unregistered_virginia_civic_ics")
        mapsee = source_key.startswith("municipal_mapsee_")
        if mapsee:
            from roomquest.mapsee_adapter import profiles
            profile = profiles().get(source["source_key"])
            if not profile or profile["type"] != "ics" or profile["url"] != source.get("feed_url"):
                raise PreviewError("unregistered_mapsee_source")
        deadline = min(monotonic() + 20, deadline_at - 8 if deadline_at is not None else float("inf"))
        try:
            if source_key in nebraska_library_ics.SOURCES:
                payload = fetch_publisher(source["feed_url"], "text/calendar", respect_robots=True,
                                          deadline_at=deadline, allowed_hosts=(urlparse(source["feed_url"]).hostname,))
                records = nebraska_library_ics.collect(source, payload)
            elif source_key in omaha_lincoln.new_ical_feeds():
                records = omaha_lincoln.collect(source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=(urlparse(omaha_lincoln.new_ical_feeds()[source_key]).hostname,)))
            elif source_key in maryland_sources.ICS:
                records = maryland_sources.collect_ics(source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=(urlparse(maryland_sources.ICS[source_key]).hostname,)))
            else:
                host_scope = {}
                if civic_ics or raleigh_url:
                    host_scope["allowed_hosts"] = (urlparse(source["feed_url"]).hostname,)
                payload = fetch_publisher(
                    source["feed_url"], "text/calendar",
                    respect_robots=civic_ics or bool(raleigh_url) or mapsee
                    or source_key in {"mecklenburg_va_libraries", "sarpy_tourism_ne"},
                    deadline_at=deadline, **host_scope)
                calendar_source = {"url": source["feed_url"], "source_key": source_key,
                                   **{key: source[key] for key in ('timezone', 'civic_contract_version',
                                      'civic_jurisdiction_id', 'civic_jurisdiction_name') if key in source}}
                records = parse(payload, calendar_source, legacy=not mapsee,
                                include_description=civic_ics or raleigh_ics or source_key == "independence_ia_library_family")
                if civic_ics:
                    from roomquest.ics_adapter import normalize_virginia_civic
                    records = normalize_virginia_civic(records, source["feed_url"])
            if source.get('source_key') == 'independence_ia_library_family':
                from roomquest.iowa_civicplus import enrich
                records = enrich(records, source, fetch_publisher, deadline)
        except PreviewError:
            # Transport errors are already safe, bounded codes (including HTTP digits).
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r"[a-z_]{3,100}", reason) else "invalid_calendar_payload") from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {"p_source_key": source["source_key"], "p_samples": samples,
                "p_future_count": len(records), "p_venue_count": sum(r["lat"] is not None for r in records),
                "p_error": None, "p_events": records}
    from roomquest.community_formats import SOURCES as format_sources
    if (source.get("source_key") in format_sources or source.get("platform_adapter") == "library" or
            (source.get("platform_adapter") == "wordpress" and source.get("kind") == "rss")):
        from roomquest.community_formats import collect
        deadline = min(monotonic() + 20, deadline_at - 8 if deadline_at is not None else float("inf"))
        try:
            records = collect(source, lambda url, accept: fetch_publisher(
                url, accept, respect_robots=True, deadline_at=deadline))
        except PreviewError:
            # Transport errors are already safe, bounded codes (including HTTP digits).
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r"[a-z_]{3,100}", reason) else "invalid_calendar_payload") from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {"p_source_key": source["source_key"], "p_samples": samples,
                "p_future_count": len(records),
                "p_venue_count": sum(1 for row in records if row["lat"] is not None),
                "p_error": None, "p_events": records}
    if source.get("platform_adapter") == "south_carolina_parks" and source.get("kind") == "json":
        from roomquest.south_carolina_parks import collect
        deadline = min(monotonic() + 30, deadline_at - 8 if deadline_at is not None else float("inf"))
        try:
            records = collect(source, lambda url, accept: fetch_publisher(
                url, accept, respect_robots=True, deadline_at=deadline), deadline_at=deadline)
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r"[a-z_]{3,100}", reason) else "invalid_calendar_payload") from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {"p_source_key": source["source_key"], "p_samples": samples,
                "p_future_count": len(records), "p_venue_count": 0,
                "p_error": None, "p_events": records,
                "p_parser_capability": "publisher_event_candidates_v1"}
    if source.get("platform_adapter") == "revize" and source.get("kind") == "json":
        from roomquest.revize import collect
        from roomquest.south_hill_markets import collect as collect_markets
        deadline = min(monotonic() + 30, deadline_at - 8 if deadline_at is not None else float("inf"))
        try:
            guarded_fetch = lambda url, accept: fetch_publisher(
                url, accept, respect_robots=True, deadline_at=deadline,
                allowed_hosts=("www.southhillva.gov",))
            records = collect(source, guarded_fetch, deadline_at=deadline)
            # Older backend claims do not yet accept market evidence URLs.
            # Enable the supplement only after the exact source advertises its
            # deployed contract; booleans are not capability version numbers.
            if (type(source.get('south_hill_market_contract_version')) is int
                    and source['south_hill_market_contract_version'] == 1):
                records.extend(collect_markets(source, guarded_fetch, deadline_at=deadline))
                if len(records) > 500 or len({row['id'] for row in records}) != len(records):
                    raise ValueError('town_source_record_identity_limit')
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r"[a-z_]{3,100}", reason) else "invalid_revize_payload") from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {"p_source_key": source["source_key"], "p_samples": samples,
                "p_future_count": len(records),
                "p_venue_count": sum(1 for row in records if row["lat"] is not None),
                "p_error": None, "p_events": records,
                "p_parser_capability": "publisher_event_candidates_v1"}
    # Independent HTML family with explicit, publisher-specific dispatch.
    if source.get("platform_adapter") == "html" and source.get("kind") == "html":
        source_key = str(source.get("source_key", ""))
        html_budget = 36
        from roomquest.raleigh_html import SOURCES as RALEIGH_SOURCES
        from roomquest.virginia_wix_events import SOURCES as VA_WIX_SOURCES
        from roomquest import maryland_public_calendars, maryland_park_programs
        from roomquest.nebraska_venues import SOURCES as NEBRASKA_VENUES
        if source_key in NEBRASKA_VENUES:
            from roomquest.nebraska_venues import collect as collect_html
            allowed_hosts = (urlparse(NEBRASKA_VENUES[source_key]).hostname,)
        elif source_key in maryland_public_calendars.SOURCES:
            collect_html = maryland_public_calendars.collect
            allowed_hosts = (urlparse(maryland_public_calendars.SOURCES[source_key]).hostname,)
        elif source_key in maryland_park_programs.SOURCES:
            collect_html = maryland_park_programs.collect
            allowed_hosts = (maryland_park_programs.HOST,)
        elif source_key in RALEIGH_SOURCES:
            from roomquest.raleigh_html import collect as collect_html
            allowed_hosts = (urlparse(RALEIGH_SOURCES[source_key][0]).hostname,)
        elif source_key in VA_WIX_SOURCES:
            from roomquest.virginia_wix_events import collect as collect_html
            allowed_hosts = (urlparse(VA_WIX_SOURCES[source_key][0]).hostname,)
        elif source_key == 'visit_farmville_va':
            from roomquest.visit_farmville import collect as collect_html
            allowed_hosts = ('visitfarmville.com',)
        elif source_key == 'prizery_va':
            from roomquest.prizery import collect as collect_html
            allowed_hosts = ('prizery.org',)
        elif source_key == 'red_door_104_va':
            from roomquest.red_door_104 import collect as collect_html
            allowed_hosts = ('www.reddoor104.com',)
        elif source_key == 'south_boston_speedway_va':
            from roomquest.south_boston_speedway import HOST, collect as collect_html
            allowed_hosts = (HOST,)
        elif source_key == 'discover_halifax_va':
            # Manual/older claims have no fenced continuation contract. Keep
            # their original bounded window until the backend advertises v1.
            from roomquest.discover_halifax import collect_legacy as collect_html
            allowed_hosts = ('gohalifaxva.com',)
        elif source_key == 'shady_shack_bracey_va':
            from roomquest.shady_shack import collect as collect_html
            allowed_hosts = ('shadyshackgrill.com',)
        elif source_key == 'mcgregor_hall_henderson_nc':
            from roomquest.mcgregor_hall import collect as collect_html
            allowed_hosts = ('www.mcgregorhall.org',)
        elif source_key == 'victoria_town_calendar_va':
            from roomquest.victoria_calendar import collect as collect_html
            allowed_hosts = ('victoriava.net',)
        elif source_key == 'vance_county_arts_council_nc':
            from roomquest.vance_arts import collect as collect_html
            allowed_hosts = ('vanceartscouncil.com',)
        elif source_key == 'sova_innovation_hub_va':
            from roomquest.sova_workshops import HOST, collect as collect_html
            allowed_hosts = (HOST,)
        elif source_key == 'council_bluffs_public_library_ia':
            from roomquest.council_bluffs_library import HOST, collect as collect_html
            allowed_hosts = (HOST,)
        elif source_key == 'experience_waterloo_ia':
            from roomquest.waterloo import collect as collect_html, API_HOST
            allowed_hosts = ('experiencewaterloo.com', API_HOST)
        elif source_key in ('unleashcb_ia', 'visit_mason_city_ia'):
            from roomquest.iowa_tourism import collect as collect_html
            allowed_hosts = (urlparse(source['feed_url']).hostname,)
        elif source_key.startswith("mycountyparks_ia_"):
            from roomquest.mycountyparks import collect as collect_html
            allowed_hosts = ("www.mycountyparks.com",)
        elif source_key.startswith("virginia_state_parks_"):
            from roomquest.virginia_state_parks import IMAGE_EXTRACTOR_VERSION, collect as collect_html
            allowed_hosts = ("www.dcr.virginia.gov",)
        elif source_key == "bellevue_times_ne":
            from roomquest.bellevue_times import collect as collect_html
            allowed_hosts = ("bellevuetimes.com",)
            html_budget = 30
        elif source_key == "chase_city_chamber_va":
            from roomquest.chase_city_chamber import collect as collect_html
            allowed_hosts = ("chasecitychamber.com",)
            html_budget = 20
        elif source_key == "municipal_749460d8567ccf71cade6771":
            from roomquest.neon_district import HOST, collect as collect_html
            allowed_hosts = (HOST,)
        elif source_key == "municipal_38cad94cfdc8628a8ce8ee90":
            from roomquest.lynnhaven_river import HOST, collect as collect_html
            allowed_hosts = (HOST,)
        elif source_key == "municipal_5effc448d9e900b8cdd14958":
            from roomquest.hampton_roads_chamber import HOST, collect as collect_html
            allowed_hosts = (HOST,)
        elif source_key == "south_hill_chamber_va":
            from roomquest.south_hill_chamber import collect as collect_html
            allowed_hosts = ("members.southhillchamber.com",)
        elif source_key == "clarksville_community_players_va":
            from roomquest.clarksville_players import collect as collect_html
            allowed_hosts = ("clarksvilleplayers.org",)
        elif source_key == "maccallum_more_va":
            from roomquest.maccallum_more import collect as collect_html
            allowed_hosts = ("maccallummore.org",)
        elif source_key == "mecklenburg_ymca_programs_va":
            from roomquest.mecklenburg_ymca import collect as collect_html
            allowed_hosts = ("mecklenburg.recliquecore.com", "mecklenburgcountyymca.org")
        elif source_key == "coopers_landing_clarksville_va":
            from roomquest.coopers_landing import collect as collect_html
            allowed_hosts = ("cooperslandinginn.net",)
        elif source_key == "clarksville_tourism_va":
            from roomquest.clarksville_tourism import collect as collect_html
            allowed_hosts = ("tourism.visitclarksvilleva.com",)
        elif source_key == "good_shepherd_food_pantry_south_hill_va":
            from roomquest.good_shepherd import collect as collect_html
            allowed_hosts = ("goodshepherdsouthhill.org",)
        elif source_key in maryland_sources.HTML:
            collect_html = maryland_sources.collect_html
            allowed_hosts = (urlparse(maryland_sources.HTML[source_key]).hostname,)
            html_budget = 36
        else:
            raise PreviewError("unregistered_html_source")
        deadline = min(monotonic() + html_budget, deadline_at - 5 if deadline_at is not None else float("inf"))
        try:
            extra = {}
            if source_key == 'good_shepherd_food_pantry_south_hill_va':
                extra['render_calendar'] = lambda *, nonce, args: render_good_shepherd_calendar(
                    nonce=nonce, args=args, deadline_at=deadline)
            records = collect_html(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=allowed_hosts,
                ), deadline_at=deadline, **extra)
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r"[a-z_]{3,100}", reason) else "invalid_html_event_payload") from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        result = {"p_source_key": source["source_key"], "p_samples": samples,
                  "p_future_count": len(records),
                  "p_venue_count": sum(1 for row in records if row["lat"] is not None),
                  "p_error": None, "p_events": records}
        if source_key in maryland_public_calendars.SOURCES or source_key in maryland_park_programs.SOURCES:
            return result  # These public facts use the v2 preview RPC without media evidence.
        if source_key.startswith("virginia_state_parks_"):
            # Capability evidence also accompanies successful empty results.
            result["p_parser_capability"] = IMAGE_EXTRACTOR_VERSION
        else:
            result["p_parser_capability"] = "publisher_event_candidates_v1"
        return result
    if source.get("platform_adapter") == "chambermate":
        from roomquest.chambermate import API_HOST, collect as collect_chambermate
        deadline = min(monotonic() + 20, deadline_at - 8 if deadline_at is not None else float("inf"))
        try:
            records = collect_chambermate(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=(API_HOST,),
                ), deadline_at=deadline)
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r"[a-z_]{3,100}", reason) else "invalid_chambermate_payload") from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {"p_source_key": source["source_key"], "p_samples": samples,
                "p_future_count": len(records),
                "p_venue_count": sum(1 for row in records if row["lat"] is not None),
                "p_error": None, "p_events": records}
    # WordPress is a collection family; Mapsee remains catalog provenance.
    if source.get("platform_adapter") == "wordpress" and source.get("kind") == "json":
        from roomquest.wordpress_adapter import collect as collect_wordpress
        maryland = source_key in (maryland_sources.PG_PARKS, maryland_sources.ARTS)
        if source.get("source_key", "").startswith("municipal_mapsee_"):
            from roomquest.mapsee_adapter import profiles
            profile = profiles().get(source["source_key"])
            if not profile or profile["type"] != "tribe" or profile["url"] != source.get("feed_url"):
                raise PreviewError("unregistered_mapsee_source")
        deadline = min(monotonic() + (35 if maryland else 20), deadline_at - 8 if deadline_at is not None else float("inf"))
        try:
            if maryland:
                host = urlparse(source['feed_url']).hostname
                records = maryland_sources.collect_wordpress(source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline, allowed_hosts=(host,)))
            else:
                records = collect_wordpress(source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline), deadline_at=deadline)
        except PreviewError:
            # Transport errors are already safe, bounded codes (including HTTP digits).
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r"[a-z_]{3,100}", reason) else "invalid_calendar_payload") from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {**({"p_parser_capability": "publisher_event_candidates_v1"}
                   if maryland or source_key in ('madison_county_parks_ia', 'think_iowa_city_ia', 'rosemont_of_virginia', 'longwood_basketball_va', 'hurrdat_sports_bar_ne') else {}),
                "p_source_key": source["source_key"], "p_samples": samples,
                "p_future_count": len(records),
                "p_venue_count": sum(1 for row in records if row["lat"] is not None),
                "p_error": None, "p_events": records}
    if source.get("platform_adapter") == "jsonld" and source.get("kind") == "json":
        from roomquest.jsonld_adapter import collect as collect_jsonld
        if source.get("source_key", "").startswith("municipal_mapsee_"):
            from roomquest.mapsee_adapter import profiles
            profile = profiles().get(source["source_key"])
            if not profile or profile["type"] != "jsonld" or profile["url"] != source.get("feed_url"):
                raise PreviewError("unregistered_mapsee_source")
        else:
            raise PreviewError("unregistered_jsonld_source")
        deadline = min(monotonic() + 20, deadline_at - 8 if deadline_at is not None else float("inf"))
        try:
            records = collect_jsonld(source, lambda url, accept: fetch_publisher(
                url, accept, respect_robots=True, deadline_at=deadline))
        except PreviewError:
            # Transport errors are already safe, bounded codes (including HTTP digits).
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r"[a-z_]{3,100}", reason) else "invalid_calendar_payload") from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {"p_source_key": source["source_key"], "p_samples": samples,
                "p_future_count": len(records),
                "p_venue_count": sum(1 for row in records if row["lat"] is not None),
                "p_error": None, "p_events": records}
    if source.get("platform_adapter") == "squarespace" and source.get("kind") == "json":
        from roomquest.squarespace import SOURCES, collect as collect_squarespace
        if source.get("source_key", "").startswith("municipal_mapsee_"):
            from roomquest.mapsee_adapter import profiles
            profile = profiles().get(source["source_key"])
            if not profile or profile["type"] != "squarespace" or profile["url"] != source.get("feed_url"):
                raise PreviewError("unregistered_mapsee_source")
        elif source.get("feed_url") not in SOURCES:
            raise PreviewError("unregistered_squarespace_source")
        deadline = min(monotonic() + 20, deadline_at - 8 if deadline_at is not None else float("inf"))
        try:
            records = collect_squarespace(source, lambda url, accept: fetch_publisher(
                url, accept, respect_robots=True, deadline_at=deadline))
        except PreviewError:
            # Transport errors are already safe, bounded codes (including HTTP digits).
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r"[a-z_]{3,100}", reason) else "invalid_calendar_payload") from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {"p_source_key": source["source_key"], "p_samples": samples,
                "p_future_count": len(records),
                "p_venue_count": sum(1 for row in records if row["lat"] is not None),
                "p_error": None, "p_events": records}
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
        except PreviewError:
            # Transport errors are already safe, bounded codes (including HTTP digits).
            raise
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
        "application/json" if adapter in {"wordpress", "squarespace"} else "text/html,application/xml"
    )
    from roomquest.sarpy_tourism import KEY as SARPY_TOURISM, URL as SARPY_URL
    sarpy_tourism = source.get("source_key") == SARPY_TOURISM
    if sarpy_tourism and (url != SARPY_URL or adapter != "ical" or source.get("kind") != "ical"):
        raise PreviewError("unregistered_sarpy_tourism")
    chambermaster = source.get("source_key", "").startswith("municipal_chambermaster_")
    if adapter == "squarespace":
        from roomquest.squarespace import SOURCES
        if url not in SOURCES:
            raise PreviewError("unregistered_squarespace_source")
    payload = fetch_publisher(url, accept, respect_robots=True, deadline_at=deadline_at) if chambermaster or sarpy_tourism or adapter == "squarespace" else fetch_publisher(url, accept)
    try:
        if sarpy_tourism:
            from roomquest.sarpy_tourism import collect
            events = collect(source, payload)
        elif adapter == "ical":
            from roomquest.ics_adapter import parse
            events = parse(payload, {"url": url}, legacy=True)
        elif adapter == "squarespace":
            from roomquest.squarespace import parse
            events = parse(payload, source)
        elif adapter == "jsonld":
            events = parse_jsonld_preview(payload)
        elif adapter == "growthzone":
            if chambermaster:
                from roomquest.chambermaster import collect
                events = collect(source, payload, min(monotonic() + 34, deadline_at or float("inf")))
            else:
                events = parse_growthzone_preview(payload, source)
        else:
            events = parse_wordpress_preview(payload, source)
    except PreviewError:
        raise
    except (ValueError, TypeError, KeyError) as exc:
        raise PreviewError("invalid_calendar_payload") from exc
    from roomquest.reviewed_chambers import SOURCES as REVIEWED_CHAMBERS
    reviewed_chamber = source.get('source_key') in REVIEWED_CHAMBERS
    unique = {((row.get("id") or row.get("title") or ""), row["starts_at"]): row for row in events}
    records = sorted(unique.values(), key=lambda row: (row["starts_at"], row["title"]))[:500]
    return {
        "p_source_key": source["source_key"], "p_samples": records[:MAX_PREVIEWS],
        "p_future_count": len(records),
        "p_venue_count": sum(1 for row in records if row["lat"] is not None),
        "p_error": None,
        "p_events": records if reviewed_chamber or sarpy_tourism else records[:100],
        **({"p_parser_capability": "publisher_event_candidates_v1"} if reviewed_chamber else {}),
    }


def supabase_rpc(path: str, payload: dict, *, timeout: float = 4):
    """Call ONLY the preview-scoped RPCs. The service_role key never leaves Supabase.

    Supabase's publishable API key identifies the project but grants no privileged
    role. A separate 256-bit, rotated collector token authorizes only these two
    security-definer RPCs. The token must never enter a public client or log.
    """
    import urllib.request
    allowed = {"community_collector_claim_category", "community_collector_publish_category", "community_collector_finish_category", "community_collector_claim_previews", "community_collector_claim_demand_preview", "community_collector_claim_chambermaster", "community_collector_record_preview", "community_collector_record_preview_v2", "community_collector_record_preview_v3",
               "community_collector_read_fetch_checkpoint", "community_collector_write_fetch_checkpoint",
               "community_collector_record_staged_events", "community_collector_geocoder", "community_collector_geocoder_claim",
               "community_collector_venues", "community_collector_media", "community_collector_media_demand"}
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
        with urllib.request.urlopen(request, timeout=timeout) as response:
            # Only the private, fenced fetch checkpoint may contain the complete
            # bounded aggregate. All other RPCs retain their existing limit.
            maximum = 920_000 if path == "community_collector_read_fetch_checkpoint" else 150_000
            raw = response.read(maximum + 1)
            if len(raw) > maximum:
                raise PreviewError("database_unavailable")
            return json.loads(raw.decode()) if raw else None
    except (HTTPError, URLError, ValueError, OSError) as exc:
        raise PreviewError("database_unavailable") from exc


def _observe_collection_phase(observer, phase, *, operation=None, error=None):
    """Optional diagnostics only: an observer cannot fail collection or recording."""
    if observer is not None:
        try:
            observer(phase, operation=operation, error=error)
        except Exception:
            pass


def _process_claimed_source(source: dict, *, deadline_at=None, publisher_handoff=None,
                            observe_phase=None, collection_context=None) -> dict:
    """Process a single claimed feed with the existing private staging contract."""
    with capture_publisher_pacing() as pacing:
        return _process_claimed_source_with_pacing(
            source, pacing, deadline_at=deadline_at, publisher_handoff=publisher_handoff,
            observe_phase=observe_phase, collection_context=collection_context)


def _preview_halifax_chunk(source, pacing, *, collection_context, deadline_at,
                           publisher_handoff=None, observe_phase=None):
    """Persist one fenced HTML fetch chunk before any staging can begin."""
    from roomquest import discover_halifax

    operation = None
    try:
        if (not isinstance(collection_context, dict)
                or collection_context.get("p_category") != "html"
                or not isinstance(collection_context.get("p_ticket"), str)
                or not collection_context["p_ticket"]):
            raise PreviewError("fetch_checkpoint_context_missing")
        args = {"p_category": "html", "p_ticket": collection_context["p_ticket"],
                "p_source_key": source["source_key"]}
        operation = "community_collector_read_fetch_checkpoint"
        _observe_collection_phase(observe_phase, "fetch", operation=operation)
        saved = supabase_rpc(operation, args)
        if (not isinstance(saved, dict) or type(saved.get("revision")) is not int
                or saved["revision"] < 0 or "checkpoint" not in saved
                or (saved["checkpoint"] is not None and not isinstance(saved["checkpoint"], dict))
                or (saved["checkpoint"] is None and saved["revision"] != 0)):
            raise PreviewError("fetch_checkpoint_invalid_response")
        operation = None
        _observe_collection_phase(observe_phase, "fetch")
        # Match the ordinary HTML fetch budget while reserving checkpoint write,
        # staging and completed-preview time inside the claimed source budget.
        deadline = min(monotonic() + 36, deadline_at - 9)
        try:
            chunk = discover_halifax.collect_chunk(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=("gohalifaxva.com",)),
                checkpoint=saved["checkpoint"], deadline_at=deadline)
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            # Adapter messages are controlled diagnostics, never raw HTML or
            # parser values (for example an unparseable publisher clock).
            codes = {"unregistered_discover_halifax", "halifax_checkpoint_invalid",
                     "halifax_checkpoint_size_limit", "halifax_directory_incomplete",
                     "halifax_directory_event_identity", "halifax_directory_detail_identity",
                     "halifax_directory_detail_conflict", "collection_deadline"}
            reason = exc.args[0] if len(exc.args) == 1 else None
            raise PreviewError(reason if type(reason) is str and reason in codes
                               else "invalid_html_event_payload") from exc
        if pacing["wait_unbounded"]:
            raise PreviewError("publisher_wait_requires_review")
        operation = "community_collector_write_fetch_checkpoint"
        _observe_collection_phase(observe_phase, "fetch", operation=operation)
        acknowledged = supabase_rpc(operation, {
            **args, "p_expected_revision": saved["revision"],
            "p_checkpoint": chunk["checkpoint"], **pacing_rpc_fields(pacing)})
        if (not isinstance(acknowledged, dict) or acknowledged.get("checkpoint_saved") is not True
                or type(acknowledged.get("revision")) is not int
                or acknowledged["revision"] != saved["revision"] + 1):
            raise PreviewError("fetch_checkpoint_invalid_response")
        if publisher_handoff is not None:
            publisher_handoff["ready_at"] = monotonic() + max(
                1, pacing["crawl_delay_seconds"], pacing["retry_after_seconds"])
        if not chunk["complete"]:
            return {"fetch_pending": True}
        # A complete cursor is durable before the ordinary staging path starts.
        # Its database row is cleared atomically by successful preview recording.
        records = chunk["events"]
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {"p_source_key": source["source_key"], "p_samples": samples,
                "p_future_count": len(records), "p_venue_count": sum(
                    row.get("lat") is not None for row in records),
                "p_error": None, "p_events": records,
                "p_parser_capability": "publisher_event_candidates_v1"}
    except Exception as exc:
        _observe_collection_phase(observe_phase, "fetch", operation=operation, error=exc)
        raise


def _process_claimed_source_with_pacing(source, pacing, *, deadline_at=None, publisher_handoff=None,
                                       observe_phase=None, collection_context=None):
    phase, failure = "collection", {}
    operation = None
    try:
        _observe_collection_phase(observe_phase, "fetch")
        deadline = min(monotonic() + 43, deadline_at or float("inf"))
        if (source.get("source_key") == "discover_halifax_va" and collection_context is not None
                and type(source.get("fetch_checkpoint_version")) is int
                and source["fetch_checkpoint_version"] == 1):
            output = _preview_halifax_chunk(
                source, pacing, collection_context=collection_context, deadline_at=deadline,
                publisher_handoff=publisher_handoff, observe_phase=observe_phase)
            if output.get("fetch_pending"):
                return {"complete": 0, "failed": 0, "staged": 0, "fetch_pending": True}
        else:
            output = preview_source(source, deadline_at=deadline - 4)
        if pacing["wait_unbounded"]:
            raise PreviewError("publisher_wait_requires_review")
        events = output.pop("p_events", [])
        phase = "staging"
        _observe_collection_phase(observe_phase, "stage")
        staged = 0
        # Keep each transaction below the API statement budget. Completion is
        # recorded only after every bounded batch has been accepted.
        batches, batch, size = [], [], 2
        for event in events:
            event_size = len(json.dumps(event, ensure_ascii=False)) + 2
            if batch and (len(batch) >= STAGING_BATCH_SIZE or size + event_size > 150_000):
                batches.append(batch)
                batch, size = [], 2
            batch.append(event)
            size += event_size
        batches.append(batch)
        for batch in batches:
            operation = None
            _observe_collection_phase(observe_phase, "stage")
            if monotonic() > deadline - 4:
                raise PreviewError("staging_deadline")
            operation = "community_collector_record_staged_events"
            _observe_collection_phase(observe_phase, "stage", operation=operation)
            written = supabase_rpc("community_collector_record_staged_events", {
                "p_source_key": source["source_key"], "p_events": batch
            })
            staged += int(written or 0)
    except (PreviewError, OSError, ValueError) as exc:
        _observe_collection_phase(observe_phase, "fetch" if phase == "collection" else "stage",
                                  operation=operation, error=exc)
        output = {
            "p_source_key": source["source_key"], "p_samples": [],
            "p_future_count": 0, "p_venue_count": 0,
            "p_error": str(exc)[:120] if isinstance(exc, PreviewError) else "source_parse_error",
        }
        staged = 0
        failure = failure_details(output["p_error"],
                                  expected_source_error=isinstance(exc, PreviewError), phase=phase)
    # A failed result is returned only after its source error/hold has been
    # recorded. If this RPC fails, the exception remains a worker failure.
    html = source.get("kind") == "html" and source.get("platform_adapter") == "html"
    ical = source.get("kind") == "ical" and source.get("platform_adapter") == "ical"
    source_key = str(source.get('source_key', ''))
    from roomquest import civic_local_calendars, civic_schedule, legistar, municipal_notices, virginia_civic
    civic = (source_key in legistar.SOURCES or source_key in virginia_civic.SOURCES
             or source_key in municipal_notices.SOURCES or source_key in civic_local_calendars.SOURCES
             or source_key == civic_schedule.PUBLIC_WORKS_KEY)
    from roomquest.reviewed_chambers import SOURCES as REVIEWED_CHAMBERS
    reviewed_chamber = (source_key in REVIEWED_CHAMBERS and source.get('kind') == 'xml'
                        and source.get('platform_adapter') == 'growthzone')
    from roomquest.raleigh_html import SOURCES as RALEIGH_SOURCES
    from roomquest.virginia_wix_events import SOURCES as VA_WIX_SOURCES
    from roomquest.maryland_sources import ARTS, HTML as MARYLAND_HTML, PG_PARKS
    from roomquest.nebraska_venues import SOURCES as NEBRASKA_VENUES
    publisher_media = (html and (source_key in NEBRASKA_VENUES or source_key in RALEIGH_SOURCES or source_key in MARYLAND_HTML or source_key in VA_WIX_SOURCES or source_key in ('visit_farmville_va', 'prizery_va', 'red_door_104_va', 'south_boston_speedway_va', 'discover_halifax_va', 'sova_innovation_hub_va'))) or reviewed_chamber or (source_key in ('madison_county_parks_ia', 'think_iowa_city_ia', 'rosemont_of_virginia', 'longwood_basketball_va', 'hurrdat_sports_bar_ne', ARTS, PG_PARKS) and source.get('kind') == 'json'
                       and source.get('platform_adapter') == 'wordpress') or (html and (source_key.startswith(('virginia_state_parks_', 'mycountyparks_ia_'))
                                or source_key in ('council_bluffs_public_library_ia', 'bellevue_times_ne', 'unleashcb_ia', 'visit_mason_city_ia', 'chase_city_chamber_va', 'experience_waterloo_ia',
                                                  'south_hill_chamber_va', 'clarksville_community_players_va',
                                                  'maccallum_more_va', 'mecklenburg_ymca_programs_va',
                                                  'coopers_landing_clarksville_va', 'clarksville_tourism_va',
                                                  'good_shepherd_food_pantry_south_hill_va'))) or source.get('platform_adapter') == 'south_carolina_parks' or (
                        source_key == 'south_hill_town_va' and source.get('kind') == 'json'
                        and source.get('platform_adapter') == 'revize')
    publisher_media = publisher_media or (html and source_key in (
        'shady_shack_bracey_va', 'mcgregor_hall_henderson_nc',
        'victoria_town_calendar_va', 'vance_county_arts_council_nc'))
    from roomquest.holly_hill_sources import publisher_media as holly_hill_media
    publisher_media = publisher_media or holly_hill_media(source)
    preview_rpc = ("community_collector_record_preview_v3"
                   if publisher_media
                   else "community_collector_record_preview_v2" if html or ical or civic
                   else "community_collector_record_preview")
    _observe_collection_phase(observe_phase, "record", operation=preview_rpc)
    if html or ical or publisher_media or civic:
        supabase_rpc(preview_rpc, {**output, **pacing_rpc_fields(pacing)})
        if publisher_handoff is not None and not pacing["wait_unbounded"]:
            # The server starts its durable wait while recording the preview.
            # Starting our estimate after the RPC returns cannot shorten it.
            # The separate recent-preview host guard also requires one second,
            # even when the publisher did not advertise a delay. This local
            # handoff state never enters an RPC payload or response result.
            publisher_handoff["ready_at"] = monotonic() + max(
                1, pacing["crawl_delay_seconds"], pacing["retry_after_seconds"])
    else:
        supabase_rpc("community_collector_record_preview", output)
    return {"complete": int(output["p_error"] is None),
            "failed": int(output["p_error"] is not None), "staged": staged, **failure}


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


def collect_demand_previews() -> dict:
    """Refresh at most one source requested by the iCal publisher."""
    claimed = supabase_rpc("community_collector_claim_demand_preview", {})
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
