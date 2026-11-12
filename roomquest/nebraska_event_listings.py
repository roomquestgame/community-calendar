"""Collect dated Nebraska public event listings with venue-specific locations."""
from datetime import datetime, timedelta
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from lxml import html

from roomquest.mapsee_adapter import plain, record

ZONE = "America/Chicago"
SPIEL = "spielbound_meetup_ne"
QUIZ = "americas_pub_quiz_ne"
AUDUBON = "spring_creek_prairie_audubon_ne"
SOURCES = {
    SPIEL: "https://www.meetup.com/playing-games-at-spielbound/",
    QUIZ: "https://americaspubquiz.com/events/nebraska",
    AUDUBON: "https://www.audubon.org/spring-creek-prairie/get-involved",
}
CLASS = "contains(concat(' ', normalize-space(@class), ' '), $token)"
CLOCK = re.compile(r"\b(\d{1,2}:\d{2})\s*([ap]m)\b", re.I)
EXCLUDED = re.compile(r"\b(canceled|cancelled|postponed|closed)\b", re.I)
QUIZ_CITY = re.compile(r"([A-Za-z][A-Za-z .'-]+),\s*NE", re.I)
STREET = re.compile(r"\d{1,6}\s+\S")
QUIZ_VENUES = {
    ("Barred Owl", "2101 Transformation Dr 6th Floor, Lincoln, NE"):
        ("2101 Transformation Dr, Lincoln, NE", 40.833715, -96.6921),
    ("Blue Sky Bar & Patio", "10730 Pacific St, #150, Omaha, NE"):
        ("10730 Pacific St, Omaha, NE", 41.24907, -96.081173),
    ("Bison Witches Bar & Deli", "1320 P St #100, Lincoln, NE 68508, Lincoln, NE"):
        ("1320 P Street, Lincoln, NE 68508", None, None),
}


def elements(node, name, tag="*"):
    return node.xpath(f".//{tag}[{CLASS}]", token=f" {name} ")


def field(node, name):
    matches = elements(node, name)
    return plain(matches[0].text_content()) if matches else ""


def clocks(text, day):
    return [datetime.combine(day, datetime.strptime(f"{value} {period.upper()}", "%I:%M %p").time())
            for value, period in CLOCK.findall(text)]


def event(title, start, end, venue, address, city, url, *, lat=None, lng=None):
    identity = sha256(f"{url}:{start.isoformat()}".encode()).hexdigest()
    return record(title, start.isoformat(), end.isoformat() if end and end > start else None,
                  venue, address, city, url, identity, lat=lat, lng=lng, tz=ZONE)


def meetup(document, today):
    found = False
    for script in document.xpath("//script[@type='application/ld+json']"):
        try:
            items = json.loads(script.text or "null")
        except ValueError:
            continue
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or item.get("@type") != "Event":
                continue
            url = item.get("url") or ""
            target = urlsplit(url)
            if (target.scheme, target.netloc) != ("https", "www.meetup.com") or not re.fullmatch(
                r"/playing-games-at-spielbound/events/\d+/", target.path,
            ):
                continue
            found = True
            if (not str(item.get("eventStatus", "")).endswith("/EventScheduled")
                    or not str(item.get("eventAttendanceMode", "")).endswith("/OfflineEventAttendanceMode")):
                continue
            place = item.get("location")
            address = place.get("address") if isinstance(place, dict) else None
            if not isinstance(address, dict) or not re.match(r"3229 Harney St\b", address.get("streetAddress") or "", re.I):
                continue
            start = datetime.fromisoformat(item["startDate"])
            end = datetime.fromisoformat(item["endDate"]) if item.get("endDate") else None
            if start.tzinfo is None or end is not None and end.tzinfo is None:
                continue
            yield event(item["name"], start, end, "Spielbound Board Game Cafe",
                        "3229 Harney St, Omaha, NE 68131", "Omaha", url, lat=41.2566, lng=-95.9612)
    if not found and not re.search(r"no upcoming events", document.text_content(), re.I):
        raise ValueError("missing_meetup_event_data")


