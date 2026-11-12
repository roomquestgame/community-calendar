"""Normalize The RiverFront's Omaha calendar using its published park labels."""

import re


SOURCE_KEY = "municipal_12d43121684b51963c95626a"

# The calendar's displayed wall times match the export's clock values, while
# the export incorrectly labels them Eastern. Leave UTC and Central values intact.
EASTERN_EVENT_TIME = re.compile(
    r'^(DTSTART|DTEND|RDATE|EXDATE|RECURRENCE-ID);TZID=America/New_York(?=:)',
    re.MULTILINE | re.IGNORECASE,
)

GENE_LEAHY = "Gene Leahy Mall"
HEARTLAND = "Heartland of America Park"
ARCHES = "Arches Playground"
RIBBON = "Skate Ribbon"
FLAG = "American Flag"

# Park addresses and pins: https://www.lewisandclark.travel/listing/gene-leahy-mall/
# and https://www.lewisandclark.travel/listing/heartland-of-america-park/.
PARKS = {
    GENE_LEAHY: ("1001 Douglas St, Omaha, NE 68102", (41.2586, -95.9292)),
    HEARTLAND: ("800 Douglas St, Omaha, NE", (41.2567, -95.9248)),
}

# Publisher locations: https://theriverfrontomaha.com/visit-the-riverfront/.
# Landmark coordinates: https://mapcarta.com/N10014265280 and
# https://skaterground.com/item/skate-ribbon/.
ARCHES_PIN = (41.25782, -95.93155)
RIBBON_PIN = (41.25782, -95.92556)


def correct_timezone(payload):
    """Correct the publisher's Eastern-labeled event times before parsing."""
    return EASTERN_EVENT_TIME.sub(r'\1;TZID=America/Chicago', payload)


def set_venue(record):
    """Fill missing locations when the calendar names one supported anchor park."""
    if (record.get("venue_address") or record.get("venue_name")
            or record.get("lat") is not None):
        return

    parks = PARKS.keys() & set(record.get("publisher_categories", ()))
    if len(parks) != 1:
        return

    park = parks.pop()
    name = park
    # Publication requires a postal address. The park supplies that address,
    # and the point and venue label can identify a landmark within the park.
    address, pin = PARKS[park]
    description = record.get("description") or ""
    note = "Map pin shows the park's general location."
    if park == GENE_LEAHY and ARCHES.casefold() in description.casefold():
        name, pin = f"{ARCHES} at {park}", ARCHES_PIN
        note = "Arches Playground is near 11th Street and Farnam Street."
    elif park == HEARTLAND and RIBBON.casefold() in description.casefold():
        name, pin = f"{RIBBON} at {park}", RIBBON_PIN
        note = "The Skate Ribbon is at 8th Street and Farnam Street."
    elif park == HEARTLAND and FLAG.casefold() in description.casefold():
        name = f"{FLAG} at {park} (approximate pin)"
        note = "Map pin is approximate. The event is at the American Flag."
    elif park == HEARTLAND and record["title"].casefold() == "the riverfront holly days":
        name, pin = f"{park} ({RIBBON} entrance)", RIBBON_PIN
        note = "Map pin shows the Skate Ribbon entrance. Activities take place throughout the park."

    lat, lng = pin
    record.update(venue_name=name, venue_address=address, venue_city="Omaha",
                  lat=lat, lng=lng, reason=None)
    if note:
        record["description"] = f"{description[:2000 - len(note) - 2].rstrip()}\n\n{note}".strip()
