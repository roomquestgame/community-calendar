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
import ipaddress
import json
import os
import re
import socket
import requests
from roomquest.activity_request_admission import before_request as activity_before_request
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlsplit
from urllib.parse import urljoin
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from roomquest.collector_errors import failure_details
from roomquest import publisher_robots_checkpoint as robots_checkpoint
from roomquest.publisher_robots_policy import PublisherRobotsPolicy
from roomquest.publisher_pacing import (capture_publisher_pacing, observe_crawl_delay,
                                       observe_retry_after, pacing_rpc_fields, robots_crawl_delay)
from roomquest.incremental_snapshot import capture_snapshot, current_snapshot

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
ROBOTS_CACHE_SECONDS = robots_checkpoint.TTL_SECONDS
MAX_ROBOTS_HOSTS = 128
_robots_cache = OrderedDict()
_robots_cache_lock = Lock()
_publisher_next = {}
_publisher_retry_after = {}
_publisher_lock = Lock()


class PreviewError(ValueError):
    """Expected, safely reportable source failure."""


def _publisher_body_limit(url, accept, allowed_hosts, respect_robots):
    # Two reviewed current calendar PDFs are 12.8/15.9MB. Keep the ordinary limit
    # everywhere else, including redirects to a different object on this CDN.
    from roomquest import atlantic_city_pdf_programs
    if atlantic_city_pdf_programs.reviewed_large_document(
            url, accept, allowed_hosts, respect_robots):
        return atlantic_city_pdf_programs.MAX_PDF
    return MAX_BODY


class RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise PreviewError("redirect_blocked")


class ReviewedRobotsRedirects(RejectRedirects):
    """Allow only reviewed robots redirects."""
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # Reviewed Nov 21: Django appends a slash to this absent robots route,
        # whose destination returns an ordinary 404. Recheck the original every
        # cache window; newly published rules and access denials remain binding.
        if (request.full_url == 'https://cambridgesouthhockeyclub.co.uk/robots.txt'
                and newurl == 'https://cambridgesouthhockeyclub.co.uk/robots.txt/'
                and code == 301 and request.get_method() == 'GET'):
            validate_public_dns('cambridgesouthhockeyclub.co.uk')
            activity_before_request(newurl, auxiliary=True, redirect=True)
            return Request(newurl, headers={
                'User-Agent': 'RoomQuestCommunityCalendar/0.1 (community-event research)'
            }, method='GET')
        # Observed November 6: this API host routes a nonexistent robots file
        # to its vendor's explicit 404 endpoint. Recheck the original each
        # cache window so newly published rules are still authoritative.
        if (request.full_url == 'https://eyqhj2iy2m-dsn.algolia.net/robots.txt'
                and newurl == 'https://algolia.net/1/404'
                and code in (301, 302, 307, 308)):
            validate_public_dns('algolia.net')
            activity_before_request(newurl, auxiliary=True, redirect=True)
            return Request(newurl, headers={
                'User-Agent': 'RoomQuestCommunityCalendar/0.1 (community-event research)'
            }, method='GET')
        # The club serves its robots rules at this same-origin WordPress endpoint.
        if (request.full_url == 'https://omaharun.org/robots.txt'
                and newurl == 'https://omaharun.org/?robots=1'
                and code in (301, 302, 303, 307, 308)):
            validate_public_dns('omaharun.org')
            activity_before_request(newurl, auxiliary=True, redirect=True)
            return Request(newurl, headers={
                'User-Agent': 'RoomQuestCommunityCalendar/0.1 (community-event research)'
            }, method='GET')
        # Observed November 14: Night Shift publishes its robots policy at
        # this exact same-origin WordPress endpoint, not a challenge page.
        if (request.full_url == 'https://nightshiftbrewing.com/robots.txt'
                and newurl == 'https://nightshiftbrewing.com/?robots=1'
                and code == 301 and request.get_method() == 'GET'):
            validate_public_dns('nightshiftbrewing.com')
            activity_before_request(newurl, auxiliary=True, redirect=True)
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


def _robots_utc_now():
    return datetime.now(timezone.utc)


def _cache_robots(host, parser, *, raw=None, status=200):
    # Age a policy from its completed response, not a shared wall-clock bucket.
    # A policy fetched just before a five-minute boundary must not expire a
    # moment later while that same publisher's crawl delay is still running.
    evidence = robots_checkpoint.response_evidence(
        host, raw, status, now=_robots_utc_now()) if raw is not None else None
    with _robots_cache_lock:
        _robots_cache[host] = (monotonic() + ROBOTS_CACHE_SECONDS, parser, evidence)
        _robots_cache.move_to_end(host)
        while len(_robots_cache) > MAX_ROBOTS_HOSTS:
            _robots_cache.popitem(last=False)
    return parser


def _parse_robots_policy(host, raw):
    """One policy parser for fetched responses and authenticated fresh caches."""
    lines = raw.decode("utf-8-sig", errors="replace").splitlines()
    # A soft-404 app shell or structured error is not an empty robots policy.
    # Ignore actual robots comments, but never cache a recognizable HTML/XML/
    # JSON document as permission. Keep ordinary empty and sitemap-only files.
    if any(line.lstrip().startswith(("<", "{", "["))
           for line in lines if line.strip() and not line.lstrip().startswith("#")):
        raise PreviewError("robots_unavailable")
    parser = PublisherRobotsPolicy(lines)
    delay = robots_crawl_delay(lines, robots_checkpoint.PERMISSION_USER_AGENT)
    if host in ("nytransitmuseum.org", "www.nytransitmuseum.org"):
        # The reviewed orphan directive remains a pacing floor on cache restore.
        delay = max(10, delay)
    return parser, delay


def _restore_checkpoint_robots(source, snapshot):
    restored = robots_checkpoint.restore(source, snapshot,
        secret=os.environ.get("ROOMQUEST_COLLECTOR_TOKEN", ""), now=_robots_utc_now())
    if restored is None:
        return False
    host = robots_checkpoint.profile(source)
    now, clock = _robots_utc_now(), monotonic()
    remaining = (restored["expires_at"] - now).total_seconds()
    if remaining <= 0:
        return False
    parser, delay = (_parse_robots_policy(host, restored["raw"])
                     if restored["status"] == 200 else (None, 1))
    if delay > 86400:
        return False
    with _publisher_lock:
        # Never shorten a stronger wait already observed in this process.
        _publisher_next[host] = max(_publisher_next.get(host, 0),
            clock + max(0, (restored["not_before"] - now).total_seconds()))
        retry = restored["retry_after_until"]
        if retry is not None:
            _publisher_retry_after[host] = max(_publisher_retry_after.get(host, 0),
                clock + max(0, (retry - now).total_seconds()))
    with _robots_cache_lock:
        cached = _robots_cache.get(host)
        # Never knowingly prefer an older allow over a newer deny, in either
        # direction. Legacy cache entries have no portable age evidence.
        if cached is not None and cached[0] > clock:
            local_fetched = robots_checkpoint.evidence_fetched_at(cached[2] if len(cached) > 2 else None)
            if local_fetched is None or local_fetched >= restored["fetched_at"]:
                return True
        _robots_delays[host] = delay
        evidence = robots_checkpoint.response_evidence(host, restored["raw"], restored["status"],
                                                      now=restored["fetched_at"])
        _robots_cache[host] = (clock + remaining, parser, evidence)
        _robots_cache.move_to_end(host)
        while len(_robots_cache) > MAX_ROBOTS_HOSTS:
            _robots_cache.popitem(last=False)
    return True


def _checkpoint_robots_snapshot(source):
    host = robots_checkpoint.profile(source)
    if host is None:
        return None
    now, clock = _robots_utc_now(), monotonic()
    with _robots_cache_lock:
        cached = _robots_cache.get(host)
        if cached is None or cached[0] <= clock or len(cached) < 3 or cached[2] is None:
            return None
        evidence = cached[2]
    with _publisher_lock:
        wait = max(0, _publisher_next.get(host, clock) - clock,
                   _publisher_retry_after.get(host, clock) - clock)
        retry = max(0, _publisher_retry_after.get(host, clock) - clock)
    return robots_checkpoint.seal(source, evidence,
        not_before=now + timedelta(seconds=wait),
        retry_after_until=now + timedelta(seconds=retry) if retry else None,
        secret=os.environ.get("ROOMQUEST_COLLECTOR_TOKEN", ""), now=now)


def _robots_request_path(url):
    """Retain path parameters and query in the exact outgoing request target."""
    parsed = urlsplit(url)
    return (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")


def _checkpoint_publisher_ready(source, url, deadline):
    """Radegast may persist a robots-only phase instead of losing cold progress."""
    host, parsed = robots_checkpoint.profile(source), urlparse(url)
    if not public_source_url(url) or parsed.netloc != host:
        raise PreviewError("redirect_host_not_approved")
    validate_public_dns(host)
    path = _robots_request_path(url)
    if not robots_allowed(host, path, deadline_at=deadline):
        raise PreviewError("robots_denied")
    try:
        # Leave the existing twelve-second adapter guard for the calendar GET.
        # This admission does not reserve a request that has not occurred.
        pace_publisher(host, deadline - 12, reserve=False)
    except PreviewError as exc:
        if str(exc) == "publisher_pacing_deferred":
            return False
        raise
    return True


def _robots_rules(host: str, *, deadline_at: float | None = None):
    """Cache each publisher's rules for five minutes after a valid response.

    Only exact reviewed robots redirects are permitted; every
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
            "User-Agent": robots_checkpoint.ROBOTS_USER_AGENT
        })
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise PreviewError("source_fetch_deadline")
        activity_before_request(robots_url, auxiliary=True)
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
            return _cache_robots(host, None, raw=b"", status=exc.code)
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
    parser, _robots_delays[host] = _parse_robots_policy(host, raw)
    # The newly learned delay also separates this robots response from the
    # first calendar request. An oversized value is held before that request.
    _reserve_known_crawl_delay(host)
    return _cache_robots(host, parser, raw=raw, status=200)


def robots_allowed(host: str, path: str, *, deadline_at: float | None = None) -> bool:
    """Evaluate the current path against cached, publisher-specific rules."""
    parser = _robots_rules(host, deadline_at=deadline_at)
    _, unbounded = observe_crawl_delay(_robots_delays.get(host, 1))
    if unbounded:
        raise PreviewError("publisher_wait_requires_review")
    return parser is None or parser.can_fetch(robots_checkpoint.PERMISSION_USER_AGENT, "https://" + host + path)


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


def _html_declared_charset(payload: bytes) -> str | None:
    """Accept only explicit, supported early HTML charset declarations."""
    match = re.search(
        rb"<meta\s+[^>]*charset\s*=\s*['\"]?([a-zA-Z0-9._-]+)",
        payload[:4096], flags=re.I)
    if not match:
        return None
    label = match.group(1).decode("ascii").lower()
    return label if label in ("utf-8", "utf8", "windows-1252", "iso-8859-1") else None


def fetch_publisher(url: str, accept: str, *, respect_robots: bool = False,
                    deadline_at: float | None = None, allowed_hosts=None,
                    follow_redirects: bool = True) -> str | bytes:
    """Fetch an approved public source with the existing bounded GET transport."""
    return _fetch_publisher_request(url, accept, respect_robots=respect_robots,
                                    deadline_at=deadline_at, allowed_hosts=allowed_hosts,
                                    follow_redirects=follow_redirects)


def fetch_visit_raleigh_page(url: str, *, deadline_at=None) -> str:
    """Read the exact public Raleigh query, retaining ordinary access guards."""
    from roomquest.visit_raleigh import HOST
    return _fetch_publisher_request(url, 'application/json', respect_robots=True,
        deadline_at=deadline_at, allowed_hosts=(HOST,), visit_raleigh_api=True)


def render_cfengage_calendar(*, deadline_at: float | None = None) -> str:
    """Read the anonymous display endpoint used by CFengage's public calendar."""
    from roomquest.richmond_public_calendars import CF_API, CF_HOST, calendar_form
    return _fetch_publisher_request(
        CF_API, 'application/json', respect_robots=True, deadline_at=deadline_at,
        allowed_hosts=(CF_HOST,), calendar_form=calendar_form())


def _valid_boston_cares_window(start_day, end_day):
    if any(not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)
           for value in (start_day, end_day)):
        return False
    try:
        start, end = date.fromisoformat(start_day), date.fromisoformat(end_day)
        today = datetime.now(ZoneInfo('America/New_York')).date()
        return (timedelta(0) < end - start <= timedelta(days=14)
                and today - timedelta(days=1) <= start <= today + timedelta(days=14)
                and end <= today + timedelta(days=28))
    except ValueError:
        return False


def render_boston_cares_calendar(*, start_day, end_day, deadline_at=None):
    """Read Boston Cares' exact anonymous public calendar display operation.

    Only a bounded date window is caller supplied. No action, account,
    registration, destination URL or arbitrary form fields can be submitted.
    """
    if not _valid_boston_cares_window(start_day, end_day):
        raise PreviewError('invalid_calendar_render_parameters')
    return _fetch_publisher_request(
        'https://www.bostoncares.org/search/getOpportunitiesCalendar',
        'application/json', respect_robots=True, deadline_at=deadline_at,
        allowed_hosts=('www.bostoncares.org',), calendar_form={
            'searchvo_startfrom': start_day, 'searchvo_endfrom': end_day,
            'searchvo_searchresultblockid': '589'})


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


def _virginia_beach_cultural_window():
    start = datetime.now(ZoneInfo('America/New_York')).date()
    end = start + timedelta(days=60)
    return {'startDate': f'{start.isoformat()}T00:00', 'endDate': f'{end.isoformat()}T23:59',
            'productionSeasonIdFilter': [], 'keywordIds': None}


def render_virginia_beach_cultural_calendar(*, deadline_at: float | None = None) -> str:
    """Read the anonymous Tessitura calendar listing with a bounded date window."""
    from roomquest.virginia_beach_cultural import API, HOST
    return _fetch_publisher_request(
        API, 'application/json', respect_robots=True, deadline_at=deadline_at,
        allowed_hosts=(HOST,), calendar_json=_virginia_beach_cultural_window())


def _valid_cardboard_calendar_window(starts_at, ends_at):
    pattern = r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z'
    if any(not isinstance(value, str) or not re.fullmatch(pattern, value)
           for value in (starts_at, ends_at)):
        return False
    try:
        start, end = (datetime.fromisoformat(value.replace('Z', '+00:00'))
                      for value in (starts_at, ends_at))
        return timedelta(0) < end - start <= timedelta(days=62)
    except ValueError:
        return False


def render_cardboard_arena_calendar(*, starts_at, ends_at, deadline_at=None):
    """Read one store's public dated event list using its public routing ID."""
    from urllib.parse import urlencode
    if not _valid_cardboard_calendar_window(starts_at, ends_at):
        raise PreviewError('invalid_cardboard_calendar_parameters')
    url = ('https://api.carde.io/api/play/establishments/'
           '0571b1bc-5f97-40ac-bd29-b73170f3df8b/events?' + urlencode({
               'startsAt': starts_at, 'endsAt': ends_at, 'limit': '100', 'page': '1'}))
    return _fetch_publisher_request(url, 'application/json', respect_robots=True,
        deadline_at=deadline_at, allowed_hosts=('api.carde.io',), cardboard_arena_calendar=True)


def render_artspace_calendar(*, year, month, atts, window_start, deadline_at=None):
    """Read the publisher's exact anonymous MEC month-display operation."""
    from roomquest.raleigh_direct_arts import ARTSPACE_API, artspace_calendar_form
    try:
        form = artspace_calendar_form(year, month, atts, window_start)
    except ValueError as exc:
        raise PreviewError('invalid_calendar_render_parameters') from exc
    return _fetch_publisher_request(ARTSPACE_API, 'application/json', respect_robots=True,
        deadline_at=deadline_at, allowed_hosts=('artspacenc.org',), calendar_form=form)


def read_game_theory_events(*, public_key, window_start, window_end, deadline_at=None):
    """Read the store's public event table using its frontend publishable key.

    The key is extracted from the official public calendar by the adapter. It
    never enters checkpoints or logs and is scoped to one host, route and query.
    """
    from roomquest.raleigh_direct_community import GAME_API_HOST, game_theory_request
    try:
        url = game_theory_request(public_key, window_start, window_end)
    except ValueError as exc:
        raise PreviewError('invalid_game_theory_request') from exc
    return _fetch_publisher_request(url, 'application/json', respect_robots=True,
        deadline_at=deadline_at, allowed_hosts=(GAME_API_HOST,), game_theory_key=public_key)


def read_raleigh_followup_events(*, request_kind, page=None, offset=None,
                                 public_instance=None, deadline_at=None):
    """Read the two reviewed publishers' exact anonymous display operations.

    Caller input cannot select an arbitrary endpoint, JSON body or header.
    Wix's public frontend instance remains local to this request and is never
    persisted in a checkpoint. Both transports retain the ordinary robots,
    DNS, pacing, deadline, response-type and body-size controls.
    """
    from roomquest import raleigh_followup_performance as calendars
    if request_kind in {'chapel_bootstrap', 'chapel_page'}:
        if offset is not None or public_instance is not None:
            raise PreviewError('invalid_chapel_calendar_request')
        try:
            url, body = calendars.chapel_calendar_request(page=page,
                bootstrap=request_kind == 'chapel_bootstrap')
        except ValueError as exc:
            raise PreviewError('invalid_chapel_calendar_request') from exc
        return _fetch_publisher_request(url, 'application/json', respect_robots=True,
            deadline_at=deadline_at, allowed_hosts=('www.tickpick.com',), chapel_calendar_body=body)
    if request_kind == 'comedyworx_page':
        if page is not None:
            raise PreviewError('invalid_comedyworx_calendar_request')
        try:
            url = calendars.comedyworx_calendar_url(offset)
        except ValueError as exc:
            raise PreviewError('invalid_comedyworx_calendar_request') from exc
        if not calendars.valid_comedyworx_calendar_request(url, public_instance):
            raise PreviewError('invalid_comedyworx_calendar_request')
        return _fetch_publisher_request(url, 'application/json', respect_robots=True,
            deadline_at=deadline_at, allowed_hosts=('www.comedyworx.com',), comedyworx_instance=public_instance)
    raise PreviewError('unregistered_raleigh_followup_source')


def read_raleigh_brewing_occurrences(*, event_id, offset, public_instance, deadline_at=None):
    """Use the public calendar's exact dated-occurrences operation."""
    from roomquest import raleigh_next_social as calendars
    try:
        url = calendars.brewing_occurrences_url(event_id, offset)
    except ValueError as exc:
        raise PreviewError('invalid_raleigh_brewing_request') from exc
    if not calendars.valid_brewing_occurrences_request(url, public_instance):
        raise PreviewError('invalid_raleigh_brewing_request')
    return _fetch_publisher_request(url, 'application/json', respect_robots=True,
        deadline_at=deadline_at, allowed_hosts=('www.raleighbrewing.com',), brewing_instance=public_instance)


def read_liberty_public_action(*, script_url, script, getter, deadline_at=None):
    """Read one of the current public calendar's two anonymous bootstrap getters.

    The action is extracted from the page's fetched same-origin script, never
    accepted as a caller-selected identifier. No body, headers or other action
    names can be supplied. The transient response is excluded from checkpoints.
    """
    from roomquest import liberty_calendar as calendar
    return _fetch_publisher_request(calendar.ORIGINAL, 'text/x-component', respect_robots=True,
        deadline_at=deadline_at, allowed_hosts=(calendar.HOST,), follow_redirects=False,
        liberty_action=(script_url, script, getter))


def read_liberty_events(*, page, window_start, public_token, deadline_at=None):
    """Read only the bounded published-events view with its anonymous token."""
    from roomquest import liberty_calendar as calendar
    if not calendar.valid_public_token(public_token):
        raise PreviewError('invalid_liberty_events_request')
    try:
        url = calendar.events_url(page=page, window_start=window_start)
    except ValueError:
        raise PreviewError('invalid_liberty_events_request') from None
    return _fetch_publisher_request(url, 'application/json', respect_robots=True,
        deadline_at=deadline_at, allowed_hosts=(calendar.API_HOST,), follow_redirects=False,
        liberty_token=public_token)