def quiz(document, today):
    cards = elements(document, "venue-card")
    tables = elements(document, "data-row", "tr")
    if not cards and not tables:
        raise ValueError("missing_quiz_calendar")
    for row in [*cards, *tables]:
        links = row.xpath(".//a[contains(@href,'/event/')]")
        if not links:
            continue
        url = links[0].get("href")
        target = urlsplit(url)
        match = re.fullmatch(r"/event/[^/]+-(\d{4}-\d{2}-\d{2})-\d+", target.path)
        if (target.scheme, target.netloc) != ("https", "americaspubquiz.com") or not match:
            continue
        day = datetime.fromisoformat(match[1]).date()
        if not today <= day <= today + timedelta(days=30):
            continue
        if row.tag == "tr":
            cells = row.xpath("./td")
            if len(cells) != 4:
                continue
            venue = plain(cells[1].text_content())
            addresses = [plain(x) for x in cells[2].itertext() if plain(x)]
            schedule = plain(" ".join(cells[0].itertext()))
            # The compact table does not distinguish trivia from music bingo.
            label = "America’s Pub Quiz"
        else:
            venue = field(row, "card-title")
            label = field(row, "venue-card-show-type") or "America’s Pub Quiz"
            address = row.xpath(".//address/p")
            addresses = [plain(x.text_content()) for x in address]
            schedule = field(row, "h5")
        if not venue or len(addresses) != 2 or not STREET.match(addresses[0]):
            continue
        city = QUIZ_CITY.fullmatch(addresses[1])
        start = clocks(schedule, day)
        if city is None or len(start) != 1 or EXCLUDED.search(label):
            continue
        address = f"{addresses[0]}, {addresses[1]}"
        address, lat, lng = QUIZ_VENUES.get((venue, address), (address, None, None))
        yield event(f"{label} at {venue}", start[0], None, venue, address, city[1], url, lat=lat, lng=lng)


def audubon(document, today):
    cards = elements(document, "event-card-item")
    if not cards:
        raise ValueError("missing_audubon_calendar")
    for card in cards:
        venue = field(card, "event-card-item-center")
        city = field(card, "event-card-item-location")
        title = field(card, "event-card-item-title")
        if venue != "Spring Creek Prairie Audubon Center" or city != "Denton, NE" or not title or EXCLUDED.search(title):
            continue
        if not card.xpath(".//a[contains(@href,'category=in-person')]"):
            continue
        anchors = elements(card, "card-link", "a")
        if not anchors:
            continue
        url = anchors[0].get("href") or ""
        target = urlsplit(url)
        if target.scheme != "https" or target.netloc not in {"act.audubon.org", "www.audubon.org"}:
            continue
        month, number = field(card, "event-month"), field(card, "event-day")
        for year in (today.year, today.year + 1):
            try:
                day = datetime.strptime(f"{month} {number} {year}", "%b %d %Y").date()
            except ValueError:
                continue
            if not today <= day <= today + timedelta(days=59):
                continue
            times = clocks(field(card, "event-time"), day)
            if len(times) == 2 and times[0] < times[1]:
                yield event(title, times[0], times[1], venue,
                            "11700 SW 100th St, Denton, NE 68339", "Denton", url)


def collect(source, fetch, *, deadline_at=None, now=None):
    key = source.get("source_key")
    url = SOURCES.get(key)
    if not url or tuple(source.get(k) for k in ("feed_url", "timezone", "kind", "platform_adapter")) != (
        url, ZONE, "html", "html",
    ):
        raise ValueError("unregistered_nebraska_event_listing")
    zone = ZoneInfo(ZONE)
    today = (now or datetime.now(zone)).astimezone(zone).date()
    document = html.fromstring(fetch(url, "text/html"))
    collector = {SPIEL: meetup, QUIZ: quiz, AUDUBON: audubon}[key]
    rows = {row["id"]: row for row in collector(document, today) if row is not None}
    return sorted(rows.values(), key=lambda row: (row["starts_at"], row["id"]))
