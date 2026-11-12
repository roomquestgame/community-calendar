"""Collect the visible local times from First United Methodist's MEC calendar."""
from datetime import datetime, timedelta
from hashlib import sha256
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from lxml import html

from roomquest.mapsee_adapter import plain, record

KEY = "omaha_first_united_methodist_mec_ne"
HOST = "fumcomaha.org"
URL = f"https://{HOST}/events/"
ZONE = "America/Chicago"
VENUE = "First United Methodist Church of Omaha"
ADDRESS = "7020 Cass Street, Omaha, NE 68132"
CLASS = "contains(concat(' ', normalize-space(@class), ' '), $class_name)"
EXCLUDED = re.compile(r"\b(closed|cancelled|canceled|postponed)\b", re.I)


def field(node, name):
    values = node.xpath(f".//*[{CLASS}]", class_name=f" {name} ")
    return plain(values[0].text_content()) if values else ""


def clock(day, text):
    if not re.fullmatch(r"\d{1,2}:\d{2}\s+[ap]m", text, re.I):
        return None
    return datetime.combine(day, datetime.strptime(text.upper(), "%I:%M %p").time())


def collect(source, fetch, *, deadline_at=None, now=None):
    if tuple(source.get(key) for key in ("source_key", "feed_url", "timezone", "kind", "platform_adapter")) != (
        KEY, URL, ZONE, "html", "html",
    ):
        raise ValueError("unregistered_mec_calendar")
    today = (now or datetime.now(ZoneInfo(ZONE))).astimezone(ZoneInfo(ZONE)).date()
    document = html.fromstring(fetch(URL, "text/html"))
    cards = document.xpath(f"//article[{CLASS}]", class_name=" mec-event-article ")
    if not cards:
        raise ValueError("missing_mec_event_list")
    events = {}
    for card in cards:
        if {"mec-cancelled", "mec-canceled", "mec-postponed"} & set(card.get("class", "").split()):
            continue
        anchors = card.xpath(f".//h3[{CLASS}]/a[@href]", class_name=" mec-event-title ")
        month = re.search(r"\bmec-toggle-(\d{4})(\d{2})-", card.get("class", ""))
        date_text = field(card, "mec-start-date-label")
        day_number = re.fullmatch(r"(\d{1,2}) ([A-Za-z]{3})", date_text)
        if not anchors or month is None or day_number is None:
            continue
        title = plain(anchors[0].text_content())
        address = field(card, "mec-event-address")
        if not title or EXCLUDED.search(title) or not re.match(r"^7020 Cass St(?:reet)?\.?,\s*Omaha\b", address, re.I):
            continue
        day = datetime(int(month[1]), int(month[2]), int(day_number[1])).date()
        if day.strftime("%b").casefold() != day_number[2].casefold() or not today <= day <= today + timedelta(days=59):
            continue
        start = clock(day, field(card, "mec-start-time"))
        end = clock(day, field(card, "mec-end-time"))
        if start is None or end is not None and end <= start:
            continue
        link = anchors[0].get("href")
        target = urlsplit(link)
        if (target.scheme, target.netloc) != ("https", HOST) or not re.fullmatch(r"/event/[^/]+/", target.path):
            raise ValueError("invalid_mec_event_link")
        identity = sha256(f"{target.path}:{start.isoformat()}".encode()).hexdigest()
        row = record(title, start.isoformat(), end.isoformat() if end else None, VENUE, ADDRESS,
                     "Omaha", link, identity, tz=ZONE)
        if row is not None:
            events[row["id"]] = row
    return sorted(events.values(), key=lambda row: (row["starts_at"], row["id"]))
