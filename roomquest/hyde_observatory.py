"""Collect the next public Saturday programs from Hyde's published winter hours."""
from datetime import date, datetime, timedelta
import re
from zoneinfo import ZoneInfo

from lxml import html

from roomquest.mapsee_adapter import plain, record

KEY = "hyde_observatory_programs_ne"
HOST = "www.hydeobservatory.info"
URL = f"https://{HOST}/"
ZONE = "America/Chicago"


def near_holiday(day):
    november = date(day.year, 11, 1)
    thanksgiving = november + timedelta(days=(3 - november.weekday()) % 7 + 21)
    holidays = (date(day.year, 1, 1), thanksgiving, date(day.year, 12, 25),
                date(day.year + 1, 1, 1))
    return any(abs((day - holiday).days) <= 3 for holiday in holidays)


def collect(source, fetch, *, deadline_at=None, now=None):
    if tuple(source.get(k) for k in ("source_key", "feed_url", "timezone", "kind", "platform_adapter")) != (
        KEY, URL, ZONE, "html", "html",
    ):
        raise ValueError("unregistered_hyde_calendar")
    zone = ZoneInfo(ZONE)
    today = (now or datetime.now(zone)).astimezone(zone).date()
    page = html.fromstring(fetch(URL, "text/html"))
    body = plain(" ".join(page.xpath("//body//text()")))
    if not re.search(r"open every Saturday year-round", body, re.I):
        raise ValueError("hyde_saturday_program_changed")
    if not re.search(r"October 1\s*[-–]\s*March 14\s+7 PM to 10 PM", body, re.I):
        raise ValueError("hyde_winter_hours_changed")
    if re.search(r"\b(?:closed|closure)\b", body.split("Hours", 1)[0], re.I):
        return []
    events = []
    for offset in range(15):
        day = today + timedelta(days=offset)
        in_winter = (day.month, day.day) >= (10, 1) or (day.month, day.day) <= (3, 14)
        if day.weekday() != 5 or not in_winter or near_holiday(day):
            continue
        start = datetime(day.year, day.month, day.day, 19)
        end = datetime(day.year, day.month, day.day, 22)
        row = record("Saturday Astronomy Programs at Hyde Observatory", start.isoformat(), end.isoformat(),
                     "Hyde Memorial Observatory", "3701 S 70th St, Lincoln, NE 68506",
                     "Lincoln", URL, f"hyde-{day.isoformat()}", lat=40.777812, lng=-96.636292,
                     tz=ZONE, publisher_geo=True)
        if row is not None:
            events.append(row)
    return events
