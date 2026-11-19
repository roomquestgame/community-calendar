"""GOAT Santa Cruz's first-party Punchpass fitness class schedule.

Only independently dated HYROX sessions with full owner descriptions, exact
ends and genuine event-specific venue street. No synthesized repeats or pins.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from roomquest.mapsee_adapter import record
from roomquest.publisher_evidence import attach
from roomquest.event_description import description

KEY = "goat_santa_cruz_hyrox_ca"
CALENDAR = "https://goatsantacruz.punchpass.com/calendar"
HOST = "goatsantacruz.punchpass.com"
ZONE = "America/Los_Angeles"
SOURCES = {KEY: (CALENDAR, "html", "html")}
ALLOWED_HOSTS = {KEY: (HOST,)}
ADDRESS = "1055 17th Ave, Santa Cruz, CA 95062"
MAX_RECORDS = 6
MAX_DESCRIPTION = 9000
CLASS_LINK = re.compile(r"/(?:org/10771/)?classes/([0-9]{6,12})")
SCHEDULED = "https://schema.org/EventScheduled"
EVENT_TYPE = "https://schema.org/OfflineEventAttendanceMode"


def event_url(value):
    if not isinstance(value, str):
        return False
    try:
        u = urlsplit(value)
        return (u.scheme == "https" and u.hostname == HOST
                and u.port in (None, 443) and not u.username and not u.password
                and not u.query and not u.fragment
                and re.fullmatch(r"/classes/[0-9]{6,12}", u.path) is not None)
    except ValueError:
        return False


def _detail(url, fetch, now):
    raw = fetch(url, "text/html")
    if not isinstance(raw, str) or not 1000 <= len(raw) <= 150000:
        raise ValueError("goat_detail_invalid")
    soup = BeautifulSoup(raw, "html.parser")
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    events = []
    for script in scripts:
        try:
            item = json.loads(script.string or script.get_text())
        except (TypeError, ValueError):
            continue
        if isinstance(item, dict) and item.get("@type") == "Event":
            events.append(item)
    if len(events) != 1:
        raise ValueError("goat_event_schema_missing")
    e = events[0]
    if (e.get("eventStatus") != SCHEDULED
            or e.get("eventAttendanceMode") != EVENT_TYPE
            or not isinstance(e.get("name"), str)
            or "HYROX" not in e["name"].upper()):
        return None
    owner = e.get("organizer") or {}
    venue = e.get("location") or {}
    addr = venue.get("address") or {} if isinstance(venue, dict) else {}
    if (not isinstance(owner, dict) or owner.get("name") != "GOAT Santa Cruz"
            or owner.get("url") != "https://www.goatsantacruz.com"
            or not isinstance(addr, dict)
            or addr.get("streetAddress") != "1055 17th Ave"
            or addr.get("addressLocality") != "Santa Cruz"
            or addr.get("addressRegion") != "CA"
            or addr.get("postalCode") != "95062"
            or addr.get("addressCountry") != "US"):
        return None
    try:
        start = datetime.fromisoformat(e["startDate"])
        end = datetime.fromisoformat(e["endDate"])
        if start.utcoffset() is None or end.utcoffset() is None:
            return None
        zone = ZoneInfo(ZONE)
        if (start.astimezone(zone).replace(tzinfo=None) != start.replace(tzinfo=None)
                or end.astimezone(zone).replace(tzinfo=None) != end.replace(tzinfo=None)):
            return None
    except (ValueError, TypeError, KeyError):
        return None
    start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    if not (now - timedelta(hours=3) <= start <= now + timedelta(days=60)
            and end > start and end - start <= timedelta(hours=3)):
        return None
    original = soup.select_one(".wysiwygified-text")
    if original is None:
        return None
    body = description(original.get_text("\n", strip=True), limit=MAX_DESCRIPTION + 1)
    if not body or not 120 <= len(body) <= MAX_DESCRIPTION:
        return None
    title = e["name"].strip()
    uid = urlsplit(url).path.rsplit("/", 1)[-1]
    row = record(title, start.isoformat(), end.isoformat(), "GOAT Santa Cruz",
                 ADDRESS, "Santa Cruz", url, "goat-" + uid, "HYROX",
                 None, None, ZONE, retain_until_end=True)
    if row is None:
        return None
    row.update(description=body, timezone=ZONE,
               publisher_categories=["HYROX"],
               location_provenance="original_punchpass_event_schema_exact_street",
               location_evidence_url=url, schedule_evidence_url=url)
    return attach(row, KEY, evidence_url=url)


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY
            or (source.get("feed_url"), source.get("kind"),
                source.get("platform_adapter")) != SOURCES[KEY]
            or source.get("timezone") != ZONE):
        raise ValueError("goat_source_identity_mismatch")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    raw = fetch(CALENDAR, "text/html")
    if not isinstance(raw, str) or not 1000 <= len(raw) <= 600000:
        raise ValueError("goat_calendar_invalid")
    soup = BeautifulSoup(raw, "html.parser")
    links = soup.select('a[href*="/classes/"]')
    if not links or len(links) > 250:
        raise ValueError("goat_calendar_card_limit")
    ids = []
    for link in links:
        label = link.get_text(" ", strip=True)
        if "HYROX" not in label.upper() or re.search(r"cancel(?:led|ed)", label, re.I):
            continue
        try:
            href = urlsplit(link.get("href", ""))
        except ValueError:
            continue
        if (href.scheme != "https" or href.hostname != HOST
                or href.port not in (None, 443)
                or href.username or href.password or href.fragment
                or href.query not in ("", "source=cal")):
            continue
        m = CLASS_LINK.fullmatch(href.path)
        if m and m.group(1) not in ids:
            ids.append(m.group(1))
    if not ids:
        return []
    out = []
    for uid in ids[:MAX_RECORDS]:
        if deadline_at is not None and monotonic() >= deadline_at - 2:
            raise ValueError("goat_collection_deadline")
        url = "https://" + HOST + "/classes/" + uid
        if not event_url(url):
            raise ValueError("goat_event_url_invalid")
        row = _detail(url, fetch, now)
        if row is not None:
            out.append(row)
    return out
