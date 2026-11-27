"""First-party Santa Cruz Art League exhibition receptions (HTML-only).

Squarespace robots disallows ?format=json and ?format=ical; use only bounded,
allowlisted normal HTML via the existing guarded publisher transport.
First Friday's 2026 date/year must agree with the official show detail.
Do not infer every monthly reception, invent street coordinates, or use
artist-owned exhibition artwork as an image.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import re
from bs4 import BeautifulSoup

from roomquest.collection_window import calendar_anchor
from roomquest.event_description import description
from roomquest.mapsee_adapter import record

KEY = "santa_cruz_art_league_receptions_ca"
INDEX = "https://scal.org/first-friday"
DETAIL = "https://scal.org/members-show-2026"
ZONE = "America/Los_Angeles"
SOURCES = {KEY: (INDEX, "html", "html")}
ALLOWED_HOSTS = {KEY: ("scal.org",)}
VENUE = "Santa Cruz Art League"
STREET = "526 Broadway, Santa Cruz, CA 95060"
MAX_RECORDS = 2
MAX_DESCRIPTION = 12000
CLOCK = re.compile(r"\bFirst Friday Reception:\s*December 4,\s*5:00\s*pm\s*[-–—]\s*7:30\s*pm\b", re.I)
ADDRESS = re.compile(r"\b526\s+Broadway\s+Santa Cruz,?\s+CA\s+95060\b", re.I)
EXHIBIT = re.compile(r"\bOn View:\s*Wednesday,?\s*November 18\s*[-–—]\s*Friday,?\s*December 18,?\s*2026\b", re.I)
NONPUBLIC = re.compile(r"\b(?:cancelled|canceled|postponed|members[- ]only|private event)\b", re.I)


def event_url(value):
    if value != DETAIL:
        return False
    u = urlsplit(value)
    return (u.scheme == "https" and u.hostname == "scal.org"
            and u.port in (None, 443) and not u.username and not u.password
            and not u.query and not u.fragment)


def _content(value, role):
    if not isinstance(value, str) or len(value) > 1_000_000:
        raise ValueError("art_league_html_invalid")
    soup = BeautifulSoup(value, "html.parser")
    main = soup.select_one("main")
    if main is None:
        raise ValueError("art_league_main_missing")
    texts = [p.get_text(" ", strip=True) for p in main.select("p")]
    if sum(bool(CLOCK.search(t)) for t in texts) != 1:
        raise ValueError("art_league_event_clock_missing")
    if not ADDRESS.search(main.get_text(" ", strip=True)):
        # The owner footer in Squarespace can be outside main. It is still on
        # this exact official publisher page, not guessed from a source city.
        if not ADDRESS.search(soup.get_text(" ", strip=True)):
            raise ValueError("art_league_official_street_missing")
    heading = main.find(["h1", "h2", "h3"], string=re.compile(r"Simple Pleasures", re.I))
    if heading is None:
        raise ValueError("art_league_show_identity_missing")
    if role == "detail" and not any(EXHIBIT.search(t) for t in texts):
        raise ValueError("art_league_exhibition_year_missing")
    return soup, main, texts


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY
            or (source.get("feed_url"), source.get("kind"),
                source.get("platform_adapter")) != SOURCES[KEY]
            or source.get("timezone") != ZONE):
        raise ValueError("art_league_source_identity_mismatch")
    index, detail = (_content(fetch(INDEX, "text/html"), "index"),
                     _content(fetch(DETAIL, "text/html"), "detail"))
    _, _, texts = detail
    blocks = []
    for text in texts:
        if (text.startswith("Join us in celebrating the creativity of our artistic community!")
                or text.startswith("This year’s theme, Simple Pleasures")
                or text.startswith("Open to all mediums and styles")):
            blocks.append(text)
    if len(blocks) < 2 or NONPUBLIC.search(" ".join(blocks)):
        raise ValueError("art_league_narrative_missing")
    narrative = description("\n\n".join(blocks), limit=MAX_DESCRIPTION)
    if not narrative or not 80 <= len(narrative) <= MAX_DESCRIPTION:
        raise ValueError("art_league_narrative_missing")
    now = (calendar_anchor(now or datetime.now(timezone.utc))).astimezone(timezone.utc)
    start = datetime(2026, 12, 4, 17, tzinfo=ZoneInfo(ZONE))
    end = datetime(2026, 12, 4, 19, 30, tzinfo=ZoneInfo(ZONE))
    if not now - timedelta(hours=3) <= start.astimezone(timezone.utc) <= now + timedelta(days=60):
        return []
    row = record("Simple Pleasures — Santa Cruz Art League First Friday Reception",
                 start.isoformat(), end.isoformat(), VENUE, STREET, "Santa Cruz",
                 DETAIL, "scal-2026-simple-pleasures-first-friday",
                 "art, gallery, first friday reception", None, None, ZONE,
                 retain_until_end=True)
    if row is None:
        return []
    row.update(description=narrative, timezone=ZONE,
               publisher_categories=["Art Exhibition", "First Friday", "Reception"],
               location_provenance="original_publisher_exhibition_and_footer_street",
               location_evidence_url=DETAIL, schedule_evidence_url=INDEX)
    from roomquest.publisher_evidence import attach
    # Do not claim redistribution rights over artists' copyrighted exhibit images.
    result = [attach(row, KEY, evidence_url=DETAIL)]
    if len(result) > MAX_RECORDS:
        raise ValueError("art_league_record_limit")
    return result
