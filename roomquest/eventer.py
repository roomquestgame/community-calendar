"""Read the published, dated cards on a WordPress Eventer listing."""
from datetime import datetime, timezone
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from lxml import html

from roomquest.mapsee_adapter import plain, record

KEY = "omaha_lauritzen_gardens_events"
HOST = "www.lauritzengardens.org"
CALENDAR = f"https://{HOST}/events-exhibits/"
ZONE = "America/Chicago"
VENUE = "Lauritzen Gardens"
ADDRESS = "100 Bancroft St, Omaha, NE 68108"
EVENT_PATH = re.compile(r"/eventer/([a-z0-9-]+)(?:/edate/(\d{4}-\d{2}-\d{2}))?/?")
TIMES = re.compile(r"(\d{1,2}:\d{2}\s+[AP]M)(?:\s+to\s+(\d{1,2}:\d{2}\s+[AP]M))?", re.I)
HAS_CLASS = "contains(concat(' ', normalize-space(@class), ' '), $class_name)"


def elements(node, class_name):
    return node.xpath(f"descendant-or-self::*[{HAS_CLASS}]", class_name=f" {class_name} ")


def field(node, class_name):
    values = elements(node, class_name)
    return plain(values[0].text_content()) if values else ""


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key"), source.get("feed_url"), source.get("timezone"),
            source.get("kind"), source.get("platform_adapter")) != (KEY, CALENDAR, ZONE, "html", "html"):
        raise ValueError("unregistered_eventer_calendar")
    today = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(ZONE)).date()
    document = html.fromstring(fetch(CALENDAR, "text/html"))
    if not elements(document, "eventer-dynamic-listings-main"):
        raise ValueError("missing_eventer_listing")
    events = {}
    for card in elements(document, "eventer-event-item-link"):
        link = urljoin(CALENDAR, card.get("href", ""))
        parsed = urlsplit(link)
        occurrence = EVENT_PATH.fullmatch(parsed.path)
        if parsed.scheme != "https" or parsed.netloc != HOST or parsed.query or parsed.fragment or not occurrence:
            continue
        title = field(card, "eventer-event-title")
        status = field(card, "eventer-status-badge")
        times = TIMES.fullmatch(field(card, "eventer-event-time"))
        if not title or not times or re.search(r"\b(cancelled|canceled|postponed)\b", f"{status} {title}", re.I):
            continue
        day = datetime.strptime(" ".join(field(card, "eventer-event-" + part)
                                        for part in ("day", "month", "year")), "%d %b %Y").date()
        if occurrence[2] and occurrence[2] != day.isoformat():
            raise ValueError("eventer_event_date_mismatch")
        if day < today or (day.year, day.month) != (today.year, today.month):
            continue
        starts = datetime.combine(day, datetime.strptime(times[1], "%I:%M %p").time())
        ends = datetime.combine(day, datetime.strptime(times[2], "%I:%M %p").time()) if times[2] else None
        if ends is not None and ends <= starts:
            raise ValueError("invalid_eventer_end_time")
        row = record(title, starts.isoformat(), ends.isoformat() if ends else None, VENUE, ADDRESS,
                     "Omaha", link, f"{occurrence[1]}:{day.isoformat()}", tz=ZONE)
        if row is not None:
            previous = events.setdefault(row["id"], row)
            if previous != row:
                raise ValueError("conflicting_eventer_event")
    return sorted(events.values(), key=lambda row: (row["starts_at"], row["id"]))
