"""Collect timed public events from the two Nebraska preserve calendars."""
from datetime import datetime, timedelta
from hashlib import sha256
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from lxml import html

from roomquest.mapsee_adapter import plain, record

ZONE = "America/Chicago"
SOURCES = {
    "prairie_pines_events_ne": (
        "https://prairiepines.org/events/",
        "Prairie Pines Nature Preserve", "3100 N 112th Street, Lincoln, NE 68527", "Lincoln",
    ),
    "glacier_creek_preserve_events_ne": (
        "https://www.unomaha.edu/college-of-arts-and-sciences/nature-preserves/preserves/preserve-events.php",
        "Glacier Creek Preserve", "14810 State Street, Bennington, NE 68007", "Bennington",
    ),
}
DATE = re.compile(
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
    r"(?P<day>[A-Za-z]+ \d{1,2}, \d{4})", re.I,
)
TIME_RANGE = re.compile(
    r"[,|]?\s*(?P<start>\d{1,2}(?::\d{2})?)\s*(?P<first>AM|PM)?"
    r"\s*[-–—]\s*(?P<end>\d{1,2}(?::\d{2})?)\s*(?P<last>AM|PM)\b", re.I,
)
INVALID_TITLE = re.compile(r"\b(cancelled|canceled|postponed|save.the.date)\b", re.I)
CLASS = "contains(concat(' ', normalize-space(@class), ' '), $token)"


def by_class(node, name):
    return node.xpath(f".//*[{CLASS}]", token=f" {name} ")


def clock(value, period):
    return datetime.strptime(f"{value} {period.upper()}", "%I:%M %p" if ":" in value else "%I %p").time()


def times(text):
    for match in DATE.finditer(text):
        span = TIME_RANGE.match(text, match.end())
        if span is None:
            continue
        day = datetime.strptime(match["day"], "%B %d, %Y").date()
        start = clock(span["start"], span["first"] or span["last"])
        end = clock(span["end"], span["last"])
        if span["first"] is None and start > end:
            start = clock(span["start"], "AM" if span["last"].upper() == "PM" else "PM")
        if start < end:
            yield datetime.combine(day, start), datetime.combine(day, end)


def prairie_events(document):
    columns = by_class(document, "x-col")
    if not columns or not by_class(document, "x-text-content-text-primary"):
        raise ValueError("missing_prairie_pines_calendar")
    for column in columns:
        for block in column.xpath(f"./*[{CLASS}]", token=" x-text-headline "):
            titles = by_class(block, "x-text-content-text-primary")
            if len(titles) != 1:
                continue
            schedule = by_class(block, "x-text-content-text-subheadline")
            if not schedule:
                following = block.xpath(f"following-sibling::*[not(self::hr)][1][{CLASS}]",
                                        token=" x-content ")
                schedule = following
            if schedule:
                yield plain(titles[0].text_content()), plain(" ".join(schedule[0].itertext()))


def glacier_events(document):
    heading = document.xpath("//h2[normalize-space(.)='Upcoming Events']")
    if len(heading) != 1:
        raise ValueError("missing_glacier_creek_calendar")
    title = ""
    location_confirmed = False
    for node in heading[0].itersiblings():
        if node.tag == "h2":
            break
        if node.tag in {"h3", "hr"}:
            title = plain(node.text_content()) if node.tag == "h3" else ""
            location_confirmed = False
        elif node.tag == "p":
            text = plain(" ".join(node.itertext()))
            if text.startswith("Location:"):
                location_confirmed = bool(re.search(r"\b14810 State St(?:reet)?\.?,\s*Bennington\b", text, re.I))
            elif title and location_confirmed and re.match(r"^[\w /-]*Dates?/Times?:", text, re.I):
                yield title.removeprefix("Join us for "), text


def collect(source, fetch, *, deadline_at=None, now=None):
    profile = SOURCES.get(source.get("source_key"))
    if profile is None or tuple(source.get(k) for k in ("feed_url", "timezone", "kind", "platform_adapter")) != (
        profile[0], ZONE, "html", "html",
    ):
        raise ValueError("unregistered_nebraska_preserve")
    url, venue, address, city = profile
    today = (now or datetime.now(ZoneInfo(ZONE))).astimezone(ZoneInfo(ZONE)).date()
    document = html.fromstring(fetch(url, "text/html"))
    parser = prairie_events if urlsplit(url).hostname == "prairiepines.org" else glacier_events
    events = {}
    for title, schedule in parser(document):
        if not title or INVALID_TITLE.search(title):
            continue
        for start, end in times(schedule):
            if not today <= start.date() <= today + timedelta(days=59):
                continue
            identity = sha256(f"{title.casefold()}:{start.isoformat()}".encode()).hexdigest()
            row = record(title, start.isoformat(), end.isoformat(), venue, address, city, url, identity, tz=ZONE)
            if row is not None:
                events[row["id"]] = row
    return sorted(events.values(), key=lambda row: (row["starts_at"], row["id"]))
