"""Collect the Norfolk taproom's timed events from The Veil's shared calendar."""
from datetime import datetime, timedelta
import re
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record

KEY = "municipal_5a87362d39d182aed1cf4a6c"
URL = "https://www.theveilbrewing.com/events/"
ZONE = "America/New_York"
VENUE = "The Veil Brewing Co. Norfolk"
ADDRESS = "2314 Colonial Avenue, Norfolk, VA 23517"
CLOCK = r"\d{1,2}(?::\d{2})?\s*[ap]m"


def text(card, cls):
    node = card.select_one(f".{cls}")
    return plain(node.get_text(" ", strip=True)) if node else ""


def local_time(day, value):
    fmt = "%I:%M%p" if ":" in value else "%I%p"
    return datetime.combine(day, datetime.strptime(re.sub(r"\s+", "", value).upper(), fmt).time())


def collect(source, fetch, *, deadline_at=None, now=None):
    if tuple(source.get(field) for field in ("source_key", "feed_url", "timezone", "kind", "platform_adapter")) != (
        KEY, URL, ZONE, "html", "html",
    ):
        raise ValueError("unregistered_veil_calendar")
    now = (now or datetime.now(ZoneInfo(ZONE))).astimezone(ZoneInfo(ZONE)).replace(tzinfo=None)
    stop = now + timedelta(days=60)
    page = BeautifulSoup(fetch(URL, "text/html"), "html.parser")
    cards = page.select(".event-tile")
    if not cards or len(cards) > 100:
        raise ValueError("invalid_veil_event_list")
    rows = {}
    for card in cards:
        if text(card, "event-location") not in {"Norfolk", "All Locations"}:
            continue
        title = text(card, "h4")
        day = text(card, "event-date")
        clock = re.fullmatch(rf"({CLOCK})(?:\s*[-–]\s*({CLOCK}))?", text(card, "event-time"), re.I)
        if not title or not day or not clock or re.search(r"\b(cancelled|canceled|postponed)\b", title, re.I):
            continue
        for year in {now.year, stop.year}:
            when = datetime.strptime(f"{day} {year}", "%a %b %d %Y")
            if when.strftime("%a") != day.split()[0]:
                continue
            start = local_time(when.date(), clock[1])
            if not now <= start < stop:
                continue
            end = local_time(when.date(), clock[2]) if clock[2] else None
            if end and end <= start:
                end += timedelta(days=1)
            identity = f"{start.date().isoformat()}:{title.casefold()}"
            row = record(title, start.isoformat(), end.isoformat() if end else None,
                         VENUE, ADDRESS, "Norfolk", URL, identity, tz=ZONE)
            if row:
                previous = rows.setdefault(identity, row)
                if previous != row:
                    raise ValueError("conflicting_veil_event")
    return sorted(rows.values(), key=lambda row: (row["starts_at"], row["id"]))