def _fetch_publisher_request(url: str, accept: str, *, respect_robots: bool = False,
                             deadline_at: float | None = None, allowed_hosts=None,
                             calendar_form=None, calendar_json=None, localhop_app_id=None,
                             cardboard_arena_calendar=False, visit_raleigh_api=False,
                             game_theory_key=None, chapel_calendar_body=None,
                             comedyworx_instance=None, brewing_instance=None,
                             liberty_action=None, liberty_token=None,
                             follow_redirects: bool = True) -> str | bytes:
    """Use the shared bounded transport for approved HTTPS publisher content.

    Keep URL/DNS validation and bounded downloads. As in upstream Udell,
    fetch registered calendar endpoints directly without a robots preflight;
    destination URLs still pass public-network checks before each GET redirect.
    Reviewed display-only POSTs are source scoped and never redirected.
    """
    liberty_action_id = None
    if liberty_action is not None or liberty_token is not None:
        from roomquest import liberty_calendar as calendar
        exclusive = (respect_robots and follow_redirects is False
            and calendar_form is None and calendar_json is None and localhop_app_id is None
            and cardboard_arena_calendar is False and visit_raleigh_api is False
            and game_theory_key is None and chapel_calendar_body is None
            and comedyworx_instance is None and brewing_instance is None)
        if liberty_action is not None:
            if (not exclusive or liberty_token is not None or url != calendar.ORIGINAL
                    or accept != 'text/x-component' or allowed_hosts != (calendar.HOST,)
                    or not isinstance(liberty_action, tuple) or len(liberty_action) != 3):
                raise PreviewError('invalid_liberty_action_request')
            try:
                liberty_action_id = calendar.action_reference(*liberty_action)
            except ValueError:
                raise PreviewError('invalid_liberty_action_request') from None
        elif (not exclusive or accept != 'application/json' or allowed_hosts != (calendar.API_HOST,)
                or not calendar.valid_events_request(url, liberty_token)):
            raise PreviewError('invalid_liberty_events_request')
    if brewing_instance is not None:
        from roomquest import raleigh_next_social as calendars
        if (not respect_robots or accept != 'application/json' or allowed_hosts != ('www.raleighbrewing.com',)
                or calendar_form is not None or calendar_json is not None or localhop_app_id is not None
                or cardboard_arena_calendar is not False or visit_raleigh_api is not False
                or game_theory_key is not None or chapel_calendar_body is not None or comedyworx_instance is not None
                or not calendars.valid_brewing_occurrences_request(url, brewing_instance)):
            raise PreviewError('invalid_raleigh_brewing_request')
    if chapel_calendar_body is not None or comedyworx_instance is not None:
        from roomquest import raleigh_followup_performance as calendars
        exclusive = (respect_robots and accept == 'application/json'
            and calendar_form is None and calendar_json is None and localhop_app_id is None
            and cardboard_arena_calendar is False and visit_raleigh_api is False and game_theory_key is None)
        if chapel_calendar_body is not None:
            if (not exclusive or comedyworx_instance is not None or allowed_hosts != ('www.tickpick.com',)
                    or not calendars.valid_chapel_calendar_request(url, chapel_calendar_body)):
                raise PreviewError('invalid_chapel_calendar_request')
        elif (not exclusive or allowed_hosts != ('www.comedyworx.com',)
                or not calendars.valid_comedyworx_calendar_request(url, comedyworx_instance)):
            raise PreviewError('invalid_comedyworx_calendar_request')
    if game_theory_key is not None:
        from roomquest.raleigh_direct_community import GAME_API_HOST, valid_game_theory_request
        if (not respect_robots or accept != 'application/json'
                or allowed_hosts != (GAME_API_HOST,)
                or not valid_game_theory_request(url, game_theory_key)
                or calendar_form is not None or calendar_json is not None
                or localhop_app_id is not None or cardboard_arena_calendar is not False
                or visit_raleigh_api is not False):
            raise PreviewError('invalid_game_theory_request')
    if visit_raleigh_api is not False:
        from roomquest import visit_raleigh
        if (visit_raleigh_api is not True or not respect_robots or accept != 'application/json'
                or allowed_hosts != (visit_raleigh.HOST,) or not visit_raleigh.valid_api_url(url)
                or calendar_form is not None or calendar_json is not None
                or localhop_app_id is not None or cardboard_arena_calendar is not False):
            raise PreviewError('invalid_visit_raleigh_request')
    if cardboard_arena_calendar is not False:
        from urllib.parse import parse_qs
        parsed = urlparse(url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if (cardboard_arena_calendar is not True or not respect_robots
                or accept != 'application/json' or allowed_hosts != ('api.carde.io',)
                or calendar_form is not None or calendar_json is not None or localhop_app_id is not None
                or parsed.scheme != 'https' or parsed.netloc != 'api.carde.io' or parsed.fragment
                or parsed.path != '/api/play/establishments/0571b1bc-5f97-40ac-bd29-b73170f3df8b/events'
                or set(query) != {'startsAt', 'endsAt', 'limit', 'page'}
                or query.get('limit') != ['100'] or query.get('page') != ['1']
                or len(query.get('startsAt', [])) != 1 or len(query.get('endsAt', [])) != 1
                or not _valid_cardboard_calendar_window(query['startsAt'][0], query['endsAt'][0])):
            raise PreviewError('invalid_cardboard_calendar_parameters')
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
        cultural = (url == 'https://culture.virginiabeach.gov/api/products/productionseasons'
                    and accept == 'application/json' and allowed_hosts == ('culture.virginiabeach.gov',)
                    and isinstance(calendar_json, dict) and calendar_json == _virginia_beach_cultural_window())
        if calendar_form is not None or not respect_robots or not (elloree or recdesk or cultural):
            raise PreviewError('invalid_calendar_render_parameters')
        render_content_type = 'text/html' if recdesk else 'application/json'
        json_referer = ('https://elloreesc.com/elloree-town-calendar/' if elloree
                        else 'https://oldsanteecanal.recdesk.com/Community/Program')
        if cultural:
            json_referer = 'https://culture.virginiabeach.gov/events'
        if recdesk:
            json_content_type = 'application/json; charset=utf-8'
    cfengage_form = False
    eventon_form = False
    boston_cares_form = False
    artspace_form = False
    if calendar_form is not None:
        from roomquest.richmond_public_calendars import CF_API, CF_HOST, calendar_form as cfengage_window
        cfengage_form = (url == CF_API and accept == 'application/json' and respect_robots
                         and allowed_hosts == (CF_HOST,) and calendar_form == cfengage_window())
        boston_cares_form = (
            url == 'https://www.bostoncares.org/search/getOpportunitiesCalendar'
            and accept == 'application/json' and respect_robots
            and allowed_hosts == ('www.bostoncares.org',)
            and isinstance(calendar_form, dict)
            and set(calendar_form) == {'searchvo_startfrom', 'searchvo_endfrom', 'searchvo_searchresultblockid'}
            and calendar_form.get('searchvo_searchresultblockid') == '589'
            and _valid_boston_cares_window(calendar_form.get('searchvo_startfrom'),
                                          calendar_form.get('searchvo_endfrom')))
        from roomquest.raleigh_direct_arts import ARTSPACE_API, valid_artspace_calendar_form
        artspace_form = (url == ARTSPACE_API and accept == 'application/json' and respect_robots
                         and allowed_hosts == ('artspacenc.org',)
                         and valid_artspace_calendar_form(calendar_form))
        from roomquest import eventon
        eventon_form = (url == eventon.ENDPOINT and accept == 'application/json'
                        and respect_robots and allowed_hosts == (eventon.HOST,)
                        and isinstance(calendar_form, dict) and len(calendar_form) <= 150
                        and all(isinstance(v, str) and len(v) <= 2048
                                for v in calendar_form.values())
                        and re.fullmatch(r'[a-zA-Z0-9]{8,24}', calendar_form.get('nonce', ''))
                        and all(k == 'nonce' or re.fullmatch(
                            r'(?:global|cals\[evcal_calendar_277\]\[sc\])(?:\[[a-zA-Z0-9_-]+\])+', k)
                                for k in calendar_form))
        # A second boundary keeps internal callers from turning this into an
        # arbitrary write-capable transport. Never replay a POST on redirect.
        if not (cfengage_form or eventon_form or boston_cares_form or artspace_form) and (url != 'https://goodshepherdsouthhill.org/wp-admin/admin-ajax.php'
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
    if visit_raleigh_api:
        # The exact bounded query is validated above. The real URL still goes
        # through robots, pacing and the GET; only the generic length check
        # uses this fixed public endpoint, as for other reviewed API queries.
        safe_url = visit_raleigh.API
    elif localhop_app_id is not None:
        from roomquest.nebraska_final import LOCALHOP_API, LOCALHOP_HOST
        if (not url.startswith(LOCALHOP_API + "?") or len(url) > 2400 or not respect_robots
                or allowed_hosts != (LOCALHOP_HOST,) or accept != "application/json"
                or not re.fullmatch(r"[A-Za-z0-9]{20,80}", localhop_app_id)):
            raise PreviewError("invalid_localhop_request")
        safe_url = LOCALHOP_API
    else:
        safe_url = url
    if not public_source_url(safe_url):
        raise PreviewError("invalid_source_url")
    headers = {
        "User-Agent": (robots_checkpoint.PUBLISHER_USER_AGENT if respect_robots
                       else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"),
        "Accept": accept,
    }
    if calendar_form is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8'
        headers['Referer'] = ('https://www.cfengage.org/calendar' if cfengage_form
                              else 'https://goodshepherdsouthhill.org/welcome/calendar/')
        if eventon_form:
            headers['Referer'] = eventon.CALENDAR
        if boston_cares_form:
            headers['Referer'] = 'https://www.bostoncares.org/calendar'
        if artspace_form:
            headers['Referer'] = 'https://artspacenc.org/calendar/'
        if cfengage_form or eventon_form or boston_cares_form or artspace_form:
            headers['X-Requested-With'] = 'XMLHttpRequest'
    elif calendar_json is not None:
        headers['Content-Type'] = json_content_type
        headers['Referer'] = json_referer
    if localhop_app_id is not None:
        headers["X-Parse-Application-Id"] = localhop_app_id
    if game_theory_key is not None:
        headers['apikey'] = game_theory_key
        headers['Authorization'] = 'Bearer ' + game_theory_key
    if chapel_calendar_body is not None:
        headers['Content-Type'] = 'application/json'
    if comedyworx_instance is not None:
        headers['Authorization'] = comedyworx_instance
    if brewing_instance is not None:
        headers['Authorization'] = brewing_instance
    if liberty_action_id is not None:
        headers['Content-Type'] = 'text/plain;charset=UTF-8'
        headers['Next-Action'] = liberty_action_id
        headers['Origin'] = 'https://events.liberty.edu'
    if liberty_token is not None:
        headers['Authorization'] = 'Bearer ' + liberty_token
    if cardboard_arena_calendar:
        # Public GenericEvents routing identity published in the store's SSR.
        # This is neither a credential nor an arbitrary caller-supplied header.
        headers['game-id'] = '2f532764-e06a-494b-9ca1-3e5dfea425ec'
    # Only ordinary public GET representations participate. Conditional headers
    # are available solely inside an independently validated detail request;
    # a moving-window feed must still be fetched and completely parsed.
    incremental = (current_snapshot() if calendar_form is None and calendar_json is None
                   and localhop_app_id is None and not cardboard_arena_calendar and not visit_raleigh_api
                   and game_theory_key is None and chapel_calendar_body is None
                   and comedyworx_instance is None and brewing_instance is None
                   and liberty_action is None and liberty_token is None else None)
    current = url
    admission_deadline = deadline_at if deadline_at is not None else monotonic() + 18
    deadline = min(admission_deadline, monotonic() + 18)
    network_started = False
    unconditional = set()
    with requests.Session() as session:
        for _ in range(5):
            parsed = urlparse(current)
            if allowed_hosts is not None and parsed.hostname not in allowed_hosts:
                raise PreviewError("redirect_host_not_approved")
            if not public_source_url(safe_url if localhop_app_id is not None or visit_raleigh_api else current):
                raise PreviewError("invalid_redirect_url")
            current_deadline = deadline if network_started else admission_deadline
            if respect_robots and monotonic() >= current_deadline:
                raise PreviewError("source_fetch_deadline")
            validate_public_dns(parsed.hostname or "")
            if respect_robots and not robots_allowed(
                    parsed.netloc, _robots_request_path(current),
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
                activity_before_request(current, redirect=current != url)
                if liberty_action_id is not None:
                    response = session.post(current, data=b'[]', headers=headers,
                                            timeout=timeout, stream=True, allow_redirects=False)
                elif chapel_calendar_body is not None:
                    response = session.post(current, data=chapel_calendar_body, headers=headers,
                                            timeout=timeout, stream=True, allow_redirects=False)
                elif calendar_form is None and calendar_json is None:
                    conditional = (incremental.conditional_headers(current, accept)
                                   if incremental is not None and current not in unconditional else {})
                    response = session.get(current, headers={**headers, **conditional}, timeout=timeout,
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
                    if not follow_redirects:
                        response.close()
                        raise PreviewError("redirect_blocked")
                    if calendar_form is not None or calendar_json is not None or localhop_app_id is not None or cardboard_arena_calendar or visit_raleigh_api or game_theory_key is not None or chapel_calendar_body is not None or comedyworx_instance is not None or brewing_instance is not None:
                        response.close()
                        raise PreviewError('calendar_render_redirect_blocked')
                    from urllib.parse import urljoin
                    location = response.headers.get("Location")
                    response.close()
                    if not location:
                        raise PreviewError("redirect_missing_location")
                    current = urljoin(current, location)
                    continue
                if response.status_code == 304 and incremental is not None:
                    response_encoding = response.encoding or "utf-8-sig"
                    if respect_robots and "charset=" not in response.headers.get("Content-Type", "").lower():
                        response_encoding = "utf-8-sig"
                    reused = incremental.revalidated(current, accept, response.headers,
                        encoding=response_encoding, errors="strict" if respect_robots else "replace") if conditional else None
                    response.close()
                    if reused is not None:
                        return reused
                    if conditional and current not in unconditional:
                        # A changed parse representation on304 needs a body.
                        # Retry once within the same redirect/network/deadline
                        # bounds, including normal robots and pacing admission.
                        unconditional.add(current)
                        continue
                    # A 304 without an exact validated normalized representation
                    # is a failed fetch, never a successful empty calendar.
                    raise PreviewError("publisher_http_304")
                if response.status_code != 200:
                    code = response.status_code
                    response.close()
                    raise PreviewError("publisher_http_" + str(code))
                if ((liberty_action is not None or liberty_token is not None)
                        and response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
                        != ('text/x-component' if liberty_action is not None else 'application/json')):
                    response.close()
                    raise PreviewError('invalid_liberty_content_type')
                if (calendar_form is not None and
                        response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
                        not in ({'application/json', 'text/html'} if (cfengage_form or boston_cares_form or artspace_form) else
                                {'application/json'} if eventon_form else {'text/html'})):
                    response.close()
                    raise PreviewError('invalid_calendar_render_content_type')
                if (calendar_json is not None and
                        response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
                        != render_content_type):
                    response.close()
                    raise PreviewError('invalid_calendar_render_content_type')
                if ((cardboard_arena_calendar or game_theory_key is not None or chapel_calendar_body is not None or comedyworx_instance is not None or brewing_instance is not None) and response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
                        != 'application/json'):
                    response.close()
                    raise PreviewError('invalid_calendar_render_content_type')
                if (accept in ('image/jpeg', 'image/png') and response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
                        != accept):
                    response.close()
                    raise PreviewError('invalid_publisher_image_content_type')
                length = int(response.headers.get("Content-Length") or 0)
                body_limit = _publisher_body_limit(current, accept, allowed_hosts, respect_robots)
                if liberty_action is not None:
                    body_limit = min(body_limit, calendar.MAX_ACTION_BYTES)
                if length > body_limit:
                    response.close()
                    raise PreviewError("source_unavailable_or_oversized")
                chunks, size = [], 0
                for chunk in response.iter_content(chunk_size=32768):
                    if respect_robots and monotonic() >= deadline:
                        response.close()
                        raise PreviewError("source_fetch_deadline")
                    size += len(chunk)
                    if size > body_limit:
                        response.close()
                        raise PreviewError("source_too_large")
                    chunks.append(chunk)
                encoding = response.encoding or "utf-8-sig"
                if respect_robots and "charset=" not in response.headers.get("Content-Type", "").lower():
                    # An HTML document can declare its own legacy encoding even
                    # when the HTTP server omits charset. Trust only a literal
                    # publisher declaration, never a guessed lossy fallback.
                    # The payload is already bounded; do not fetch a second time.
                    encoding = "utf-8-sig"
                    if "html" in response.headers.get("Content-Type", "").lower():
                        encoding = _html_declared_charset(b"".join(chunks)) or encoding
                response.close()
                if accept in ('image/jpeg', 'image/png'):
                    payload = b''.join(chunks)
                    signature = b'\xff\xd8\xff' if accept == 'image/jpeg' else b'\x89PNG\r\n\x1a\n'
                    if not payload.startswith(signature):
                        raise PreviewError('invalid_publisher_image')
                    return payload
                if accept == 'application/pdf':
                    payload = b"".join(chunks)
                    if not payload.startswith(b'%PDF-'):
                        raise PreviewError('invalid_publisher_pdf')
                    return payload
                try:
                    payload = b"".join(chunks)
                    decoded = payload.decode(encoding, errors="strict" if respect_robots else "replace")
                    if incremental is not None:
                        reused = incremental.record_body(current, accept, payload, response.headers,
                            encoding=encoding, errors="strict" if respect_robots else "replace")
                        if reused is not None:
                            return reused
                    return decoded
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
                tzid = item["DTSTART"].params.get("TZID")
                if isinstance(tzid, str):
                    try:
                        zone = ZoneInfo(tzid)
                    except (ValueError, ZoneInfoNotFoundError):
                        # A feed may define a custom VTIMEZONE with no IANA key.
                        pass
                    else:
                        if started.astimezone(zone).replace(tzinfo=None) == started.replace(tzinfo=None):
                            record["timezone"] = zone.key
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
    from roomquest import nebraska_public_calendars
    from roomquest.firespring import SOURCES as FIRESPRING_SOURCES
    from roomquest.rockhouse import SOURCES as ROCKHOUSE_SOURCES
    from roomquest import civic_local_calendars, civic_schedule, legistar, municipal_notices, virginia_civic
    source_key = source.get('source_key')
    from roomquest import provider_registration
    from roomquest.registration_formats import source_key as registration_key
    adapter = source.get('platform_adapter')
    url = source.get('feed_url') or ''
    if adapter in provider_registration.FAMILIES and source_key == registration_key(url):
        if source.get('kind') != ('xml' if adapter == 'growthzone' else 'json'):
            raise PreviewError('provider_kind_mismatch')
        deadline = min(monotonic() + 32, deadline_at - 8 if deadline_at is not None else float('inf'))
        def fetch(target, accept):
            return fetch_publisher(target, accept, respect_robots=True, deadline_at=deadline,
                                   allowed_hosts=(urlparse(url).hostname,))
        try:
            profile = provider_registration.read_profile(url, adapter, supabase_rpc)
            records = provider_registration.collect(url, adapter, fetch, deadline=deadline, profile=profile)
        except PreviewError:
            raise
        except (ValueError, KeyError, TypeError, OverflowError, AttributeError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}', reason) else 'invalid_provider_collection') from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {'p_source_key':source_key, 'p_samples':samples, 'p_events':records,
                'p_future_count':len(records), 'p_venue_count':sum(row.get('lat') is not None for row in records),
                'p_error':None}
    from roomquest import raleigh_direct_sources
    if raleigh_direct_sources.adapter_for(source_key) is not None:
        try:
            raleigh_direct_sources.validate_source(source)
        except ValueError as exc:
            raise PreviewError('unregistered_raleigh_direct_source') from exc
        raise PreviewError('publisher_checkpoint_required')
    if source_key == 'visit_raleigh_nc':
        from roomquest.visit_raleigh import validate_source
        try:
            validate_source(source)
        except ValueError as exc:
            raise PreviewError('unregistered_visit_raleigh') from exc
        # Thousands of dated occurrences require a durable complete snapshot.
        raise PreviewError('publisher_checkpoint_required')
    from roomquest import boston_sources
    if boston_sources.adapter_for(source_key) is not None:
        try:
            adapter = boston_sources.validate_source(source)
            if source_key in boston_sources.checkpoint_keys():
                raise PreviewError('publisher_checkpoint_required')
            deadline = min(monotonic() + 36,
                           deadline_at - 8 if deadline_at is not None else float('inf'))
            extra = {}
            if source_key == 'boston_cares_ma':
                extra['render_calendar'] = lambda **window: render_boston_cares_calendar(
                    **window, deadline_at=deadline)
            records = adapter.collect(source, lambda url, accept: fetch_publisher(
                url, accept, respect_robots=True, deadline_at=deadline,
                allowed_hosts=adapter.ALLOWED_HOSTS[source_key]), deadline_at=deadline, **extra)
            boston_sources.validate_records(records, source)
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            code = str(exc)
            raise PreviewError(code if code in boston_sources.diagnostic_codes()
                               else 'invalid_boston_payload') from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {'p_source_key': source_key, 'p_samples': samples,
                'p_future_count': len(records),
                'p_venue_count': sum(row.get('lat') is not None for row in records),
                'p_error': None, 'p_events': records}
    from roomquest import new_york_sources
    if new_york_sources.adapter_for(source_key) is not None:
        try:
            adapter = new_york_sources.validate_source(source)
            if source_key in new_york_sources.checkpoint_keys():
                raise PreviewError('publisher_checkpoint_required')
            deadline = min(monotonic() + 36,
                           deadline_at - 8 if deadline_at is not None else float('inf'))
            records = adapter.collect(source, lambda url, accept: fetch_publisher(
                url, accept, respect_robots=True, deadline_at=deadline,
                allowed_hosts=adapter.ALLOWED_HOSTS[source_key]), deadline_at=deadline)
            new_york_sources.validate_records(records, source)
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            code = str(exc)
            raise PreviewError(code if code in new_york_sources.diagnostic_codes()
                               else 'invalid_new_york_payload') from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {'p_source_key': source_key, 'p_samples': samples,
                'p_future_count': len(records),
                'p_venue_count': sum(row.get('lat') is not None for row in records),
                'p_error': None, 'p_events': records}
    from roomquest import atlantic_city_community, atlantic_city_venues, visit_atlantic_city
    from roomquest import atlantic_city_stockton, atlantic_city_pdf_programs, greatday_atlantic_city
    from roomquest import atlantic_city_library_chamber, atlantic_city_nightlife_more, atlantic_city_outdoors_more
    from roomquest import atlantic_city_social, atlantic_city_independent_venues
    from roomquest import atlantic_city_recreation, atlantic_city_markets_gaming
    from roomquest import atlantic_city_reviewed_posters, atlantic_city_studio, atlantic_city_cardboard_arena
    from roomquest import atlantic_city_local_community, atlantic_city_local_markets
    from roomquest import atlantic_city_local_recreation, atlantic_city_local_venues
    from roomquest import atlantic_city_remaining_fair, atlantic_city_remaining_inland
    from roomquest import atlantic_city_remaining_balic
    continuation_adapters = (atlantic_city_library_chamber, atlantic_city_nightlife_more,
                             atlantic_city_outdoors_more, atlantic_city_social,
                             atlantic_city_independent_venues, atlantic_city_recreation,
                             atlantic_city_markets_gaming, atlantic_city_reviewed_posters,
                             atlantic_city_studio, atlantic_city_cardboard_arena,
                             atlantic_city_local_community, atlantic_city_local_markets,
                             atlantic_city_local_recreation, atlantic_city_local_venues,
                             atlantic_city_remaining_fair, atlantic_city_remaining_inland,
                             atlantic_city_remaining_balic)
    continuation_adapter = next((module for module in continuation_adapters
                                 if source_key in module.SOURCES), None)
    if (source_key in atlantic_city_community.SOURCES
            or source_key in atlantic_city_venues.SOURCES
            or source_key in atlantic_city_stockton.SOURCES
            or source_key in atlantic_city_pdf_programs.SOURCES
            or source_key == greatday_atlantic_city.KEY
            or continuation_adapter is not None
            or source_key == visit_atlantic_city.SOURCE_KEY):
        if continuation_adapter is not None:
            if source_key in getattr(continuation_adapter, 'CHECKPOINT_KEYS', set()):
                raise PreviewError('publisher_checkpoint_required')
            adapter = continuation_adapter
            hosts = adapter.ALLOWED_HOSTS[source_key]
        elif source_key in atlantic_city_community.SOURCES:
            adapter = atlantic_city_community
            hosts = adapter.ALLOWED_HOSTS[source_key]
        elif source_key in atlantic_city_venues.SOURCES:
            adapter = atlantic_city_venues
            hosts = adapter.SOURCES[source_key][1]
        elif source_key in atlantic_city_stockton.SOURCES:
            adapter = atlantic_city_stockton
            hosts = adapter.ALLOWED_HOSTS[source_key]
        elif source_key in atlantic_city_pdf_programs.SOURCES:
            adapter = atlantic_city_pdf_programs
            hosts = adapter.ALLOWED_HOSTS[source_key]
        elif source_key == greatday_atlantic_city.KEY:
            # Never run the multi-page calendar without a durable snapshot.
            raise PreviewError('publisher_checkpoint_required')
        else:
            # Legacy/manual calls cannot publish a partial tourism manifest.
            # Normal HTML claims use the fenced continuation path below.
            adapter = visit_atlantic_city
            hosts = (adapter.HOST,)
        deadline = min(monotonic() + 36,
                       deadline_at - 8 if deadline_at is not None else float('inf'))
        try:
            records = adapter.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=hosts), deadline_at=deadline)
            if len(records) > 500:
                raise ValueError('atlantic_city_record_limit')
            if any(not isinstance(row.get('description'), str)
                   or not row['description'].strip() or len(row['description']) > 12000
                   or not isinstance(row.get('venue_address'), str)
                   or not row['venue_address'].strip() for row in records):
                raise ValueError('atlantic_city_incomplete_event')
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}', reason)
                               else 'invalid_atlantic_city_payload') from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {'p_source_key': source_key, 'p_samples': samples,
                'p_future_count': len(records),
                'p_venue_count': sum(row.get('lat') is not None for row in records),
                'p_error': None, 'p_events': records}
    from roomquest import anchorage_batch20_dirty_apron
    if source_key in anchorage_batch20_dirty_apron.SOURCES:
        deadline = min(monotonic() + 38,
                       deadline_at - 8 if deadline_at is not None else float('inf'))
        try:
            records = anchorage_batch20_dirty_apron.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=anchorage_batch20_dirty_apron.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if any(not isinstance(row.get('description'), str) or not row['description'].strip()
                   or len(row['description']) > anchorage_batch20_dirty_apron.MAX_DESCRIPTION
                   or row.get('category') != 'create'
                   or row.get('venue_address') != anchorage_batch20_dirty_apron.VENUE[1]
                   or row.get('lat') != anchorage_batch20_dirty_apron.VENUE_LAT or row.get('lng') != anchorage_batch20_dirty_apron.VENUE_LNG
                   or not anchorage_batch20_dirty_apron.event_url(source_key, row.get('event_url'))
                   for row in records):
                raise ValueError('dirty_apron_unverified_event')
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}', reason)
                               else 'invalid_dirty_apron_payload') from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {'p_source_key': source_key, 'p_samples': samples,
                'p_future_count': len(records), 'p_venue_count': len(records),
                'p_error': None, 'p_events': records}
    from roomquest import anchorage_four_valleys
    if source_key in anchorage_four_valleys.SOURCES:
        deadline = min(monotonic() + 38,
                       deadline_at - 8 if deadline_at is not None else float("inf"))
        try:
            records = anchorage_four_valleys.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=anchorage_four_valleys.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if any(
                not anchorage_four_valleys.event_url(source_key, row.get("event_url"))
                or not isinstance(row.get("description"), str)
                or len(row["description"]) > anchorage_four_valleys.MAX_DESCRIPTION
                or row.get("category") != "create"
                or row.get("venue_address") != anchorage_four_valleys.VENUE[1]
                or row.get("timezone") != anchorage_four_valleys.ZONE
                or (row.get("lat"), row.get("lng")) != anchorage_four_valleys.POINT
                or row.get("image_url")
                for row in records):
                raise ValueError("fvcs_unverified_occurrence")
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r"[a-z_]{3,100}", reason)
                               else "fvcs_invalid_payload") from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {"p_source_key": source_key, "p_samples": samples,
                "p_future_count": len(records), "p_venue_count": len(records),
                "p_error": None, "p_events": records}

    from roomquest import anchorage_scottish_club
    if source_key in anchorage_scottish_club.SOURCES:
        deadline = min(monotonic() + 38,
                       deadline_at - 8 if deadline_at is not None else float("inf"))
        try:
            records = anchorage_scottish_club.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=anchorage_scottish_club.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if any(
                not anchorage_scottish_club.event_url(source_key, row.get("event_url"))
                or not isinstance(row.get("description"), str) or not row["description"].strip()
                or len(row["description"]) > anchorage_scottish_club.MAX_DESCRIPTION
                or row.get("category") not in ("festival", "arts_culture")
                or row.get("venue_address") != anchorage_scottish_club.VENUE[1]
                or row.get("timezone") != anchorage_scottish_club.ZONE
                or (row.get("lat"), row.get("lng")) != anchorage_scottish_club.POINT
                or row.get("image_url")
                for row in records):
                raise ValueError("scottish_unverified_occurrence")
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r"[a-z_]{3,100}", reason)
                               else "scottish_invalid_payload") from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {"p_source_key": source_key, "p_samples": samples,
                "p_future_count": len(records), "p_venue_count": len(records),
                "p_error": None, "p_events": records}
    from roomquest import anchorage_trappers_public
    if source_key in anchorage_trappers_public.SOURCES:
        deadline = min(monotonic() + 38,
                       deadline_at - 8 if deadline_at is not None else float("inf"))
        try:
            records = anchorage_trappers_public.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=anchorage_trappers_public.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if any(
                not anchorage_trappers_public.event_url(source_key, row.get("event_url"))
                or not isinstance(row.get("description"), str) or not row["description"].strip()
                or len(row["description"]) > anchorage_trappers_public.MAX_DESCRIPTION
                or row.get("category") != "learn"
                or row.get("venue_address") != anchorage_trappers_public.VENUE[1]
                or row.get("timezone") != anchorage_trappers_public.ZONE
                or (row.get("lat"), row.get("lng")) != anchorage_trappers_public.POINT
                or row.get("image_url")
                for row in records):
                raise ValueError("trappers_unverified_occurrence")
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r"[a-z_]{3,100}", reason)
                               else "trappers_invalid_payload") from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {"p_source_key": source_key, "p_samples": samples,
                "p_future_count": len(records), "p_venue_count": len(records),
                "p_error": None, "p_events": records}
    from roomquest import anchorage_skinny_raven
    if source_key in anchorage_skinny_raven.SOURCES:
        deadline = min(monotonic() + 38,
                       deadline_at - 8 if deadline_at is not None else float("inf"))
        try:
            records = anchorage_skinny_raven.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=anchorage_skinny_raven.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records) > 1 or any(
                    not anchorage_skinny_raven.event_url(source_key, row.get("event_url"))
                    or not isinstance(row.get("description"), str)
                    or not row["description"].strip()
                    or len(row["description"]) > anchorage_skinny_raven.MAX_DESCRIPTION
                    or row.get("category") != "sports"
                    or row.get("timezone") != anchorage_skinny_raven.ZONE
                    or row.get("venue_address") != anchorage_skinny_raven.VENUE[1]
                    or row.get("lat") != anchorage_skinny_raven.POINT[0]
                    or row.get("lng") != anchorage_skinny_raven.POINT[1]
                    or row.get("image_url")
                    for row in records):
                raise ValueError("skinny_raven_unverified_occurrence")
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r"[a-z_]{3,100}", reason)
                               else "invalid_skinny_raven_payload") from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {"p_source_key": source_key, "p_samples": samples,
                "p_future_count": len(records), "p_venue_count": len(records),
                "p_error": None, "p_events": records}
    from roomquest import anchorage_chamber_public
    if source_key in anchorage_chamber_public.SOURCES:
        deadline = min(monotonic() + 38,
                       deadline_at - 8 if deadline_at is not None else float("inf"))
        try:
            records = anchorage_chamber_public.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=anchorage_chamber_public.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if any(
                    not anchorage_chamber_public.event_url(source_key, row.get("event_url"))
                    or not isinstance(row.get("description"), str) or not row["description"].strip()
                    or len(row["description"]) > anchorage_chamber_public.MAX_DESCRIPTION
                    or row.get("category") not in ("learn", "hang_out")
                    or not re.match(r"^\d{1,6}\s", row.get("venue_address") or "")
                    or row.get("timezone") != anchorage_chamber_public.ZONE
                    or row.get("lat") is None or row.get("lng") is None
                    or row.get("image_url")
                    for row in records):
                raise ValueError("chamber_unverified_occurrence")
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r"[a-z_]{3,100}", reason)
                               else "invalid_chamber_data") from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {"p_source_key": source_key, "p_samples": samples,
                "p_future_count": len(records), "p_venue_count": len(records),
                "p_error": None, "p_events": records}
    from roomquest import anchorage_winter_wonder_fest
    if source_key in anchorage_winter_wonder_fest.SOURCES:
        deadline = min(monotonic() + 38,
                       deadline_at - 8 if deadline_at is not None else float('inf'))
        try:
            records = anchorage_winter_wonder_fest.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=anchorage_winter_wonder_fest.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if any(not anchorage_winter_wonder_fest.event_url(source_key, row.get('event_url'))
                   or not isinstance(row.get('description'), str) or not row['description'].strip()
                   or len(row['description']) > anchorage_winter_wonder_fest.MAX_DESCRIPTION
                   or row.get('venue_address') != anchorage_winter_wonder_fest.VENUE[1]
                   or row.get('category') != 'festival'
                   or row.get('lat') != anchorage_winter_wonder_fest.POINT[0]
                   or row.get('lng') != anchorage_winter_wonder_fest.POINT[1]
                   or row.get('image_url')
                   or row.get('timezone') != anchorage_winter_wonder_fest.ZONE
                   for row in records):
                raise ValueError('winter_wonder_fest_incomplete_event')
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}', reason)
                               else 'invalid_winter_wonder_fest_payload') from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {'p_source_key': source_key, 'p_samples': samples,
                'p_future_count': len(records), 'p_venue_count': len(records),
                'p_error': None, 'p_events': records}
    from roomquest import anchorage_batch20_wasilla
    if source_key == anchorage_batch20_wasilla.KEY:
        raise PreviewError("publisher_checkpoint_required")
    from roomquest import anchorage_batch20_aiga
    if source_key in anchorage_batch20_aiga.SOURCES:
        deadline = min(monotonic() + 38,
                       deadline_at - 8 if deadline_at is not None else float('inf'))
        try:
            records = anchorage_batch20_aiga.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=anchorage_batch20_aiga.ALLOWED_HOSTS[source_key]), deadline_at=deadline)
            if any(not isinstance(row.get('description'), str) or not row['description'].strip()
                   or len(row['description']) > anchorage_batch20_aiga.MAX_DESCRIPTION
                   or not isinstance(row.get('venue_address'), str)
                   or not row['venue_address'].strip()
                   or row.get('category') not in ('hang_out',)
                   or row.get('lat') != anchorage_batch20_aiga.VENUE_LAT or row.get('lng') != anchorage_batch20_aiga.VENUE_LNG
                   for row in records):
                raise ValueError('anchorage_aiga_incomplete_event')
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}', reason)
                               else 'invalid_anchorage_aiga_payload') from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {'p_source_key': source_key, 'p_samples': samples,
                'p_future_count': len(records),
                'p_venue_count': sum(row.get('lat') is not None for row in records),
                'p_error': None, 'p_events': records}
    from roomquest import anchorage_batch20_multi
    if source_key in anchorage_batch20_multi.SOURCES:
        deadline = min(monotonic() + 38,
                       deadline_at - 8 if deadline_at is not None else float('inf'))
        try:
            records = anchorage_batch20_multi.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=anchorage_batch20_multi.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if any(not isinstance(row.get('description'), str) or not row['description'].strip()
                   or len(row['description']) > anchorage_batch20_multi.MAX_DESCRIPTION
                   or not isinstance(row.get('venue_address'), str)
                   or not row['venue_address'].strip()
                   or not isinstance(row.get('category'), str)
                   or row['category'].lower() in ('other', '')
                   or row.get('lat') is None or row.get('lng') is None
                   for row in records):
                raise ValueError('anchorage_batch20_multi_incomplete_event')
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}', reason)
                               else 'invalid_anchorage_batch20_multi_payload') from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {'p_source_key': source_key, 'p_samples': samples,
                'p_future_count': len(records),
                'p_venue_count': sum(row.get('lat') is not None for row in records),
                'p_error': None, 'p_events': records}
    from roomquest import anchorage_batch20_tec
    if source_key in anchorage_batch20_tec.SOURCES:
        deadline = min(monotonic() + 38,
                       deadline_at - 8 if deadline_at is not None else float('inf'))
        try:
            records = anchorage_batch20_tec.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=anchorage_batch20_tec.ALLOWED_HOSTS[source_key]), deadline_at=deadline)
            if any(not isinstance(row.get('description'), str) or not row['description'].strip()
                   or len(row['description']) > anchorage_batch20_tec.MAX_DESCRIPTION
                   or not isinstance(row.get('venue_address'), str)
                   or not row['venue_address'].strip()
                   or not isinstance(row.get('category'), str)
                   or row['category'].lower() in ('other', '')
                   or (row.get('lat') is None) != (row.get('lng') is None)
                   for row in records):
                raise ValueError('anchorage_batch20_tec_incomplete_event')
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}', reason)
                               else 'invalid_anchorage_batch20_tec_payload') from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {'p_source_key': source_key, 'p_samples': samples,
                'p_future_count': len(records),
                'p_venue_count': sum(row.get('lat') is not None for row in records),
                'p_error': None, 'p_events': records}
    from roomquest import anchorage_batch20
    if source_key in anchorage_batch20.SOURCES:
        deadline = min(monotonic() + 38,
                       deadline_at - 8 if deadline_at is not None else float('inf'))
        try:
            records = anchorage_batch20.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=anchorage_batch20.ALLOWED_HOSTS[source_key]), deadline_at=deadline)
            if any(not isinstance(row.get('description'), str) or not row['description'].strip()
                   or len(row['description']) > anchorage_batch20.MAX_DESCRIPTION
                   or not isinstance(row.get('venue_address'), str)
                   or not row['venue_address'].strip()
                   or not isinstance(row.get('category'), str)
                   or row['category'].lower() in ('other', '')
                   or (row.get('lat') is None) != (row.get('lng') is None)
                   for row in records):
                raise ValueError('anchorage_batch20_incomplete_event')
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}', reason)
                               else 'invalid_anchorage_batch20_payload') from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {'p_source_key': source_key, 'p_samples': samples,
                'p_future_count': len(records),
                'p_venue_count': sum(row.get('lat') is not None for row in records),
                'p_error': None, 'p_events': records}
    from roomquest import anchorage_expansion
    if source_key in anchorage_expansion.SOURCES:
        deadline = min(monotonic() + 38,
                       deadline_at - 8 if deadline_at is not None else float('inf'))
        try:
            records = anchorage_expansion.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=anchorage_expansion.ALLOWED_HOSTS[source_key]), deadline_at=deadline)
            if any(not isinstance(row.get('description'), str) or not row['description'].strip()
                   or len(row['description']) > anchorage_expansion.MAX_DESCRIPTION
                   or not isinstance(row.get('venue_address'), str)
                   or not row['venue_address'].strip()
                   or not isinstance(row.get('category'), str)
                   or row['category'].lower() in ('other', '')
                   or row.get('lat') is None or row.get('lng') is None for row in records):
                raise ValueError('anchorage_expansion_incomplete_event')
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}', reason)
                               else 'invalid_anchorage_expansion_payload') from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {'p_source_key': source_key, 'p_samples': samples,
                'p_future_count': len(records),
                'p_venue_count': sum(row.get('lat') is not None for row in records),
                'p_error': None, 'p_events': records}
    from roomquest import anchorage_sources
    if source_key in anchorage_sources.SOURCES:
        deadline = min(monotonic() + 36,
                       deadline_at - 8 if deadline_at is not None else float('inf'))
        try:
            records = anchorage_sources.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=anchorage_sources.ALLOWED_HOSTS[source_key]), deadline_at=deadline)
            if any(not isinstance(row.get('description'), str) or not row['description'].strip()
                   or len(row['description']) > anchorage_sources.MAX_DESCRIPTION
                   or not isinstance(row.get('venue_address'), str)
                   or not row['venue_address'].strip() or row.get('category') in ('Other', '', None)
                   for row in records):
                raise ValueError('anchorage_incomplete_event')
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}', reason)
                               else 'invalid_anchorage_payload') from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {'p_source_key': source_key, 'p_samples': samples,
                'p_future_count': len(records),
                'p_venue_count': sum(row.get('lat') is not None for row in records),
                'p_error': None, 'p_events': records}
    from roomquest import bullitt_library_branches
    if source_key in bullitt_library_branches.SOURCES:
        deadline = min(monotonic() + 43,
                       deadline_at - 8 if deadline_at is not None else float('inf'))
        try:
            records = bullitt_library_branches.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=bullitt_library_branches.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records) > bullitt_library_branches.MAX_ITEMS or any(
                not isinstance(row.get('description'),str)
                or len(row['description']) > bullitt_library_branches.MAX_DESCRIPTION
                or not isinstance(row.get('venue_address'),str)
                or not row['venue_address'].strip()
                or row.get('category') not in bullitt_library_branches.CORE
                or row.get('lat') is None or row.get('lng') is None for row in records):
                raise ValueError('bullitt_library_incomplete_event')
        except PreviewError:
            raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_bullitt_library_payload') from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False)) > 18_000:
            samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),
                'p_venue_count':sum(row.get('lat') is not None for row in records),
                'p_error':None,'p_events':records,
                'p_parser_capability':'publisher_event_candidates_v1'}
    from roomquest import beaufort_library_branches
    if source_key in beaufort_library_branches.SOURCES:
        deadline = min(monotonic() + 43,
                       deadline_at - 8 if deadline_at is not None else float('inf'))
        try:
            records = beaufort_library_branches.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=beaufort_library_branches.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records) > beaufort_library_branches.MAX_ITEMS or any(
                not isinstance(row.get('description'),str) or not row['description'].strip()
                or len(row['description']) > beaufort_library_branches.MAX_DESCRIPTION
                or not isinstance(row.get('venue_address'),str) or not row['venue_address'].strip()
                or row.get('category') not in beaufort_library_branches.CORE_CATEGORIES
                or row.get('lat') is None or row.get('lng') is None for row in records):
                raise ValueError('beaufort_library_incomplete_event')
        except PreviewError:
            raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_beaufort_library_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:
            samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),
                'p_venue_count':sum(row.get('lat') is not None for row in records),
                'p_error':None,'p_events':records,
                'p_parser_capability':'publisher_event_candidates_v1'}
    from roomquest import lowcountry_michael_anthonys
    if source_key == lowcountry_michael_anthonys.KEY:
        deadline = min(monotonic() + 43, deadline_at - 8 if deadline_at is not None else float("inf"))
        try:
            records = lowcountry_michael_anthonys.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=lowcountry_michael_anthonys.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records) > lowcountry_michael_anthonys.MAX_DETAILS or any(
                    not lowcountry_michael_anthonys.event_url(row.get("event_url"))
                    or row.get("category") != "learn"
                    or row.get("venue_address") != lowcountry_michael_anthonys.ADDRESS
                    or row.get("lat") != lowcountry_michael_anthonys.LAT
                    or row.get("lng") != lowcountry_michael_anthonys.LNG
                    or row.get("image_url") for row in records):
                raise ValueError("michael_unverified_records")
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r"[a-z_]{3,100}", reason)
                               else "michael_invalid_data") from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {"p_source_key": source_key, "p_samples": samples,
                "p_future_count": len(records),
                "p_venue_count": sum(row.get("lat") is not None for row in records),
                "p_error": None, "p_events": records,
                "p_parser_capability": "publisher_event_candidates_v1"}
    from roomquest import lowcountry_bluffton_chamber
    if source_key == lowcountry_bluffton_chamber.KEY:
        deadline = min(monotonic() + 43,
                       deadline_at - 8 if deadline_at is not None else float("inf"))
        try:
            records = lowcountry_bluffton_chamber.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=lowcountry_bluffton_chamber.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records) > lowcountry_bluffton_chamber.MAX_CANDIDATES or any(
                    not lowcountry_bluffton_chamber.event_url(row.get("event_url"))
                    or row.get("category") != "learn"
                    or not isinstance(row.get("description"), str)
                    or not 80 <= len(row["description"]) <= lowcountry_bluffton_chamber.MAX_DESCRIPTION
                    or row.get("venue_address") != "97 Progressive Street, Bluffton, SC 29910"
                    or row.get("lat") != lowcountry_bluffton_chamber.VENUES["the cove"]["lat"]
                    or row.get("lng") != lowcountry_bluffton_chamber.VENUES["the cove"]["lng"]
                    or row.get("timezone") != lowcountry_bluffton_chamber.ZONE
                    or row.get("image_url") for row in records):
                raise ValueError("bluffton_chamber_unverified_occurrence")
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r"[a-z_]{3,100}", reason)
                               else "bluffton_chamber_invalid_data") from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {"p_source_key": source_key, "p_samples": samples,
                "p_future_count": len(records),
                "p_venue_count": sum(row.get("lat") is not None for row in records),
                "p_error": None, "p_events": records,
                "p_parser_capability": "publisher_event_candidates_v1"}
    from roomquest import lowcountry_palmetto_running
    if source_key == lowcountry_palmetto_running.KEY:
        deadline = min(monotonic() + 43,
                       deadline_at - 8 if deadline_at is not None else float('inf'))
        try:
            records = lowcountry_palmetto_running.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=lowcountry_palmetto_running.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records)>lowcountry_palmetto_running.MAX_DETAILS or any(
                    not row.get('description') or row.get('category')!='sports'
                    or not lowcountry_palmetto_running.event_url(row.get('event_url'))
                    or not row.get('venue_address') or row.get('lat') is None
                    or row.get('lng') is None or row.get('end_time_verified') is not False
                    for row in records):
                raise ValueError('prc_invalid_event')
        except PreviewError:
            raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason=str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_prc_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:
            samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),
                'p_venue_count':sum(row.get('lat') is not None for row in records),
                'p_error':None,'p_events':records,
                'p_parser_capability':'publisher_event_candidates_v1'}
    from roomquest import lowcountry_palmetto_bluff_conservancy
    if source_key == lowcountry_palmetto_bluff_conservancy.KEY:
        deadline = min(monotonic() + 43,
                       deadline_at - 8 if deadline_at is not None else float('inf'))
        try:
            records = lowcountry_palmetto_bluff_conservancy.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=lowcountry_palmetto_bluff_conservancy.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records) > lowcountry_palmetto_bluff_conservancy.MAX_ITEMS or any(
                not isinstance(row.get('description'),str)
                or not row['description'].strip()
                or len(row['description']) > lowcountry_palmetto_bluff_conservancy.MAX_DESCRIPTION
                or row.get('category') not in ('festival','gardens_nature','learn')
                or row.get('venue_address') != lowcountry_palmetto_bluff_conservancy.STREET
                or row.get('lat') != lowcountry_palmetto_bluff_conservancy.LAT
                or row.get('lng') != lowcountry_palmetto_bluff_conservancy.LNG
                or not lowcountry_palmetto_bluff_conservancy.event_url(row.get('event_url'))
                for row in records):
                raise ValueError('palmetto_bluff_incomplete_event')
        except PreviewError:
            raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason=str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_palmetto_bluff_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:
            samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),
                'p_venue_count':sum(row.get('lat') is not None for row in records),
                'p_error':None,'p_events':records,
                'p_parser_capability':'publisher_event_candidates_v1'}
    from roomquest import lowcountry_roasting_room
    if source_key == lowcountry_roasting_room.KEY:
        deadline = min(monotonic() + 43,
                       deadline_at - 8 if deadline_at is not None else float('inf'))
        try:
            records = lowcountry_roasting_room.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=lowcountry_roasting_room.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records) > lowcountry_roasting_room.MAX_ITEMS or any(
                not isinstance(row.get('description'), str)
                or not row['description'].strip()
                or len(row['description']) > lowcountry_roasting_room.MAX_DESCRIPTION
                or row.get('category') != 'music'
                or row.get('venue_address') != lowcountry_roasting_room.STREET
                or row.get('lat') != lowcountry_roasting_room.LAT
                or row.get('lng') != lowcountry_roasting_room.LNG
                or row.get('ends_at') is not None
                or not lowcountry_roasting_room.event_url(row.get('event_url'))
                for row in records):
                raise ValueError('roasting_room_incomplete_event')
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}', reason)
                               else 'invalid_roasting_room_payload') from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),
                'p_venue_count':sum(row.get('lat') is not None for row in records),
                'p_error':None,'p_events':records,
                'p_parser_capability':'publisher_event_candidates_v1'}
    from roomquest import lowcountry_southern_barrel
    if source_key == lowcountry_southern_barrel.KEY:
        deadline = min(monotonic() + 43,
                       deadline_at - 8 if deadline_at is not None else float('inf'))
        try:
            records = lowcountry_southern_barrel.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=lowcountry_southern_barrel.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records)>lowcountry_southern_barrel.MAX_ITEMS or any(
                not isinstance(row.get('description'),str)
                or not row['description'].strip()
                or len(row['description'])>lowcountry_southern_barrel.MAX_DESCRIPTION
                or row.get('category')!='hang_out'
                or row.get('venue_address')!=lowcountry_southern_barrel.STREET
                or row.get('lat')!=lowcountry_southern_barrel.LAT
                or row.get('lng')!=lowcountry_southern_barrel.LNG
                or not lowcountry_southern_barrel.event_url(row.get('event_url'))
                for row in records):
                raise ValueError('southern_barrel_incomplete_event')
        except PreviewError:
            raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason=str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_southern_barrel_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:
            samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),
                'p_venue_count':sum(row.get('lat') is not None for row in records),
                'p_error':None,'p_events':records,
                'p_parser_capability':'publisher_event_candidates_v1'}
    from roomquest import lowcountry_greenhouse
    if source_key == lowcountry_greenhouse.KEY:
        deadline = min(monotonic() + 43,
                       deadline_at - 8 if deadline_at is not None else float('inf'))
        try:
            records = lowcountry_greenhouse.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=lowcountry_greenhouse.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records) > lowcountry_greenhouse.MAX_ITEMS or any(
                not isinstance(row.get('description'),str)
                or not row['description'].strip()
                or len(row['description'])>lowcountry_greenhouse.MAX_DESCRIPTION
                or row.get('category') not in {'music','hang_out','give_back','party'}
                or row.get('venue_address') != lowcountry_greenhouse.STREET
                or row.get('lat') != lowcountry_greenhouse.LAT
                or row.get('lng') != lowcountry_greenhouse.LNG
                or not lowcountry_greenhouse.event_url(row.get('event_url'))
                for row in records):
                raise ValueError('lowcountry_greenhouse_incomplete_event')
        except PreviewError:
            raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_lowcountry_greenhouse_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:
            samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),
                'p_venue_count':sum(row.get('lat') is not None for row in records),
                'p_error':None,'p_events':records,
                'p_parser_capability':'publisher_event_candidates_v1'}
    from roomquest import hilton_head_sources
    if source_key in hilton_head_sources.SOURCES:
        deadline = min(monotonic() + 43,
                       deadline_at - 8 if deadline_at is not None else float('inf'))
        try:
            records = hilton_head_sources.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=hilton_head_sources.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records) > hilton_head_sources.MAX_ITEMS or any(
                not isinstance(row.get('description'), str) or not row['description'].strip()
                or len(row['description']) > hilton_head_sources.MAX_DESCRIPTION
                or not isinstance(row.get('venue_address'), str)
                or not row['venue_address'].strip() for row in records):
                raise ValueError('hilton_head_incomplete_event')
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}', reason)
                               else 'invalid_hilton_head_payload') from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {'p_source_key': source_key, 'p_samples': samples,
                'p_future_count': len(records),
                'p_venue_count': sum(row.get('lat') is not None for row in records),
                'p_error': None, 'p_events': records,
                'p_parser_capability': 'publisher_event_candidates_v1'}
    from roomquest import hall_ga_civic_ical
    if source_key in hall_ga_civic_ical.SOURCES:
        deadline = min(monotonic() + 44,
                       deadline_at - 8 if deadline_at is not None else float('inf'))
        try:
            records = hall_ga_civic_ical.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=hall_ga_civic_ical.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if any(not isinstance(row.get('description'), str)
                   or len(row['description']) > hall_ga_civic_ical.MAX_DESCRIPTION
                   or not isinstance(row.get('venue_address'), str)
                   or not row['venue_address'].strip()
                   or row.get('category') != 'civic'
                   or not hall_ga_civic_ical.event_url(source_key,row.get('event_url'))
                   for row in records):
                raise ValueError('hall_ga_civic_incomplete_event')
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_hall_ga_civic_payload') from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {'p_source_key': source_key, 'p_samples': samples,
                'p_future_count': len(records),
                'p_venue_count': sum(row.get('lat') is not None for row in records),
                'p_error': None, 'p_events': records,
                'p_parser_capability': 'publisher_event_candidates_v1'}
    from roomquest import gainesville_direct_feeds
    if source_key in gainesville_direct_feeds.SOURCES:
        deadline = min(monotonic() + 43,
                       deadline_at - 8 if deadline_at is not None else float('inf'))
        try:
            records = gainesville_direct_feeds.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=gainesville_direct_feeds.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if any(not isinstance(row.get('description'), str)
                   or len(row['description']) > gainesville_direct_feeds.MAX_DESCRIPTION
                   or not isinstance(row.get('venue_address'), str)
                   or not row['venue_address'].strip() for row in records):
                raise ValueError('gainesville_direct_incomplete_event')
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}', reason)
                               else 'invalid_gainesville_direct_payload') from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {'p_source_key': source_key, 'p_samples': samples,
                'p_future_count': len(records),
                'p_venue_count': sum(row.get('lat') is not None for row in records),
                'p_error': None, 'p_events': records,
                'p_parser_capability': 'publisher_event_candidates_v1'}
    from roomquest import gainesville_sources
    if source_key in gainesville_sources.SOURCES:
        deadline = min(monotonic() + 40,
                       deadline_at - 8 if deadline_at is not None else float('inf'))
        try:
            records = gainesville_sources.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=gainesville_sources.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if any(not isinstance(row.get('description'), str)
                   or len(row['description']) > gainesville_sources.MAX_DESCRIPTION
                   or not isinstance(row.get('venue_address'), str)
                   or not row['venue_address'].strip() for row in records):
                raise ValueError('gainesville_incomplete_event')
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}', reason)
                               else 'invalid_gainesville_payload') from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {'p_source_key': source_key, 'p_samples': samples,
                'p_future_count': len(records),
                'p_venue_count': sum(row.get('lat') is not None for row in records),
                'p_error': None, 'p_events': records,
                'p_parser_capability': 'publisher_event_candidates_v1'}
    from roomquest import santa_cruz_game_night
    if source_key == santa_cruz_game_night.KEY:
        deadline=min(monotonic()+36,deadline_at-8 if deadline_at is not None else float('inf'))
        try:
            records=santa_cruz_game_night.collect(
                source,lambda url,accept:fetch_publisher(
                    url,accept,respect_robots=True,deadline_at=deadline,
                    allowed_hosts=santa_cruz_game_night.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records)>santa_cruz_game_night.MAX_RECORDS or any(
                not isinstance(r.get('description'),str) or not r['description'].strip()
                or not isinstance(r.get('venue_address'),str)
                or not r['venue_address'].strip() for r in records):
                raise ValueError('game_night_incomplete_event')
        except PreviewError:raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            code=str(exc)
            raise PreviewError(code if re.fullmatch(r'[a-z_]{3,100}',code)
                               else 'invalid_game_night_feed') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),'p_venue_count':0,
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_jack_oneill
    if source_key==santa_cruz_jack_oneill.KEY:
        deadline=min(monotonic()+39,deadline_at-5 if deadline_at is not None else float('inf'))
        try:
            records=santa_cruz_jack_oneill.collect(source,
                lambda url,accept:fetch_publisher(
                    url,accept,respect_robots=True,deadline_at=deadline,
                    allowed_hosts=santa_cruz_jack_oneill.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records)>santa_cruz_jack_oneill.MAX_RECORDS or any(
               not isinstance(r.get('description'),str) or not r['description'].strip()
               or len(r['description'])>santa_cruz_jack_oneill.MAX_DESCRIPTION
               or not isinstance(r.get('venue_address'),str) or not r['venue_address'].strip()
               for r in records):
                raise ValueError('incomplete_jack_oneill_event')
        except PreviewError:raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason=str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_jack_oneill_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:samples.pop()
        return {'p_parser_capability':'publisher_event_candidates_v1',
                'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),'p_venue_count':0,
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_mah
    if source_key==santa_cruz_mah.KEY:
        deadline=min(monotonic()+39,deadline_at-5 if deadline_at is not None else float('inf'))
        try:
            records=santa_cruz_mah.collect(
                source,lambda url,accept:fetch_publisher(
                    url,accept,respect_robots=True,deadline_at=deadline,
                    allowed_hosts=santa_cruz_mah.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records)>santa_cruz_mah.MAX_RECORDS or any(
                not isinstance(r.get('description'),str) or not r['description'].strip()
                or len(r['description'])>santa_cruz_mah.MAX_DESCRIPTION
                or not isinstance(r.get('venue_address'),str) or not r['venue_address'].strip()
                for r in records):
                raise ValueError('incomplete_mah_event')
        except PreviewError:raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason=str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_mah_event_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),'p_venue_count':0,
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_catalyst
    if source_key==santa_cruz_catalyst.KEY:
        deadline=min(monotonic()+39,deadline_at-5 if deadline_at is not None else float('inf'))
        try:
            records=santa_cruz_catalyst.collect(
                source,lambda url,accept:fetch_publisher(
                    url,accept,respect_robots=True,deadline_at=deadline,
                    allowed_hosts=santa_cruz_catalyst.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records)>santa_cruz_catalyst.MAX_RECORDS or any(
                not isinstance(r.get('description'),str) or not r['description'].strip()
                or len(r['description'])>santa_cruz_catalyst.MAX_DESCRIPTION
                or not isinstance(r.get('venue_address'),str) or not r['venue_address'].strip()
                for r in records):
                raise ValueError('incomplete_catalyst_event')
        except PreviewError:raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason=str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_catalyst_event_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),'p_venue_count':0,
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_418
    if source_key==santa_cruz_418.KEY:
        deadline=min(monotonic()+38,deadline_at-6 if deadline_at is not None else float('inf'))
        try:
            records=santa_cruz_418.collect(source,lambda url,accept:fetch_publisher(
                url,accept,respect_robots=True,deadline_at=deadline,
                allowed_hosts=santa_cruz_418.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records)>santa_cruz_418.MAX_RECORDS or any(
                not isinstance(r.get('description'),str) or not r['description'].strip()
                or len(r['description'])>santa_cruz_418.MAX_DESCRIPTION
                or not isinstance(r.get('venue_address'),str)
                or not r['venue_address'].strip() for r in records):
                raise ValueError('incomplete_418_event')
        except PreviewError:raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason=str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_418_event_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),'p_venue_count':0,
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_libnet
    if source_key == santa_cruz_libnet.KEY:
        deadline = min(monotonic() + 45, deadline_at - 6 if deadline_at is not None else float('inf'))
        try:
            records = santa_cruz_libnet.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=santa_cruz_libnet.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if not records or len(records) > santa_cruz_libnet.MAX_EVENTS or any(
                not isinstance(r.get('description'), str) or not r['description'].strip()
                or len(r['description']) > santa_cruz_libnet.MAX_DESCRIPTION
                or not isinstance(r.get('venue_address'), str) or not r['venue_address'].strip()
                for r in records
            ):
                raise ValueError('santa_cruz_library_incomplete_preview')
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}', reason)
                               else 'invalid_santa_cruz_library_payload') from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {'p_source_key': source_key, 'p_samples': samples,
                'p_future_count': len(records), 'p_venue_count': 0,
                'p_error': None, 'p_events': records}
    from roomquest import santa_cruz_turkey_trot, santa_cruz_melo
    for module in (santa_cruz_turkey_trot, santa_cruz_melo):
        if source_key != module.KEY:
            continue
        deadline = min(monotonic() + 38, deadline_at - 5 if deadline_at is not None else float('inf'))
        try:
            records = module.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=module.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records) > module.MAX_RECORDS or any(
                    not r.get('description') or not r.get('venue_address')
                    or not r.get('ends_at') or r.get('lat') is not None or r.get('lng') is not None
                    for r in records):
                raise ValueError('santa_cruz_new_source_incomplete_event')
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}', reason)
                               else 'invalid_santa_cruz_new_source_payload') from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {'p_source_key': source_key, 'p_samples': samples,
                'p_future_count': len(records), 'p_venue_count': 0,
                'p_error': None, 'p_events': records}
    from roomquest import santa_cruz_bargetto
    if source_key == santa_cruz_bargetto.KEY:
        deadline = min(monotonic() + 38, deadline_at - 5 if deadline_at is not None else float('inf'))
        try:
            records = santa_cruz_bargetto.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=santa_cruz_bargetto.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records) > santa_cruz_bargetto.MAX_RECORDS or any(
                    not r.get('description') or not r.get('venue_address') or not r.get('ends_at')
                    for r in records):
                raise ValueError('bargetto_incomplete_event')
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}', reason)
                               else 'invalid_bargetto_event_payload') from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {'p_source_key': source_key, 'p_samples': samples,
                'p_future_count': len(records), 'p_venue_count': 0,
                'p_error': None, 'p_events': records}
    from roomquest import santa_cruz_sparkys
    if source_key == santa_cruz_sparkys.KEY:
        deadline = min(monotonic() + 38, deadline_at - 5 if deadline_at is not None else float('inf'))
        try:
            records = santa_cruz_sparkys.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=santa_cruz_sparkys.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records) > santa_cruz_sparkys.MAX_RECORDS or any(
                    not r.get('description') or not r.get('venue_address')
                    for r in records):
                raise ValueError('sparkys_incomplete_event')
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}', reason)
                               else 'invalid_sparkys_event_payload') from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {'p_source_key': source_key, 'p_samples': samples,
                'p_future_count': len(records), 'p_venue_count': 0,
                'p_error': None, 'p_events': records}
    from roomquest import santa_cruz_reindeer
    if source_key==santa_cruz_reindeer.KEY:
        deadline=min(monotonic()+37,deadline_at-6 if deadline_at is not None else float('inf'))
        try:
            records=santa_cruz_reindeer.collect(source,lambda url,accept:fetch_publisher(
                url,accept,respect_robots=True,deadline_at=deadline,
                allowed_hosts=santa_cruz_reindeer.ALLOWED_HOSTS[source_key]),deadline_at=deadline)
            if len(records)>santa_cruz_reindeer.MAX_RECORDS or any(
                not r.get('description') or not r.get('venue_address') for r in records):
                raise ValueError('reindeer_incomplete_event')
        except PreviewError:raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason=str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_reindeer_event_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),'p_venue_count':0,
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_boardwalk
    if source_key==santa_cruz_boardwalk.KEY:
        deadline=min(monotonic()+37,deadline_at-6 if deadline_at is not None else float('inf'))
        try:
            records=santa_cruz_boardwalk.collect(source,lambda url,accept:fetch_publisher(
                url,accept,respect_robots=True,deadline_at=deadline,
                allowed_hosts=santa_cruz_boardwalk.ALLOWED_HOSTS[source_key]),deadline_at=deadline)
            if len(records)>santa_cruz_boardwalk.MAX_RECORDS or any(
                not r.get('description') or not r.get('venue_address') for r in records):
                raise ValueError('boardwalk_incomplete_event')
        except PreviewError:raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason=str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_boardwalk_event_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),'p_venue_count':0,
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_symphony
    if source_key==santa_cruz_symphony.KEY:
        deadline=min(monotonic()+37,deadline_at-6 if deadline_at is not None else float('inf'))
        try:
            records=santa_cruz_symphony.collect(
                source,lambda url,accept:fetch_publisher(
                    url,accept,respect_robots=True,deadline_at=deadline,
                    allowed_hosts=santa_cruz_symphony.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if (len(records)>santa_cruz_symphony.MAX_RECORDS or
                any(not isinstance(r.get('description'),str) or not r['description'].strip()
                    or len(r['description'])>santa_cruz_symphony.MAX_DESCRIPTION
                    or not r.get('venue_address') for r in records)):
                raise ValueError('symphony_incomplete_event')
        except PreviewError:raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason=str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_symphony_event_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),'p_venue_count':0,
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_save_our_shores
    if source_key == santa_cruz_save_our_shores.KEY:
        deadline = min(monotonic()+44, deadline_at-6 if deadline_at is not None else float('inf'))
        try:
            records = santa_cruz_save_our_shores.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=santa_cruz_save_our_shores.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if (len(records) > santa_cruz_save_our_shores.MAX_RECORDS
                    or any(not isinstance(r.get('description'),str)
                           or len(r['description'])<120
                           or not isinstance(r.get('venue_address'),str)
                           or not r['venue_address'].strip() for r in records)):
                raise ValueError('save_our_shores_incomplete_event')
        except PreviewError: raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason=str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_save_our_shores_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),'p_venue_count':0,
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_shakespeare
    if source_key == santa_cruz_shakespeare.KEY:
        deadline = min(monotonic()+39, deadline_at-6 if deadline_at is not None else float('inf'))
        try:
            records = santa_cruz_shakespeare.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=santa_cruz_shakespeare.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records) > santa_cruz_shakespeare.MAX_RECORDS or any(
                not isinstance(r.get('description'),str) or len(r['description'])<220
                or not isinstance(r.get('venue_address'),str) or not r['venue_address'].strip()
                for r in records):
                raise ValueError('shakespeare_incomplete_event')
        except PreviewError: raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason=str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_shakespeare_event_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),'p_venue_count':0,
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_faith_community
    if source_key == santa_cruz_faith_community.KEY:
        deadline = min(monotonic()+39, deadline_at-6 if deadline_at is not None else float('inf'))
        try:
            records = santa_cruz_faith_community.collect(
                source, lambda url,accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=santa_cruz_faith_community.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records)>santa_cruz_faith_community.MAX_RECORDS or any(
                not isinstance(r.get('description'),str) or len(r['description'])<115
                or len(r['description'])>santa_cruz_faith_community.MAX_DESCRIPTION
                or not isinstance(r.get('venue_address'),str) or not r['venue_address'].strip()
                for r in records):
                raise ValueError('faith_incomplete_event')
        except PreviewError: raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason=str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_faith_event_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),'p_venue_count':0,
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_little_giant
    if source_key == santa_cruz_little_giant.KEY:
        deadline = min(monotonic()+39, deadline_at-6 if deadline_at is not None else float('inf'))
        try:
            records = santa_cruz_little_giant.collect(
                source, lambda url,accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=santa_cruz_little_giant.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records)>santa_cruz_little_giant.MAX_RECORDS or any(
                not isinstance(r.get('description'),str) or len(r['description'])<170
                or len(r['description'])>santa_cruz_little_giant.MAX_DESCRIPTION
                or not isinstance(r.get('venue_address'),str) or not r['venue_address'].strip()
                for r in records):
                raise ValueError('little_giant_incomplete_event')
        except PreviewError: raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason=str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_little_giant_event_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),'p_venue_count':0,
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_goat_fitness
    if source_key == santa_cruz_goat_fitness.KEY:
        deadline = min(monotonic() + 39, deadline_at-6 if deadline_at is not None else float('inf'))
        try:
            records = santa_cruz_goat_fitness.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=santa_cruz_goat_fitness.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records)>santa_cruz_goat_fitness.MAX_RECORDS or any(
                not isinstance(r.get('description'),str) or len(r['description'])<120
                or not r.get('venue_address') or not r.get('ends_at')
                or not r.get('timezone') or r.get('lat') is not None
                or r.get('lng') is not None for r in records):
                raise ValueError('goat_incomplete_event')
        except PreviewError: raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason=str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_goat_event_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),'p_venue_count':0,
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_chess_club
    if source_key == santa_cruz_chess_club.KEY:
        deadline = min(monotonic()+40, deadline_at-6 if deadline_at is not None else float('inf'))
        try:
            records = santa_cruz_chess_club.collect(
                source, lambda url,accept: fetch_publisher(
                    url,accept,respect_robots=True,deadline_at=deadline,
                    allowed_hosts=santa_cruz_chess_club.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records)>santa_cruz_chess_club.MAX_RECORDS or any(
                not isinstance(r.get('description'),str) or len(r['description'])<150
                or not r.get('venue_address') or not r.get('ends_at')
                or not r.get('timezone') or r.get('latitude') is not None
                or r.get('longitude') is not None for r in records):
                raise ValueError('chess_incomplete_event')
        except PreviewError: raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason=str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_chess_event_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),'p_venue_count':0,
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_downtown
    if source_key == santa_cruz_downtown.KEY:
        deadline = min(monotonic()+39, deadline_at-6 if deadline_at is not None else float('inf'))
        try:
            records = santa_cruz_downtown.collect(
                source, lambda url,accept: fetch_publisher(
                    url,accept,respect_robots=True,deadline_at=deadline,
                    allowed_hosts=santa_cruz_downtown.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records)>santa_cruz_downtown.MAX_RECORDS or any(
                not isinstance(r.get('description'),str) or len(r['description'])<250
                or len(r['description'])>santa_cruz_downtown.MAX_DESCRIPTION
                or not isinstance(r.get('venue_address'),str) or not r['venue_address'].strip()
                for r in records):
                raise ValueError('downtown_incomplete_event')
        except PreviewError: raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason=str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_downtown_event_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:
            samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),'p_venue_count':0,
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_hotel_holidays
    if source_key in santa_cruz_hotel_holidays.SOURCES:
        deadline = min(monotonic()+39, deadline_at-6 if deadline_at is not None else float('inf'))
        try:
            records = santa_cruz_hotel_holidays.collect(
                source, lambda url,accept: fetch_publisher(
                    url,accept,respect_robots=True,deadline_at=deadline,
                    allowed_hosts=santa_cruz_hotel_holidays.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records)>santa_cruz_hotel_holidays.MAX_RECORDS or any(
                not isinstance(r.get('description'),str) or len(r['description'])<90
                or len(r['description'])>santa_cruz_hotel_holidays.MAX_DESCRIPTION
                or not isinstance(r.get('venue_address'),str) or not r['venue_address'].strip()
                for r in records):
                raise ValueError('hotel_incomplete_event')
        except PreviewError: raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason=str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_hotel_event_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:
            samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),'p_venue_count':0,
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_watsonville_taiko
    if source_key == santa_cruz_watsonville_taiko.KEY:
        deadline = min(monotonic()+35, deadline_at-6 if deadline_at is not None else float('inf'))
        try:
            records = santa_cruz_watsonville_taiko.collect(
                source, lambda url,accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=santa_cruz_watsonville_taiko.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records)>santa_cruz_watsonville_taiko.MAX_RECORDS or any(
                not isinstance(r.get('description'),str) or len(r['description'])<90
                or not r.get('venue_address') or not r.get('ends_at')
                or r.get('lat') is not None or r.get('lng') is not None for r in records):
                raise ValueError('taiko_incomplete_event')
        except PreviewError: raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason=str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'taiko_invalid_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000: samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),'p_venue_count':0,
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_dante
    if source_key == santa_cruz_dante.KEY:
        deadline = min(monotonic()+39, deadline_at-6 if deadline_at is not None else float('inf'))
        try:
            records = santa_cruz_dante.collect(
                source, lambda url,accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=santa_cruz_dante.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records)>santa_cruz_dante.MAX_RECORDS or any(
                not isinstance(r.get('description'),str) or not r['description'].strip()
                or not r.get('venue_address') or not r.get('ends_at')
                or r.get('lat') is not None or r.get('lng') is not None for r in records):
                raise ValueError('dante_incomplete_event')
        except PreviewError: raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason=str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_dante_event_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),'p_venue_count':0,
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_art_league
    if source_key == santa_cruz_art_league.KEY:
        deadline = min(monotonic()+39, deadline_at-6 if deadline_at is not None else float('inf'))
        try:
            records = santa_cruz_art_league.collect(
                source, lambda url,accept: fetch_publisher(
                    url,accept,respect_robots=True,deadline_at=deadline,
                    allowed_hosts=santa_cruz_art_league.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records)>santa_cruz_art_league.MAX_RECORDS or any(
                not isinstance(r.get('description'),str) or not r['description'].strip()
                or len(r['description'])>santa_cruz_art_league.MAX_DESCRIPTION
                or not isinstance(r.get('venue_address'),str) or not r['venue_address'].strip()
                for r in records):
                raise ValueError('art_league_incomplete_event')
        except PreviewError: raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_art_league_event_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:
            samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),'p_venue_count':0,
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_fabrica
    if source_key == santa_cruz_fabrica.KEY:
        deadline = min(monotonic()+39, deadline_at-6 if deadline_at is not None else float('inf'))
        try:
            records = santa_cruz_fabrica.collect(
                source, lambda url,accept: fetch_publisher(
                    url,accept,respect_robots=True,deadline_at=deadline,
                    allowed_hosts=santa_cruz_fabrica.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records)>santa_cruz_fabrica.MAX_RECORDS or any(
                not isinstance(r.get('description'),str) or not r['description'].strip()
                or len(r['description'])>santa_cruz_fabrica.MAX_DESCRIPTION
                or not isinstance(r.get('venue_address'),str) or not r['venue_address'].strip()
                for r in records):
                raise ValueError('fabrica_incomplete_event')
        except PreviewError: raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_fabrica_event_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:
            samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),'p_venue_count':0,
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_landing
    if source_key == santa_cruz_landing.KEY:
        deadline=min(monotonic()+37,deadline_at-6 if deadline_at is not None else float('inf'))
        try:
            records=santa_cruz_landing.collect(
                source,lambda url,accept:fetch_publisher(
                    url,accept,respect_robots=True,deadline_at=deadline,
                    allowed_hosts=santa_cruz_landing.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records)>santa_cruz_landing.MAX_RECORDS or any(
                not isinstance(r.get('description'),str) or not r['description'].strip()
                or len(r['description'])>santa_cruz_landing.MAX_DESCRIPTION
                or not isinstance(r.get('venue_address'),str) or not r['venue_address'].strip()
                for r in records):
                raise ValueError('landing_incomplete_event')
        except PreviewError:raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason=str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_landing_event_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),'p_venue_count':0,
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_winegrowers
    if source_key==santa_cruz_winegrowers.KEY:
        deadline=min(monotonic()+38,deadline_at-6 if deadline_at is not None else float('inf'))
        try:
            records=santa_cruz_winegrowers.collect(
                source,lambda url,accept:fetch_publisher(
                    url,accept,respect_robots=True,deadline_at=deadline,
                    allowed_hosts=santa_cruz_winegrowers.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records)>santa_cruz_winegrowers.MAX_RECORDS or any(
                not isinstance(r.get('description'),str) or not r['description'].strip()
                or len(r['description'])>santa_cruz_winegrowers.MAX_DESCRIPTION
                or not isinstance(r.get('venue_address'),str) or not r['venue_address'].strip()
                for r in records):
                raise ValueError('scmwa_incomplete_event')
        except PreviewError:raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason=str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_scmwa_event_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:samples.pop()
        return {'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),'p_venue_count':0,
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_square_venues
    if source_key in santa_cruz_square_venues.SOURCES:
        deadline=min(monotonic()+37,deadline_at-6 if deadline_at is not None else float('inf'))
        try:
            records=santa_cruz_square_venues.collect(
                source,lambda url,accept:fetch_publisher(
                    url,accept,respect_robots=True,deadline_at=deadline,
                    allowed_hosts=santa_cruz_square_venues.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records)>santa_cruz_square_venues.MAX_RECORDS or any(
                not isinstance(r.get('description'),str) or not r['description'].strip()
                or len(r['description'])>santa_cruz_square_venues.MAX_DESCRIPTION
                or not isinstance(r.get('venue_address'),str) or not r['venue_address'].strip()
                for r in records):
                raise ValueError('santa_cruz_square_incomplete_event')
        except PreviewError:raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            reason=str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}',reason)
                               else 'invalid_santa_cruz_square_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:samples.pop()
        return {'p_parser_capability':'publisher_event_candidates_v1',
                'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),
                'p_venue_count':sum(r.get('lat') is not None for r in records),
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_rio
    if source_key == santa_cruz_rio.KEY:
        deadline=min(monotonic()+36,deadline_at-8 if deadline_at is not None else float('inf'))
        try:
            records=santa_cruz_rio.collect(
                source,lambda url,accept:fetch_publisher(
                    url,accept,respect_robots=True,deadline_at=deadline,
                    allowed_hosts=santa_cruz_rio.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records)>santa_cruz_rio.MAX_RECORDS or any(
                not isinstance(r.get('description'),str) or not r['description'].strip()
                or not isinstance(r.get('venue_address'),str)
                or not r['venue_address'].strip() for r in records):
                raise ValueError('rio_incomplete_event')
        except PreviewError:raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            code=str(exc)
            raise PreviewError(code if re.fullmatch(r'[a-z_]{3,100}',code)
                               else 'invalid_rio_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:samples.pop()
        return {'p_parser_capability':'publisher_event_candidates_v1',
                'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),'p_venue_count':sum(r.get('lat') is not None for r in records),
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_felton_fire
    if source_key == santa_cruz_felton_fire.KEY:
        deadline=min(monotonic()+45,deadline_at-8 if deadline_at is not None else float('inf'))
        try:
            records=santa_cruz_felton_fire.collect(
                source, lambda url,accept: fetch_publisher(
                    url,accept,respect_robots=True,deadline_at=deadline,
                    allowed_hosts=santa_cruz_felton_fire.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records)>santa_cruz_felton_fire.MAX_RECORDS or any(
                len(r.get('description') or '')<300 or not r.get('venue_address')
                or not r.get('ends_at') or r.get('lat') is not None
                or r.get('lng') is not None for r in records):
                raise ValueError('felton_fire_original_event_incomplete')
        except PreviewError:
            raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            code=str(exc)
            raise PreviewError(code if re.fullmatch(r'[a-z_]{3,100}',code)
                               else 'invalid_felton_fire_original_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:samples.pop()
        return {'p_parser_capability':'publisher_event_candidates_v1',
                'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),'p_venue_count':sum(r.get('lat') is not None for r in records),
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_rcnv
    if source_key == santa_cruz_rcnv.KEY:
        deadline = min(monotonic()+45, deadline_at-8 if deadline_at is not None else float('inf'))
        try:
            records = santa_cruz_rcnv.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=santa_cruz_rcnv.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records)>santa_cruz_rcnv.MAX_RECORDS or any(
                not r.get('description') or len(r['description'])<250
                or not r.get('venue_address') or not r.get('ends_at')
                or r.get('lat') is not None or r.get('lng') is not None for r in records):
                raise ValueError('rcnv_original_event_incomplete')
        except PreviewError:
            raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            code=str(exc)
            raise PreviewError(code if re.fullmatch(r'[a-z_]{3,100}',code)
                               else 'invalid_rcnv_original_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:samples.pop()
        return {'p_parser_capability':'publisher_event_candidates_v1',
                'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),'p_venue_count':0,
                'p_error':None,'p_events':records}
    from roomquest import scotts_valley_cocoa
    if source_key==scotts_valley_cocoa.KEY:
        deadline=min(monotonic()+35,deadline_at-6 if deadline_at is not None else float('inf'))
        try:
            records=scotts_valley_cocoa.collect(
                source,lambda url,accept:fetch_publisher(
                    url,accept,respect_robots=True,deadline_at=deadline,
                    allowed_hosts=scotts_valley_cocoa.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records)>scotts_valley_cocoa.MAX_RECORDS or any(
                not isinstance(r.get('description'),str) or len(r['description'])<175
                or not r.get('venue_address') or not r.get('ends_at')
                or r.get('lat') is not None or r.get('lng') is not None for r in records):
                raise ValueError('scotts_cocoa_incomplete_original_event')
        except PreviewError:raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            code=str(exc)
            raise PreviewError(code if re.fullmatch(r'[a-z_]{3,100}',code)
                               else 'invalid_scotts_cocoa_original_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:samples.pop()
        return {'p_parser_capability':'publisher_event_candidates_v1',
                'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),'p_venue_count':0,
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_local_venues
    if source_key in santa_cruz_local_venues.SOURCES:
        deadline=min(monotonic()+36,deadline_at-8 if deadline_at is not None else float('inf'))
        try:
            records=santa_cruz_local_venues.collect(
                source,lambda url,accept:fetch_publisher(
                    url,accept,respect_robots=True,deadline_at=deadline,
                    allowed_hosts=santa_cruz_local_venues.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records)>santa_cruz_local_venues.MAX_RECORDS or any(
                not isinstance(row.get('description'),str) or not row['description'].strip()
                or len(row['description'])>santa_cruz_local_venues.MAX_DESCRIPTION
                or not isinstance(row.get('venue_address'),str)
                or not row['venue_address'].strip() for row in records):
                raise ValueError('santa_cruz_local_incomplete_event')
        except PreviewError:
            raise
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            code=str(exc)
            raise PreviewError(code if re.fullmatch(r'[a-z_]{3,100}',code)
                               else 'invalid_santa_cruz_local_payload') from exc
        samples=records[:MAX_PREVIEWS]
        while len(json.dumps(samples,ensure_ascii=False))>18_000:samples.pop()
        return {'p_parser_capability':'publisher_event_candidates_v1',
                'p_source_key':source_key,'p_samples':samples,
                'p_future_count':len(records),
                'p_venue_count':sum(row.get('lat') is not None for row in records),
                'p_error':None,'p_events':records}
    from roomquest import santa_cruz_sources
    if source_key in santa_cruz_sources.SOURCES:
        deadline = min(monotonic() + 40,
                       deadline_at - 8 if deadline_at is not None else float('inf'))
        try:
            records = santa_cruz_sources.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=santa_cruz_sources.ALLOWED_HOSTS[source_key]),
                deadline_at=deadline)
            if len(records) > santa_cruz_sources.MAX_RECORDS or any(
                    not isinstance(row.get('description'), str) or not row['description'].strip()
                    or len(row['description']) > santa_cruz_sources.MAX_DESCRIPTION
                    or not isinstance(row.get('venue_address'), str)
                    or not row['venue_address'].strip() for row in records):
                raise ValueError('santa_cruz_incomplete_event')
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}', reason)
                               else 'invalid_santa_cruz_payload') from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {'p_parser_capability': 'publisher_event_candidates_v1',
                'p_source_key': source_key, 'p_samples': samples,
                'p_future_count': len(records),
                'p_venue_count': sum(row.get('lat') is not None for row in records),
                'p_error': None, 'p_events': records}
    from roomquest import knoxville_sources
    if source_key in knoxville_sources.SOURCES:
        # Exact registered Knoxville publishers: complete narratives and each
        # event's own street, or the record is held by the adapter.
        deadline = min(monotonic() + 36,
                       deadline_at - 8 if deadline_at is not None else float('inf'))
        hosts = knoxville_sources.ALLOWED_HOSTS[source_key]
        try:
            records = knoxville_sources.collect(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=hosts), deadline_at=deadline)
            if len(records) > knoxville_sources.MAX_RECORDS:
                raise ValueError('source_record_limit')
            if any(not isinstance(row.get('description'), str) or not row['description'].strip()
                   or len(row['description']) > knoxville_sources.MAX_DESCRIPTION
                   or not isinstance(row.get('venue_address'), str)
                   or not row['venue_address'].strip() for row in records):
                raise ValueError('knoxville_incomplete_event')
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r'[a-z_]{3,100}', reason)
                               else 'invalid_knoxville_payload') from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {**({'p_parser_capability': 'publisher_event_candidates_v1'}
                   if source.get('platform_adapter') == 'wordpress' else {}),
                'p_source_key': source_key, 'p_samples': samples,
                'p_future_count': len(records),
                'p_venue_count': sum(row.get('lat') is not None for row in records),
                'p_error': None, 'p_events': records}
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
        from roomquest.ics_adapter import PORTSMOUTH_VENUE_FEEDS
        portsmouth_url = PORTSMOUTH_VENUE_FEEDS.get(source_key)
        if portsmouth_url and (source.get('feed_url'), source.get('timezone')) != (portsmouth_url, 'America/New_York'):
            raise PreviewError('unregistered_portsmouth_venue_calendar')
        civic_ics = source_key in VIRGINIA_CIVIC_ICS
        raleigh_ics = source_key in RALEIGH_CATALOG_ICS
        raleigh_url = RALEIGH_CATALOG_ICS.get(source_key) or RALEIGH_UDELL_ICS.get(source_key)
        if raleigh_url and source.get("feed_url") != raleigh_url:
            raise PreviewError("unregistered_raleigh_catalog_ics")
        if civic_ics and (source.get("feed_url") != VIRGINIA_CIVIC_ICS[source_key]
                          or source.get("timezone") != "America/New_York"):
            raise PreviewError("unregistered_virginia_civic_ics")
        mapsee = source_key.startswith("municipal_mapsee_")
        direct_ical = bool(re.fullmatch(r"municipal_[0-9a-f]{24}", source_key))
        if mapsee:
            from roomquest.mapsee_adapter import profiles
            profile = profiles().get(source["source_key"])
            if not profile or profile["type"] != "ics" or profile["url"] != source.get("feed_url"):
                raise PreviewError("unregistered_mapsee_source")
        deadline = min(monotonic() + (35 if direct_ical else 20), deadline_at - 8 if deadline_at is not None else float("inf"))
        try:
            if source_key in nebraska_library_ics.SOURCES:
                payload = fetch_publisher(source["feed_url"], "text/calendar", respect_robots=True,
                                          deadline_at=deadline, allowed_hosts=(urlparse(source["feed_url"]).hostname,))
                records = nebraska_library_ics.collect(source, payload)
            elif source_key == omaha_lincoln.BOTTLE_ROCKET:
                records = omaha_lincoln.collect_bottle_rocket(source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=("calendar.google.com",)))
            elif source_key == omaha_lincoln.UNL_PUBLIC:
                records = omaha_lincoln.collect_unl_public(source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=(omaha_lincoln.UNL_HOST,)))
            elif source_key in nebraska_public_calendars.SOURCES:
                records = nebraska_public_calendars.collect(source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=(urlparse(nebraska_public_calendars.SOURCES[source_key][0]).hostname,)))
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
                if civic_ics or raleigh_url or portsmouth_url:
                    host_scope["allowed_hosts"] = (urlparse(source["feed_url"]).hostname,)
                payload = fetch_publisher(
                    source["feed_url"], "text/calendar",
                    respect_robots=civic_ics or bool(raleigh_url or portsmouth_url) or mapsee or direct_ical
                    or source_key in {"mecklenburg_va_libraries", "sarpy_tourism_ne"},
                    deadline_at=deadline, **host_scope)
                calendar_source = {"url": source["feed_url"], "source_key": source_key,
                                   **{key: source[key] for key in ('timezone', 'civic_contract_version',
                                      'civic_jurisdiction_id', 'civic_jurisdiction_name') if key in source}}
                records = parse(payload, calendar_source, legacy=not mapsee,
                                include_description=civic_ics or raleigh_ics or source_key == "independence_ia_library_family")
                if direct_ical and not (civic_ics or raleigh_url or portsmouth_url):
                    from roomquest.ical_venue_address import extract_venue_addresses
                    extract_venue_addresses(records)
                if source_key == omaha_lincoln.LA_VISTA_LIBRARY and source["feed_url"] == omaha_lincoln.LA_VISTA_FEED:
                    records = omaha_lincoln.normalize_la_vista_library(records)
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
    # Exact reviewed BiblioCommons RSS profiles, not the proprietary JSON gateway.
    # A source is not activated by this dispatch; DB registration and publisher
    # rights remain independent and mandatory before any live collection.
    from roomquest.bibliocommons_rss import (
        SOURCES as BIBLIO_RSS_SOURCES, GATEWAY as BIBLIO_RSS_HOST,
        collect as collect_bibliocommons_rss)
    if source.get("source_key") in BIBLIO_RSS_SOURCES:
        deadline = min(monotonic() + 30, deadline_at - 7 if deadline_at is not None else float("inf"))
        try:
            records = collect_bibliocommons_rss(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=(BIBLIO_RSS_HOST,)), deadline_at=deadline)
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r"[a-z_]{3,100}", reason)
                               else "invalid_bibliocommons_rss_payload") from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {"p_source_key": source["source_key"], "p_samples": samples,
                "p_future_count": len(records),
                "p_venue_count": sum(row.get("lat") is not None for row in records),
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
        html_fetch_options = {}
        from roomquest.raleigh_html import SOURCES as RALEIGH_SOURCES
        from roomquest.virginia_wix_events import SOURCES as VA_WIX_SOURCES
        from roomquest import maryland_public_calendars, maryland_park_programs
        from roomquest.nebraska_venues import SOURCES as NEBRASKA_VENUES
        from roomquest import nebraska_final, richmond_public_calendars
        from roomquest import gulf_recurring, gulf_seasonal, gulf_venues
        from roomquest import liberty_calendar, registered_listings
        if source.get('feed_url') in registered_listings.URLS and source_key == registered_listings.source_key(source['feed_url']):
            collect_html = registered_listings.collect
            allowed_hosts = registered_listings.allowed_hosts(source['feed_url'])
            if source['feed_url'] == liberty_calendar.ORIGINAL:
                html_fetch_options['follow_redirects'] = False
        elif source_key in gulf_recurring.SOURCES:
            collect_html = gulf_recurring.collect
            allowed_hosts = gulf_recurring.allowed_hosts(source_key)
        elif source_key in gulf_seasonal.SOURCES:
            collect_html = gulf_seasonal.collect
            allowed_hosts = gulf_seasonal.allowed_hosts(source_key)
        elif source_key in gulf_venues.SOURCES:
            collect_html = gulf_venues.collect
            allowed_hosts = gulf_venues.allowed_hosts(source_key)
        elif source_key in nebraska_final.SOURCES:
            collect_html = nebraska_final.collect
            allowed_hosts = nebraska_final.SOURCES[source_key][1]
        elif source_key in richmond_public_calendars.SOURCES:
            collect_html = richmond_public_calendars.collect
            allowed_hosts = richmond_public_calendars.SOURCES[source_key][1]
        elif source_key in NEBRASKA_VENUES:
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
        elif source_key == "neighbors_bar_braselton_ga":
            from roomquest.neighbors_braselton_ga import HOST, collect as collect_html
            allowed_hosts = (HOST,)
            html_budget = 44
        elif source_key == "clermont_town_calendar_ga":
            # Must dispatch inside the HTML family before the generic
            # unregistered_html_source guard (not after it).
            from roomquest.clermont_ga import HOST, collect as collect_html
            allowed_hosts = (HOST,)
            html_budget = 26
        elif source_key == "explore_braselton_official_ga":
            from roomquest.explore_braselton_ga import HOST, collect as collect_html
            allowed_hosts = (HOST,)
        elif source_key == "hall_bourbon_brothers_gainesville_ga":
            from roomquest.hall_bourbon_ga import HOST, collect as collect_html
            allowed_hosts = (HOST,)
        elif source_key == "lanier_islands_events_ga":
            from roomquest.lanier_islands_ga import HOST, collect as collect_html
            allowed_hosts = (HOST,)
        elif source_key == "porch_on_main_flowery_branch_ga":
            from roomquest.porch_on_main_ga import HOST, collect as collect_html
            allowed_hosts = (HOST,)
        elif source_key == "barefoot_sailing_flowery_branch_ga":
            from roomquest.barefoot_sailing_ga import HOST, collect as collect_html
            allowed_hosts = (HOST,)
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
        elif source_key == 'municipal_5a87362d39d182aed1cf4a6c':
            from roomquest.veil_events import URL, collect as collect_html
            allowed_hosts = (urlparse(URL).hostname,)
        elif source_key in ('pageturners_lounge_omaha_ne', 'blue_sky_bar_patio_omaha_ne', 'saro_cider_lincoln_ne',
                           'thor_trails_squarespace_ne', 'municipal_91c26eb4ef4205c03947decd'):
            from roomquest.squarespace_events_html import SOURCES, collect as collect_html
            allowed_hosts = (urlparse(SOURCES[source_key][0]).hostname,)
        elif source_key in ('prairie_pines_events_ne', 'glacier_creek_preserve_events_ne'):
            from roomquest.nebraska_preserves import SOURCES, collect as collect_html
            allowed_hosts = (urlparse(SOURCES[source_key][0]).hostname,)
        elif source_key in ('spielbound_meetup_ne', 'americas_pub_quiz_ne', 'spring_creek_prairie_audubon_ne'):
            from roomquest.nebraska_event_listings import SOURCES, collect as collect_html
            allowed_hosts = (urlparse(SOURCES[source_key]).hostname,)
        elif source_key in ('lincoln_parks_opencities_ne', 'omaha_running_club_eventon_ne', 'goatz_hitchcock_experience_ne'):
            from roomquest.nebraska_recreation import SOURCES, collect as collect_html
            allowed_hosts = (urlparse(SOURCES[source_key]).hostname,)
        elif source_key == 'sower_books_lit_circle_ne':
            from roomquest.sower_books import HOST, collect as collect_html
            allowed_hosts = (HOST,)
        elif source_key == 'cellar_426_events_ne':
            from roomquest.cellar_calendar import HOST, collect as collect_html
            allowed_hosts = (HOST,)
        elif source_key == 'friends_omaha_library_mec_ne':
            from roomquest.friends_omaha_calendar import HOST, collect as collect_html
            allowed_hosts = (HOST,)
        elif source_key == 'omaha_first_united_methodist_mec_ne':
            from roomquest.mec_calendar import HOST, collect as collect_html
            allowed_hosts = (HOST,)
        elif source_key == 'mana_games_official_programs_ne':
            from roomquest.mana_official_programs import HOST, collect as collect_html
            allowed_hosts = (HOST,)
        elif source_key == 'mana_games_topdeck_ne':
            from roomquest.mana_games import HOST, collect as collect_html
            allowed_hosts = (HOST,)
        elif source_key == 'hyde_observatory_programs_ne':
            from roomquest.hyde_observatory import HOST, collect as collect_html
            allowed_hosts = (HOST,)
        elif source_key == 'omaha_kiewit_luminarium_ne':
            from roomquest.kiewit_luminarium import HOST, collect as collect_html
            allowed_hosts = (HOST,)
        elif source_key == 'lincoln_chamber_weblink_ne':
            from roomquest.lincoln_chamber import HOST, collect as collect_html
            allowed_hosts = (HOST,)
        elif source_key == 'omaha_parks_webtrac_ne':
            from roomquest.webtrac import HOST, collect as collect_html
            allowed_hosts = (HOST,)
        elif source_key == 'omaha_lauritzen_gardens_events':
            from roomquest.eventer import HOST, collect as collect_html
            allowed_hosts = (HOST,)
        elif source_key == 'omaha_henry_doorly_zoo_events':
            from roomquest.sitewrench_calendar import HOST, collect as collect_html
            allowed_hosts = (HOST,)
        elif source_key in ROCKHOUSE_SOURCES:
            from roomquest.rockhouse import collect as collect_html
            allowed_hosts = (urlparse(ROCKHOUSE_SOURCES[source_key][0]).hostname,)
            html_budget = 36
        elif source_key in FIRESPRING_SOURCES:
            from roomquest.firespring import collect as collect_html
            allowed_hosts = (urlparse(FIRESPRING_SOURCES[source_key][0]).hostname,)
            html_budget = 36
        elif source_key == 'oc_parks_verified_partial_ca':
            from roomquest.oc_parks_partial import HOST, collect as collect_html
            allowed_hosts = (HOST,)
            # Reviews at most 32 individual publisher detail pages. This is an
            # explicitly partial calendar scope, not 500 complete events.
            html_budget = 36
        elif source_key == 'omaha_public_library_biblioevents_ne':
            from roomquest.biblioevents import GATEWAY, collect as collect_html
            allowed_hosts = (GATEWAY,)
            html_budget = 36
        elif source_key == 'mountain_home_chamber_calendar_ar':
            from roomquest.mountain_home_chamber import HOST, collect as collect_html
            allowed_hosts = (HOST,)
            html_budget = 30
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
        elif source_key in ("municipal_ae345229f73806e1a26d20ac", "municipal_fbeab18ea945d530eccf2189",
                            "municipal_cafd15041a039d27e1a37fc3"):
            from roomquest.hampton_roads_markets import collect as collect_html
            allowed_hosts = (urlparse(source['feed_url']).hostname,)
        elif source_key == "municipal_e1e032feac65ae6f1c75b39f":
            from roomquest.hermitage_programs import HOST, collect as collect_html
            allowed_hosts = (HOST,)
        elif source_key == "municipal_175e7cdf657e22645f5d5ef6":
            from roomquest.downtown_norfolk import HOST, collect as collect_html
            allowed_hosts = (HOST,)
        elif source_key in ("municipal_c95c95a5b06056f26da007e7", "municipal_8f59bd98f751e3f218ee5ce1", "municipal_cdbebcd2be97bebce865a8fb"):
            from roomquest.hampton_roads_spothopper import SOURCES, collect as collect_html
            allowed_hosts = (urlparse(SOURCES[source_key][0]).hostname,)
        elif source_key in ("municipal_376911a33eeef7ed0d9df1a0", "municipal_4c5a2b0a7c39f7beb74e6342"):
            from roomquest.virginia_beach_meetings import HOST, collect as collect_html
            allowed_hosts = (HOST,)
            html_budget = 40
        elif source_key in ("municipal_f1228683d362efb24e29c98c", "municipal_34ba9ee0424a01d0551a9e69"):
            from roomquest.hampton_roads_venues import SOURCES, collect as collect_html
            allowed_hosts = (urlparse(SOURCES[source_key][0]).hostname,)
            html_budget = 45
        elif source_key in (
            "municipal_12c58b8068db81adc4284433",
            "municipal_23d62d2d858c7e93630fe5e3",
            "municipal_a9fd322416e6536699a69f66",
        ):
            from roomquest.hampton_roads_public_events import SOURCES, collect as collect_html
            allowed_hosts = (urlparse(SOURCES[source_key][0]).hostname,)
            html_budget = 40
        elif source_key == "municipal_675453b56a7c6bd1a1458ce2":
            from roomquest.odu_public_calendar import HOST, collect as collect_html
            allowed_hosts = (HOST,)
            html_budget = 40
        elif source_key == "municipal_2c72672bcb8c47b895b8cb3e":
            from roomquest.virginia_beach_cultural import HOST, collect as collect_html
            allowed_hosts = (HOST,)
        elif source_key == "municipal_1e4397337c81260b0712c2df":
            from roomquest.tidewater_college import HOST, collect as collect_html
            allowed_hosts = (HOST,)
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
            if source_key in nebraska_final.GROUPS:
                extra["fetch_localhop"] = lambda url, app_id: _fetch_publisher_request(
                    url, "application/json", respect_robots=True, deadline_at=deadline,
                    allowed_hosts=(nebraska_final.LOCALHOP_HOST,), localhop_app_id=app_id)
            if source_key == richmond_public_calendars.CFENGAGE:
                extra['render_volunteers'] = lambda: render_cfengage_calendar(deadline_at=deadline)
            if source_key == 'good_shepherd_food_pantry_south_hill_va':
                extra['render_calendar'] = lambda *, nonce, args: render_good_shepherd_calendar(
                    nonce=nonce, args=args, deadline_at=deadline)
            if source_key == 'municipal_2c72672bcb8c47b895b8cb3e':
                extra['render_calendar'] = lambda: render_virginia_beach_cultural_calendar(deadline_at=deadline)
            records = collect_html(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=allowed_hosts, **html_fetch_options,
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
        direct_calendar = bool(re.fullmatch(r"municipal_[0-9a-f]{24}", source_key))
        deadline = min(monotonic() + (35 if maryland or direct_calendar else 20), deadline_at - 8 if deadline_at is not None else float("inf"))
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
        from roomquest.registered_native_content import enabled as native_enabled, VERSION as NATIVE_VERSION
        return {**({"p_parser_capability": NATIVE_VERSION} if native_enabled(source) else {}),
                **({"p_parser_capability": "publisher_event_candidates_v1"}
                   if maryland or source_key in ('madison_county_parks_ia', 'think_iowa_city_ia', 'rosemont_of_virginia', 'longwood_basketball_va', 'hurrdat_sports_bar_ne') else {}),
                "p_source_key": source["source_key"], "p_samples": samples,
                "p_future_count": len(records),
                "p_venue_count": sum(1 for row in records if row["lat"] is not None),
                "p_error": None, "p_events": records}
    if source.get("platform_adapter") == "jsonld" and source.get("kind") == "json":
        from roomquest.jsonld_adapter import collect as collect_jsonld
        from roomquest.registration_formats import source_key as registration_source_key
        if source.get("source_key", "").startswith("municipal_mapsee_"):
            from roomquest.mapsee_adapter import profiles
            profile = profiles().get(source["source_key"])
            if not profile or profile["type"] != "jsonld" or profile["url"] != source.get("feed_url"):
                raise PreviewError("unregistered_mapsee_source")
        elif source_key != registration_source_key(source["feed_url"]):
            raise PreviewError("unregistered_jsonld_source")
        deadline = min(monotonic() + 20, deadline_at - 8 if deadline_at is not None else float("inf"))
        try:
            from roomquest import eventon
            if source['feed_url'] == eventon.CALENDAR:
                page = fetch_publisher(eventon.CALENDAR, 'text/html', respect_robots=True,
                                       deadline_at=deadline, allowed_hosts=(eventon.HOST,))
                body = _fetch_publisher_request(
                    eventon.ENDPOINT, 'application/json', respect_robots=True, deadline_at=deadline,
                    allowed_hosts=(eventon.HOST,), calendar_form=eventon.calendar_form(page))
                records = eventon.parse(body)
            else:
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
        from roomquest.registered_native_content import enabled as native_enabled, VERSION as NATIVE_VERSION
        return {**({"p_parser_capability": NATIVE_VERSION} if native_enabled(source) else {}),
                "p_source_key": source["source_key"], "p_samples": samples,
                "p_future_count": len(records),
                "p_venue_count": sum(1 for row in records if row["lat"] is not None),
                "p_error": None, "p_events": records}
    if source.get("source_key") == "hall_arts_council_gainesville_ga":
        from roomquest.hall_arts_council_ga import collect as collect_arts
        deadline = min(monotonic() + 24,
                       deadline_at - 8 if deadline_at is not None else float("inf"))
        try:
            records = collect_arts(source, lambda url, accept: fetch_publisher(
                url, accept, respect_robots=True, deadline_at=deadline),
                deadline_at=deadline)
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r"[a-z_]{3,100}", reason)
                               else "invalid_calendar_payload") from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {"p_source_key": source["source_key"], "p_samples": samples,
                "p_future_count": len(records),
                "p_venue_count": sum(1 for r in records if r["lat"] is not None),
                "p_error": None, "p_events": records}
    if source.get("source_key") == "cork_it_gainesville_ga":
        from roomquest.cork_it_ga import collect as collect_cork
        deadline = min(monotonic() + 24,
                       deadline_at - 8 if deadline_at is not None else float("inf"))
        try:
            records = collect_cork(source, lambda url, accept: fetch_publisher(
                url, accept, respect_robots=True, deadline_at=deadline,
                allowed_hosts=("www.corkitgainesville.com",)),
                deadline_at=deadline)
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            raise PreviewError(reason if re.fullmatch(r"[a-z_]{3,100}", reason)
                               else "invalid_cork_it_payload") from exc
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        return {"p_source_key": source["source_key"], "p_samples": samples,
                "p_future_count": len(records),
                "p_venue_count": sum(1 for row in records if row.get("lat") is not None),
                "p_error": None, "p_events": records,
                "p_parser_capability": "publisher_event_candidates_v1"}
    if source.get("platform_adapter") == "squarespace" and source.get("kind") == "json":
        from roomquest.squarespace import SOURCES, collect as collect_squarespace
        from roomquest.registration_formats import source_key as registration_source_key
        if source.get("source_key", "").startswith("municipal_mapsee_"):
            from roomquest.mapsee_adapter import profiles
            profile = profiles().get(source["source_key"])
            if not profile or profile["type"] != "squarespace" or profile["url"] != source.get("feed_url"):
                raise PreviewError("unregistered_mapsee_source")
        elif source.get("feed_url") not in SOURCES and source_key != registration_source_key(source["feed_url"]):
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
    registered_localist = source.get('platform_adapter') == 'localist' and source.get('kind') == 'json'
    if source.get("source_key", "").startswith("municipal_mapsee_") or registered_localist:
        from roomquest.mapsee_adapter import profiles, collect
        from roomquest.registration_formats import source_key as registration_key
        from roomquest.localist_registration import collect as collect_localist
        direct_localist = registered_localist and source_key == registration_key(source['feed_url'])
        profile = None if direct_localist else profiles().get(source["source_key"])
        if not direct_localist and (not profile or profile["url"] != source.get("feed_url")):
            raise PreviewError("unregistered_mapsee_source")
        try:
            deadline = min(monotonic() + 20, deadline_at - 8 if deadline_at is not None else float("inf"))
            if monotonic() >= deadline:
                raise PreviewError("collection_deadline")
            if direct_localist:
                records = collect_localist(source['feed_url'], lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline, allowed_hosts=(urlparse(source['feed_url']).hostname,)))
            else:
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
    allowed = {"community_collector_feed_profile", "community_collector_claim_registration", "community_collector_finish_registration",
               "community_collector_claim_api_venue_discovery", "community_collector_finish_api_venue_discovery",
               "community_collector_claim_category", "community_collector_publish_category", "community_collector_finish_category", "community_collector_claim_previews", "community_collector_claim_demand_preview", "community_collector_claim_chambermaster", "community_collector_record_preview", "community_collector_record_preview_v2", "community_collector_record_preview_v3",
               "community_collector_read_fetch_checkpoint", "community_collector_write_fetch_checkpoint",
               "community_collector_stage_incremental", "community_collector_complete_incremental",
               "community_collector_record_staged_events", "community_collector_geocoder", "community_collector_geocoder_claim",
               "community_collector_venues", "community_collector_media", "community_collector_media_demand",
               "community_collector_things_to_do", "community_collector_activity_discovery",
               "community_collector_timezones"}
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
    with capture_publisher_pacing() as pacing, capture_snapshot(source, collection_context):
        return _process_claimed_source_with_pacing(
            source, pacing, deadline_at=deadline_at, publisher_handoff=publisher_handoff,
            observe_phase=observe_phase, collection_context=collection_context)


