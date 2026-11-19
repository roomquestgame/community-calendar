"""Strict original hotel holiday schedules, Santa Cruz CA.

Two distinct original hotel publishers. Only owner-authored 2026 holiday sessions,
not a hotel events aggregator, restaurant hours, or recurrence guesses. HTML is
fetched through guarded, robots-aware transport with exact host allowlists.
All addresses are first-party verified streets; Geocodio runs only downstream.
No photography redistribution rights assumed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone, time
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit
import re
from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import record
from roomquest.publisher_evidence import attach

ZONE = "America/Los_Angeles"
CHAMINADE = "chaminade_resort_holiday_santa_cruz_ca"
DREAM_INN = "dream_inn_holiday_santa_cruz_ca"
SANTA_URL = "https://www.chaminade.com/santa-cruz-restaurants/breakfast-with-santa/"
THANKSGIVING_URL = "https://www.chaminade.com/santa-cruz-restaurants/thanksgiving-at-chaminade/"
DREAM_URL = "https://www.dreaminnsantacruz.com/activities/event-calendar/breakfast-with-santa-"
SOURCES = {
    CHAMINADE: (SANTA_URL, "html", "html"),
    DREAM_INN: (DREAM_URL, "html", "html"),
}
ALLOWED_HOSTS = {
    CHAMINADE: ("www.chaminade.com",),
    DREAM_INN: ("www.dreaminnsantacruz.com",),
}
VENUES = {
    CHAMINADE: ("Chaminade Resort & Spa", "One Chaminade Lane, Santa Cruz, CA 95065"),
    DREAM_INN: ("Dream Inn", "175 W Cliff Dr, Santa Cruz, CA 95060"),
}
GEOCODIO_CHAMINADE_STREET = "1 Chaminade Lane, Santa Cruz, CA 95065"  # Official written 'One'
MAX_RECORDS = 3
MAX_DESCRIPTION = 12000
MAX_HTML = 650000
CANCELLED = re.compile(r"\b(?:cancelled|canceled|postponed|private event|members[- ]only)\b", re.I)
CHAMINADE_SANTA = re.compile(
    r"Two Dates\s*:\s*Saturday,?\s*December 5\s*&\s*Sunday,?\s*December 13,?\s*2026"
    r".{0,70}?Times\s*:\s*9:00\s*am\s*[-–—]\s*11:00\s*am"
    r".{0,100}?Where\s*:\s*Sunset Dining Room at Chaminade Resort\s*&\s*Spa", re.I | re.S)
CHAMINADE_THANKS = re.compile(
    r"Thanksgiving Day Buffet\s+Thursday,?\s*November 26,?\s*2026"
    r"\s+9:00\s*am\s*[-–—]\s*5:00\s*pm", re.I)
DREAM_DATE = re.compile(r"Saturday\s+December 12th,?\s*2026", re.I)
DREAM_TIME = re.compile(r"9:00\s*am\s*[-–—]\s*12:00\s*pm", re.I)


def event_url(key, url):
    if key not in SOURCES or not isinstance(url, str):
        return False
    valid = {SANTA_URL, THANKSGIVING_URL} if key == CHAMINADE else {DREAM_URL}
    if url not in valid:
        return False
    parts = urlsplit(url)
    return (parts.scheme == "https" and parts.hostname in ALLOWED_HOSTS[key]
            and parts.username is None and parts.password is None
            and parts.port in (None, 443) and not parts.query and not parts.fragment)


def _page(raw, expected_heading):
    if not isinstance(raw, str) or len(raw) > MAX_HTML:
        raise ValueError("hotel_html_invalid")
    soup = BeautifulSoup(raw, "html.parser")
    main = soup.select_one("main")
    if main is None:
        raise ValueError("hotel_main_missing")
    h1 = main.select_one("h1")
    if h1 is None or expected_heading.casefold() not in h1.get_text(" ", strip=True).casefold():
        raise ValueError("hotel_event_heading_drift")
    if CANCELLED.search(main.get_text(" ", strip=True)):
        raise ValueError("hotel_event_cancelled")
    return soup, main, main.get_text(" ", strip=True)


def _street(soup, key):
    # Verified first-party venue footer, not a source city centroid.
    owner_street = VENUES[key][1]
    normalized = " ".join(soup.get_text(" ", strip=True).split())
    if owner_street not in normalized:
        raise ValueError("hotel_official_street_missing")
    # Publisher spells the exact civic number "One". Convert spelling to digit
    # for ordinary shared street-number/Geocodio processing, not a guessed pin.
    return GEOCODIO_CHAMINADE_STREET if key == CHAMINADE else owner_street


def _narrative(raw):
    body = description(raw, limit=MAX_DESCRIPTION)
    if not body or len(body) < 90 or len(body) > MAX_DESCRIPTION:
        raise ValueError("hotel_description_missing")
    return body


def _chaminade_records(fetch):
    santa_soup, santa_main, santa_text = _page(
        fetch(SANTA_URL, "text/html"), "Breakfast with Santa")
    thanks_soup, thanks_main, thanks_text = _page(
        fetch(THANKSGIVING_URL, "text/html"), "Thanksgiving at Chaminade")
    santa_street = _street(santa_soup, CHAMINADE)
    thanks_street = _street(thanks_soup, CHAMINADE)
    if not CHAMINADE_SANTA.search(santa_text):
        raise ValueError("hotel_santa_schedule_missing")
    if not CHAMINADE_THANKS.search(thanks_text):
        raise ValueError("hotel_thanksgiving_schedule_missing")
    def lead(main, prefix):
        texts = [p.get_text(" ", strip=True) for p in main.select("p")]
        out = [p for p in texts if p.startswith(prefix)]
        if len(out) != 1:
            raise ValueError("hotel_publisher_narrative_drift")
        return out[0]
    santa_lead = lead(santa_main, "Gather the family for a merry morning")
    thanks_lead = lead(thanks_main, "Celebrate Thanksgiving with a festive meal")
    # Keep the original owner's relevant menu information (not widgets/ads).
    santa_food = re.search(r"Buffet Selections\s+(.{30,1000}?)\s+Selections subject to change", santa_text, re.I | re.S)
    thanks_food = re.search(r"Selections\s+(.{80,5500}?)\s+Selections subject to change", thanks_text, re.I | re.S)
    if not santa_food or not thanks_food:
        raise ValueError("hotel_menu_detail_missing")
    santa_desc = _narrative(santa_lead + "\n\nBuffet Selections: " + santa_food.group(1).strip())
    thanks_desc = _narrative(thanks_lead + "\n\nSelections: " + thanks_food.group(1).strip())
    return [
        ("Breakfast with Santa at Chaminade", datetime(2026, 12, day, 9), datetime(2026, 12, day, 11),
         "Sunset Dining Room at Chaminade Resort & Spa", santa_street, SANTA_URL,
         "chaminade-breakfast-santa-2026-12-%02d" % day, santa_desc, ["Family", "Holiday", "Breakfast"])
        for day in (5, 13)
    ] + [
        ("Thanksgiving Day Buffet at Chaminade", datetime(2026, 11, 26, 9), datetime(2026, 11, 26, 17),
         VENUES[CHAMINADE][0], thanks_street, THANKSGIVING_URL,
         "chaminade-thanksgiving-2026-11-26", thanks_desc, ["Food", "Thanksgiving", "Dining"])
    ]


def _dream_record(fetch):
    soup, main, text = _page(fetch(DREAM_URL, "text/html"), "8th Annual Breakfast with Santa")
    street = _street(soup, DREAM_INN)
    detail = main.select_one(".event-details .description")
    if detail is None:
        raise ValueError("hotel_event_detail_missing")
    owner = detail.get_text(" ", strip=True)
    if (not DREAM_DATE.search(owner) or not DREAM_TIME.search(owner)
            or "Dream Inn Presents Breakfast with Santa" not in owner
            or "Program Starts 9:45am" not in owner
            or "COOKIE DECORATING" not in owner
            or "MRS. CLAUS" not in owner):
        raise ValueError("hotel_dream_schedule_or_narrative_drift")
    # The original detail body contains the complete owner program and its activities.
    narrative = _narrative(owner.replace("Reserve Your Tickets! (opens in a new tab)", "").strip())
    return [("Dream Inn Presents Breakfast with Santa",
             datetime(2026, 12, 12, 9), datetime(2026, 12, 12, 12),
             VENUES[DREAM_INN][0], street, DREAM_URL,
             "dream-inn-breakfast-santa-2026-12-12", narrative,
             ["Family", "Holiday", "Breakfast", "Arts & Crafts"])]


def collect(source, fetch, *, deadline_at=None, now=None):
    key = source.get("source_key")
    if (key not in SOURCES or
            (source.get("feed_url"), source.get("kind"), source.get("platform_adapter")) != SOURCES[key]
            or source.get("timezone") != ZONE):
        raise ValueError("hotel_source_identity_mismatch")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    upcoming = _chaminade_records(fetch) if key == CHAMINADE else _dream_record(fetch)
    rows = []
    for title, start_wall, end_wall, venue, street, url, identity, narrative, categories in upcoming:
        start = start_wall.replace(tzinfo=ZoneInfo(ZONE)).astimezone(timezone.utc)
        end = end_wall.replace(tzinfo=ZoneInfo(ZONE)).astimezone(timezone.utc)
        if start < now - timedelta(hours=3) or start > now + timedelta(days=60):
            continue
        if not event_url(key, url) or end <= start:
            raise ValueError("hotel_event_identity_or_schedule_invalid")
        row = record(title, start.isoformat(), end.isoformat(), venue, street,
                     "Santa Cruz", url, identity, ", ".join(categories),
                     None, None, ZONE, retain_until_end=True)
        if row is None:
            continue
        row.update(description=narrative, timezone=ZONE, publisher_categories=categories,
                   location_provenance="publisher_owned_hotel_event_and_official_footer",
                   location_evidence_url=url, schedule_evidence_url=url)
        rows.append(attach(row, key, evidence_url=url))
    if len(rows) > MAX_RECORDS:
        raise ValueError("hotel_event_limit")
    return sorted(rows, key=lambda row: (row["starts_at"], row["id"]))
