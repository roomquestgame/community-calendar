"""Publisher schedule/coordinate evidence, captured before venue enrichment.

No digest is computed here: PostgreSQL event_content_v1 remains authoritative.
These fields are evidence, not a change to the existing occurrence identity.
"""
from datetime import date, datetime, timezone


NORMALIZATION_VERSION = "ical-publisher-facts-1"


def anchor(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        return value.astimezone(timezone.utc).isoformat()
    return value.isoformat() if isinstance(value, date) else None


def capture(component):
    start = component.decoded("DTSTART")
    end = component.decoded("DTEND", None)
    all_day = isinstance(start, date) and not isinstance(start, datetime)
    geo = component.get("GEO")
    lat, lng = getattr(geo, "latitude", None), getattr(geo, "longitude", None)
    if isinstance(geo, (tuple, list)) and len(geo) == 2:
        lat, lng = geo
    original_uid = str(component.get("X-EVENTQUEST-ORIGINAL-UID", component.get("UID", "")))
    recurrence = component.get("X-EVENTQUEST-RECURRENCE-ANCHOR")
    if recurrence is None:
        recurrence = anchor(component.decoded("RECURRENCE-ID", None))
    return {
        "version": 1,
        "is_all_day": all_day,
        "all_day_start_date": start.isoformat() if all_day else None,
        "all_day_end_date_exclusive": anchor(end) if all_day else None,
        "original_uid": original_uid,
        "recurrence_anchor": str(recurrence) if recurrence is not None else None,
        "source_latitude": str(lat) if lat is not None else None,
        "source_longitude": str(lng) if lng is not None else None,
    }
