"""Firespring monthly calendars and their publisher-generated iCalendar events."""
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
import re
from time import monotonic
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from roomquest.mapsee_adapter import plain, record

SOURCES = {
    "great_plains_trail_network_ne": (
        "https://www.gptn.org/news_publications/event_calendar.html", "/news_publications/event_calendar.html",
    ),
    "plantnebraska_events_ne": (
        "https://plantnebraska.org/resources-events/events/events.html", "/resources-events/events",
    ),
    "conservation_nebraska_events_ne": (
        "https://neconserve.org/news-events/event-calendar.html", "/news-events/event-calendar.html",
    ),
}
ZONE = "America/Chicago"
MAX_EVENTS = 20
EVENT = re.compile(r"/event/(\d{4})/(\d{2})/(\d{2})/([a-z0-9-]+)/([0-9]+)/?$")
POSTAL = re.compile(r"(?P<street>\d{1,6}\s+[^,\n]+)[,\n]\s*(?P<city>[^,\n]+),\s*(?P<state>[A-Z]{2})(?:\s+(?P<zip>\d{5}))?(?:[,\s]+(?:US|USA))?$")


class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


def links(payload, base):
    parser = Links()
    parser.feed(payload)
    parser.close()
    return {urljoin(base, href) for href in parser.hrefs}


def listing_events(payload, url, root, today, horizon):
    if "Go to Next" not in payload and "Go to Previous" not in payload:
        raise ValueError("invalid_firespring_calendar")
    host = urlsplit(url).netloc
    result = set()
    for link in links(payload, url):
        parsed = urlsplit(link)
        if parsed.scheme != "https" or parsed.netloc != host or parsed.query or parsed.fragment:
            continue
        if not parsed.path.startswith(root + "/event/"):
            continue
        match = EVENT.search(parsed.path)
        if match and today <= date(*map(int, match.group(1, 2, 3))) <= horizon:
            result.add(link)
    return result


def venue_fields(location):
    value = str(location or "").replace("\r", "").strip()
    matched = POSTAL.search(value)
    if not matched:
        return plain(value), "", ""
    street, city, state, zip_code = matched.group("street", "city", "state", "zip")
    name = plain(value[:matched.start()].rstrip(", \n"))
    address = f"{plain(street)}, {plain(city)}, {state}"
    if zip_code:
        address += f" {zip_code}"
    return name or plain(street), address, plain(city)


def event_record(payload, detail, identity):
    from icalendar import Calendar

    if not payload.lstrip("\ufeff \r\n").startswith("BEGIN:VCALENDAR"):
        raise ValueError("invalid_firespring_icalendar")
    events = Calendar.from_ical(payload).walk("VEVENT")
    if len(events) != 1:
        raise ValueError("invalid_firespring_occurrence")
    event = events[0]
    status = str(event.get("STATUS", "")).upper()
    if status in {"CANCELED", "CANCELLED"}:
        return None
    start = event.decoded("DTSTART", None)
    end = event.decoded("DTEND", None)
    if not isinstance(start, datetime):
        return None
    if end is not None and not isinstance(end, datetime):
        raise ValueError("invalid_firespring_end")
    name, street, city = venue_fields(event.get("LOCATION"))
    if not name or re.search(r"https?://|^online\b|^virtual\b|^zoom\b", name, re.I):
        return None
    return record(event.get("SUMMARY"), start.isoformat(), end.isoformat() if end else None,
                  name, street, city, detail, identity, tz=ZONE)


def collect(source, fetch, *, deadline_at=None, now=None):
    profile = SOURCES.get(source.get("source_key"))
    if profile is None or (source.get("feed_url"), source.get("timezone"),
                           source.get("kind"), source.get("platform_adapter")) != (
            profile[0], ZONE, "html", "html"):
        raise ValueError("unregistered_firespring_source")
    base, root = profile
    today = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(ZONE)).date()
    horizon = today + timedelta(days=60)
    month = today.replace(day=1)
    details = set()

    def read(url, accept):
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError("collection_deadline")
        return fetch(url, accept)

    while month <= horizon:
        listing = f"{base}/calendar/{month.year}/{month.month}"
        details.update(listing_events(read(listing, "text/html"), listing, root, today, horizon))
        if len(details) > MAX_EVENTS:
            raise ValueError("firespring_event_limit")
        month = (month + timedelta(days=32)).replace(day=1)

    result = []
    exports_found = 0
    for detail in sorted(details):
        parsed_detail = urlsplit(detail)
        event = EVENT.search(parsed_detail.path)
        identity = event.group(5)
        prefix = re.escape(root) + r"/ical/\d{4}/\d{2}/\d{2}/[a-z0-9-]+/"
        exports = []
        for link in links(read(detail, "text/html"), detail):
            parsed = urlsplit(link)
            if (parsed.scheme == "https" and parsed.netloc == parsed_detail.netloc
                    and not parsed.query and not parsed.fragment
                    and re.fullmatch(prefix + identity + r"/?", parsed.path)):
                exports.append(link)
        if not exports:
            continue
        if len(exports) != 1:
            raise ValueError("ambiguous_firespring_icalendar_link")
        exports_found += 1
        row = event_record(read(exports[0], "text/calendar"), detail, identity)
        if row is not None:
            result.append(row)
    if details and not exports_found:
        raise ValueError("missing_firespring_icalendar_link")
    return sorted(result, key=lambda row: (row["starts_at"], row["id"]))
