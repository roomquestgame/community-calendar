"""Two explicitly named, current WCS seasonal public programs in New York.

The full event page is retained. Exact public operating dates and clocks come
from the publisher, never a continuous interpretation of a 'select dates'
season. Public contact addresses are checked separately from the shared WCS
headquarters footer. Normal guarded transport supplies robots, pacing and TLS.
"""
from __future__ import annotations

from calendar import month_name
from datetime import date, datetime, time, timedelta, timezone
import re
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.collection_window import collection_window
from roomquest.event_description import description
from roomquest.mapsee_adapter import record, timestamp

ZONE = "America/New_York"
ZOO = "bronx_zoo_holiday_lights_ny"
AQUARIUM = "new_york_aquarium_holiday_tides_ny"
SOURCES = {
    ZOO: ("https://bronxzoo.com/holiday-lights", "html", "html"),
    AQUARIUM: ("https://nyaquarium.com/holiday-tides", "html", "html"),
}
ALLOWED_HOSTS = {key: (urlsplit(value[0]).hostname,) for key, value in SOURCES.items()}
CHECKPOINT_KEYS = set()
MAX_DESCRIPTION = 12000
MAX_RECORDS = 100
VENUES = {
    ZOO: ("Bronx Zoo", "2300 Southern Boulevard, Bronx, NY 10460", "Bronx", 40.851082, -73.881525),
    AQUARIUM: ("New York Aquarium", "602 Surf Avenue, Brooklyn, NY 11224", "Brooklyn", 40.574008, -73.975672),
}
CONTACTS = {
    ZOO: ("https://bronxzoo.com/contact", "BRONX ZOO 2300 Southern Boulevard Bronx, New York 10460"),
    AQUARIUM: ("https://nyaquarium.com/contact", "NEW YORK AQUARIUM 602 Surf Avenue Brooklyn, New York 11224"),
}
FAQ_URL = "https://bronxzoo.com/holiday-lights/faqs"
MONTHS = {name: n for n, name in enumerate(month_name) if name}
MONTH_PATTERN = "(?:" + "|".join(MONTHS) + ")"
ERROR_CODES = {
    "unregistered_nyc_family_final", "nyc_family_identity_changed", "nyc_family_description_missing",
    "nyc_family_description_limit", "nyc_family_calendar_changed", "nyc_family_schedule_conflict",
    "nyc_family_address_changed", "nyc_family_record_limit", "collection_deadline",
}


def _normalized(value):
    return re.sub(r"\s+", " ", value).strip()


def _body(value):
    text = description(value, limit=MAX_DESCRIPTION + 1)
    if not text:
        raise ValueError("nyc_family_description_missing")
    if len(text) > MAX_DESCRIPTION:
        raise ValueError("nyc_family_description_limit")
    return text


def _get(fetch, url, deadline):
    if monotonic() >= deadline:
        raise ValueError("collection_deadline")
    return BeautifulSoup(fetch(url, "text/html"), "html.parser")


def _event_main(soup, key):
    main = soup.select_one("main#content")
    title = soup.select_one('meta[property="og:title"]')
    expected = {ZOO: "Holiday Lights at the Bronx Zoo", AQUARIUM: "Holiday Tides - New York Aquarium"}[key]
    if main is None or title is None or title.get("content") != expected:
        raise ValueError("nyc_family_identity_changed")
    # Remove controls and the duplicate mobile hero; preserve every narrative
    # section, including paid admission, membership and activity caveats.
    for node in main.select("script,style,noscript,svg,video,button,nav,form,.page-hero-mobile"):
        node.decompose()
    return main


def _verify_address(fetch, key, deadline):
    url, expected = CONTACTS[key]
    soup = _get(fetch, url, deadline)
    main = soup.select_one("main#content")
    if main is None or expected.casefold() not in _normalized(main.get_text(" ", strip=True)).casefold():
        raise ValueError("nyc_family_address_changed")


def _faq_answers(soup):
    values = {}
    for question in soup.select(".bz-lights-faqs__question"):
        title = _normalized(question.get_text(" ", strip=True))
        answer = question.find_next_sibling("div", class_="bz-lights-faqs__answer")
        if answer is not None:
            if title in values:
                raise ValueError("nyc_family_identity_changed")
            values[title] = answer
    return values


