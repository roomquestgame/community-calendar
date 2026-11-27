"""Dante Society Santa Cruz: original dated Italian conversation sessions.

Only owner-linked, already-dated schema.org Events at the independently confirmed
Loft Coffee venue. Never generate second/fourth-Saturday recurrences. Scopa and
literature events at incomplete/ambiguous venues are deliberately held.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import json
import re
from bs4 import BeautifulSoup

from roomquest.collection_window import calendar_anchor
from roomquest.mapsee_adapter import record

KEY = "dante_santa_cruz_coffee_ca"
INDEX = "https://www.dantesantacruz.com/events"
ZONE = "America/Los_Angeles"
SOURCES = {KEY: (INDEX, "html", "html")}
ALLOWED_HOSTS = {KEY: ("www.dantesantacruz.com",)}
VENUE = "Loft Coffee"
STREET = "2701 Cabrillo College Dr 9000 Building, Aptos, CA 95003"
PREFIX = "https://www.dantesantacruz.com/event-details/"
SLUG = re.compile(r"una-tazzina-di-caffe-loft-coffee-(20\d{2}-\d{2}-\d{2})-11-00\Z")
MAX_RECORDS = 4
MAX_DESCRIPTION = 10000


def event_url(value):
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return False
    parsed = urlsplit(value)
    return (parsed.scheme == "https" and parsed.hostname == "www.dantesantacruz.com"
            and parsed.port in (None, 443) and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment
            and bool(SLUG.fullmatch(parsed.path.removeprefix("/event-details/"))))


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY
            or (source.get("feed_url"), source.get("kind"), source.get("platform_adapter"))
            != SOURCES[KEY] or source.get("timezone") != ZONE):
        raise ValueError("dante_source_identity_mismatch")
    now = calendar_anchor(now or datetime.now(timezone.utc))
    if now.tzinfo is None:
        raise ValueError("dante_naive_now")
    index = fetch(INDEX, "text/html")
    if not isinstance(index, str) or len(index) > 2_000_000:
        raise ValueError("dante_index_invalid")
    soup = BeautifulSoup(index, "html.parser")
    urls = sorted({
        a["href"] for a in soup.select("a[href]")
        if event_url(a["href"])
    })
    candidates = []
    for url in urls:
        slug = url.split("/event-details/")[-1]
        day = datetime.fromisoformat(SLUG.fullmatch(slug).group(1))
        localday = calendar_anchor(datetime.now(ZoneInfo(ZONE))).date() if now is None else now.astimezone(ZoneInfo(ZONE)).date()
        if localday - timedelta(days=1) <= day.date() <= localday + timedelta(days=60):
            candidates.append(url)
    if len(candidates) > MAX_RECORDS:
        raise ValueError("dante_too_many_calendar_links")
    output = []
    for url in candidates:
        raw = fetch(url, "text/html")
        if not isinstance(raw, str) or len(raw) > 2_000_000:
            raise ValueError("dante_detail_invalid")
        page = BeautifulSoup(raw, "html.parser")
        events = []
        for script in page.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.get_text())
            except (ValueError, TypeError):
                continue
            if isinstance(data, dict) and data.get("@type") == "Event":
                events.append(data)
        if len(events) != 1:
            raise ValueError("dante_event_schema_missing")
        data = events[0]
        venue = data.get("location") or {}
        if not isinstance(venue, dict) or venue.get("name") != VENUE or venue.get("address") != STREET:
            raise ValueError("dante_event_venue_unverified")
        if data.get("eventStatus") != "https://schema.org/EventScheduled":
            continue
        title = data.get("name") or ""
        if "Una tazzina di caff" not in title:
            raise ValueError("dante_event_identity_mismatch")
        start = datetime.fromisoformat(str(data.get("startDate", "")))
        end = datetime.fromisoformat(str(data.get("endDate", "")))
        if not start.tzinfo or not end.tzinfo or not timedelta(minutes=20) <= end-start <= timedelta(hours=3):
            raise ValueError("dante_event_clock_unverified")
        local = start.astimezone(ZoneInfo(ZONE))
        if start.utcoffset() != local.utcoffset() or local.strftime("%Y-%m-%d") not in url:
            raise ValueError("dante_event_date_mismatch")
        if not now-timedelta(hours=3) <= start.astimezone(timezone.utc) <= now+timedelta(days=60):
            continue
        summary = data.get("description")
        if not isinstance(summary, str) or len(summary.strip()) < 45:
            raise ValueError("dante_full_narrative_missing")
        # Wix now renders the full owner-authored body through its rich-text
        # content viewer. Preserve the old markup path, but never use the
        # short JSON-LD excerpt in place of the full narrative.
        blocks = [x.get_text(" ", strip=True) for x in page.select("div.X7JGg")]
        blocks.extend(x.get_text(" ", strip=True) for x in
                      page.select('[data-hook="about-section"] [data-id="content-viewer"]'))
        def normalized(text):
            return re.sub(r"\s+", " ", text).strip()
        blocks = [normalized(x) for x in blocks
                  if normalized(x).startswith("Ci vediamo per un caffè?")
                  and normalized(summary) in normalized(x)]
        if len(blocks) != 1:
            raise ValueError("dante_full_narrative_missing")
        narrative = blocks[0]
        if len(narrative) < len(normalized(summary)) + 45:
            raise ValueError("dante_full_narrative_missing")
        if not 80 <= len(narrative) <= MAX_DESCRIPTION:
            raise ValueError("dante_description_incomplete")
        row = record(title.strip(), start.isoformat(), end.isoformat(), VENUE,
                     STREET, "Aptos", url, url.split("/")[-1],
                     "Italian conversation, culture, coffee", None, None, ZONE,
                     retain_until_end=True)
        if row is None:
            continue
        row.update(description=narrative.strip(), timezone=ZONE,
                   publisher_categories=["Italian Language", "Coffee Meetup"],
                   location_provenance="owner_event_schema_loft_coffee_official_street",
                   location_evidence_url=url, schedule_evidence_url=url)
        from roomquest.publisher_evidence import attach
        output.append(attach(row, KEY, evidence_url=url))
    return output
