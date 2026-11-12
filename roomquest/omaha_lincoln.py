"""Reviewed Omaha and Lincoln publisher identities and iCalendar normalization."""

from datetime import datetime
from functools import lru_cache
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from icalendar import Calendar

from roomquest.ics_adapter import parse
from roomquest import riverfront


@lru_cache(maxsize=1)
def intake_rows():
    path = Path(__file__).with_name("data") / "omaha_lincoln_intake.json"
    return tuple(json.loads(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def new_ical_feeds():
    return {
        BENNINGTON: BENNINGTON_FEED,
        CLAIR_MEMORIAL: CLAIR_MEMORIAL_FEED,
        **{row["source_key"]: row["feed_url"] for row in intake_rows()
           if row.get("adapter") == "ical" and "existing_id" not in row},
    }


CLAIR_MEMORIAL = "clair_memorial_umc_omaha_ne"
CLAIR_MEMORIAL_FEED = "https://www.cmumc.net/events.ics"
CLAIR_WORSHIP_PATH = re.compile(r"/events/sunday-worship/20[0-9]{2}-[0-9]{2}-[0-9]{2}/?")

BENNINGTON = "bennington_public_library_ical_ne"
BENNINGTON_FEED = "https://benningtonlibrary.org/events/list/?ical=1"
BENNINGTON_LIBRARY_VENUE = (
    "Bennington Public Library", "11401 North 156th Street, Bennington, NE 68007",
)
BENNINGTON_PROGRAMS = {
    "thursday-storytime", "thursday-storytime-2", "1st-saturday-storytime",
    "3rd-saturday-storytime", "preschool-steam-3", "open-art-studio-4",
    "lego-your-library-5", "voyager-1-light-day-lego-your-library",
    "teen-crochet-corner-4", "teen-crochet-corner-3-2", "read-with-a-dog-5",
}
BENNINGTON_RIDGEWOOD = (
    "Ridgewood Senior Living", "12301 North 149th Circle, Bennington, NE",
)

FRANCIE_AND_FINCH = "municipal_5e01aa207622e684433576ed"
CROOK_HOUSE = "municipal_ab8764ae8583f76b90fc6de9"
LA_VISTA_LIBRARY = "municipal_mapsee_853907f4222c2608e7bf5e67"
LA_VISTA_FEED = ("https://www.cityoflavista.org/common/modules/iCalendar/"
                 "iCalendar.aspx?catID=17&feed=calendar")
LA_VISTA_CALENDAR = "https://www.cityoflavista.org/LibraryCalendar"
LA_VISTA_VENUE = re.compile(r"<p>([^<]+)</p>\s*-\s*(.+?)\s+La Vista\s+NE\s+68128", re.I)
LA_VISTA_ADDRESSES = {
    ("la vista public library", "9110 giles rd"): ("La Vista Public Library", "9110 Giles Road"),
    ("la vista public library", "9110 giles road"): ("La Vista Public Library", "9110 Giles Road"),
    ("community center", "8116 park view blvd"): ("La Vista Community Center", "8116 Park View Boulevard"),
}

BOTTLE_ROCKET = "bottle_rocket_brewing_seward_ne"
BOTTLE_ROCKET_FEED = (
    "https://calendar.google.com/calendar/ical/"
    "dcpbes1grqdipacmhaq7gh1cdk%40group.calendar.google.com/public/basic.ics"
)
BOTTLE_ROCKET_EVENTS = "https://bottlerocketbrewing.com/brewery-events/"
BOTTLE_ROCKET_ADDRESS = "230 South 5th Street, Seward, NE 68434"
BOTTLE_ROCKET_PROGRAMS = {
    "comedy night", "hog wild bbq food truck", "wagon wheel food truck", "homerun bbq food truck",
}

UNL_PUBLIC = "unl_main_events_ical_ne"
UNL_HOST = "events.unl.edu"
UNL_FEED = f"https://{UNL_HOST}/audience/?audience=Public&format=ics&limit=100"
UNL_UID = re.compile(r"([1-9][0-9]{0,11})(?:-[1-9][0-9]{0,11})?@events[.]unl[.]edu")
UNL_DETAIL_PATH = re.compile(r"/[0-9]{4}/[0-9]{2}/[0-9]{2}/[1-9][0-9]{0,11}/")
UNL_ONLINE_VENUE = re.compile(r"^(?:https?://|(?:zoom|virtual|online|webinar)\b)", re.I)
BOOKSHOP_ADDRESS = re.compile(
    r"130\s+S\.?\s+13th\s+(?:Street|St\.?),\s*Lincoln,\s*NE(?:\s+68508)?",
    re.IGNORECASE,
)
CROOK_HOUSE_NO_CLASS = re.compile(r"^No Class This Week\s*:", re.IGNORECASE)


VENUE = re.compile(
    r"(?P<venue>.+?),\s*(?P<street>[0-9]+\s+[^,]+),\s*"
    r"(?P<city>[A-Za-z][A-Za-z .'-]+),\s*(?:NE|Nebraska)"
    r"(?:\s*,?\s*(?P<zip>[0-9]{5}(?:-[0-9]{4})?))?(?:,\s*United States)?$",
    re.IGNORECASE,
)
NON_PUBLIC = re.compile(
    r"^(?:private event|private booking|room reservation|closed|library closed)"
    r"(?:\s*[:–—-].*|\s*)$", re.IGNORECASE,
)


def collect(source, fetch):
    """Use the shared occurrence parser and preserve explicit publisher venues."""
    key = source["source_key"]
    url = new_ical_feeds().get(key)
    if not url or (source.get("feed_url"), source.get("kind"),
                   source.get("platform_adapter"), source.get("timezone")) != (
            url, "ical", "ical", "America/Chicago"):
        raise ValueError("unregistered_omaha_lincoln_ical")

    payload = fetch(url, "text/calendar")
    if key == riverfront.SOURCE_KEY:
        payload = riverfront.correct_timezone(payload)
    records = parse(payload, {"url": url, "source_key": key, "timezone": source["timezone"]},
                    legacy=True, include_description=True)
    private_ids = {
        str(event.get("UID", "")) for event in Calendar.from_ical(payload).walk("VEVENT")
        if str(event.get("CLASS", "PUBLIC")).strip().upper() != "PUBLIC"
    }
    host = urlsplit(url).hostname
    result = []
    for record in records:
        if record["id"].split("__", 1)[0] in private_ids or NON_PUBLIC.fullmatch(record["title"]):
            continue
        if key == CROOK_HOUSE and CROOK_HOUSE_NO_CLASS.match(record["title"]):
            continue
        event_url = urlsplit(record["event_url"] or "")
        if event_url.scheme != "https" or event_url.hostname != host:
            continue
        # Export locations frequently put the venue name and a complete postal
        # address in one field. Keep unresolved locations for venue review.
        match = VENUE.fullmatch((record.get("venue_address") or "").strip())
        if match:
            venue = match.groupdict()
            address = f"{venue['street']}, {venue['city']}, NE"
            if venue["zip"]:
                address += f" {venue['zip']}"
            record.update(venue_name=venue["venue"], venue_address=address,
                          venue_city=venue["city"])
        if (key == CLAIR_MEMORIAL and CLAIR_WORSHIP_PATH.fullmatch(event_url.path)
                and record["title"].strip().casefold() == "sunday worship"
                and not (record.get("venue_name") or record.get("venue_address"))):
            record.update(venue_name="Clair Memorial United Methodist Church",
                          venue_address="5544 Ames Avenue, Omaha, NE", venue_city="Omaha")
        if key == BENNINGTON and not (record.get("venue_name") or record.get("venue_address")):
            # The publisher's series pages identify these library programs
            # and separately locate the Ridgewood book club off-site.
            parts = event_url.path.strip("/").split("/")
            if len(parts) in (2, 3) and parts[0] == "event":
                slug = parts[1]
                venue = BENNINGTON_RIDGEWOOD if slug == "ridgewood-book-club-2" else (
                    BENNINGTON_LIBRARY_VENUE if slug in BENNINGTON_PROGRAMS else None)
                if venue:
                    record.update(venue_name=venue[0], venue_address=venue[1], venue_city="Bennington")
        if key == riverfront.SOURCE_KEY:
            riverfront.set_venue(record)
        elif (key == FRANCIE_AND_FINCH
              and (record.get("venue_name") or "").strip().casefold() == "francie & finch bookshop"
              and BOOKSHOP_ADDRESS.fullmatch(record.get("venue_address") or "")):
            # Publisher contact address matches the existing EventQuest bookshop pin.
            record.update(lat=40.8129603, lng=-96.7022956)
        else:
            record.update(lat=None, lng=None)
        result.append(record)
    return result


def collect_unl_public(source, fetch):
    """Collect timed, in-person listings from UNL's publisher-filtered public export."""
    if (source.get("source_key"), source.get("feed_url"), source.get("kind"),
            source.get("platform_adapter"), source.get("timezone")) != (
            UNL_PUBLIC, UNL_FEED, "ical", "ical", "America/Chicago"):
        raise ValueError("unregistered_unl_public_calendar")

    payload = fetch(UNL_FEED, "text/calendar")
    records = parse(payload, {"url": UNL_FEED, "source_key": UNL_PUBLIC,
                              "timezone": source["timezone"]}, legacy=True)
    zone = ZoneInfo(source["timezone"])
    result = []
    for record in records:
        venue = (record.get("venue_name") or "").strip()
        uid = UNL_UID.fullmatch(record["id"].split("__", 1)[0])
        if not venue or UNL_ONLINE_VENUE.match(venue) or not uid:
            continue
        event_url = record.get("event_url")
        if not event_url or event_url == UNL_FEED:
            # UNL's public listing uses the local calendar date and the
            # event ID preceding any occurrence ID in its exported UID.
            day = datetime.fromisoformat(record["starts_at"]).astimezone(zone)
            record["event_url"] = f"https://{UNL_HOST}/{day:%Y/%m/%d}/{uid[1]}/"
        else:
            url = urlsplit(event_url)
            if url.scheme != "https" or url.netloc != UNL_HOST or not UNL_DETAIL_PATH.fullmatch(url.path):
                continue
        result.append(record)
    return result


def collect_bottle_rocket(source, fetch):
    """Read public taproom programs from the brewery's embedded event calendar."""
    if (source.get("source_key"), source.get("feed_url"), source.get("kind"),
            source.get("platform_adapter"), source.get("timezone")) != (
            BOTTLE_ROCKET, BOTTLE_ROCKET_FEED, "ical", "ical", "America/Chicago"):
        raise ValueError("unregistered_bottle_rocket_calendar")

    payload = fetch(BOTTLE_ROCKET_FEED, "text/calendar")
    records = parse(payload, {"url": BOTTLE_ROCKET_FEED, "source_key": BOTTLE_ROCKET,
                              "timezone": source["timezone"]}, legacy=True)
    private_ids = {
        str(event.get("UID", "")) for event in Calendar.from_ical(payload).walk("VEVENT")
        if str(event.get("CLASS", "PUBLIC")).strip().upper() != "PUBLIC"
    }
    result = []
    for record in records:
        if (record["id"].split("__", 1)[0] in private_ids
                or record["title"].strip().casefold() not in BOTTLE_ROCKET_PROGRAMS
                or record.get("venue_address") or record.get("venue_name")):
            continue
        record.update(venue_name="Bottle Rocket Brewing", venue_address=BOTTLE_ROCKET_ADDRESS,
                      venue_city="Seward", event_url=BOTTLE_ROCKET_EVENTS, lat=None, lng=None)
        result.append(record)
    return result


def normalize_la_vista_library(records):
    """Separate the city's marked-up event location and skip library closures."""
    result = []
    for record in records:
        if re.match(r"^library closed\b", record["title"].strip(), re.I):
            continue
        match = LA_VISTA_VENUE.fullmatch((record.get("venue_address") or "").strip())
        if match:
            venue, street = (part.strip().rstrip(".").casefold() for part in match.groups())
            address = LA_VISTA_ADDRESSES.get((venue, street))
            if address:
                record.update(venue_name=address[0],
                              venue_address=f"{address[1]}, La Vista, NE 68128",
                              venue_city="La Vista")
        if record.get("event_url") == LA_VISTA_FEED:
            record["event_url"] = LA_VISTA_CALENDAR
        result.append(record)
    return result
