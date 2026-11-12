"""Collect public WebTrac calendar blocks with publisher meeting addresses."""
from datetime import datetime, timedelta, timezone
import re
from time import monotonic
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from lxml import html

from roomquest.mapsee_adapter import plain, record

KEY = "omaha_parks_webtrac_ne"
HOST = "neomahaweb.myvscloud.com"
CALENDAR = f"https://{HOST}/webtrac/web/search.html?display=Calendar&module=Event"
ZONE = "America/Chicago"
HAS_CLASS = "contains(concat(' ', normalize-space(@class), ' '), $class_name)"
TIME_RANGE = re.compile(r"(\d{1,2}:\d{2}\s+[ap]m)\s*[-–]\s*(\d{1,2}:\d{2}\s+[ap]m)", re.I)
CITY_STATE = re.compile(r"([^,]+),\s*(NE),\s*(\d{5})")
DATE_RANGE = re.compile(r"Date\(s\):\s*(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})")


def read_date(value):
    return datetime.strptime(value, "%m/%d/%Y").date()


def calendar_blocks(payload, today, horizon):
    doc = html.fromstring(payload)
    tables = doc.xpath("//table[caption[normalize-space(.)='Event Calendar']]")
    if len(tables) != 1:
        raise ValueError("missing_webtrac_calendar")
    for card in tables[0].xpath(f".//a[{HAS_CLASS}]", class_name=" calendar__block "):
        target = urlsplit(urljoin(CALENDAR, card.get("href", "")))
        params = {name.lower(): values for name, values in parse_qs(target.query).items()}
        ids = params.get("fmid")
        if (target.scheme != "https" or target.netloc != HOST
                or target.path != "/webtrac/web/search.html"
                or params.get("module") != ["AR"] or not ids or len(ids) != 1
                or not re.fullmatch(r"\d{1,20}", ids[0]) or ids[0] != card.get("data-state-item")):
            continue
        dates = card.xpath("ancestor::td[1]//button[starts-with(@aria-label,'Date: ')]/@aria-label")
        if len(dates) != 1:
            raise ValueError("missing_webtrac_event_date")
        day = read_date(dates[0][6:])
        if not today <= day <= horizon:
            continue
        parts = (card.get("aria-label") or "").splitlines()
        if len(parts) != 2 or not parts[0].strip() or not TIME_RANGE.fullmatch(plain(parts[1])):
            continue
        title, times = map(plain, parts)
        if re.match(r"^(cancelled|canceled|postponed)\b", title, re.I):
            continue
        yield ids[0], day, title, times


def meeting_location(payload, day, times):
    doc = html.fromstring(payload)
    for header in doc.xpath(f"//h4[{HAS_CLASS} and normalize-space(.)='Meeting Details']",
                            class_name=" item-info__details-heading "):
        fields = [plain(node.text_content()) for node in header.xpath("following-sibling::div[1]/div")]
        if len(fields) < 6:
            continue
        dates = DATE_RANGE.fullmatch(fields[0])
        if not dates or not read_date(dates[1]) <= day <= read_date(dates[2]):
            continue
        if not fields[1].startswith("Time: ") or times.casefold() != fields[1][6:].casefold():
            continue
        venue, street, locality = fields[3:6]
        city = CITY_STATE.fullmatch(locality)
        if venue and re.match(r"^\d{1,6}\s+\S", street) and city:
            return venue, f"{street}, {city[1]}, {city[2]} {city[3]}", city[1]
    return None


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key"), source.get("feed_url"), source.get("timezone"),
            source.get("kind"), source.get("platform_adapter")) != (KEY, CALENDAR, ZONE, "html", "html"):
        raise ValueError("unregistered_webtrac_calendar")
    today = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(ZONE)).date()
    blocks = list(calendar_blocks(fetch(CALENDAR, "text/html"), today, today + timedelta(days=59)))
    if len(blocks) > 30:
        raise ValueError("webtrac_calendar_event_limit")
    details = {}
    events = {}
    for event_id, day, title, times in blocks:
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError("collection_deadline")
        query = urlencode({"FMID": event_id, "Module": "AR"})
        url = f"https://{HOST}/webtrac/web/iteminfo.html?{query}"
        if event_id not in details:
            details[event_id] = fetch(url, "text/html")
        venue = meeting_location(details[event_id], day, times)
        if venue is None:
            continue
        start, end = TIME_RANGE.fullmatch(times).groups()
        begins = datetime.combine(day, datetime.strptime(start.upper(), "%I:%M %p").time())
        finishes = datetime.combine(day, datetime.strptime(end.upper(), "%I:%M %p").time())
        if finishes <= begins:
            continue
        row = record(title, begins.isoformat(), finishes.isoformat(), *venue, url,
                     f"{event_id}:{day.isoformat()}", tz=ZONE)
        if row is not None:
            previous = events.setdefault(row["id"], row)
            if previous != row:
                raise ValueError("conflicting_webtrac_event")
    if blocks and not events:
        raise ValueError("missing_verified_webtrac_meetings")
    return sorted(events.values(), key=lambda row: (row["starts_at"], row["id"]))
