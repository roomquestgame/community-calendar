"""Collect timed Lincoln Parks events and the Omaha Running Club's own races."""
from datetime import datetime, timedelta
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from lxml import html

from roomquest.mapsee_adapter import plain, record

ZONE = "America/Chicago"
PARKS = "lincoln_parks_opencities_ne"
RUN = "omaha_running_club_eventon_ne"
GOATZ = "goatz_hitchcock_experience_ne"
SOURCES = {
    PARKS: "https://www.lincoln.ne.gov/City/Departments/Parks-and-Recreation/Calendar-and-Events",
    RUN: "https://omaharun.org/race-calendar/",
    GOATZ: "https://www.goatz.org/the-hitchcock-experience",
}
PARK_VENUES = {
    "sunken gardens": ("Sunken Gardens", "2601 D Street, Lincoln, NE 68502"),
    "veterans memorial garden": ("Veterans Memorial Garden", "3200 Veterans Memorial Drive, Lincoln, NE 68502"),
}
PARK_TIME = re.compile(
    r"Next date:\s*(\w+, \w+ \d{1,2}, \d{4})\s*\|\s*(\d{1,2}:\d{2} [AP]M)\s+to\s+(\d{1,2}:\d{2} [AP]M)",
)
RUN_TIME = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})T(\d{2}):(\d{2})[+-]\d{1,2}:\d{2}")
THANKSGIVING = "https://omaharun.org/events/orc-thanksgiving-day-run/"
RUN_LOCATION = {
    "orc thanksgiving day run": ("Zorinsky Lake Park – Southeast (Shelter 5)", "3808 S 156th Street, Omaha, NE"),
    "orc holiday lights run": ("10th and Harney", "10th Street and Harney Street, Omaha, NE"),
}
EXCLUDED = re.compile(r"\b(cancelled|canceled|postponed|closed)\b", re.I)


def build(title, start, end, venue, address, city, url):
    key = sha256(f"{url}:{start.isoformat()}".encode()).hexdigest()
    return record(title, start.isoformat(), end.isoformat() if end and end > start else None,
                  venue, address, city, url, key, tz=ZONE)


def park_events(document, fetch, today):
    prefix = SOURCES[PARKS] + "/"
    cards = document.xpath("//div[contains(concat(' ',normalize-space(@class),' '),' events-list-container ')]//article/a")
    if not cards:
        raise ValueError("missing_lincoln_park_calendar")
    if len(cards) > 24:
        raise ValueError("lincoln_park_detail_limit")
    for card in cards:
        url = card.get("href") or ""
        if not url.startswith(prefix):
            continue
        title = plain(" ".join(card.xpath("./h4//text()")))
        address_text = plain(" ".join(card.xpath("./p[contains(@class,'list-item-address')]//text()"))).casefold()
        venue = next((v for k, v in PARK_VENUES.items() if address_text.startswith(k)), None)
        if not title or EXCLUDED.search(title) or venue is None:
            continue
        detail = html.fromstring(fetch(url, "text/html"))
        if EXCLUDED.search(plain(" ".join(detail.xpath("//h1//text()")))):
            continue
        dates = set()
        for entry in detail.xpath("//li[@data-start-year and @data-start-hour and @data-end-hour]"):
            start, end = (datetime(*(int(entry.get(f"data-{side}-{field}"))
                                     for field in ("year", "month", "day", "hour", "mins")))
                          for side in ("start", "end"))
            dates.add((start, end))
        if not dates:
            line = plain(" ".join(detail.xpath("//p[contains(@class,'event-date')]//text()")))
            match = PARK_TIME.fullmatch(line)
            if match:
                day, start, end = match.groups()
                dates.add(tuple(datetime.strptime(f"{day} {time}", "%A, %B %d, %Y %I:%M %p")
                                for time in (start, end)))
        for start, end in dates:
            if today <= start.date() <= today + timedelta(days=365) and end > start:
                yield build(title, start, end, venue[0], venue[1], "Lincoln", url)


def race_time(text):
    match = RUN_TIME.fullmatch(text or "")
    return datetime(*(int(part) for part in match.groups())) if match else None


def club_events(document, fetch, today):
    rows = list(club_rows(document, today))
    if rows:
        yield from rows
        return
    detail = html.fromstring(fetch(THANKSGIVING, "text/html"))
    yield from club_rows(detail, today)


def club_rows(document, today):
    for script in document.xpath("//script[@type='application/ld+json']"):
        try:
            row = json.loads(script.text or "null")
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("@type") != "Event":
            continue
        title = row.get("name") or ""
        venue = RUN_LOCATION.get(title.casefold())
        if not venue or not str(row.get("eventStatus", "")).endswith("/EventScheduled"):
            continue
        url = row.get("url") or ""
        target = urlsplit(url)
        if (target.scheme, target.netloc) != ("https", "omaharun.org") or not target.path.startswith("/events/"):
            continue
        start, end = race_time(row.get("startDate")), race_time(row.get("endDate"))
        if start and today <= start.date() <= today + timedelta(days=59):
            yield build(title, start, end, venue[0], venue[1], "Omaha", url)


def hitchcock_events(document, today):
    text = plain(" ".join(document.xpath("//main//text()")))
    day = re.search(r"Race Date:\s*Saturday[-–]Sunday,\s*([A-Za-z]+ \d{1,2})[-–]\d{1,2},\s*(\d{4})", text, re.I)
    starts = re.search(r"Start Time:\s*(\d{1,2}) a\.m\..*?;\s*(\d{1,2}) p\.m\. 50M", text, re.I)
    if not day or not starts or "27792 Ski Hill Loop" not in text:
        raise ValueError("missing_hitchcock_race_schedule")
    date = datetime.strptime(f"{day[1]} {day[2]}", "%B %d %Y").date()
    if not today <= date <= today + timedelta(days=59):
        return
    for title, hour in (("Hitchcock Experience Endurance Runs", int(starts[1])),
                        ("Hitchcock Experience 50 Mile Night Start", int(starts[2]) + 12)):
        yield build(title, datetime(date.year, date.month, date.day, hour), None, "Hitchcock Nature Center",
                    "27792 Ski Hill Loop, Honey Creek, IA 51542", "Honey Creek", SOURCES[GOATZ])


def collect(source, fetch, *, deadline_at=None, now=None):
    key = source.get("source_key")
    url = SOURCES.get(key)
    if not url or tuple(source.get(k) for k in ("feed_url", "timezone", "kind", "platform_adapter")) != (
        url, ZONE, "html", "html",
    ):
        raise ValueError("unregistered_nebraska_recreation")
    zone = ZoneInfo(ZONE)
    today = (now or datetime.now(zone)).astimezone(zone).date()
    document = html.fromstring(fetch(url, "text/html"))
    if key == PARKS:
        rows = park_events(document, fetch, today)
    elif key == RUN:
        rows = club_events(document, fetch, today)
    else:
        rows = hitchcock_events(document, today)
    return sorted((row for row in rows if row is not None), key=lambda row: (row["starts_at"], row["id"]))
