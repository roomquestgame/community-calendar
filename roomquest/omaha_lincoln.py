"""Reviewed Omaha and Lincoln publisher identities and iCalendar normalization."""

from functools import lru_cache
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from icalendar import Calendar

from roomquest.ics_adapter import parse


@lru_cache(maxsize=1)
def intake_rows():
    path = Path(__file__).with_name("data") / "omaha_lincoln_intake.json"
    return tuple(json.loads(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def new_ical_feeds():
    return {
        row["source_key"]: row["feed_url"] for row in intake_rows()
        if row.get("adapter") == "ical" and "existing_id" not in row
    }


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
        record.update(lat=None, lng=None)
        result.append(record)
    return result
