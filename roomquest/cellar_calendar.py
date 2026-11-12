"""Read the public Cellar 426 events listing and confirm dates on detail pages."""
from datetime import datetime, timedelta
from hashlib import sha256
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from lxml import html

from roomquest.mapsee_adapter import plain, record

KEY = "cellar_426_events_ne"
HOST = "www.cellar426.com"
URL = f"https://{HOST}/events"
ZONE = "America/Chicago"
ADDRESS = "1005 Prairie Agate Drive, Ashland, NE 68003"
DATE = re.compile(r"([A-Za-z]+), ([A-Za-z]+) (\d{1,2})(?:st|nd|rd|th)?")
TIME = re.compile(r"(\d{1,2}:\d{2})\s*([ap]m)?\s*[–—-]\s*(\d{1,2}:\d{2})\s*([ap]m)", re.I)
EXCLUDED = re.compile(r"\b(?:closed|cancelled|canceled|postponed)\b", re.I)


def elements(node, token):
    return node.xpath(".//*[contains(concat(' ', normalize-space(@class), ' '), $token)]",
                      token=f" {token} ")


def scheduled_day(text, today):
    match = DATE.fullmatch(text)
    if match is None:
        return None
    weekday, month, number = match.groups()
    for year in (today.year, today.year + 1):
        try:
            day = datetime.strptime(f"{month} {number} {year}", "%B %d %Y").date()
        except ValueError:
            continue
        if today <= day <= today + timedelta(days=59) and day.strftime("%A") == weekday:
            return day
    return None


def collect(source, fetch, *, deadline_at=None, now=None):
    if tuple(source.get(k) for k in ("source_key", "feed_url", "timezone", "kind", "platform_adapter")) != (
        KEY, URL, ZONE, "html", "html",
    ):
        raise ValueError("unregistered_cellar_calendar")
    today = (now or datetime.now(ZoneInfo(ZONE))).astimezone(ZoneInfo(ZONE)).date()
    listing = html.fromstring(fetch(URL, "text/html"))
    cards = elements(listing, "views-row")
    if not cards:
        raise ValueError("missing_cellar_calendar")
    candidates = {}
    for card in cards:
        titles = elements(card, "views-field-title")
        dates = elements(card, "views-field-field-date-range")
        times = elements(card, "views-field-field-date-range-1")
        if not titles or not dates or not times:
            continue
        links = titles[0].xpath(".//a[@href]")
        if not links:
            continue
        title = plain(links[0].text_content())
        date_text = plain(dates[0].text_content())
        time_text = plain(times[0].text_content())
        if not title or EXCLUDED.search(title) or not TIME.fullmatch(time_text):
            continue
        url = urljoin(URL, links[0].get("href"))
        target = urlsplit(url)
        if (target.scheme, target.netloc) != ("https", HOST) or not re.fullmatch(r"/[a-z0-9-]+", target.path):
            raise ValueError("invalid_cellar_event_url")
        candidates[url] = title, date_text, time_text
    if len(candidates) > 12:
        raise ValueError("cellar_event_detail_limit")
    result = []
    for url, (title, date_text, time_text) in candidates.items():
        detail = html.fromstring(fetch(url, "text/html"))
        fields = elements(detail, "field--name-field-date-range")
        for field in fields:
            parts = [plain(part) for part in field.itertext() if plain(part)]
            if len(parts) != 2 or parts[1] != time_text:
                continue
            day = scheduled_day(parts[0], today)
            if day is None or f"{day:%B} {day.day}" != date_text:
                continue
            first, first_period, last, last_period = TIME.fullmatch(time_text).groups()
            start = datetime.strptime(f"{first} {(first_period or last_period).upper()}", "%I:%M %p").time()
            end = datetime.strptime(f"{last} {last_period.upper()}", "%I:%M %p").time()
            if start >= end:
                continue
            identity = sha256(f"{url}:{day.isoformat()}".encode()).hexdigest()
            row = record(title, datetime.combine(day, start).isoformat(), datetime.combine(day, end).isoformat(),
                         "Cellar 426 Winery", ADDRESS, "Ashland", url, identity, tz=ZONE)
            if row is not None:
                result.append(row)
            break
    return sorted(result, key=lambda row: (row["starts_at"], row["id"]))
