"""The Fábrica's own live Mending Circle calendar, Santa Cruz.

Require agreement between the event index and an independently dated owner post:
their December 6 versus December 8 mismatch is held, not guessed. Do not
invent sessions from "Tuesdays" or treat general workshop open hours as events.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import re
from bs4 import BeautifulSoup

from roomquest.collection_window import calendar_anchor
from roomquest.event_description import description
from roomquest.mapsee_adapter import record, plain

KEY = "the_fabrica_santa_cruz_ca"
URL = "https://thefabricaworkshop.org/events-at-the-fabrica/"
BLOG = "https://thefabricaworkshop.org/2026/10/27/spooky-season-happenings-at-the-fabrica-and-the-hub/"
CONTACT = "https://thefabricaworkshop.org/contact/"
ZONE = "America/Los_Angeles"
SOURCES = {KEY: (URL, "html", "html")}
ALLOWED_HOSTS = {KEY: ("thefabricaworkshop.org",)}
MAX_RECORDS = 12
MAX_DESCRIPTION = 12000
VENUE = "The Fábrica"
STREET = "703 Pacific Avenue, Santa Cruz, CA 95060"
STREET_RE = re.compile(r"\b703\s+Pacific\s+Ave(?:nue)?\b", re.I)
DATE_RE = re.compile(r"\b(October|November|December)\s+(\d{1,2})(?:\s*&\s*(\d{1,2}))?\b", re.I)
TIME_RE = re.compile(r"\b6\s*p\.?m\.?\s*[-–—]\s*8\s*p\.?m\.?\b", re.I)
NONPUBLIC = re.compile(r"\b(?:cancell?ed|postponed|private|members[- ]only)\b", re.I)
PHOTO_PATH = re.compile(r"/wp-content/uploads/2026/09/[a-z0-9][a-z0-9_.-]*\.(?:jpe?g|png|webp)", re.I)

def event_url(value):
    if value != BLOG:
        return False
    u = urlsplit(value)
    return (u.scheme == "https" and u.hostname == "thefabricaworkshop.org"
            and u.username is None and u.password is None and u.port in (None, 443)
            and not u.query and not u.fragment)

def photo_url(value):
    if not isinstance(value, str) or len(value) > 1700:
        return None
    u = urlsplit(value)
    if (u.scheme != "https" or u.hostname != "thefabricaworkshop.org"
            or u.username or u.password or u.port not in (None, 443)
            or u.fragment or u.query or not PHOTO_PATH.fullmatch(u.path)
            or re.search(r"(?:logo|avatar|favicon|placeholder|pixel)", u.path, re.I)):
        return None
    return value

def _section(payload):
    soup = BeautifulSoup(payload, "html.parser")
    content = soup.select_one("article .entry-content")
    if content is None:
        raise ValueError("fabrica_article_missing")
    headings = [x for x in content.select("h2") if plain(x.get_text(" ", strip=True)).strip("“”\" ") == "Mending Circle"]
    if len(headings) != 1:
        raise ValueError("fabrica_mending_identity_drift")
    parent = headings[0].parent.parent
    if "wp-block-columns" not in (parent.get("class") or []):
        raise ValueError("fabrica_mending_layout_drift")
    paragraphs = [plain(p.get_text(" ", strip=True)) for p in parent.find_all("p")]
    if len(paragraphs) < 3:
        raise ValueError("fabrica_mending_incomplete")
    # Require the date, clock and address in the *same* owner event block.
    where = next((p for p in paragraphs if STREET_RE.search(p) and "Santa Cruz" in p), "")
    when = next((p for p in paragraphs if "Tuesdays" in p and TIME_RE.search(p)), "")
    prose = next((p for p in paragraphs if p.startswith("Bring something to mend")), "")
    if not where or not when or not prose or NONPUBLIC.search(" ".join(paragraphs)):
        raise ValueError("fabrica_event_incomplete")
    return parent, when, prose

def _days(text):
    found = set()
    for m in DATE_RE.finditer(text):
        month = datetime.strptime(m.group(1).title(), "%B").month
        for day in (m.group(2), m.group(3)):
            if day is None:
                continue
            try:
                date = datetime(2026, month, int(day)).date()
            except ValueError:
                raise ValueError("fabrica_date_invalid")
            if date.weekday() == 1:  # publisher explicitly says Tuesdays
                found.add(date)
    return found

def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY or
            (source.get("feed_url"), source.get("kind"), source.get("platform_adapter")) != SOURCES[KEY] or
            source.get("timezone") != ZONE):
        raise ValueError("fabrica_source_identity_mismatch")
    index, announcement, contact = (
        fetch(URL, "text/html"), fetch(BLOG, "text/html"), fetch(CONTACT, "text/html"))
    primary, main_when, main_prose = _section(index)
    _, blog_when, blog_prose = _section(announcement)
    official_contact = BeautifulSoup(contact, "html.parser")
    contact_main = official_contact.select_one("article .entry-content")
    if (contact_main is None or not STREET_RE.search(contact_main.get_text(" ", strip=True))
            or "Santa Cruz" not in contact_main.get_text(" ", strip=True)):
        raise ValueError("fabrica_official_address_drift")
    if "2026" not in blog_when:
        raise ValueError("fabrica_publisher_year_missing")
    now = calendar_anchor(now or datetime.now(timezone.utc))
    body = description(main_prose, limit=MAX_DESCRIPTION)
    if (not body or len(body) > MAX_DESCRIPTION or
            not blog_prose.startswith("Bring something to mend")):
        raise ValueError("fabrica_description_missing")
    picture = primary.find("img", attrs={"data-orig-file": True})
    candidate = photo_url(picture.get("data-orig-file")) if picture else None
    days = sorted(_days(main_when) & _days(blog_when))
    out = []
    for day in days:
        start = datetime.combine(day, time(18), tzinfo=ZoneInfo(ZONE))
        end = datetime.combine(day, time(20), tzinfo=ZoneInfo(ZONE))
        if not now-timedelta(hours=3) <= start.astimezone(timezone.utc) <= now+timedelta(days=60):
            continue
        row = record("Mending Circle", start.isoformat(), end.isoformat(),
                     VENUE, STREET, "Santa Cruz", BLOG,
                     "fabrica-mending-"+day.isoformat(), "textile arts, mending workshop",
                     None, None, ZONE, retain_until_end=True)
        if row is None:
            continue
        row.update(description=body, timezone=ZONE, publisher_categories=[
            "Mending", "Textile Art", "Community Workshop"],
            location_provenance="original_publisher_event_and_contact_street",
            location_evidence_url=CONTACT,
            schedule_evidence_url=URL)
        from roomquest.publisher_evidence import attach
        out.append(attach(row, KEY, candidate=candidate, evidence_url=URL))
    if len(out) > MAX_RECORDS:
        raise ValueError("fabrica_record_limit")
    return out

