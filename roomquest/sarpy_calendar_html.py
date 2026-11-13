"""Read dated events from the public Sarpy County tourism calendars."""
from datetime import datetime, timedelta
import re
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record
from roomquest.mycountyparks import cancelled

HOST = "www.sarpy.gov"
ZONE = "America/Chicago"
SOURCES = {"sarpy_recurring_tourism_html_ne": 36, "sarpy_sports_tourism_html_ne": 35}


def listing_url(category):
    return f"https://{HOST}/Calendar.aspx?" + urlencode({"CID": category, "view": "list"})


def value(node, selector):
    element = node.select_one(selector)
    return plain(element.get_text(" ", strip=True)) if element else ""


def collect(source, fetch, *, deadline_at=None, now=None):
    category = SOURCES.get(source.get("source_key"))
    if category is None or tuple(source.get(field) for field in
            ("feed_url", "kind", "platform_adapter", "timezone")) != (
            listing_url(category), "html", "html", ZONE):
        raise ValueError("unregistered_sarpy_calendar")
    zone = ZoneInfo(ZONE)
    now = now or datetime.now(zone)
    soup = BeautifulSoup(fetch(listing_url(category), "text/html"), "html.parser")
    listing = soup.select_one(f"#CID{category}")
    if listing is None:
        raise ValueError("missing_sarpy_calendar")
    rows = []
    seen = set()
    for item in listing.select('[itemtype$="/Event"]'):
        parent = item.find_parent("li")
        link = parent.select_one("a[id^=eventTitle_]") if parent else None
        identity = re.fullmatch(r"eventTitle_(\d{1,12})", link.get("id", "")) if link else None
        title = value(item, '[itemprop="name"]')
        start = value(item, '[itemprop="startDate"]')
        place = item.select_one('[itemprop="location"]')
        if not identity or not title or not start or place is None or cancelled(title, ""):
            continue
        starts = datetime.fromisoformat(start).replace(tzinfo=zone)
        if not now < starts < now + timedelta(days=60):
            continue
        venue = value(place, '[itemprop="name"]')
        street = value(place, '[itemprop="streetAddress"]')
        city = value(place, '[itemprop="addressLocality"]')
        state = value(place, '[itemprop="addressRegion"]')
        postal = value(place, '[itemprop="postalCode"]')
        if venue == "Gretna Crossing YMCA" and not street:
            street, city, state, postal = "12358 S 208th Ave", "Gretna", "NE", "68028"
        if not re.match(r"^\d{1,6}\s+", street) or not city or state != "NE":
            continue
        key = (identity[1], starts)
        if key in seen:
            continue
        seen.add(key)
        ends = None
        displayed = value(parent, ".subHeader .date")
        clocks = re.findall(r"\b\d{1,2}:\d{2}\s*[AP]M\b", displayed)
        if len(clocks) == 2 and clocks[0] == starts.strftime("%I:%M %p").lstrip("0"):
            end_time = datetime.strptime(clocks[1], "%I:%M %p").time()
            candidate = datetime.combine(starts.date(), end_time, zone)
            if candidate > starts:
                ends = candidate.isoformat()
        url = f"https://{HOST}/Calendar.aspx?EID={identity[1]}"
        row = record(title, starts.isoformat(), ends, venue, f"{street}, {city}, {state} {postal}".rstrip(),
                     city, url, identity[1], tz=ZONE)
        if row:
            rows.append(row)
    return sorted(rows, key=lambda row: (row["starts_at"], row["id"]))
