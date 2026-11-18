"""Source-scoped canary for Mountain Home Chamber's official HTML event calendar.

Publisher supplies one calendar card per date, with event-owned time/address,
plus a separate month print view with full descriptions. No guessable event
times, borrowed HQ pins, third-party image rights or background crawling.
"""
from __future__ import annotations

from datetime import datetime, date, timezone
import re
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record

SOURCE_KEY = "mountain_home_chamber_calendar_ar"
HOST = "enjoymountainhome.com"
CALENDAR = "https://enjoymountainhome.com/events/"
PRINT = "https://enjoymountainhome.com/events/print-events/"
ZONE = "America/Chicago"
MAX_CARDS = 80
DAY_TITLE = re.compile(r"^(\d{2})/(\d{2})/(\d{2})\s+-\s+(.+)$")
DETAIL = re.compile(r"^/events/(\d{8})-[a-z0-9-]+/$")
TIME = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*([ap])\.?m\.?", re.I)
# A numbered street and the publisher's exact Arkansas town must BOTH be present.
STREET = re.compile(r"^\s*(\d{1,6}\s+.+?)\s*,?\s+Mountain Home(?:,\s*AR(?:\s+(\d{5}))?)?\s*$", re.I)


def _key(value):
    return " ".join(plain(value).casefold().split())


def print_descriptions(html):
    root = BeautifulSoup(html, "html.parser").select_one("#print_cont")
    if root is None:
        raise ValueError("mountain_home_print_missing")
    results = {}
    for header in root.select("h3"):
        match = DAY_TITLE.fullmatch(header.get_text(" ", strip=True))
        if not match:
            continue
        try:
            day = date(2000 + int(match[3]), int(match[1]), int(match[2]))
        except ValueError as exc:
            raise ValueError("mountain_home_date_invalid") from exc
        next_div = header.parent.find_next_sibling("div")
        body = description(next_div.decode_contents() if next_div else "", limit=2001)
        if len(body) > 2000:
            raise ValueError("mountain_home_description_limit")
        key = (day, _key(match[4]))
        if key in results and results[key] != body:
            raise ValueError("mountain_home_conflicting_descriptions")
        results[key] = body
    if not results or len(results) > 400:
        raise ValueError("mountain_home_print_incomplete")
    return results


def _card_value(card, css_class):
    for div in card.select("div.text-sm-set"):
        if div.select_one("i." + css_class):
            return div.get_text(" ", strip=True)
    return ""


def _time(day, value):
    match = TIME.match(value or "")
    if match is None:
        return None
    hour, minute = int(match[1]), int(match[2])
    if not (1 <= hour <= 12 and 0 <= minute <= 59):
        return None
    hour = (hour % 12) + (12 if match[3].lower() == "p" else 0)
    return datetime(day.year, day.month, day.day, hour, minute,
                    tzinfo=ZoneInfo(ZONE))


def _street(value):
    match = STREET.fullmatch(" ".join(str(value or "").split()))
    if not match:
        return ""
    street, postal = match.groups()
    return f"{street}, Mountain Home, AR" + (f" {postal}" if postal else "")


def parse_calendar(calendar_html, print_html, *, now=None):
    descriptions = print_descriptions(print_html)
    soup = BeautifulSoup(calendar_html, "html.parser")
    cards = [
        anchor for anchor in soup.select("a.link.primary[href]")
        if DETAIL.fullmatch(urlsplit(anchor.get("href", "")).path)
        and urlsplit(anchor.get("href", "")).scheme == "https"
        and urlsplit(anchor.get("href", "")).netloc == HOST
    ]
    if not cards or len(cards) > MAX_CARDS:
        raise ValueError("mountain_home_card_count_invalid")
    today = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(ZONE)).date()
    seen, records = set(), []
    for card in cards:
        url = card.get("href")
        match = DETAIL.fullmatch(urlsplit(url).path)
        try:
            value = match[1]
            day = date(int(value[:4]), int(value[4:6]), int(value[6:8]))
        except (ValueError, TypeError) as exc:
            raise ValueError("mountain_home_date_invalid") from exc
        label = card.select_one(".lead strong")
        title = plain(label.get_text(" ", strip=True)) if label else ""
        if not title:
            raise ValueError("mountain_home_title_missing")
        # Verify URL and the visible date tile independently. The calendar
        # occasionally shows a span covering many days: do not invent repeats.
        badge = card.select_one("div.f300")
        tile = card.select_one("h3.main")
        if (not badge or not tile or _key(badge.get_text(" ", strip=True)) != day.strftime("%b").casefold()
                or tile.get_text(" ", strip=True).strip() != str(day.day)):
            raise ValueError("mountain_home_card_date_mismatch")
        if day < today:
            continue
        start = _time(day, _card_value(card, "fa-clock"))
        street = _street(_card_value(card, "fa-map-marker-alt"))
        body = descriptions.get((day, _key(title)), "")
        if not start or not street or not body:
            # Incomplete publishers' event details are review holds, not guessed cards.
            continue
        if url in seen:
            raise ValueError("mountain_home_repeated_identity")
        seen.add(url)
        row = record(title, start.isoformat(), None,
                     street, street, "Mountain Home", url,
                     urlsplit(url).path.strip("/"), tz=ZONE)
        if row is not None:
            row["description"] = body
            records.append(row)
    return sorted(records, key=lambda r: (r["starts_at"], r["id"]))


def collect(source, fetch, *, deadline_at=None):
    if (source.get("source_key"), source.get("feed_url"),
            source.get("kind"), source.get("platform_adapter"),
            source.get("timezone")) != (SOURCE_KEY, CALENDAR, "html", "html", ZONE):
        raise ValueError("unregistered_mountain_home_source")
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError("collection_deadline")
    calendar_html = fetch(CALENDAR, "text/html")
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError("collection_deadline")
    print_html = fetch(PRINT, "text/html")
    return parse_calendar(calendar_html, print_html)
