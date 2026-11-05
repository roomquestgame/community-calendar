"""Shared bounded ICS validation; existing recurrence/VEVENT normalizer retained.

Legacy output fields and media stay intact to preserve venue-cache identity.
Mapsee URL/address fallbacks stay restricted to its existing catalog records.
"""
from datetime import datetime, timezone
import logging
import re
from urllib.parse import urlsplit, parse_qs

logger = logging.getLogger(__name__)


def civicplus_detail_url(description, identity, source_url):
    """Use an explicit same-publisher EID link; never synthesize from the UID."""
    origin = urlsplit(source_url)
    matches = []
    for candidate in re.findall(r'https://[^\s<>"\']+', description):
        candidate = candidate.rstrip('.,;)')
        parsed = urlsplit(candidate)
        if (parsed.scheme == 'https' and parsed.netloc.lower() == origin.netloc.lower()
                and not parsed.username and not parsed.password
                and parsed.path.lower() == '/calendar.aspx'
                and parse_qs(parsed.query) == {'EID': [identity]}):
            matches.append(candidate)
    return matches[0] if len(set(matches)) == 1 else None

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
            end = e.decoded('DTEND') if e.get('DTEND') else start
            if max(start, end) >= datetime.now(timezone.utc).date():
                unsupported.append("unsupported_all_day_time")
                logger.warning('ics_record_withheld source=%s uid=%s reason=unsupported_all_day_time',
                               source.get('source_key', ''), str(e.get('UID', ''))[:180])
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
    detail_urls = {}
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
        if include_description and source.get('source_key') == 'independence_ia_library_family':
            uid = str(event.get('UID', ''))
            detail_urls[uid] = civicplus_detail_url(str(event.get('DESCRIPTION', '')), uid, source['url'])

    for e in result:
        if include_description and source.get('source_key') == 'independence_ia_library_family':
            uid = e['id'].split('__', 1)[0]
            if not detail_urls.get(uid):
                raise ValueError('publisher_detail_link_missing')
            e['event_url'] = detail_urls[uid]
        if legacy and not include_description:
            continue
        e.pop("image_url",None)
        e["publisher_categories"]=categories.get(e["id"].split("__",1)[0], [])
        e["category"]=", ".join(e["publisher_categories"])[:80]
        if not e.get("event_url"):e["event_url"]=source["url"]
        if not e.get("venue_address") and e.get("venue_name"):e["venue_address"]=e["venue_name"]
    if len(result)>500:raise ValueError("source_record_limit")
    return result
