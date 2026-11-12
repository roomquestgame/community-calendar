"""Public Nebraska calendars whose official pages link or embed iCalendar."""
from datetime import datetime
from urllib.parse import urlsplit

from icalendar import Calendar

from roomquest.ics_adapter import parse

ZONE = "America/Chicago"
ARBOR = "arbor_day_farm_tockify_ne"
MEMORIAL = "omaha_memorial_sda_google_ical_ne"
SHARON = "omaha_sharon_sda_ical_ne"
SOURCES = {
    ARBOR: ("https://tockify.com/api/feeds/ics/liedlodgetest", "https://www.arbordayfarm.org/events/calendar"),
    MEMORIAL: ("https://calendar.google.com/calendar/ical/omahamemorialcalendar%40gmail.com/public/basic.ics",
               "https://omahamemorialne.adventistchurch.org/bulletin/"),
    SHARON: ("https://omahasharonsda.org/?post_type=tribe_events&ical=1&eventDisplay=list",
             "https://omahasharonsda.org/home-2/events/"),
}
MEMORIAL_ONSITE = {"sabbath school", "worship service at omaha memorial church"}
CLOSED = ("will be closed", "closed for", "cancelled", "canceled", "postponed")


def collect(source, fetch):
    key = source["source_key"]
    feed, listing = SOURCES[key]
    if (source.get("feed_url"), source.get("kind"), source.get("platform_adapter"), source.get("timezone")) != (
        feed, "ical", "ical", ZONE,
    ):
        raise ValueError("unregistered_nebraska_calendar")
    payload = fetch(feed, "text/calendar")
    allowed_uids = {
        str(event.get("UID", "")) for event in Calendar.from_ical(payload).walk("VEVENT")
        if str(event.get("CLASS", "PUBLIC")).strip().upper() == "PUBLIC"
        and event.get("DTSTART") is not None and isinstance(event.decoded("DTSTART"), datetime)
    }
    rows = parse(payload, {"url": feed, "source_key": key, "timezone": ZONE},
                 legacy=True, include_description=False)
    events = []
    for row in rows:
        if row["id"].split("__", 1)[0] not in allowed_uids:
            continue
        title = row["title"].casefold()
        if any(phrase in title for phrase in CLOSED):
            continue
        if key == MEMORIAL:
            if title not in MEMORIAL_ONSITE:
                continue
            row.update(venue_name="Omaha Memorial SDA Church",
                       venue_address="840 N 72nd St, Omaha, NE 68114", venue_city="Omaha")
        elif key == SHARON and not row.get("venue_address"):
            continue
        elif key == ARBOR and not row.get("venue_address"):
            continue
        link = urlsplit(row.get("event_url") or "")
        if row.get("event_url") == feed or link.scheme != "https" or link.hostname not in {
            "tockify.com", "www.arbordayfarm.org", "omahasharonsda.org",
        }:
            row["event_url"] = listing
        row.update(lat=None, lng=None)
        events.append(row)
    return events
