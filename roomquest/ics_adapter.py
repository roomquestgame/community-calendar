"""Shared bounded ICS validation; existing recurrence/VEVENT normalizer retained.

Legacy output fields and media stay intact to preserve venue-cache identity.
Mapsee URL/address fallbacks stay restricted to its existing catalog records.
"""
from datetime import datetime, timezone

def parse(payload, source, *, legacy=False, include_description=False):
    from icalendar import Calendar
    from roomquest.preview_worker import parse_ics_preview
    if not payload.lstrip("\ufeff \r\n").upper().startswith("BEGIN:VCALENDAR") or "END:VCALENDAR" not in payload.upper():
        raise ValueError("invalid_calendar_payload")
    cal=Calendar.from_ical(payload)
    events=cal.walk("VEVENT")
    if len(events)>5000:raise ValueError("source_record_limit")
    unsupported=[]
    for e in events:
        if str(e.get("STATUS","")).upper() in {"CANCELLED","CANCELED"}:continue
        if e.errors:
            if any(str(error[0]).upper() in {"RRULE","RDATE","EXDATE","RECURRENCE-ID"} for error in e.errors):
                raise ValueError("recurrence_invalid")
            raise ValueError("invalid_ical_component")
        start=e.decoded("DTSTART") if e.get("DTSTART") else None
        if start is None:raise ValueError("invalid_ical_missing_start")
        # Date-only events have no advertised time; the existing collector does
        # not invent one. Distinguish that unsupported shape from valid empty.
        if not isinstance(start,datetime):
            if start>=datetime.now(timezone.utc).date():unsupported.append("unsupported_all_day_time")
            continue
        if start.tzinfo is None:
            if start.date()>=datetime.now(timezone.utc).date():unsupported.append("timezone_unresolved")
            continue
        if e.get("RRULE"):
            rule=e["RRULE"]
            frequency=str((rule.get("FREQ") or [""])[0]).upper()
            density=1
            for field in ("BYSECOND","BYMINUTE","BYHOUR","BYDAY"):
                density*=max(1,len(rule.get(field) or []))
            if frequency not in {"DAILY","WEEKLY","MONTHLY","YEARLY"} or density>24:
                raise ValueError("unsupported_dense_recurrence")
            try:
                from dateutil.rrule import rrulestr
                rrulestr(e["RRULE"].to_ical().decode(),dtstart=start)
            except (ValueError,TypeError,OverflowError) as exc:raise ValueError("recurrence_invalid") from exc
    # Udell's recurrence expander intentionally returns None on a malformed
    # recurrence. For new catalog sources that must be reported as a failure.
    if sum(bool(e.get("RRULE")) for e in events)>50:
        raise ValueError("recurrence_record_limit")
    if any(e.get("RRULE") for e in events):
        from scripts.combine_ics import expand_rrules
        if expand_rrules(payload,window_days=60) is None:
            raise ValueError("recurrence_expansion_failed")
    # Feed histories can precede the future records. Keep the existing 1000-item
    # parser bound honest instead of silently calling a truncated feed empty.
    if len(events)>1000:
        raise ValueError("source_record_limit")
    result=parse_ics_preview(payload,allow_ongoing=True,include_images=legacy, include_description=include_description)
    if not result and unsupported:raise ValueError(unsupported[0])
    # A feed URL is an actual publisher link when its VEVENT omits URL. Never
    # fabricate a detail URL, venue, publisher host, description or image.
    # Retain the actual publisher labels separately from the legacy single text
    # category. VEVENT CATEGORIES can be a multi-valued vCategory or repeated.
    # Bound the labels before they enter our JSON staging contract.
    categories = {}
    for event in events:
        labels = []
        raw = event.get("CATEGORIES")
        for value in (raw if isinstance(raw, list) else [raw]):
            if value is None:
                continue
            for label in getattr(value, "cats", []):
                cleaned = str(label).strip()
                if cleaned and cleaned not in labels:
                    labels.append(cleaned[:100])
                if len(labels) >= 20:
                    break
        categories[str(event.get("UID", ""))] = labels

    for e in result:
        if legacy:
            continue
        e.pop("image_url",None)
        e["publisher_categories"]=categories.get(e["id"].split("__",1)[0], [])
        e["category"]=", ".join(e["publisher_categories"])[:80]
        if not e.get("event_url"):e["event_url"]=source["url"]
        if not e.get("venue_address") and e.get("venue_name"):e["venue_address"]=e["venue_name"]
    if len(result)>500:raise ValueError("source_record_limit")
    return result