def public_dates(value):
    """Expand only explicitly listed day ranges with a carried publisher year."""
    value = _normalized(value).replace("–", "-").replace("—", "-")
    value = re.sub(r"^PUBLIC EVENT DATES:\s*", "", value)
    value = value.split("(", 1)[0].strip().rstrip(".")
    days = set()
    year = None
    for sentence in value.split("."):
        match = re.fullmatch(r"\s*(?:(20\d{2}):\s*)?(" + MONTH_PATTERN + r")\s+([\d,\-\sand]+)\s*", sentence)
        if not match:
            raise ValueError("nyc_family_calendar_changed")
        year = int(match[1]) if match[1] else year
        if year is None:
            raise ValueError("nyc_family_calendar_changed")
        month = MONTHS[match[2]]
        for component in re.split(r"\s*(?:,|\band\b)\s*", match[3].strip()):
            span = re.fullmatch(r"(\d{1,2})(?:-(\d{1,2}))?", component)
            if not span:
                raise ValueError("nyc_family_calendar_changed")
            first, last = int(span[1]), int(span[2] or span[1])
            if not 1 <= first <= last <= 31:
                raise ValueError("nyc_family_calendar_changed")
            try:
                for day in range(first, last + 1):
                    item = date(year, month, day)
                    if item in days:
                        raise ValueError("nyc_family_schedule_conflict")
                    days.add(item)
            except ValueError as exc:
                if str(exc).startswith("nyc_family_"):
                    raise
                raise ValueError("nyc_family_calendar_changed") from exc
    if not days or len(days) > MAX_RECORDS or (max(days) - min(days)).days > 120:
        raise ValueError("nyc_family_calendar_changed")
    return sorted(days)


def _clock(value):
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", value, re.I)
    if not match or not 1 <= int(match[1]) <= 12 or int(match[2] or 0) > 59:
        raise ValueError("nyc_family_calendar_changed")
    return time(int(match[1]) % 12 + (12 if match[3].lower() == "pm" else 0), int(match[2] or 0))


def _attach_content(row, body, venue_name, venue_address, venue_city):
    start, end = timestamp(row.get("starts_at")), timestamp(row.get("ends_at"))
    if start is None or start.tzinfo is None or end is None or end.tzinfo is None or end <= start:
        raise ValueError("nyc_family_schedule_conflict")
    postal = re.search(r"\bNY\s+(\d{5}(?:-\d{4})?)\s*$", venue_address)
    facts = {
        "title": row["title"], "description": body, "is_all_day": False,
        "starts_at_utc": start.astimezone(timezone.utc).isoformat(),
        "ends_at_utc": end.astimezone(timezone.utc).isoformat(),
        "source_timezone": ZONE, "event_url": row["event_url"],
        "venue_name": venue_name, "venue_address": venue_address,
        "venue_city": venue_city, "venue_region": "NY",
        "venue_postal_code": postal[1] if postal else None,
        "attendance_mode": "in_person",
    }
    facts = {name: value for name, value in facts.items() if value not in (None, "")}
    row["collector_event_content_v1"] = {"version": 1, "event_id": row["id"], "facts": facts}
    return row


def _rows(key, days, opening, closing, body, now, sensory=None):
    window = collection_window(now)
    if closing <= opening:
        raise ValueError("nyc_family_schedule_conflict")
    name, address, city, lat, lng = VENUES[key]
    rows = []
    for day in days:
        start = datetime.combine(day, opening, ZoneInfo(ZONE))
        end = datetime.combine(day, closing, ZoneInfo(ZONE))
        if start >= window.end or end <= window.start:
            continue
        title = "Bronx Zoo Holiday Lights" if key == ZOO else "New York Aquarium Holiday Tides"
        if day == sensory:
            title += " — Sensory-Friendly Night"
        row = record(title, start.isoformat(), end.isoformat(), name, address, city,
                     SOURCES[key][0], f"{key}:{day.isoformat()}", "", lat, lng, ZONE,
                     publisher_geo=True, retain_until_end=True)
        if row is None:
            raise ValueError("nyc_family_schedule_conflict")
        native_body = _body(body)
        row.update(description=native_body, timezone=ZONE, attendance_mode="in_person",
                   publisher_categories=[], location_provenance="publisher_contact_address_exact_nyc_pad_point",
                   schedule_provenance="publisher_explicit_season_dates_and_operating_hours")
        _attach_content(row, native_body, name, address, city)
        rows.append(row)
    if len(rows) > MAX_RECORDS:
        raise ValueError("nyc_family_record_limit")
    return rows


