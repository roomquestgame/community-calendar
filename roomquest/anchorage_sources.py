"""Anchorage publisher calendars, using the existing ICS and Squarespace lanes.

No city-center or SquareSpace's default New York map pins. Every staged event
has its own nonempty, untruncated, sanitized publisher description and a
reviewed venue street. Ambiguous places and activities are held for curation.
Image URLs are publisher candidates only; downstream rights gates decide use.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import math
import re
from time import monotonic
from urllib.parse import urljoin, urlsplit

from roomquest.mapsee_adapter import plain, record, timestamp

log = logging.getLogger(__name__)
ZONE = "America/Anchorage"
LIBRARY = "anchorage_public_library_ak"
GARDEN = "municipal_mapsee_e6deef1a689464c9cd322b7b"
SOURCES = {
    LIBRARY: ("https://anchorage.librarycalendar.com/events/feed/ical", "ical", "ical"),
    GARDEN: ("https://www.alaskabg.org/upcoming-events-workshops", "json", "squarespace"),
}
ALLOWED_HOSTS = {key: (urlsplit(value[0]).hostname,) for key, value in SOURCES.items()}
MAX_DESCRIPTION = 12000
MAX_RECORDS = 500
WINDOW_DAYS = 60
GARDEN_VENUE = ("Alaska Botanical Garden", "4601 Campbell Airstrip Road, Anchorage, AK 99507", "Anchorage")

# Verified against the Anchorage Public Library branch directory and the
# publisher's own ICS LOCATION. The address must appear in each event's record.
# The library's posted Loussac ZIP is 99502; do not invent a corrected ZIP.
LIBRARY_BRANCHES = {
    "3600 denali": ("Z.J. Loussac Library", "3600 Denali Street, Anchorage, AK 99502", "Anchorage"),
    "12001 business": ("Chugiak-Eagle River Library", "12001 Business Blvd #176, Eagle River, AK 99577", "Eagle River"),
    "1251 muldoon": ("Muldoon Library", "1251 Muldoon Road Suite 158, Anchorage, AK 99504", "Anchorage"),
    "120 bragaw": ("Mountain View Library", "120 Bragaw Street, Anchorage, AK 99508", "Anchorage"),
    "250 egloff": ("Scott & Wesley Gerrish Library", "250 Egloff Drive, Girdwood, AK 99587", "Girdwood"),
}
NONPUBLIC = re.compile(r"\b(?:cancelled|canceled|postponed|private event|invitation[- ]only|staff[- ]only)\b", re.I)
VIRTUAL = re.compile(r"\b(?:online only|virtual only|zoom only|webinar)\b", re.I)
IMAGE_BLOCK = re.compile(r"(?:^|[-_/])(?:favicon|logo|icon|avatar|pixel|placeholder)(?:[-_.]|$)", re.I)
EVENT_PATH = re.compile(r"/event/[a-z0-9]+(?:-[a-z0-9]+)*/?")
GARDEN_PATH = re.compile(r"/upcoming-events-workshops/[a-z0-9]+(?:-[a-z0-9]+)*/?")
IMAGE_PATH = re.compile(r"/content/v1/[A-Za-z0-9]+/[A-Za-z0-9_-]+/[^?#]+\.(?:jpe?g|png|webp)", re.I)

def _hold(source, identity, reason):
    log.warning("anchorage_event_held source=%s id=%s reason=%s", source, str(identity)[:140], reason)

def _description(raw):
    from roomquest.event_description import description
    if not isinstance(raw, str):
        return ""
    text = description(raw, limit=max(len(raw), MAX_DESCRIPTION + 1))
    return text if text.strip() and len(text) <= MAX_DESCRIPTION else None

def event_url(source_key, url):
    if source_key not in SOURCES or not isinstance(url, str) or len(url) > 2000:
        return False
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname == urlsplit(SOURCES[source_key][0]).hostname
                and not parsed.username and not parsed.password and parsed.port in (None, 443)
                and not parsed.query and not parsed.fragment
                and bool((EVENT_PATH if source_key == LIBRARY else GARDEN_PATH).fullmatch(parsed.path)))
    except ValueError:
        return False

def photo_url(source_key, url):
    """Only original-size images from Garden's own Squarespace asset space."""
    if source_key != GARDEN or not isinstance(url, str) or len(url) > 2000:
        return None
    try:
        parsed = urlsplit(url)
        return (url if parsed.scheme == "https" and parsed.netloc == "images.squarespace-cdn.com"
                and not parsed.query and not parsed.fragment and not IMAGE_BLOCK.search(parsed.path)
                and IMAGE_PATH.fullmatch(parsed.path) else None)
    except ValueError:
        return None