def _process_visit_raleigh(source, pacing, *, collection_context, deadline_at,
                          publisher_handoff=None, observe_phase=None):
    """Fetch completely, then stage acknowledged bounded batches across leases.

    Raleigh alone uses a compressed source-specific checkpoint and staging cursor.
    Other providers retain their existing complete-manifest processing behavior.
    """
    from roomquest import visit_raleigh as adapter

    deadline = min(monotonic() + 43, deadline_at or float('inf'))
    phase, operation, staged = 'collection', None, 0
    try:
        adapter.validate_source(source)
        if (not isinstance(collection_context, dict)
                or collection_context.get('p_category') != 'html'
                or not isinstance(collection_context.get('p_ticket'), str)
                or not collection_context['p_ticket']
                or type(source.get('fetch_checkpoint_version')) is not int
                or source['fetch_checkpoint_version'] != 1):
            raise PreviewError('fetch_checkpoint_context_missing')
        args = {'p_category': 'html', 'p_ticket': collection_context['p_ticket'],
                'p_source_key': adapter.SOURCE_KEY}
        operation = 'community_collector_read_fetch_checkpoint'
        _observe_collection_phase(observe_phase, 'fetch', operation=operation)
        saved = supabase_rpc(operation, args)
        if (not isinstance(saved, dict) or type(saved.get('revision')) is not int
                or saved['revision'] < 0 or 'checkpoint' not in saved
                or (saved['checkpoint'] is not None and not isinstance(saved['checkpoint'], dict))
                or (saved['checkpoint'] is None and saved['revision'] != 0)):
            raise PreviewError('fetch_checkpoint_invalid_response')
        revision = saved['revision']
        checkpoint, snapshot = robots_checkpoint.detach(saved['checkpoint'])
        _restore_checkpoint_robots(source, snapshot)
        operation = None

        def save_checkpoint(value):
            nonlocal revision, operation
            if pacing['wait_unbounded']:
                raise PreviewError('publisher_wait_requires_review')
            with_transport = robots_checkpoint.attach(value, _checkpoint_robots_snapshot(source))
            operation = 'community_collector_write_fetch_checkpoint'
            _observe_collection_phase(observe_phase, 'fetch' if phase == 'collection' else 'stage',
                                      operation=operation)
            acknowledged = supabase_rpc(operation, {
                **args, 'p_expected_revision': revision, 'p_checkpoint': with_transport,
                **pacing_rpc_fields(pacing)})
            if (not isinstance(acknowledged, dict) or acknowledged.get('checkpoint_saved') is not True
                    or type(acknowledged.get('revision')) is not int
                    or acknowledged['revision'] != revision + 1):
                raise PreviewError('fetch_checkpoint_invalid_response')
            revision = acknowledged['revision']
            if publisher_handoff is not None:
                publisher_handoff['ready_at'] = monotonic() + max(
                    1, pacing['crawl_delay_seconds'], pacing['retry_after_seconds'])
            operation = None

        already_complete = checkpoint is not None and checkpoint.get('phase') == 'stage'
        if not already_complete:
            operation = None
            _observe_collection_phase(observe_phase, 'fetch')
            fetch_deadline = min(monotonic() + 32, deadline - 9)
            def fetch(url, accept):
                if accept == 'application/json':
                    return fetch_visit_raleigh_page(url, deadline_at=fetch_deadline)
                return fetch_publisher(url, accept, respect_robots=True,
                    deadline_at=fetch_deadline, allowed_hosts=(adapter.HOST,))
            chunk = adapter.collect_chunk(source, fetch, checkpoint=checkpoint, deadline_at=fetch_deadline)
            checkpoint = chunk['checkpoint']
            # Commit the complete fetched prefix before staging even one row.
            save_checkpoint(checkpoint)
            if not chunk['complete']:
                return {'complete': 0, 'failed': 0, 'staged': 0, 'fetch_pending': True}
        header, state = adapter.decode_checkpoint(checkpoint, now=datetime.now(timezone.utc))
        if header['phase'] != 'stage' or header['cursor'] != header['manifest_count']:
            raise PreviewError('visit_raleigh_checkpoint_invalid')
        phase = 'staging'
        records = state['events']
        batches = 0
        while header['stage_cursor'] < header['record_count']:
            # Reserve a stage RPC, checkpoint RPC, finish callback and overhead.
            # Checkpoint bytes are unchanged while this header cursor advances.
            if monotonic() > deadline - 12 or batches >= 12:
                return {'complete': 0, 'failed': 0, 'staged': staged, 'fetch_pending': True}
            batch, size = [], 2
            for event in records[header['stage_cursor']:header['stage_cursor'] + STAGING_BATCH_SIZE]:
                event_size = len(json.dumps(event, ensure_ascii=False)) + 2
                if batch and size + event_size > 150_000:
                    break
                batch.append(event)
                size += event_size
            if not batch or size > 150_000:
                raise PreviewError('visit_raleigh_incomplete_event')
            operation = 'community_collector_record_staged_events'
            _observe_collection_phase(observe_phase, 'stage', operation=operation)
            written = supabase_rpc(operation, {'p_source_key': adapter.SOURCE_KEY, 'p_events': batch})
            if type(written) is not int or written != len(batch):
                # Never advance across an unacknowledged record. The ordinary
                # idempotent upsert makes replay safe after a lost checkpoint.
                raise PreviewError('database_unavailable')
            header['stage_cursor'] += written
            checkpoint = dict(checkpoint, stage_cursor=header['stage_cursor'])
            save_checkpoint(checkpoint)
            staged += written
            batches += 1
        if monotonic() > deadline - 6:
            return {'complete': 0, 'failed': 0, 'staged': staged, 'fetch_pending': True}
        samples = records[:MAX_PREVIEWS]
        while len(json.dumps(samples, ensure_ascii=False)) > 18_000:
            samples.pop()
        operation = 'community_collector_record_preview_v2'
        _observe_collection_phase(observe_phase, 'record', operation=operation)
        supabase_rpc(operation, {'p_source_key': adapter.SOURCE_KEY,
            'p_samples': samples, 'p_future_count': header['record_count'],
            'p_venue_count': sum(row.get('lat') is not None for row in records),
            'p_error': None, **pacing_rpc_fields(pacing)})
        if publisher_handoff is not None:
            publisher_handoff['ready_at'] = monotonic() + max(
                1, pacing['crawl_delay_seconds'], pacing['retry_after_seconds'])
        return {'complete': 1, 'failed': 0, 'staged': staged}
    except (PreviewError, OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
        # Infrastructure failures retain the checkpoint and acknowledged cursor
        # for the existing lease retry. They must not certify or erase a snapshot.
        if operation is not None or (isinstance(exc, PreviewError) and str(exc) in (
                'database_unavailable', 'fetch_checkpoint_context_missing', 'fetch_checkpoint_invalid_response')):
            _observe_collection_phase(observe_phase, 'stage' if phase == 'staging' else 'fetch',
                                      operation=operation, error=exc)
            raise
        code = str(exc) if isinstance(exc, PreviewError) or str(exc) in adapter.DIAGNOSTIC_CODES else 'invalid_visit_raleigh_payload'
        error = PreviewError(code)
        _observe_collection_phase(observe_phase, 'fetch', error=error)
        supabase_rpc('community_collector_record_preview_v2', {
            'p_source_key': source.get('source_key'), 'p_samples': [], 'p_future_count': 0,
            'p_venue_count': 0, 'p_error': code, **pacing_rpc_fields(pacing)})
        failure = failure_details(code, expected_source_error=True, phase=phase)
        return {'complete': 0, 'failed': 1, 'staged': 0, **failure}


def _preview_halifax_chunk(source, pacing, *, collection_context, deadline_at,
                           publisher_handoff=None, observe_phase=None):
    from roomquest import discover_halifax

    return _preview_fetch_chunk(source, pacing, adapter=discover_halifax,
        allowed_hosts=("gohalifaxva.com",), collection_context=collection_context,
        deadline_at=deadline_at, publisher_handoff=publisher_handoff, observe_phase=observe_phase)


def _preview_linked_description_chunk(source, pacing, *, collection_context, deadline_at,
                                      publisher_handoff=None, observe_phase=None):
    from roomquest import linked_event_descriptions

    return _preview_fetch_chunk(source, pacing, adapter=linked_event_descriptions,
        allowed_hosts=(linked_event_descriptions.PROFILES[source["source_key"]][2],),
        collection_context=collection_context, deadline_at=deadline_at,
        publisher_handoff=publisher_handoff, observe_phase=observe_phase)


def _preview_visit_atlantic_chunk(source, pacing, *, collection_context, deadline_at,
                                publisher_handoff=None, observe_phase=None):
    from roomquest import visit_atlantic_city

    return _preview_fetch_chunk(source, pacing, adapter=visit_atlantic_city,
        allowed_hosts=(visit_atlantic_city.HOST,), collection_context=collection_context,
        deadline_at=deadline_at, publisher_handoff=publisher_handoff, observe_phase=observe_phase)


def _preview_atlantic_community_chunk(source, pacing, *, collection_context, deadline_at,
                                     publisher_handoff=None, observe_phase=None):
    from roomquest import atlantic_city_community

    return _preview_fetch_chunk(source, pacing, adapter=atlantic_city_community,
        allowed_hosts=atlantic_city_community.ALLOWED_HOSTS[source['source_key']],
        collection_context=collection_context, deadline_at=deadline_at,
        publisher_handoff=publisher_handoff, observe_phase=observe_phase)


def _preview_greatday_chunk(source, pacing, *, collection_context, deadline_at,
                            publisher_handoff=None, observe_phase=None):
    from roomquest import greatday_atlantic_city

    return _preview_fetch_chunk(source, pacing, adapter=greatday_atlantic_city,
        allowed_hosts=greatday_atlantic_city.ALLOWED_HOSTS[source['source_key']],
        collection_context=collection_context, deadline_at=deadline_at,
        publisher_handoff=publisher_handoff, observe_phase=observe_phase)


def _preview_atlantic_continuation_chunk(source, pacing, *, collection_context, deadline_at,
                                         publisher_handoff=None, observe_phase=None):
    from roomquest import atlantic_city_library_chamber, atlantic_city_nightlife_more
    from roomquest import atlantic_city_studio, atlantic_city_cardboard_arena
    from roomquest import atlantic_city_local_venues

    adapter = next((module for module in (atlantic_city_library_chamber, atlantic_city_nightlife_more,
                                         atlantic_city_studio, atlantic_city_cardboard_arena,
                                         atlantic_city_local_venues)
                    if source['source_key'] in module.CHECKPOINT_KEYS), None)
    if adapter is None:
        raise PreviewError('publisher_checkpoint_required')
    return _preview_fetch_chunk(source, pacing, adapter=adapter,
        allowed_hosts=adapter.ALLOWED_HOSTS[source['source_key']],
        collection_context=collection_context, deadline_at=deadline_at,
        publisher_handoff=publisher_handoff, observe_phase=observe_phase)


def _preview_wasilla_chunk(source, pacing, **kwargs):
    from roomquest import anchorage_batch20_wasilla as wasilla
    return _preview_fetch_chunk(source, pacing, adapter=wasilla,
                                allowed_hosts=wasilla.ALLOWED_HOSTS[wasilla.KEY], **kwargs)


def _preview_new_york_chunk(source, pacing, *, collection_context, deadline_at,
                            publisher_handoff=None, observe_phase=None):
    from roomquest import new_york_sources
    try:
        adapter = new_york_sources.validate_source(source)
    except ValueError as exc:
        raise PreviewError('unregistered_new_york_source') from exc
    return _preview_fetch_chunk(source, pacing, adapter=adapter,
        allowed_hosts=adapter.ALLOWED_HOSTS[source['source_key']],
        collection_context=collection_context, deadline_at=deadline_at,
        publisher_handoff=publisher_handoff, observe_phase=observe_phase)


def _preview_boston_chunk(source, pacing, *, collection_context, deadline_at,
                            publisher_handoff=None, observe_phase=None):
    from roomquest import boston_sources
    try:
        adapter = boston_sources.validate_source(source)
    except ValueError as exc:
        raise PreviewError('unregistered_boston_source') from exc
    return _preview_fetch_chunk(source, pacing, adapter=adapter,
        allowed_hosts=adapter.ALLOWED_HOSTS[source['source_key']],
        collection_context=collection_context, deadline_at=deadline_at,
        publisher_handoff=publisher_handoff, observe_phase=observe_phase)


def _preview_raleigh_direct_chunk(source, pacing, *, collection_context, deadline_at,
                                 publisher_handoff=None, observe_phase=None):
    from roomquest import raleigh_direct_sources
    try:
        adapter = raleigh_direct_sources.validate_source(source)
    except ValueError as exc:
        raise PreviewError('unregistered_raleigh_direct_source') from exc
    return _preview_fetch_chunk(source, pacing, adapter=adapter,
        allowed_hosts=adapter.ALLOWED_HOSTS[source['source_key']],
        collection_context=collection_context, deadline_at=deadline_at,
        publisher_handoff=publisher_handoff, observe_phase=observe_phase)


def _preview_fetch_chunk(source, pacing, *, adapter, allowed_hosts, collection_context,
                         deadline_at, publisher_handoff=None, observe_phase=None):
    """Persist one lease-fenced complete-manifest chunk before any staging."""

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
            adapter_args = {}
            checkpoint = saved["checkpoint"]
            robots_host = robots_checkpoint.profile(source, allowed_hosts)
            if robots_host is not None:
                checkpoint, snapshot = robots_checkpoint.detach(checkpoint)
                _restore_checkpoint_robots(source, snapshot)
                if source["source_key"] == "radegast_hall_brooklyn_ny":
                    adapter_args['prepare_publisher'] = lambda url: _checkpoint_publisher_ready(
                        source, url, deadline)
            if source.get('source_key') == 'boston_cares_ma':
                adapter_args['render_calendar'] = lambda **window: render_boston_cares_calendar(
                    **window, deadline_at=deadline)
            from roomquest import atlantic_city_cardboard_arena
            if adapter is atlantic_city_cardboard_arena:
                adapter_args['render_calendar'] = lambda **window: render_cardboard_arena_calendar(
                    **window, deadline_at=deadline)
            from roomquest import raleigh_direct_arts, raleigh_direct_community
            if adapter is raleigh_direct_arts and source['source_key'] == raleigh_direct_arts.ARTSPACE:
                adapter_args['render_calendar'] = lambda **window: render_artspace_calendar(
                    **window, deadline_at=deadline)
            if adapter is raleigh_direct_community and source['source_key'] == raleigh_direct_community.GAME:
                adapter_args['read_public_events'] = lambda **window: read_game_theory_events(
                    **window, deadline_at=deadline)
            from roomquest import raleigh_followup_performance
            if adapter is raleigh_followup_performance:
                adapter_args['read_public_events'] = lambda **request: read_raleigh_followup_events(
                    **request, deadline_at=deadline)
            from roomquest import raleigh_next_social
            if adapter is raleigh_next_social and source['source_key'] == raleigh_next_social.BREWING:
                adapter_args['read_public_events'] = lambda **request: read_raleigh_brewing_occurrences(
                    **request, deadline_at=deadline)
            chunk = adapter.collect_chunk(
                source, lambda url, accept: fetch_publisher(
                    url, accept, respect_robots=True, deadline_at=deadline,
                    allowed_hosts=allowed_hosts),
                checkpoint=checkpoint, deadline_at=deadline, **adapter_args)
            if robots_host is not None:
                # A publisher/adapter-supplied field can never become authority.
                # Only our complete guarded response cache is signed and stored.
                chunk = dict(chunk, checkpoint=robots_checkpoint.attach(
                    chunk["checkpoint"], _checkpoint_robots_snapshot(source)))
        except PreviewError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            # Adapter messages are controlled diagnostics, never raw HTML or
            # parser values (for example an unparseable publisher clock).
            codes = {"unregistered_discover_halifax",
                     'local_venue_description_incomplete',
                     'collection_deadline',
                     'local_venue_calendar_date_conflict',
                     'local_venue_checkpoint_invalid',
                     'local_venue_checkpoint_size_limit',
                     'local_venue_clock_conflict',
                     'local_venue_clock_invalid',
                     'local_venue_clock_missing',
                     'local_venue_date_invalid',
                     'local_venue_date_missing_or_ambiguous',
                     'local_venue_description_container_changed',
                     'local_venue_description_date_conflict',
                     'local_venue_description_limit',
                     'local_venue_description_missing',
                     'local_venue_detail_identity',
                     'local_venue_duplicate_identity',
                     'local_venue_event_identity',
                     'local_venue_location_changed',
                     'local_venue_manifest_incomplete',
                     'local_venue_manifest_invalid',
                     'local_venue_nonpublic_or_cancelled',
                     'local_venue_nonpublic_or_sold_out',
                     'local_venue_participation_changed',
                     'local_venue_schedule_conflict',
                     'local_venue_schedule_unverified',
                     'local_venue_ticket_identity_unverified',
                     'local_venue_undated_edition_requires_review',
                     'local_venue_weekday_conflict',
                     'publisher_checkpoint_required',
                     'unregistered_atlantic_city_local_venue',
                     'atlantic_studio_checkpoint_invalid',
                     'atlantic_studio_checkpoint_size_limit',
                     'atlantic_studio_clock_conflict',
                     'atlantic_studio_detail_identity',
                     'atlantic_studio_detail_invalid',
                     'atlantic_studio_duplicate_session',
                     'atlantic_studio_eligibility_invalid',
                     'atlantic_studio_html_invalid',
                     'atlantic_studio_instructions_invalid',
                     'atlantic_studio_location_changed',
                     'atlantic_studio_manifest_invalid',
                     'atlantic_studio_session_identity',
                     'cardboard_calendar_shape_changed',
                     'cardboard_checkpoint_invalid',
                     'cardboard_checkpoint_size_limit',
                     'cardboard_description_limit',
                     'cardboard_description_missing',
                     'cardboard_detail_changed',
                     'cardboard_event_identity_changed',
                     'cardboard_manifest_incomplete',
                     'cardboard_public_calendar_identity_changed',
                     'cardboard_public_renderer_required',
                     'cardboard_schedule_changed',
                     'collection_deadline',
                     'invalid_cardboard_calendar_parameters',
                     'invalid_publisher_image',
                     'invalid_publisher_image_content_type',
                     'publisher_checkpoint_required',
                     'publisher_description_limit',
                     'publisher_description_missing',
                     'reviewed_poster_description_limit',
                     'reviewed_poster_description_missing',
                     'reviewed_poster_duplicate_identity',
                     'reviewed_poster_edition_changed',
                     'reviewed_poster_freshness_expired',
                     'reviewed_poster_gallery_changed',
                     'reviewed_poster_gallery_incomplete',
                     'reviewed_poster_invalid_image',
                     'reviewed_poster_manifest_changed',
                     'reviewed_poster_page_changed',
                     'reviewed_poster_page_identity',
                     'reviewed_poster_record_limit',
                     'reviewed_poster_script_changed',
                     'reviewed_poster_source_identity',
                     'reviewed_poster_timezone_required',
                     'reviewed_poster_venue_changed',
                     'source_record_limit',
                     'unregistered_atlantic_studio_source',
                     'unregistered_cardboard_arena_source', "halifax_checkpoint_invalid",
                     "halifax_checkpoint_size_limit", "halifax_directory_incomplete",
                     "halifax_directory_event_identity", "halifax_directory_detail_identity",
                     "halifax_directory_detail_conflict", "collection_deadline",
                     "unregistered_linked_description_source", "linked_description_checkpoint_invalid",
                     "linked_description_manifest_invalid", "linked_description_checkpoint_size_limit",
                     "rockhouse_detail_identity_mismatch", "rockhouse_detail_structure_missing",
                     "invalid_downtown_norfolk_detail_identity", "invalid_downtown_norfolk_detail_content",
                     "invalid_sandler_detail_identity", "invalid_sandler_detail_content",
                     "unregistered_visit_atlantic_city", "visit_atlantic_checkpoint_invalid",
                     "visit_atlantic_checkpoint_required", "visit_atlantic_checkpoint_size_limit",
                     "visit_atlantic_description_limit", "visit_atlantic_detail_dates",
                     "visit_atlantic_detail_identity", "visit_atlantic_detail_structure",
                     "visit_atlantic_duplicate_occurrence", "visit_atlantic_event_limit",
                     "visit_atlantic_manifest_limit", "visit_atlantic_sitemap_invalid",
                     "noyes_checkpoint_invalid", "noyes_checkpoint_size_limit",
                     "publisher_detail_limit", "publisher_next_event_cycle",
                     "publisher_calendar_identity_changed", "publisher_calendar_date_missing",
                     "publisher_event_detail_changed", "publisher_calendar_link_changed",
                     "publisher_event_time_changed", "invalid_event_end",
                     "publisher_next_event_changed", "publisher_event_identity_changed",
                     "publisher_description_limit", "unregistered_atlantic_city_community_source",
                     "municipal_calendar_limit", "municipal_calendar_identity_changed",
                     "municipal_event_identity_changed", "municipal_event_schedule_changed",
                     "municipal_checkpoint_invalid", "municipal_checkpoint_size_limit",
                     "publisher_checkpoint_required", "unregistered_greatday_source",
                     "greatday_pagination_invalid", "greatday_upcoming_collection_changed",
                     "greatday_card_identity_changed", "greatday_event_identity",
                     "greatday_card_date_invalid", "greatday_duplicate_identity",
                     "greatday_record_limit", "greatday_detail_date_invalid",
                     "greatday_detail_identity_changed", "greatday_detail_schedule_changed",
                     "greatday_detail_location_changed", "greatday_checkpoint_invalid",
                     "greatday_checkpoint_size_limit", "atlantic_city_description_limit",
                     "unregistered_atlantic_nightlife_source", "atlantic_nightlife_checkpoint_invalid",
                     "atlantic_nightlife_checkpoint_size_limit", "atlantic_nightlife_description_missing",
                     "atlantic_nightlife_event_identity", "atlantic_nightlife_event_limit",
                     "atlantic_nightlife_duplicate_occurrence", "hard_rock_calendar_schedule_changed",
                     "hard_rock_calendar_venue_changed", "hard_rock_detail_identity_changed",
                     "hard_rock_detail_schedule_changed", "hard_rock_detail_status_changed",
                     "unregistered_atlantic_library_chamber_source", "atlantic_library_checkpoint_invalid",
                     "atlantic_library_checkpoint_source", "atlantic_library_checkpoint_size_limit",
                     "federation_event_identity_changed", "federation_timezone_changed",
                     "federation_pagination_invalid", "federation_pagination_changed",
                     "federation_payload_invalid", "federation_pagination_identity_changed",
                     "federation_pagination_duplicate", "jfs_detail_identity_changed",
                     "jfs_detail_schedule_changed", "jfs_description_container_changed",
                     "jfs_calendar_changed", "jfs_event_identity_changed", "source_record_limit"}
            reason = exc.args[0] if len(exc.args) == 1 else None
            from roomquest import new_york_sources
            codes.update(new_york_sources.diagnostic_codes())
            from roomquest import boston_sources
            codes.update(boston_sources.diagnostic_codes())
            from roomquest import raleigh_direct_sources
            codes.update(raleigh_direct_sources.diagnostic_codes())
            raise PreviewError(reason if type(reason) is str and reason in codes
                               else "invalid_html_event_payload") from exc
        if pacing["wait_unbounded"]:
            raise PreviewError("publisher_wait_requires_review")
        from roomquest import new_york_sources
        if new_york_sources.adapter_for(source.get('source_key')) is not None:
            try:
                new_york_sources.validate_checkpoint(source, chunk.get('checkpoint'))
                if chunk.get('complete') and chunk['checkpoint']['cursor'] != chunk['checkpoint']['manifest_count']:
                    raise ValueError('new_york_checkpoint_invalid')
            except ValueError as exc:
                raise PreviewError(str(exc)) from exc
        from roomquest import boston_sources
        if boston_sources.adapter_for(source.get('source_key')) is not None:
            try:
                boston_sources.validate_checkpoint(source, chunk.get('checkpoint'))
                if chunk.get('complete') and chunk['checkpoint']['cursor'] != chunk['checkpoint']['manifest_count']:
                    raise ValueError('boston_checkpoint_invalid')
            except ValueError as exc:
                raise PreviewError(str(exc)) from exc
        operation = "community_collector_write_fetch_checkpoint"
        from roomquest import raleigh_direct_sources
        if raleigh_direct_sources.adapter_for(source.get('source_key')) is not None:
            try:
                raleigh_direct_sources.validate_checkpoint(source, chunk.get('checkpoint'))
                if chunk.get('complete') and not raleigh_direct_sources.checkpoint_complete(source, chunk['checkpoint']):
                    raise ValueError('raleigh_direct_checkpoint_invalid')
            except ValueError as exc:
                raise PreviewError(str(exc)) from exc
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
        from roomquest import raleigh_direct_sources
        if raleigh_direct_sources.adapter_for(source.get('source_key')) is not None:
            try:
                raleigh_direct_sources.validate_records(records, source)
            except ValueError as exc:
                raise PreviewError(str(exc)) from exc
        from roomquest import new_york_sources
        if new_york_sources.adapter_for(source.get('source_key')) is not None:
            try:
                new_york_sources.validate_records(records, source)
            except ValueError as exc:
                raise PreviewError(str(exc)) from exc
        from roomquest import boston_sources
        if boston_sources.adapter_for(source.get('source_key')) is not None:
            try:
                boston_sources.validate_records(records, source)
            except ValueError as exc:
                raise PreviewError(str(exc)) from exc
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


def _event_batches(events, *, empty=False):
    batches, batch, size = [], [], 2
    for event in events:
        event_size = len(json.dumps(event, ensure_ascii=False).encode("utf-8")) + 2
        if batch and (len(batch) >= STAGING_BATCH_SIZE or size + event_size > 150_000):
            batches.append(batch)
            batch, size = [], 2
        batch.append(event)
        size += event_size
    if batch or empty:
        batches.append(batch)
    return batches


def _stage_legacy_events(source, events, *, native_content, deadline, observe_phase):
    staged = 0
    operation = "community_collector_record_staged_events"
    for batch in _event_batches(events, empty=True):
        _observe_collection_phase(observe_phase, "stage")
        if monotonic() > deadline - 4:
            raise PreviewError("staging_deadline")
        _observe_collection_phase(observe_phase, "stage", operation=operation)
        written = supabase_rpc(operation, {
            "p_source_key": source["source_key"], "p_events": batch,
            **({"p_registered_native_content_version": 1} if native_content else {})
        })
        staged += int(written or 0)
    return staged


def _stage_incremental_events(snapshot, plan, *, native_content, deadline, observe_phase):
    staged = 0
    operation = "community_collector_stage_incremental"
    for batch in _event_batches(plan["changed"]):
        _observe_collection_phase(observe_phase, "stage")
        if monotonic() > deadline - 4:
            raise PreviewError("staging_deadline")
        _observe_collection_phase(observe_phase, "stage", operation=operation)
        result = supabase_rpc(operation, {
            **snapshot.collection_context, "p_source_key": snapshot.source_key,
            "p_policy_context": snapshot.policy_context, "p_context_hash": snapshot.context_hash,
            "p_events": batch,
            **({"p_registered_native_content_version": 1} if native_content else {})
        })
        if (isinstance(result, dict) and result.get("accepted") is False
                and result.get("requires_full") is True):
            # This response prepares the same lease for a complete legacy
            # replay, including counters already touched by earlier batches.
            return None
        if (not isinstance(result, dict) or result.get("accepted") is not True
                or type(result.get("staged")) is not int or result["staged"] != len(batch)):
            raise PreviewError("incremental_receipt_invalid")
        staged += result["staged"]
    return staged


def _process_claimed_source_with_pacing(source, pacing, *, deadline_at=None, publisher_handoff=None,
                                       observe_phase=None, collection_context=None):
    if source.get('source_key') == 'visit_raleigh_nc':
        return _process_visit_raleigh(source, pacing, collection_context=collection_context,
            deadline_at=deadline_at, publisher_handoff=publisher_handoff, observe_phase=observe_phase)
    from roomquest import anchorage_batch20_wasilla as wasilla
    from roomquest.linked_event_descriptions import PROFILES as linked_description_profiles
    from roomquest import new_york_sources
    new_york_checkpoint_keys = new_york_sources.checkpoint_keys()
    from roomquest import boston_sources
    boston_checkpoint_keys = boston_sources.checkpoint_keys()
    from roomquest import raleigh_direct_sources
    raleigh_direct_checkpoint_keys = raleigh_direct_sources.checkpoint_keys()
    from roomquest import atlantic_city_library_chamber, atlantic_city_nightlife_more
    from roomquest import atlantic_city_studio, atlantic_city_cardboard_arena
    from roomquest import atlantic_city_local_venues
    continuation_checkpoint_keys = (atlantic_city_library_chamber.CHECKPOINT_KEYS
                                    | atlantic_city_nightlife_more.CHECKPOINT_KEYS
                                    | atlantic_city_studio.CHECKPOINT_KEYS
                                    | atlantic_city_cardboard_arena.CHECKPOINT_KEYS
                                    | atlantic_city_local_venues.CHECKPOINT_KEYS)

    phase, failure = "collection", {}
    native_content = False
    operation = None
    incremental = current_snapshot()
    incremental_plan = None
    try:
        _observe_collection_phase(observe_phase, "fetch")
        from roomquest.registered_native_content import enabled as native_enabled, validate_record, VERSION as NATIVE_VERSION
        native_content = native_enabled(source)
        deadline = min(monotonic() + 43, deadline_at or float("inf"))
        checkpoint_key = source.get("source_key")
        if ((checkpoint_key in ("discover_halifax_va", "visit_atlantic_city_nj", "noyes_arts_atlantic_city_nj", "atlantic_city_municipal_nj", "greatday_atlantic_city_nj")
                or checkpoint_key == wasilla.KEY
                or checkpoint_key in continuation_checkpoint_keys
                or checkpoint_key in new_york_checkpoint_keys
                or checkpoint_key in boston_checkpoint_keys
                or checkpoint_key in raleigh_direct_checkpoint_keys
                or checkpoint_key in linked_description_profiles)
                and collection_context is not None
                and type(source.get("fetch_checkpoint_version")) is int
                and source["fetch_checkpoint_version"] == 1):
            preview_chunk = (_preview_halifax_chunk if checkpoint_key == "discover_halifax_va"
                             else _preview_wasilla_chunk if checkpoint_key == wasilla.KEY
                             else _preview_new_york_chunk if checkpoint_key in new_york_checkpoint_keys
                             else _preview_boston_chunk if checkpoint_key in boston_checkpoint_keys
                             else _preview_raleigh_direct_chunk if checkpoint_key in raleigh_direct_checkpoint_keys
                             else _preview_atlantic_continuation_chunk if checkpoint_key in continuation_checkpoint_keys
                             else _preview_greatday_chunk if checkpoint_key == "greatday_atlantic_city_nj"
                             else _preview_visit_atlantic_chunk if checkpoint_key == "visit_atlantic_city_nj"
                             else _preview_atlantic_community_chunk if checkpoint_key in (
                                 "noyes_arts_atlantic_city_nj", "atlantic_city_municipal_nj")
                             else _preview_linked_description_chunk)
            output = preview_chunk(
                source, pacing, collection_context=collection_context, deadline_at=deadline,
                publisher_handoff=publisher_handoff, observe_phase=observe_phase)
            if output.get("fetch_pending"):
                return {"complete": 0, "failed": 0, "staged": 0, "fetch_pending": True}
        else:
            output = preview_source(source, deadline_at=deadline - 4)
        if pacing["wait_unbounded"]:
            raise PreviewError("publisher_wait_requires_review")
        events = output.pop("p_events", [])
        if native_content:
            if output.get('p_parser_capability') != NATIVE_VERSION:
                raise PreviewError('registered_native_evidence_invalid')
            for event in events:
                validate_record(event, source)
        phase = "staging"
        _observe_collection_phase(observe_phase, "stage")
        incremental_plan = incremental.plan(events, output) if incremental is not None else None
        if incremental_plan is not None:
            operation = "community_collector_stage_incremental"
            staged = _stage_incremental_events(incremental, incremental_plan,
                native_content=native_content, deadline=deadline, observe_phase=observe_phase)
            if staged is None:
                incremental_plan = None
        if incremental_plan is None:
            operation = "community_collector_record_staged_events"
            staged = _stage_legacy_events(source, events, native_content=native_content,
                                          deadline=deadline, observe_phase=observe_phase)
    except (PreviewError, OSError, ValueError) as exc:
        _observe_collection_phase(observe_phase, "fetch" if phase == "collection" else "stage",
                                  operation=operation, error=exc)
        output = {
            "p_source_key": source["source_key"], "p_samples": [],
            "p_future_count": 0, "p_venue_count": 0,
            "p_error": str(exc)[:120] if isinstance(exc, PreviewError) else "source_parse_error",
        }
        staged = 0
        incremental_plan = None
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
    publisher_media = (html and (source_key in NEBRASKA_VENUES or source_key in RALEIGH_SOURCES or source_key in MARYLAND_HTML or source_key in VA_WIX_SOURCES or source_key == 'porch_on_main_flowery_branch_ga' or source_key == 'barefoot_sailing_flowery_branch_ga' or source_key == 'explore_braselton_official_ga' or source_key in ('visit_farmville_va', 'prizery_va', 'red_door_104_va', 'south_boston_speedway_va', 'discover_halifax_va', 'sova_innovation_hub_va'))) or reviewed_chamber or (source_key in ('madison_county_parks_ia', 'think_iowa_city_ia', 'rosemont_of_virginia', 'longwood_basketball_va', 'hurrdat_sports_bar_ne', ARTS, PG_PARKS) and source.get('kind') == 'json'
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
    from roomquest import santa_cruz_faith_community
    publisher_media = publisher_media or (
        source_key == santa_cruz_faith_community.KEY
        and (source.get('feed_url'), source.get('kind'), source.get('platform_adapter'))
            == santa_cruz_faith_community.SOURCES[santa_cruz_faith_community.KEY]
        and source.get('timezone') == santa_cruz_faith_community.ZONE)
    from roomquest import santa_cruz_little_giant
    publisher_media = publisher_media or (
        source_key == santa_cruz_little_giant.KEY
        and (source.get('feed_url'), source.get('kind'), source.get('platform_adapter'))
            == santa_cruz_little_giant.SOURCES[santa_cruz_little_giant.KEY]
        and source.get('timezone') == santa_cruz_little_giant.ZONE)
    from roomquest import santa_cruz_goat_fitness
    publisher_media = publisher_media or (
        source_key == santa_cruz_goat_fitness.KEY
        and (source.get('feed_url'),source.get('kind'),source.get('platform_adapter'))
            == santa_cruz_goat_fitness.SOURCES[santa_cruz_goat_fitness.KEY]
        and source.get('timezone') == santa_cruz_goat_fitness.ZONE)
    from roomquest import santa_cruz_chess_club
    publisher_media = publisher_media or (
        source_key == santa_cruz_chess_club.KEY
        and (source.get('feed_url'),source.get('kind'),source.get('platform_adapter'))
            == santa_cruz_chess_club.SOURCES[santa_cruz_chess_club.KEY]
        and source.get('timezone') == santa_cruz_chess_club.ZONE)
    from roomquest import santa_cruz_downtown
    publisher_media = publisher_media or (
        source_key == santa_cruz_downtown.KEY
        and (source.get('feed_url'),source.get('kind'),source.get('platform_adapter'))
            == santa_cruz_downtown.SOURCES[santa_cruz_downtown.KEY]
        and source.get('timezone') == santa_cruz_downtown.ZONE)
    from roomquest import santa_cruz_hotel_holidays
    publisher_media = publisher_media or (
        source_key in santa_cruz_hotel_holidays.SOURCES
        and (source.get('feed_url'),source.get('kind'),source.get('platform_adapter'))
            == santa_cruz_hotel_holidays.SOURCES[source_key]
        and source.get('timezone') == santa_cruz_hotel_holidays.ZONE)
    from roomquest import santa_cruz_watsonville_taiko
    publisher_media = publisher_media or (
        source_key == santa_cruz_watsonville_taiko.KEY
        and (source.get('feed_url'),source.get('kind'),source.get('platform_adapter'))
            == santa_cruz_watsonville_taiko.SOURCES[santa_cruz_watsonville_taiko.KEY]
        and source.get('timezone') == santa_cruz_watsonville_taiko.ZONE)
    from roomquest import santa_cruz_dante
    publisher_media = publisher_media or (
        source_key==santa_cruz_dante.KEY
        and (source.get('feed_url'),source.get('kind'),source.get('platform_adapter'))
            == santa_cruz_dante.SOURCES[santa_cruz_dante.KEY]
        and source.get('timezone') == santa_cruz_dante.ZONE)
    from roomquest import santa_cruz_art_league
    publisher_media = publisher_media or (
        source_key==santa_cruz_art_league.KEY
        and (source.get('feed_url'),source.get('kind'),source.get('platform_adapter'))
            == santa_cruz_art_league.SOURCES[santa_cruz_art_league.KEY]
        and source.get('timezone') == santa_cruz_art_league.ZONE)
    from roomquest import santa_cruz_fabrica
    publisher_media = publisher_media or (
        source_key==santa_cruz_fabrica.KEY
        and (source.get('feed_url'),source.get('kind'),source.get('platform_adapter'))
            == santa_cruz_fabrica.SOURCES[santa_cruz_fabrica.KEY]
        and source.get('timezone') == santa_cruz_fabrica.ZONE)
    from roomquest import santa_cruz_jack_oneill
    publisher_media = publisher_media or (
       source_key==santa_cruz_jack_oneill.KEY
       and (source.get('feed_url'),source.get('kind'),source.get('platform_adapter'))
           == santa_cruz_jack_oneill.SOURCES[santa_cruz_jack_oneill.KEY]
       and source.get('timezone')==santa_cruz_jack_oneill.ZONE)
    from roomquest import santa_cruz_square_venues
    publisher_media = publisher_media or (
        source_key in santa_cruz_square_venues.SOURCES
        and (source.get('feed_url'),source.get('kind'),source.get('platform_adapter'))
            == santa_cruz_square_venues.SOURCES[source_key]
        and source.get('timezone') == santa_cruz_square_venues.ZONE)
    from roomquest import santa_cruz_rio, santa_cruz_local_venues
    publisher_media = publisher_media or (
        (source_key == santa_cruz_rio.KEY
         and (source.get('feed_url'),source.get('kind'),source.get('platform_adapter'))
             == santa_cruz_rio.SOURCES[santa_cruz_rio.KEY]
         and source.get('timezone') == santa_cruz_rio.ZONE)
        or (source_key in santa_cruz_local_venues.SOURCES
            and (source.get('feed_url'),source.get('kind'),source.get('platform_adapter'))
                == santa_cruz_local_venues.SOURCES[source_key]
            and source.get('timezone') == santa_cruz_local_venues.ZONE))
    from roomquest import santa_cruz_sources
    publisher_media = publisher_media or (
        source_key in santa_cruz_sources.SOURCES and source.get('kind') == 'json'
        and source.get('platform_adapter') == 'wordpress')
    from roomquest import knoxville_sources
    # Knoxville Events Calendar sources join the reviewed WordPress image cohort.
    publisher_media = publisher_media or (
        source_key in knoxville_sources.SOURCES and source.get('kind') == 'json'
        and source.get('platform_adapter') == 'wordpress')
    from roomquest import gulf_recurring, gulf_seasonal, gulf_venues
    publisher_media = publisher_media or (html and any(
        source_key in module.SOURCES for module in (gulf_recurring, gulf_seasonal, gulf_venues)))
    publisher_media = publisher_media or native_content
    if native_content:
        # The v3 error receipt also identifies the negotiated protocol; it does
        # not certify missing/partial/oversized snapshots as complete.
        output['p_parser_capability'] = NATIVE_VERSION
    preview_rpc = ("community_collector_record_preview_v3"
                   if publisher_media
                   else "community_collector_record_preview_v2" if html or ical or civic
                   else "community_collector_record_preview")
    if not publisher_media:
        # Only the v3 RPC accepts a parser capability marker.
        output.pop("p_parser_capability", None)
    if incremental_plan is not None and output["p_error"] is None:
        operation = "community_collector_complete_incremental"
        completion_phase = "record"
        try:
            _observe_collection_phase(observe_phase, "record", operation=operation)
            result = supabase_rpc(operation, {
                **incremental.collection_context, "p_source_key": source_key,
                "p_receipt": incremental.receipt(incremental_plan),
                "p_preview": {
                    "version": 3 if publisher_media else 2 if html or ical or civic else 1,
                    "samples": output["p_samples"], "future_count": output["p_future_count"],
                    "venue_count": output["p_venue_count"],
                    **({"parser_capability": output["p_parser_capability"]}
                       if "p_parser_capability" in output else {}),
                    **{key.removeprefix("p_"): value for key, value in pacing_rpc_fields(pacing).items()},
                },
            })
            if (isinstance(result, dict) and result.get("accepted") is False
                    and result.get("requires_full") is True):
                # All parsed bodies are still held locally. The server has
                # reset only this lease's observation counters for safe replay.
                operation = "community_collector_record_staged_events"
                completion_phase = "stage"
                staged = _stage_legacy_events(source, events, native_content=native_content,
                                              deadline=deadline, observe_phase=observe_phase)
            elif (isinstance(result, dict) and result.get("accepted") is True
                    and type(result.get("publication_required")) is bool):
                if publisher_handoff is not None and not pacing["wait_unbounded"]:
                    publisher_handoff["ready_at"] = monotonic() + max(
                        1, pacing["crawl_delay_seconds"], pacing["retry_after_seconds"])
                return {"complete": 1, "failed": 0, "staged": staged,
                        "publication_required": result["publication_required"]}
            else:
                raise PreviewError("incremental_receipt_invalid")
        except (PreviewError, OSError, ValueError) as exc:
            _observe_collection_phase(observe_phase, completion_phase, operation=operation, error=exc)
            output = {
                "p_source_key": source_key, "p_samples": [], "p_future_count": 0, "p_venue_count": 0,
                "p_error": str(exc)[:120] if isinstance(exc, PreviewError) else "source_parse_error",
                **({"p_parser_capability": NATIVE_VERSION} if native_content else {}),
            }
            staged = 0
            failure = failure_details(output["p_error"],
                expected_source_error=isinstance(exc, PreviewError), phase="staging")
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


