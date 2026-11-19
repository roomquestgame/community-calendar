"""Exact-source Hall County, Georgia CivicPlus iCalendar public meetings.

Only official VEVENT times, unique EID event links and event-owned physical
street addresses are accepted. These records are Civic, not tourism events.
Publisher descriptions/images are optional; no synthetic facts or artwork.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from time import monotonic
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo
import logging
import re

from icalendar import Calendar
from roomquest.mapsee_adapter import plain, record
from roomquest.event_description import description

HOST = "www.hallcounty.org"
ZONE = "America/New_York"
MAX_RECORDS = 200
MAX_DESCRIPTION = 12000
WINDOW_DAYS = 60
COMMISSION = "hall_ga_commissioners_ical"
TAX = "hall_ga_tax_assessors_ical"
OUTREACH = "hall_ga_planning_outreach_ical"
CATEGORIES = {COMMISSION: 63, TAX: 71, OUTREACH: 74}
SOURCES = {
    key: (f"https://{HOST}/common/modules/iCalendar/iCalendar.aspx?catID={cid}&feed=calendar",
          "ical", "ical") for key, cid in CATEGORIES.items()
}
ALLOWED_HOSTS = {key: (HOST,) for key in SOURCES}
VENUES = {
    "Hall County Government Center - 2875 Browns Bridge Road Gainesville GA 30504":
      ("Hall County Government Center", "2875 Browns Bridge Road, Gainesville, GA 30504"),
    "Free Chapel - 3001 McEver Rd Gainesville GA 30504":
      ("Free Chapel", "3001 McEver Rd, Gainesville, GA 30504"),
}
LOGGER = logging.getLogger(__name__)
OFFICIAL_EVENT_LINK = re.compile(r"https://www[.]hallcounty[.]org/calendar[.]aspx\?EID=[0-9]{3,9}", re.I)
TITLE_CANCELLED = re.compile(r"\b(?:cancelled|canceled|postponed|private|invitation only)\b", re.I)


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value)>250:
        return False
    u = urlsplit(value)
    if (u.scheme != "https" or u.hostname != HOST or u.path.lower() != "/calendar.aspx"
        or u.username or u.password or u.fragment):
        return False
    q = parse_qsl(u.query, keep_blank_values=True)
    return bool(len(q) == 1 and q[0][0] == "EID" and re.fullmatch(r"[0-9]{3,9}",q[0][1]))


def _hold(key, uid, why):
    LOGGER.info("hall_ga_civic_hold source=%s uid=%r reason=%s",key,str(uid)[:75],why)


def _location(text):
    # Retain only two verified physical locations explicitly stated by an
    # individual meeting; publisher feed may later introduce new sites.
    clean=plain(text)
    return VENUES.get(clean)


def collect(source, fetch, *, deadline_at=None, now=None):
    key = source.get("source_key")
    if (key not in SOURCES or
        (source.get("feed_url"),source.get("kind"),source.get("platform_adapter")) != SOURCES[key]
        or source.get("timezone") != ZONE):
        raise ValueError("unregistered_hall_ga_civic_source")
    deadline = min(monotonic()+44, deadline_at or float("inf"))
    raw = fetch(SOURCES[key][0], "text/calendar")
    if monotonic() > deadline:
        raise ValueError("publisher_collection_deadline")
    if isinstance(raw, str):
        raw=raw.encode("utf-8")
    if not isinstance(raw, bytes) or len(raw)>600_000:
        raise ValueError("invalid_hall_civic_ical")
    try:
        cal=Calendar.from_ical(raw)
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("invalid_hall_civic_ical") from exc
    now = now or datetime.now(timezone.utc)
    out={}
    events=cal.walk("VEVENT")
    if len(events)>MAX_RECORDS:
        raise ValueError("publisher_record_limit")
    for event in events:
        uid=plain(event.get("UID"))
        if not re.fullmatch(r"[0-9]{3,9}",uid or ""):
            _hold(key,uid,"uid_unverified");continue
        if str(event.get("STATUS","")).upper() in {"CANCELLED","CANCELED"}:
            continue
        title=plain(event.get("SUMMARY"))
        if not title or TITLE_CANCELLED.search(title):
            continue
        if event.get("RRULE") or event.get("RDATE"):
            _hold(key,uid,"unexpanded_recurrence");continue
        if not event.get("DTSTART") or not event.get("DTEND"):
            _hold(key,uid,"missing_time");continue
        if str(event["DTSTART"].params.get("TZID","")) != ZONE:
            _hold(key,uid,"timezone_not_verified");continue
        if str(event["DTEND"].params.get("TZID","")) != ZONE:
            _hold(key,uid,"end_timezone_not_verified");continue
        try:
            start=event.decoded("DTSTART")
            end=event.decoded("DTEND")
        except (ValueError,TypeError,KeyError):
            _hold(key,uid,"invalid_date");continue
        if (not isinstance(start,datetime) or not isinstance(end,datetime)
           or start.tzinfo is None or end.tzinfo is None
           or start.astimezone(ZoneInfo(ZONE)).replace(tzinfo=None) != start.replace(tzinfo=None)
           or end.astimezone(ZoneInfo(ZONE)).replace(tzinfo=None) != end.replace(tzinfo=None)
           or end<=start or end-start>timedelta(hours=12)):
            _hold(key,uid,"invalid_public_schedule");continue
        if not (now-timedelta(hours=24)<=start.astimezone(timezone.utc)<=now+timedelta(days=WINDOW_DAYS)):
            continue
        venue=_location(event.get("LOCATION"))
        if venue is None:
            _hold(key,uid,"publisher_street_unverified");continue
        desc_raw=str(event.get("DESCRIPTION",""))
        found=OFFICIAL_EVENT_LINK.findall(desc_raw)
        links=list(dict.fromkeys(found))
        if len(links)!=1 or not event_url(key,links[0]) or parse_qsl(urlsplit(links[0]).query)!=[("EID",uid)]:
            _hold(key,uid,"publisher_event_link_unverified");continue
        url=links[0]
        clean_description=description(desc_raw.replace(url,""),
                                      limit=max(len(desc_raw)+1,MAX_DESCRIPTION+1))
        if len(clean_description)>MAX_DESCRIPTION:
            _hold(key,uid,"publisher_description_limit");continue
        row=record(title,start.astimezone(timezone.utc).isoformat(),
                   end.astimezone(timezone.utc).isoformat(),
                   venue[0],venue[1],"Gainesville",url,uid,"civic",None,None,ZONE,
                   retain_until_end=True)
        if row is None:
            continue
        row.update(description=clean_description,timezone=ZONE,
                   publisher_categories=["civic","public meeting"],
                   location_provenance="publisher_vevent_explicit_street",
                   civic={"version":1,
                          "kind":"meeting",
                          "topic":"government",
                          "jurisdiction_id":"us-ga-hall-county",
                          "applicability":"jurisdiction",
                          "time_precision":"timed",
                          "timezone":ZONE,
                          "source_url":url,
                          "verified_at":datetime.now(timezone.utc).isoformat(),
                          "valid_until":end.astimezone(timezone.utc).isoformat()})
        from roomquest.publisher_evidence import attach
        row=attach(row,key,facts={"jurisdiction_id":"us-ga-hall-county",
                                   "civic_kind":"meeting","civic_topic":"government"})
        occ=(uid,row["starts_at"])
        if occ in out and out[occ] != row:
            raise ValueError("conflicting_hall_civic_occurrence")
        out[occ]=row
    return sorted(out.values(),key=lambda row:(row["starts_at"],row["id"]))