def _branch(location):
    text = plain(location).casefold()
    if "ak" not in text and "alaska" not in text:
        return None
    candidates = [branch for key, branch in LIBRARY_BRANCHES.items()
                  if re.search(r"(?<!\d)" + re.escape(key) + r"\b", text)]
    return candidates[0] if len(candidates) == 1 else None

def _event_category(title, labels, body, *, garden=False):
    """Conservative activity-specific signals; no fabricated 'Other' default."""
    primary = plain(title).casefold()
    category = " ".join(str(x) for x in labels).casefold()
    cues = primary + " " + category
    if re.search(r"storytime|read aloud|literacy|book club|author talk|lecture|tech help|computer class|stem|science|history talk", cues):
        return "learn"
    if re.search(r"craft|maker|sewing|knit|crochet|painting|watercolor|wreath|art workshop|creative writing|art class|origami|lego|build[ -]a", cues):
        return "create"
    if re.search(r"chess|board games?|dungeons|dragon|pokemon|pokémon|gaming|trivia|tournament|magic the gathering", cues):
        return "sports"
    if re.search(r"concert|live music|sing.along|choir|music performance", cues):
        return "music"
    if re.search(r"yoga|fitness|tai chi|stretching|exercise|wellness|meditation", cues):
        return "health"
    if re.search(r"food pantry|volunteer|donation drive|giveaway|coat drive", cues):
        return "give_back"
    if re.search(r"movie|film screening|puppet show|theatre|theater performance", cues):
        return "movies_theater"
    if re.search(r"garden tour|botanical|horticulture|native plants?|plant walk|gardening|seed swap|seed starting", cues):
        return "gardens_nature"
    if re.search(r"art exhibit|gallery|heritage|cultural celebration", cues):
        return "arts_culture"
    if re.search(r"community meeting|city council|public hearing|civic", cues):
        return "civic"
    if re.search(r"drop.in|social hour|meetup|game night|community gathering|coffee chat|conversation circle", cues):
        return "hang_out"
    if re.search(r"holiday market|craft fair|festival|bazaar|makers market", cues):
        return "festival"
    if re.search(r"workshop|training|tutorial|educat|class|course|tutorial|talk|book discussion|reading|homework|tutor", cues):
        return "learn"
    if garden and re.search(r"botanical garden|wildflower|flowers?|trees?|plants?|nature", primary + " " + plain(body).casefold()[:200]):
        return "gardens_nature"
    return None

def _collect_library(source, fetch, now, deadline):
    from icalendar import Calendar
    from roomquest.ics_adapter import parse as parse_ics
    if monotonic() >= deadline:
        raise ValueError("collection_deadline")
    raw = fetch(SOURCES[LIBRARY][0], "text/calendar")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    if not isinstance(raw, str) or len(raw) > 3_000_000:
        raise ValueError("source_body_limit")
    calendar = Calendar.from_ical(raw)
    components = calendar.walk("VEVENT")
    if len(components) > 1000:
        raise ValueError("source_record_limit")
    # The shared legacy ICS preview clips description at 12k. Reject those
    # occurrences *before* entering it; no silent truncation.
    invalid_uids = set()
    for event in components:
        uid = str(event.get("UID", ""))
        body = _description(str(event.get("DESCRIPTION", "")))
        if body is None:
            invalid_uids.add(uid)
    source_info = dict(source, url=SOURCES[LIBRARY][0])
    rows = parse_ics(raw, source_info, legacy=False, include_description=True)
    eligible = {}
    for row in rows:
        uid = row["id"].split("__", 1)[0]
        if uid in invalid_uids:
            _hold(LIBRARY, uid, "description_missing_or_oversized")
            continue
        title = row.get("title", "")
        if NONPUBLIC.search(title) or VIRTUAL.search(title):
            continue
        venue = _branch(row.get("venue_address") or row.get("venue_name"))
        if venue is None:
            _hold(LIBRARY, uid, "unverified_or_remote_library_venue")
            continue
        if not event_url(LIBRARY, row.get("event_url")):
            _hold(LIBRARY, uid, "event_link_unverified")
            continue
        body = _description(row.get("description"))
        if body is None:
            _hold(LIBRARY, uid, "description_missing_or_oversized")
            continue
        labels = row.get("publisher_categories") or []
        category = _event_category(title, labels, body)
        if not category:
            _hold(LIBRARY, uid, "category_review_required")
            continue
        if timestamp(row["starts_at"]) > now + timedelta(days=WINDOW_DAYS):
            continue
        row.update(venue_name=venue[0], venue_address=venue[1], venue_city=venue[2],
                   timezone=ZONE, description=body, category=category,
                   location_provenance="publisher_event_verified_library_branch",
                   publisher_categories=labels, lat=None, lng=None,
                   reason="missing_verified_venue_geo")
        key = (row["id"], row["starts_at"])
        if key in eligible and eligible[key] != row:
            raise ValueError("conflicting_library_occurrence")
        eligible[key] = row
    return list(eligible.values())

