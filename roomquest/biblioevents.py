"""Collect public BiblioEvents listings through the bounded community worker."""
from datetime import datetime, timedelta, timezone
import json
import re
from time import monotonic
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from roomquest.mapsee_adapter import address, plain, record, timestamp

GATEWAY = "gateway.bibliocommons.com"
PAGE_SIZE = 100
MAX_PAGES = 24
HORIZON = timedelta(days=60)

# https://omahalibrary.org/locations/
OMAHA_BRANCHES = {
    "a.v. sorensen branch": "4808 Cass St, Omaha, NE 68132",
    "benson branch": "6015 Binney St, Omaha, NE 68104",
    "bess johnson elkhorn branch": "2100 Reading Plaza, Elkhorn, NE 68022",
    "central library": "7205 Dodge St, Omaha, NE 68114",
    "charles b. washington branch": "2868 Ames Ave, Omaha, NE 68111",
    "downtown branch": "1401 Jones St, Omaha, NE 68102",
    "florence branch": "2920 Bondesson St, Omaha, NE 68112",
    "millard branch": "13214 Westwood Ln, Omaha, NE 68144",
    "milton r. abrahams branch": "5111 N 90th St, Omaha, NE 68134",
    "saddlebrook branch": "14850 Laurel Ave, Omaha, NE 68116",
    "south omaha library": "2808 Q St, Omaha, NE 68107",
    "w. clarke swanson branch": "9101 W Dodge Rd, Omaha, NE 68114",
    "willa cather branch": "1905 S 44th St, Omaha, NE 68105",
}
SOURCES = {
    "omaha_public_library_biblioevents_ne": ("omaha", "America/Chicago", OMAHA_BRANCHES),
}
EVENT_ID = re.compile(r"[a-zA-Z0-9_-]{1,100}")
POSTAL_ADDRESS = re.compile(r"^\d{1,6}\s+[^,]+,\s*[^,]+,\s*[A-Z]{2}(?:\s+\d{5}(?:-\d{4})?)?$")


def event_venue(definition, locations, branches):
    # An off-site venue takes precedence even when its details are incomplete.
    offsite_id = definition.get("nonBranchLocationId")
    branch_id = definition.get("branchLocationId")
    location = locations.get(offsite_id or branch_id)
    if not isinstance(location, dict):
        return "", ""
    name = plain(location.get("name"))
    raw = location.get("address")
    street = address(raw) if isinstance(raw, (str, dict)) else ""
    street = re.sub(r",\s*(\d{5}(?:-\d{4})?)$", r" \1", street)
    if not POSTAL_ADDRESS.fullmatch(street):
        street = "" if offsite_id else branches.get(name.casefold(), "")
    return name, street


def page_rows(payload, zone):
    data = json.loads(payload)
    if not isinstance(data, dict) or not isinstance(data.get("events"), dict):
        raise ValueError("invalid_biblioevents_page")
    ids = data["events"].get("items")
    if not isinstance(ids, list) or len(ids) > PAGE_SIZE:
        raise ValueError("invalid_biblioevents_page")
    if not ids:
        return []
    entities = data.get("entities")
    if not isinstance(entities, dict):
        raise ValueError("invalid_biblioevents_entities")
    events, locations = entities.get("events"), entities.get("locations", {})
    if not isinstance(events, dict) or not isinstance(locations, dict):
        raise ValueError("invalid_biblioevents_entities")
    rows = []
    for identity in ids:
        if not isinstance(identity, str) or not EVENT_ID.fullmatch(identity):
            raise ValueError("invalid_biblioevents_identity")
        item = events.get(identity)
        definition = item.get("definition") if isinstance(item, dict) else None
        if not isinstance(definition, dict):
            raise ValueError("missing_biblioevents_definition")
        start = timestamp(item.get("indexStart") or definition.get("start"), zone)
        if start is None:
            raise ValueError("event_time_missing")
        rows.append((identity, item, definition, locations, start))
    return rows


def collect(source, fetch, *, deadline_at=None, now=None):
    """Use the upstream BiblioEvents gateway shape with the worker's safe transport."""
    config = SOURCES.get(source.get("source_key"))
    if config is None:
        raise ValueError("unregistered_biblioevents_source")
    slug, zone, branches = config
    listing = f"https://{slug}.bibliocommons.com/v2/events"
    if (source.get("feed_url"), source.get("timezone"), source.get("kind"),
            source.get("platform_adapter")) != (listing, zone, "html", "html"):
        raise ValueError("unregistered_biblioevents_source")
    window_start = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(zone))
    horizon = window_start + HORIZON
    events = {}
    seen = {}
    past_horizon_pages = 0
    for page in range(1, MAX_PAGES + 1):
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError("collection_deadline")
        query = urlencode({
            "limit": PAGE_SIZE, "page": page,
            "startDate": window_start.date().isoformat(),
            "endDate": (horizon.date() + timedelta(days=1)).isoformat(),
        })
        url = f"https://{GATEWAY}/v2/libraries/{slug}/events?{query}"
        rows = page_rows(fetch(url, "application/json"), zone)
        if not rows:
            return sorted(events.values(), key=lambda row: (row["starts_at"], row["id"]))
        new_count = 0
        for identity, item, definition, locations, start in rows:
            if identity in seen:
                if seen[identity] != item:
                    raise ValueError("conflicting_biblioevents_identity")
                continue
            seen[identity] = item
            new_count += 1
            if start > horizon or definition.get("isCancelled") is True:
                continue
            if str(definition.get("attendanceMode", "")).casefold() in {"online", "virtual"}:
                continue
            venue, street = event_venue(definition, locations, branches)
            if not venue:
                continue
            end = item.get("indexEnd") or definition.get("end")
            city = street.split(",")[1].strip() if street else ""
            row = record(definition.get("title"), start.isoformat(), end, venue, street, city,
                         f"{listing}/{identity}", identity, tz=zone)
            if row is not None:
                events[identity] = row
        if not new_count:
            raise ValueError("invalid_biblioevents_pagination")
        # The public gateway can promote listings out of chronological order.
        # Require two full pages beyond the horizon before stopping early.
        if min(row[4] for row in rows) > horizon:
            past_horizon_pages += 1
        else:
            past_horizon_pages = 0
        if past_horizon_pages >= 2:
            return sorted(events.values(), key=lambda row: (row["starts_at"], row["id"]))
    raise ValueError("biblioevents_pagination_limit")
