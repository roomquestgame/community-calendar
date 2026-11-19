"""Official Santa Cruz Shakespeare 2026 holiday production performances.

Use only the original show schedule and explicitly linked ticket instances.
Student-only matinees are not public listings. Never use the organizer's
summer amphitheatre or city coverage point for this winter production.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import re

from bs4 import BeautifulSoup
from roomquest.event_description import description
from roomquest.mapsee_adapter import record
from roomquest.publisher_evidence import attach

KEY = "santa_cruz_shakespeare_christmas_carol_ca"
URL = "https://santacruzshakespeare.org/performances/christmascarol/"
SOURCES = {KEY: (URL, "html", "html")}
ALLOWED_HOSTS = {KEY: ("santacruzshakespeare.org",)}
ZONE = "America/Los_Angeles"
VENUE = "Veterans Memorial Building"
STREET = "846 Front St, Santa Cruz, CA 95060"
MAX_HTML = 450_000
MAX_RECORDS = 36
MAX_DESCRIPTION = 12000
DATE_LINE = re.compile(
    r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),"
    r"\s+December\s+(\d{1,2}),\s+2026\s+at\s+"
    r"(\d{1,2}):(\d{2})\s*(AM|PM)$", re.I)
INSTANCE = re.compile(r"^/instances/(a0F[A-Za-z0-9]{12,21})$")
UNAVAILABLE = re.compile(r"\b(cancelled|canceled|postponed|private event)\b", re.I)


def event_url(value):
    """Every occurrence links to the original publisher's exact show page."""
    if value != URL:
        return False
    u = urlsplit(value)
    return (u.scheme == "https" and u.hostname == "santacruzshakespeare.org"
            and u.port in (None, 443) and not u.username and not u.password
            and not u.query and not u.fragment)


def _ticket_id(href):
    if not isinstance(href, str):
        return None
    try:
        u = urlsplit(href)
    except ValueError:
        return None
    if (u.scheme != "https"
            or u.hostname != "santacruzshakespeare.my.salesforce-sites.com"
            or u.path != "/ticket/" or u.query or u.username or u.password
            or u.port not in (None, 443)):
        return None
    m = INSTANCE.fullmatch(u.fragment)
    return m.group(1) if m else None


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY
            or (source.get("feed_url"), source.get("kind"),
                source.get("platform_adapter")) != SOURCES[KEY]
            or source.get("timezone") != ZONE):
        raise ValueError("shakespeare_source_identity_mismatch")
    raw = fetch(URL, "text/html")
    if not isinstance(raw, str) or not 200 <= len(raw) <= MAX_HTML:
        raise ValueError("shakespeare_html_invalid")
    soup = BeautifulSoup(raw, "html.parser")
    widgets = [x for x in soup.select(".elementor-widget-text-editor")
               if "PERFORMANCES:" in x.get_text(" ", strip=True)
               and "RUN TIME:" in x.get_text(" ", strip=True)]
    if len(widgets) != 1:
        raise ValueError("shakespeare_schedule_missing")
    widget = widgets[0]
    all_text = widget.get_text(" ", strip=True)
    if (not re.search(r"Veterans Memorial Building.*?846\s+Front\s+St,?\s+Santa Cruz,?\s+CA\s+95060", all_text, re.I)
            or not re.search(r"95\s+minutes\s+with\s+no\s+intermission", all_text, re.I)
            or "A Christmas Carol returns as a holiday tradition" not in all_text):
        raise ValueError("shakespeare_venue_runtime_narrative_missing")
    intro = all_text.split("PERFORMANCES:", 1)[0]
    body = description(intro, limit=MAX_DESCRIPTION)
    if not body or len(body) < 220 or len(body) > MAX_DESCRIPTION:
        raise ValueError("shakespeare_narrative_missing")
    if UNAVAILABLE.search(intro):
        raise ValueError("shakespeare_production_cancelled")
    schedule = widget.find(string=re.compile(r"PERFORMANCES:\s*$"))
    if schedule is None or not schedule.parent.parent:
        raise ValueError("shakespeare_schedule_missing")
    # The original show page places performance anchors in the UL immediately
    # after the PERFORMANCES heading, not global navigation lists.
    listing = schedule.parent.find_next_sibling("ul")
    if listing is None:
        listing = schedule.parent.find_next("ul")
    if listing is None:
        raise ValueError("shakespeare_schedule_missing")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows = []
    seen = set()
    tz = ZoneInfo(ZONE)
    public_slots = 0
    for li in listing.find_all("li", recursive=False):
        line = li.get_text(" ", strip=True)
        if "Student Matinee" in line:
            continue
        if UNAVAILABLE.search(line):
            continue
        anchor = li.find("a", href=True)
        if anchor is None:
            raise ValueError("shakespeare_public_ticket_missing")
        matched = DATE_LINE.fullmatch(anchor.get_text(" ", strip=True))
        ticket_id = _ticket_id(anchor["href"])
        if matched is None or ticket_id is None:
            raise ValueError("shakespeare_date_or_ticket_drift")
        weekday, day, hour, minute, ampm = matched.groups()
        hour = int(hour) % 12 + (12 if ampm.upper() == "PM" else 0)
        start = datetime(2026, 12, int(day), hour, int(minute), tzinfo=tz)
        if start.strftime("%A").casefold() != weekday.casefold():
            raise ValueError("shakespeare_weekday_disagreement")
        if ticket_id in seen:
            raise ValueError("shakespeare_duplicate_instance")
        seen.add(ticket_id)
        public_slots += 1
        if not now - timedelta(hours=3) <= start.astimezone(timezone.utc) <= now + timedelta(days=60):
            continue
        end = start + timedelta(minutes=95)  # Explicit original show runtime
        row = record(
            "A Christmas Carol — Santa Cruz Shakespeare",
            start.isoformat(), end.isoformat(), VENUE, STREET, "Santa Cruz",
            URL, "scs-carol-2026-" + ticket_id, "theatre, play, christmas, family",
            None, None, ZONE, retain_until_end=True)
        if row is None:
            continue
        row.update(
            description=body, timezone=ZONE,
            publisher_categories=["Theater", "Holiday Play", "Family"],
            location_provenance="original_production_page_venue_street",
            location_evidence_url=URL, schedule_evidence_url=URL,
            publisher_ticket_url=anchor["href"])
        rows.append(attach(row, KEY,
                           evidence_url=URL))
        if len(rows) > MAX_RECORDS:
            raise ValueError("shakespeare_record_limit")
    if not 1 <= public_slots <= MAX_RECORDS:
        raise ValueError("shakespeare_public_schedule_missing")
    return rows

