"""Direct first-party Save Our Shores community program calendar (TEC REST).

Preserve only original publisher events with owner-verified event-specific
numbered streets. Corcoran's original registration corroborates a numbered
beach access address; never geocode an ambiguous route/plus-code.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from roomquest.event_description import description
from roomquest.mapsee_adapter import record
from roomquest.publisher_evidence import attach

KEY = "save_our_shores_santa_cruz_ca"
FEED = "https://saveourshores.org/wp-json/tribe/events/v1/events"
QGIV = "https://secure.qgiv.com/for/voevent/event/corcoranlagoonbeachcleanup/"
SOURCES = {KEY: (FEED, "json", "wordpress")}
ALLOWED_HOSTS = {KEY: ("saveourshores.org", "secure.qgiv.com")}
ZONE = "America/Los_Angeles"
MAX_RECORDS = 30
MAX_DESCRIPTION = 13000
MAX_JSON = 650000
TITLE_CORCORAN = "Beach Cleanup @ Corcoran Lagoon Beach"
CORCORAN_ADDRESS = "112 20th Ave, Santa Cruz, CA 95062"
SOURCE_HOST = "saveourshores.org"
LOCATION_CITIES = {"santa cruz", "aptos", "capitola", "soquel", "watsonville", "davenport", "felton"}
ADDR = re.compile(r"^\d{1,6}\s+[A-Za-z0-9][A-Za-z0-9 .#'/-]{3,110}$")
PHOTO_EXT = re.compile(r"\.(?:jpe?g|png|webp)$", re.I)


def event_url(value):
    if not isinstance(value, str) or len(value) > 400:
        return False
    try:
        u = urlsplit(value)
        return (u.scheme == "https" and u.hostname == SOURCE_HOST and
                u.port in (None,443) and u.username is None and u.password is None
                and not u.query and not u.fragment
                and re.fullmatch(r"/event/[a-z0-9-]+/",u.path) is not None)
    except ValueError:
        return False


def photo_url(value):
    if not isinstance(value, str) or len(value)>1200:
        return None
    try:
        u=urlsplit(value)
        if (u.scheme == "https" and u.hostname == SOURCE_HOST
            and u.port in (None,443) and not u.username and not u.password
            and not u.query and not u.fragment
            and u.path.startswith("/wp-content/uploads/")
            and PHOTO_EXT.search(u.path) and ".." not in u.path.split("/")):
            return value
    except ValueError:
        pass
    return None


def _registration_street(fetch):
    raw=fetch(QGIV,"text/html")
    if not isinstance(raw,str) or not 100 <= len(raw) <= 250000:
        raise ValueError("save_our_shores_registration_unavailable")
    txt=BeautifulSoup(raw,"html.parser").get_text(" ",strip=True)
    # Verify owner event-specific original registration's address and same
    # day/time, not merely a numbered address somewhere on the vendor site.
    if not all(x in txt for x in ("Corcoran Lagoon Beach","112 20th Ave",
                                   "Santa Cruz, California 95062",
                                   "Saturday, 12/12/2026",
                                   "9:00am PST","11:00am PST")):
        raise ValueError("save_our_shores_registration_street_unverified")
    return CORCORAN_ADDRESS


def _utc_check(e, key, local):
    declared=e.get(key)
    if not isinstance(declared,str):
        raise ValueError("save_our_shores_utc_absent")
    if local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")!=declared:
        raise ValueError("save_our_shores_clock_disagreement")


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key")!=KEY
            or (source.get("feed_url"),source.get("kind"),
                source.get("platform_adapter")) != SOURCES[KEY]
            or source.get("timezone")!=ZONE):
        raise ValueError("save_our_shores_source_identity_mismatch")
    raw=fetch(FEED,"application/json")
    if not isinstance(raw,str) or not 20<=len(raw)<=MAX_JSON:
        raise ValueError("save_our_shores_json_invalid")
    try:
        data=json.loads(raw)
    except (TypeError,ValueError) as exc:
        raise ValueError("save_our_shores_json_invalid") from exc
    events=data.get("events") if isinstance(data,dict) else None
    if (not isinstance(events,list) or len(events)>MAX_RECORDS
        or data.get("total_pages") not in (None,1)):
        raise ValueError("save_our_shores_pagination_or_records_invalid")
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    zone=ZoneInfo(ZONE)
    result=[]
    seen=set()
    for e in events:
        if not isinstance(e,dict) or e.get("status")!="publish" or e.get("all_day"):
            continue
        if e.get("timezone")!=ZONE or not event_url(e.get("url")):
            continue
        organizers=e.get("organizer")
        if not (isinstance(organizers,list) and
                any(isinstance(o,dict) and o.get("organizer")=="Save Our Shores"
                    for o in organizers)):
            continue
        event_id=e.get("id")
        if not isinstance(event_id,int) or event_id<1:
            continue
        try:
            start=datetime.strptime(e["start_date"],"%Y-%m-%d %H:%M:%S").replace(tzinfo=zone)
            end=datetime.strptime(e["end_date"],"%Y-%m-%d %H:%M:%S").replace(tzinfo=zone)
        except (KeyError,ValueError,TypeError) as exc:
            raise ValueError("save_our_shores_clock_invalid") from exc
        _utc_check(e,"utc_start_date",start)
        _utc_check(e,"utc_end_date",end)
        if not (end>start and end-start<=timedelta(hours=12)):
            raise ValueError("save_our_shores_duration_invalid")
        if not now-timedelta(hours=3)<=start.astimezone(timezone.utc)<=now+timedelta(days=60):
            continue
        venue=e.get("venue") or {}
        if (not isinstance(venue,dict) or venue.get("state")!="CA"
                or str(venue.get("city") or "").casefold() not in LOCATION_CITIES
                or not venue.get("venue")):
            continue
        city=venue["city"].strip()
        venue_name=str(venue["venue"]).strip()
        address=str(venue.get("address") or "").strip()
        zip_code=str(venue.get("zip") or "").strip()
        if not re.fullmatch(r"\d{5}",zip_code):
            continue
        if (event_id==26706 and e.get("title")==TITLE_CORCORAN
                and address.casefold()=="20th ave" and city.casefold()=="santa cruz"
                and zip_code=="95062"
                and QGIV in str(e.get("description") or "")):
            street=_registration_street(fetch)
            provenance="original_publisher_and_original_event_registration_numbered_access"
            location_evidence=QGIV
        else:
            if not ADDR.fullmatch(address):
                # No invented street for Scott Creek's plus-code, trails,
                # route-only or venue-name-only entries.
                continue
            street=f"{address}, {city}, CA {zip_code}"
            provenance="first_party_event_specific_tec_venue_street"
            location_evidence=e["url"]
        body_raw=e.get("description")
        if not isinstance(body_raw,str) or len(body_raw)>35000:
            continue
        body=description(BeautifulSoup(body_raw,"html.parser").get_text("\n",strip=True),
                         limit=MAX_DESCRIPTION)
        if not body or not 120<=len(body)<=MAX_DESCRIPTION:
            continue
        identity=f"sos-{event_id}-{start.strftime('%Y%m%dT%H%M')}"
        if identity in seen:
            raise ValueError("save_our_shores_duplicate_occurrence")
        seen.add(identity)
        categories=e.get("categories") or []
        clues=[str(c["name"])[:80] for c in categories
               if isinstance(c,dict) and isinstance(c.get("name"),str)]
        row=record(e.get("title") or "",start.isoformat(),end.isoformat(),
                   venue_name,street,city,e["url"],identity,", ".join(clues),
                   None,None,ZONE,retain_until_end=True)
        if row is None:
            continue
        row.update(description=body, timezone=ZONE, publisher_categories=clues,
                   location_provenance=provenance,
                   location_evidence_url=location_evidence,
                   schedule_evidence_url=FEED)
        img=e.get("image") or {}
        candidate=photo_url(img.get("url")) if isinstance(img,dict) else None
        result.append(attach(row,KEY,candidate=candidate,evidence_url=e["url"]))
    if len(result)>MAX_RECORDS:
        raise ValueError("save_our_shores_record_limit")
    return result