def _zoo(fetch, deadline, now):
    main = _event_main(_get(fetch, SOURCES[ZOO][0], deadline), ZOO)
    faq = _get(fetch, FAQ_URL, deadline)
    answers = _faq_answers(faq)
    questions = ("When is Holiday Lights?", "What are the Holiday Lights hours of operation?",
                 "Which gates/entrances are open for Holiday Lights?",
                 "Is there a night for guests with sensory sensitivities?")
    if not all(q in answers for q in questions):
        raise ValueError("nyc_family_calendar_changed")
    dates = public_dates(answers[questions[0]].get_text(" ", strip=True))
    listed = [p for p in faq.select("p") if p.get_text(" ", strip=True).startswith("PUBLIC EVENT DATES:")]
    if len(listed) != 1 or public_dates(listed[0].get_text(" ", strip=True)) != dates:
        raise ValueError("nyc_family_schedule_conflict")
    hours = answers[questions[1]].get_text(" ", strip=True)
    match = re.search(r"Holiday Lights operates\s+(\d{1,2}(?::\d{2})?\s*[ap]m)\s+to\s+(\d{1,2}(?::\d{2})?\s*[ap]m)\.", hours, re.I)
    if not match:
        raise ValueError("nyc_family_calendar_changed")
    sensory_text = answers[questions[3]].get_text(" ", strip=True)
    special = re.search(r"Sensory-Friendly Night on ("+MONTH_PATTERN+r") (\d{1,2}), (20\d{2})", sensory_text)
    sensory = date(int(special[3]), MONTHS[special[1]], int(special[2])) if special else None
    if sensory is None or sensory not in dates:
        raise ValueError("nyc_family_schedule_conflict")
    _verify_address(fetch, ZOO, deadline)
    body = str(main) + "\n" + "\n".join(str(answers[q]) for q in questions)
    return _rows(ZOO, dates, _clock(match[1]), _clock(match[2]), body, now, sensory)


def _aquarium(fetch, deadline, now):
    main = _event_main(_get(fetch, SOURCES[AQUARIUM][0], deadline), AQUARIUM)
    pattern = r"("+MONTH_PATTERN+r")\s+(\d{1,2})[–-](\d{1,2}),\s*(20\d{2})\s*[-–]\s*(\d{1,2}(?::\d{2})?[ap]m)[-–](\d{1,2}(?::\d{2})?[ap]m)"
    schedules = [re.fullmatch(pattern, _normalized(h.get_text(" ", strip=True))) for h in main.find_all(["h1", "h2"])]
    schedules = [m for m in schedules if m]
    if not schedules or len({m.group(0) for m in schedules}) != 1:
        raise ValueError("nyc_family_calendar_changed")
    match = schedules[0]
    dates = public_dates(f"{match[4]}: {match[1]} {match[2]}-{match[3]}")
    _verify_address(fetch, AQUARIUM, deadline)
    return _rows(AQUARIUM, dates, _clock(match[5]), _clock(match[6]), str(main), now)


def collect(source, fetch, *, deadline_at, now=None):
    key = source.get("source_key")
    if key not in SOURCES or (source.get("feed_url"), source.get("kind"), source.get("platform_adapter"), source.get("timezone")) != (*SOURCES[key], ZONE):
        raise ValueError("unregistered_nyc_family_final")
    current = now or datetime.now(timezone.utc)
    return (_zoo if key == ZOO else _aquarium)(fetch, deadline_at, current)
