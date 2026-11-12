"""Collect the café's own dated Mana Drag Brunch announcement."""
from datetime import datetime, timedelta
import re
from zoneinfo import ZoneInfo

from lxml import html

from roomquest.mapsee_adapter import plain, record

KEY = "mana_games_official_programs_ne"
HOST = "mana-games.com"
URL = f"https://{HOST}/events"
ZONE = "America/Chicago"
ADDRESS = "1400 Pioneers Blvd, Lincoln, NE 68502"
ANNOUNCEMENT = re.compile(
    r"Mana Drag Brunch\b.{0,130}?\bat\s+"
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm) on ([A-Za-z]{3})\.?\s*(\d{1,2})(?:st|nd|rd|th)",
    re.I,
)
# The public ticket page confirms the full date and end time of this
# announcement. Later announcements need their own dated ticket evidence.
VERIFIED_START = datetime(2026, 11, 21, 11)
VERIFIED_END = datetime(2026, 11, 21, 13)
VERIFIED_TICKET = "https://square.link/u/YmJxXJiY"


def collect(source, fetch, *, deadline_at=None, now=None):
    if tuple(source.get(key) for key in ("source_key", "feed_url", "timezone", "kind", "platform_adapter")) != (
        KEY, URL, ZONE, "html", "html",
    ):
        raise ValueError("unregistered_mana_official_programs")
    zone = ZoneInfo(ZONE)
    today = (now or datetime.now(zone)).astimezone(zone).date()
    if not today <= VERIFIED_START.date() <= today + timedelta(days=59):
        return []
    document = html.fromstring(fetch(URL, "text/html"))
    match = ANNOUNCEMENT.search(plain(" ".join(document.xpath("//body//text()"))))
    if not match:
        raise ValueError("missing_verified_mana_announcement")
    hour, minute, period, month, day = match.groups()
    date_text = f"{month} {day} {VERIFIED_START.year} {hour}:{minute or '00'} {period.upper()}"
    if datetime.strptime(date_text, "%b %d %Y %I:%M %p") != VERIFIED_START:
        return []
    event = record("November Mana Drag Brunch", VERIFIED_START.isoformat(), VERIFIED_END.isoformat(),
                   "Mana Games Café", ADDRESS, "Lincoln", VERIFIED_TICKET, "mana-brunch-2026-11-21", tz=ZONE)
    return [event] if event is not None else []