def _collect_garden(source, fetch, now, deadline):
    if monotonic() >= deadline:
        raise ValueError("collection_deadline")
    payload = json.loads(fetch(SOURCES[GARDEN][0] + "?format=json", "application/json"))
    if not isinstance(payload, dict) or not isinstance(payload.get("upcoming"), list):
        raise ValueError("invalid_squarespace_payload")
    website = payload.get("website") or {}
    if not isinstance(website, dict) or website.get("timeZone") not in (None, ZONE):
        raise ValueError("publisher_timezone_changed")
    from roomquest.squarespace import check_pagination
    check_pagination(payload, upcoming=True)
    upcoming = payload["upcoming"]
    if len(upcoming) > MAX_RECORDS:
        raise ValueError("source_record_limit")
    eligible = {}
    for item in upcoming:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("invalid_squarespace_record")
        identity = item["id"]
        if item.get("workflowState") != 1 or item.get("cancelled") or item.get("allDay") or item.get("allDayEvent"):
            continue
        title = plain(item.get("title"))
        if not title or NONPUBLIC.search(title) or VIRTUAL.search(title):
            continue
        location = item.get("location") if isinstance(item.get("location"), dict) else {}
        explicit = " ".join(str(location.get(field) or "") for field in ("addressTitle", "addressLine1", "addressLine2"))
        # Calendar's generic 40.7207559/-74.0007613 SquareSpace marker is NOT
        # an Anchorage coordinate. Verify the actual event is hosted onsite.
        if (plain(explicit) and not re.search(r"\balaska botanical garden\b|4601 campbell airstrip", explicit, re.I)):
            _hold(GARDEN, identity, "offsite_or_conflicting_garden_venue")
            continue
        if re.search(r"\b(off.site|held at another|location to be announced)\b", title + " " + str(item.get("body", "")), re.I):
            _hold(GARDEN, identity, "offsite_garden_event_review")
            continue
        times = (item.get("startDate"), item.get("endDate"))
        if any(isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) for t in times):
            _hold(GARDEN, identity, "time_missing")
            continue
        begin, end = (timestamp(t) for t in times)
        if end <= begin:
            _hold(GARDEN, identity, "end_conflict")
            continue
        if end <= now or begin > now + timedelta(days=WINDOW_DAYS):
            continue
        narrative = _description(item.get("body") or item.get("excerpt"))
        if narrative is None:
            _hold(GARDEN, identity, "description_missing_or_oversized")
            continue
        labels = [plain(x) for x in item.get("categories", []) if isinstance(x, str)]
        category = _event_category(title, labels, narrative, garden=True)
        if not category:
            _hold(GARDEN, identity, "category_review_required")
            continue
        full_url = item.get("fullUrl")
        url = urljoin(SOURCES[GARDEN][0], full_url) if isinstance(full_url, str) else ""
        if not event_url(GARDEN, url):
            _hold(GARDEN, identity, "event_link_unverified")
            continue
        row = record(title, begin.isoformat(), end.isoformat(), *GARDEN_VENUE,
                     url, identity, category, tz=ZONE, retain_until_end=True)
        if row is None:
            continue
        row.update(description=narrative, category=category, timezone=ZONE,
                   publisher_categories=labels, location_provenance="reviewed_official_garden_street",
                   lat=None, lng=None, reason="missing_verified_venue_geo")
        from roomquest.publisher_evidence import attach
        row = attach(row, GARDEN, candidate=item.get("assetUrl"))
        key = (row["id"], row["starts_at"])
        if key in eligible and eligible[key] != row:
            raise ValueError("conflicting_garden_occurrence")
        eligible[key] = row
    return list(eligible.values())

def collect(source, fetch, *, deadline_at=None, now=None):
    key = source.get("source_key")
    if (key not in SOURCES or
            (source.get("feed_url"), source.get("kind"), source.get("platform_adapter")) != SOURCES[key] or
            source.get("timezone") != ZONE):
        raise ValueError("unregistered_anchorage_source")
    now = now or datetime.now(timezone.utc)
    deadline = min(monotonic() + 36, deadline_at if deadline_at is not None else float("inf"))
    rows = _collect_library(source, fetch, now, deadline) if key == LIBRARY else _collect_garden(source, fetch, now, deadline)
    if len(rows) > MAX_RECORDS:
        raise ValueError("source_record_limit")
    return sorted(rows, key=lambda row: (row["starts_at"], row["title"], row["id"]))
