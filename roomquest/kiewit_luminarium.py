"""Collect dated program occurrences from the Kiewit Luminarium calendar."""
from datetime import datetime, timedelta
from hashlib import sha256
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from lxml import html

from roomquest.mapsee_adapter import plain, record

HOST = "kiewitluminarium.org"
KEY = "omaha_kiewit_luminarium_ne"
URL = f"https://{HOST}/events/"
ZONE = "America/Chicago"
VENUE = "Kiewit Luminarium"
ADDRESS = "345 Riverfront Drive, Omaha, NE 68102"
CLOCK = re.compile(r"\b\d{1,2}:\d{2}\s*[ap]m\b", re.I)
HAS_CLASS = "contains(concat(' ', normalize-space(@class), ' '), $token)"


def elements(node, class_name, tag="*"):
    return node.xpath(f".//{tag}[{HAS_CLASS}]", token=f" {class_name} ")


def parse_clock(day, clock):
    return datetime.combine(day, datetime.strptime(clock.upper(), "%I:%M %p").time())


def collect(source, fetch, *, deadline_at=None, now=None):
    if tuple(source.get(key) for key in ("source_key", "feed_url", "timezone", "kind", "platform_adapter")) != (
        KEY, URL, ZONE, "html", "html",
    ):
        raise ValueError("unregistered_luminarium_calendar")
    today = (now or datetime.now(ZoneInfo(ZONE))).astimezone(ZoneInfo(ZONE)).date()
    document = html.fromstring(fetch(URL, "text/html"))
    cards = elements(document, "event-thumbnail--content")
    if not cards:
        raise ValueError("missing_luminarium_event_cards")
    events = {}
    for card in cards:
        links = elements(card, "event-thumbnail--title", "h3")
        meta = elements(card, "event-thumbnail--meta", "p")
        if not links or not meta:
            continue
        anchors = links[0].xpath("./a[@href]")
        spans = meta[0].xpath("./span")
        if not anchors or len(spans) < 2:
            continue
        anchor = anchors[0]
        title = plain(anchor.text_content())
        if not title or re.search(r"\b(cancelled|canceled|postponed)\b", title, re.I):
            continue
        date_text = plain(spans[0].text_content())
        try:
            day = datetime.strptime(date_text, "%A, %b %d, %Y").date()
        except ValueError:
            continue
        if not today <= day <= today + timedelta(days=59):
            continue
        times = CLOCK.findall(plain(spans[1].text_content()))
        if len(times) not in (1, 2):
            continue
        start = parse_clock(day, times[0])
        end = parse_clock(day, times[1]) if len(times) == 2 else None
        if end is not None and end <= start:
            continue
        link = anchor.get("href")
        target = urlsplit(link)
        if (target.scheme, target.netloc) != ("https", HOST) or not re.fullmatch(r"/events/[^/]+/", target.path):
            raise ValueError("invalid_luminarium_event_link")
        identity = sha256(f"{target.path}:{start.isoformat()}".encode()).hexdigest()
        row = record(title, start.isoformat(), end.isoformat() if end else None, VENUE, ADDRESS,
                     "Omaha", link, identity, tz=ZONE)
        if row is not None:
            previous = events.setdefault(row["id"], row)
            if previous != row:
                raise ValueError("conflicting_luminarium_event")
    return sorted(events.values(), key=lambda row: (row["starts_at"], row["id"]))
