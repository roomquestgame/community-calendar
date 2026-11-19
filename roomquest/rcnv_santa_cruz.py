"""First-party Resource Center for Nonviolence (Santa Cruz) event calendar.

The Events Manager listing discovers publisher-owned detail pages. Their own
event ICS confirms exact starts/ends; detail HTML preserves full original
narratives. No venue centroids, third-party images or inferred recurrences.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from roomquest.mapsee_adapter import record
from roomquest.publisher_evidence import attach

KEY = "rcnv_santa_cruz_original_events_ca"
INDEX = "https://rcnv.org/events/"
SOURCES = {KEY: (INDEX, "html", "html")}
ALLOWED_HOSTS = {KEY: ("rcnv.org",)}
ZONE = "America/Los_Angeles"
STREET = "612 Ocean Street, Santa Cruz, CA 95060"
VENUE = "Resource Center for Nonviolence"
MAX_RECORDS = 12
MAX_DESCRIPTION = 12000


def _exact_event_url(url):
    if not isinstance(url, str):
        return False
    p = urlsplit(url)
    return (p.scheme == "https" and p.hostname == "rcnv.org"
            and bool(re.fullmatch(r"/events/[a-z0-9-]+/", p.path))
            and p.path not in ("/events/locations/", "/events/categories/")
            and not (p.query or p.fragment or p.port or p.username or p.password))


def _ics_fields(body, url):
    if not isinstance(body, str) or len(body) > 100_000:
        raise ValueError("rcnv_ics_invalid")
    unfolded = re.sub(r"\r?\n[ \t]", "", body)
    if unfolded.count("BEGIN:VEVENT") != 1 or unfolded.count("END:VEVENT") != 1:
        raise ValueError("rcnv_ics_event_count")
    values = {}
    for field, pattern in {
        "start": r"^DTSTART;TZID=America/Los_Angeles:(\d{8}T\d{6})\r?$",
        "end": r"^DTEND;TZID=America/Los_Angeles:(\d{8}T\d{6})\r?$",
        "uid": r"^UID:([A-Za-z0-9_.@-]{3,100})\r?$",
        "url": r"^URL:(https://[^\r\n]+)\r?$",
    }.items():
        found = re.findall(pattern, unfolded, flags=re.M)
        if len(found) != 1:
            raise ValueError("rcnv_ics_" + field + "_missing")
        values[field] = found[0].strip()
    if values["url"] != url:
        raise ValueError("rcnv_ics_url_mismatch")
    start = datetime.strptime(values["start"], "%Y%m%dT%H%M%S").replace(tzinfo=ZoneInfo(ZONE))
    end = datetime.strptime(values["end"], "%Y%m%dT%H%M%S").replace(tzinfo=ZoneInfo(ZONE))
    if not start < end <= start + timedelta(hours=24):
        raise ValueError("rcnv_ics_invalid_duration")
    return start, end, values["uid"]


def _parse_event(url, page, ics, now):
    soup = BeautifulSoup(page, "html.parser")
    title = soup.select_one("h1.entry-title")
    date = soup.select_one(".em-event-date")
    times = soup.select_one(".em-event-time")
    where = soup.select_one(".em-item-meta-line.em-event-location")
    narrative = soup.select_one("section.em-event-content")
    ical = soup.select_one("a.em-a2c-download")
    if not all((title, date, times, where, narrative, ical)):
        raise ValueError("rcnv_event_schema_changed")
    if ical.get("href") != url + "ical/":
        raise ValueError("rcnv_ics_not_original")
    heading = title.get_text(" ", strip=True)
    if not (15 <= len(heading) <= 220):
        raise ValueError("rcnv_title_invalid")
    # The event-specific where field, not an unrelated footer or headquarters.
    loc = where.get_text(" ", strip=True)
    if (VENUE not in loc or
        not re.search(r"612 Ocean St\.?,?\s*Santa Cruz,\s*CA,?\s*95060", loc, re.I)):
        raise ValueError("rcnv_event_venue_unverified")
    desc = narrative.get_text("\n", strip=True)
    if not 200 <= len(desc) <= MAX_DESCRIPTION:
        raise ValueError("rcnv_full_narrative_missing")
    if re.search(r"\b(cancelled|canceled|postponed)\b", heading, re.I):
        return None
    start, end, uid = _ics_fields(ics, url)
    try:
        shown_date = datetime.strptime(date.get_text(" ", strip=True), "%b %d, %Y").date()
        shown_times = [datetime.strptime(s.strip(), "%I:%M %p").time()
                       for s in re.split(r"\s+-\s+", times.get_text(" ", strip=True))]
    except ValueError as exc:
        raise ValueError("rcnv_page_schedule_invalid") from exc
    if (len(shown_times) != 2 or shown_date != start.date() or
        shown_times != [start.time(), end.time()]):
        raise ValueError("rcnv_page_ics_schedule_mismatch")
    if not (now - timedelta(hours=3) <= start.astimezone(timezone.utc)
            <= now + timedelta(days=180)):
        return None
    cats = [li.get_text(" ", strip=True)
            for li in soup.select(".em-event-categories li")]
    if not cats or any(not c or len(c) > 100 for c in cats):
        raise ValueError("rcnv_category_evidence_missing")
    stable = re.sub(r"[^a-z0-9]+", "-", uid.lower()).strip("-")
    row = record(heading, start.astimezone(timezone.utc).isoformat(),
                 end.astimezone(timezone.utc).isoformat(), VENUE, STREET,
                 "Santa Cruz", url,
                 "rcnv-" + stable + "-" + start.strftime("%Y%m%d"),
                 ", ".join(cats), None, None, ZONE, retain_until_end=True)
    if not row:
        raise ValueError("rcnv_record_invalid")
    row.update(description=desc, timezone=ZONE, publisher_categories=cats,
               location_provenance="original_event_venue_street_ics_crosscheck")
    # The original calendar's image is not automatically a reuse license.
    return attach(row, KEY)


def collect(source, fetch, *, now=None, deadline_at=None):
    if (source.get("source_key") != KEY or
        (source.get("feed_url"), source.get("kind"),
         source.get("platform_adapter")) != SOURCES[KEY] or
        source.get("timezone") != ZONE):
        raise ValueError("rcnv_wrong_source_identity")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("rcnv_now_timezone_missing")
    if deadline_at and monotonic() >= deadline_at:
        raise ValueError("rcnv_deadline")
    index = BeautifulSoup(fetch(INDEX, "text/html"), "html.parser")
    links = []
    for anchor in index.select(".em-events-grid .em-item-title a[href]"):
        url = anchor.get("href", "")
        if not _exact_event_url(url):
            raise ValueError("rcnv_index_cross_host_or_invalid_link")
        if url not in links:
            links.append(url)
    if len(links) > MAX_RECORDS:
        raise ValueError("rcnv_index_unbounded")
    rows = []
    for url in links:
        if deadline_at and monotonic() >= deadline_at:
            raise ValueError("rcnv_deadline")
        page = fetch(url, "text/html")
        ics = fetch(url + "ical/", "text/calendar")
        event = _parse_event(url, page, ics, now)
        if event:
            rows.append(event)
    return rows
