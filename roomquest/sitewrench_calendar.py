"""Read dated event cards from a SiteWrench public calendar."""
from datetime import datetime, timedelta, timezone
import re
from time import monotonic
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from lxml import html

from roomquest.mapsee_adapter import plain, record

KEY = "omaha_henry_doorly_zoo_events"
HOST = "www.omahazoo.com"
CALENDAR = f"https://{HOST}/special-events"
ZONE = "America/Chicago"
PARAMETER = "cal-414412-"
ADDRESS = "3701 S 10th St, Omaha, NE 68107"
VENUE = "Omaha’s Henry Doorly Zoo & Aquarium"
HAS_CLASS = "contains(concat(' ', normalize-space(@class), ' '), $class_name)"
EVENT_PATH = re.compile(r"/special-events/event/(\d+)(?:/date/(\d{4}-\d{2}-\d{2}))?")
DATE_TIME = re.compile(r"(.+?)\s*@\s*(\d{1,2}:\d{2}\s+[AP]M)(?:\s*[-–]\s*(\d{1,2}:\d{2}\s+[AP]M))?", re.I)
FEATURED_TIME = re.compile(r"(\d{1,2}:\d{2}\s+[AP]M)(?:\s*[-–]\s*(\d{1,2}:\d{2}\s+[AP]M))?", re.I)


def elements(node, class_name):
    return node.xpath(f".//*[{HAS_CLASS}]", class_name=f" {class_name} ")


def timed_record(title, day, start, end, event_id, link):
    starts = datetime.combine(day, datetime.strptime(start, "%I:%M %p").time())
    ends = datetime.combine(day, datetime.strptime(end, "%I:%M %p").time()) if end else None
    if ends is not None and ends <= starts:
        raise ValueError("invalid_sitewrench_end_time")
    return record(title, starts.isoformat(), ends.isoformat() if ends else None, VENUE,
                  ADDRESS, "Omaha", link, f"{event_id}:{day.isoformat()}", tz=ZONE)


def event_card(card, today, horizon):
    titles = elements(card, "CalendarListEvent__title")
    metadata = elements(card, "CalendarListEvent__meta")
    links = {urljoin(CALENDAR, link) for link in card.xpath(".//a/@href")
             if EVENT_PATH.fullmatch(urlsplit(urljoin(CALENDAR, link)).path)}
    if not titles or not metadata or len(links) != 1:
        raise ValueError("invalid_sitewrench_event")
    title = plain(titles[0].text_content())
    link = links.pop()
    parsed = urlsplit(link)
    event_id, linked_date = EVENT_PATH.fullmatch(parsed.path).groups()
    if parsed.scheme != "https" or parsed.netloc != HOST or parsed.query or parsed.fragment:
        raise ValueError("invalid_sitewrench_event_url")
    if re.match(r"^(cancelled|canceled|postponed)\b", title, re.I):
        return None
    match = DATE_TIME.fullmatch(plain(metadata[0].text_content()))
    if match is None:
        return None
    day_text, start, end = match.groups()
    day = datetime.strptime(day_text, "%B %d, %Y").date()
    if linked_date and linked_date != day.isoformat():
        raise ValueError("sitewrench_event_date_mismatch")
    if not today <= day <= horizon:
        return None
    return timed_record(title, day, start, end, event_id, link)


def featured_events(payload, today, horizon):
    document = html.fromstring(payload)
    headings = elements(document, "upcoming-events-name")
    if not headings:
        return None
    records = {}
    for heading in headings:
        cards = heading.xpath("ancestor::li[1]")
        hrefs = heading.xpath(".//a/@href")
        if not cards or len(hrefs) != 1:
            continue
        link = urljoin(CALENDAR, hrefs[0])
        parsed = urlsplit(link)
        occurrence = EVENT_PATH.fullmatch(parsed.path)
        if (parsed.scheme != "https" or parsed.netloc != HOST or parsed.query or parsed.fragment
                or occurrence is None or not occurrence[2]):
            continue
        day = datetime.strptime(occurrence[2], "%Y-%m-%d").date()
        months = elements(cards[0], "upcoming-events-month")
        dates = cards[0].xpath(f".//span[{HAS_CLASS}]", class_name=" upcoming-events-date ")
        times = elements(cards[0], "upcoming-events-time")
        title = plain(heading.text_content())
        if not today <= day <= horizon or not (months and dates and times and title):
            continue
        if re.match(r"^(cancelled|canceled|postponed)\b", title, re.I):
            continue
        shown_date = f"{plain(months[0].text_content())} {plain(dates[0].text_content())} {day.year}"
        if datetime.strptime(shown_date, "%b %d %Y").date() != day:
            raise ValueError("sitewrench_event_date_mismatch")
        match = FEATURED_TIME.fullmatch(plain(times[0].text_content()))
        if not match:
            continue
        row = timed_record(title, day, match[1], match[2], occurrence[1], link)
        if row is not None:
            previous = records.setdefault(row["id"], row)
            if previous != row:
                raise ValueError("duplicate_sitewrench_event")
    return sorted(records.values(), key=lambda row: (row["starts_at"], row["id"]))


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key"), source.get("feed_url"), source.get("timezone"),
            source.get("kind"), source.get("platform_adapter")) != (KEY, CALENDAR, ZONE, "html", "html"):
        raise ValueError("unregistered_sitewrench_calendar")
    today = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(ZONE)).date()
    horizon = today + timedelta(days=59)
    # The zoo's full listing is rendered in the browser. Its featured widget
    # already has dated links in the HTML and can be collected in one request.
    featured = featured_events(fetch(f"https://{HOST}/", "text/html"), today, horizon)
    if featured is not None:
        return featured
    params = {"startDate": today.isoformat(), "endDate": horizon.isoformat(),
              "pageSize": 60, "sortBy": "startDate"}
    records = {}
    for page in range(1, 9):
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError("collection_deadline")
        params["page"] = page
        query = urlencode({PARAMETER + name: value for name, value in params.items()})
        document = html.fromstring(fetch(f"{CALENDAR}?{query}", "text/html"))
        if not elements(document, "swCalEvents"):
            raise ValueError("missing_sitewrench_calendar")
        cards = elements(document, "CalendarListEvent")
        if page > 1 and not cards:
            raise ValueError("empty_sitewrench_page")
        for card in cards:
            row = event_card(card, today, horizon)
            if row is None:
                continue
            if row["id"] in records:
                raise ValueError("duplicate_sitewrench_event")
            records[row["id"]] = row
        pagination = elements(document, "CalendarListPagination")
        if not any(parse_qs(urlsplit(href).query).get(PARAMETER + "page") == [str(page + 1)]
                   for nav in pagination for href in nav.xpath(".//a/@href")):
            return sorted(records.values(), key=lambda row: (row["starts_at"], row["id"]))
    raise ValueError("sitewrench_pagination_limit")
