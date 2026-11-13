"""Factual Mapsee catalog intake through RoomQuest's bounded Python transport.

Mapsee's MIT adapters are an extraction reference. Publisher defaults, generated
hours, market schedules, geocoders, descriptions and images are deliberately not
part of this adapter. All network I/O goes through the existing SSRF gate.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
import html
import json
import logging
from pathlib import Path
import re
from time import monotonic
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

MAX_RECORDS = 500
MAX_PAGES = 5
SUPPORTED_TYPES = {"ics", "jsonld", "tribe", "localist", "squarespace", "opendata"}


@lru_cache(maxsize=1)
def profiles():
    base = Path(__file__).with_name("mapsee_sources.json")
    result = {row["source_key"]: row for row in json.loads(base.read_text())["sources"]}
    supplemental = base.with_name("richmond_batch_one_sources.json")
    for row in json.loads(supplemental.read_text())["sources"]:
        key = row["source_key"]
        existing = result.get(key)
        if existing and row.get("replaces_url") != existing["url"]:
            raise ValueError("conflicting_mapsee_source_profile")
        if not existing and row.get("replaces_url"):
            raise ValueError("missing_mapsee_source_profile")
        result[key] = row
    return result


def plain(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", str(value or "")))).strip()


def timestamp(value, tz=None):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, timezone.utc)
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        if not tz:
            raise ValueError("timezone_unresolved")
        result = result.replace(tzinfo=ZoneInfo(tz))
        # Ambiguous/nonexistent wall times cannot be assigned an invented offset.
        if result.astimezone(timezone.utc).astimezone(result.tzinfo).replace(tzinfo=None) != result.replace(tzinfo=None):
            raise ValueError("timezone_nonexistent")
        if result.utcoffset() != result.replace(fold=1).utcoffset():
            raise ValueError("timezone_ambiguous")
    return result


def address(value):
    """Join only the event's own complete PostalAddress, never catalog suffixes."""
    if isinstance(value, str):
        return plain(value)
    if not isinstance(value, dict):
        return ""
    region = value.get("addressRegion") or value.get("state") or value.get("region")
    return ", ".join(plain(v) for v in (value.get("streetAddress") or value.get("street"),
                       value.get("addressLocality") or value.get("city"), region,
                       value.get("postalCode") or value.get("zip")) if v)


def record(title, start, end, venue, street, city, url, identity, category="", lat=None, lng=None, tz=None, *, publisher_geo=False, retain_until_end=False):
    from roomquest.preview_worker import _preview
    if not plain(title):raise ValueError("event_title_missing")
    if not start:raise ValueError("event_time_missing")
    begins=timestamp(start,tz);ends=timestamp(end,tz)
    if ends and ends<begins:raise ValueError("invalid_event_end")
    if not publisher_geo and (not re.search(r"\b[0-9]{1,6}\s+[A-Za-z]",plain(street)) or not re.search(r",[^,]+,\s*[A-Z]{2}\b",plain(street))):
        lat=lng=None
    if str(lat) in {"0","0.0"} and str(lng) in {"0","0.0"}:lat=lng=None
    out = _preview(plain(title), begins, ends, plain(venue) or plain(street),
                   lat,lng,url,str(identity or ""),plain(category),plain(street),plain(city),
                   allow_ongoing=True, retain_until_end=retain_until_end)
    if out is not None:
        out.pop("image_url",None)
    if out is not None and not out.get("event_url"):
        raise ValueError("event_link_missing")
    return out


def parse_localist(data):
    if not isinstance(data, dict) or not isinstance(data.get("events"),list):
        raise ValueError("unsupported_localist_payload")
    out=[]
    for wrapper in data["events"]:
        if not isinstance(wrapper,dict) or not isinstance(wrapper.get("event"),dict):
            raise ValueError("unsupported_localist_payload")
        event=wrapper.get("event",{})
        if event.get("status") in {"canceled","cancelled","postponed"} or event.get("experience")=="virtual":
            continue
        geo=event.get("geo") or {}; street=event.get("address") or ""
        instances=event.get("event_instances")
        if not isinstance(instances,list) or not instances:raise ValueError("event_occurrences_missing")
        for instance in instances:
            if not isinstance(instance,dict) or not isinstance(instance.get("event_instance"),dict):
                raise ValueError("unsupported_localist_occurrence")
            v=instance.get("event_instance",{})
            venue=", ".join(plain(x) for x in (event.get("location_name"),event.get("room_number")) if x)
            r=record(event.get("title"),v.get("start"),v.get("end"),venue,street,
                "",event.get("localist_url") or event.get("url"),event.get("id"),
                ", ".join(x.get("name","") for x in (event.get("filters") or {}).get("event_types",[]) if isinstance(x,dict)),
                geo.get("latitude"),geo.get("longitude"),event.get("timezone"))
            if r:out.append(r)
    return out


TRIBE_ZERO_OFFSET = re.compile(r"(?:UTC|GMT|Etc/(?:UTC|GMT)|UTC[+-]0{1,2}(?::?00)?)", re.I)

# Reviewed publishers whose WordPress site zone was left at the "UTC+0" default,
# so Tribe's local and utc_* dates both carry the venue's wall clock. Each zone
# was confirmed from the publisher's own venue addresses (2026-11-09); only the
# listed sources are reinterpreted, every other zero-offset event is held.
TRIBE_UTC_DEFAULT_ZONES = {
    "municipal_mapsee_e4f0600735a6ef7191c25f5f": "America/New_York",  # MacDill AFB Library, FL
    "municipal_mapsee_42223f3cfcfe33208ed63601": "America/New_York",  # NC Museum of Art, Raleigh
    "municipal_mapsee_6b6a983c5d1ea8a1fe3fede2": "America/Chicago",   # BUILD, Chicago IL
    "municipal_mapsee_5456f7396725fdc4a0bbda86": "America/New_York",  # Community Music Center of Boston
    "municipal_mapsee_96de39930db49d669fa567c3": "America/New_York",  # Hardeeville Public Library, SC
    "municipal_mapsee_eb47acc3ae4c308074d03f5e": "America/New_York",  # The PARC at Tysons (Fairfax, VA)
    "municipal_mapsee_f63b83aa136931e0a77618b3": "America/New_York",  # Main Street Takoma, MD/DC
}


def tribe_timezone(value):
    """WordPress permits fixed UTC offsets as well as IANA timezone names."""
    match = re.fullmatch(r"UTC([+-])(\d{1,2})(?:(?:\.(\d+))|(?::(\d{2})))?", str(value or ""))
    if not match:
        return ZoneInfo(value), value
    sign, hours, fraction, minutes = match.groups()
    offset = int(hours) * 60 + (round(float('0.' + fraction) * 60) if fraction else int(minutes or 0))
    if offset > 14 * 60 or (minutes and int(minutes) >= 60):
        raise ValueError('timezone_unresolved')
    offset *= 1 if sign == '+' else -1
    # UTC timestamps remain authoritative. Fractional offsets have no generic
    # IANA identifier, so normalize their instants and display zone to UTC.
    name = 'UTC' if offset == 0 or offset % 60 else 'Etc/GMT' + ('-' if offset > 0 else '+') + str(abs(offset) // 60)
    return timezone(timedelta(minutes=offset)), name


def parse_tribe(data, *, strict_public=False, retain_description=False, utc_default_zone=None):
    # The same upstream Tribe parser used by Udell, with UTC dates and complete
    # event addresses retained rather than inferred from the publisher's city.
    from scrapers.lib.tribe_events import TribeEventsScraper
    parser=TribeEventsScraper();out=[]
    if not isinstance(data,dict) or not isinstance(data.get("events"),list):
        raise ValueError("unsupported_wordpress_payload")
    for e in data["events"]:
        if not isinstance(e,dict):raise ValueError("unsupported_wordpress_payload")
        if strict_public and e.get("status") != "publish":continue
        if e.get("status") in {"cancelled","canceled","trash"}:continue
        if strict_public and e.get("event_status") in ("cancelled", "canceled", "postponed"):continue
        if strict_public and any(e.get(k) in (True, 1, "1", "true") for k in
               ("hide_from_listings", "is_virtual", "virtual", "all_day")):continue
        tz=e.get("timezone")
        reinterpret=False
        # WordPress defaults an event zone to "UTC+0"; its utc_* dates then repeat
        # the local wall clock (9:30 AM local -> 09:30Z). Only a reviewed source
        # zone may reinterpret that wall clock; otherwise hold, never guess a zone.
        if tz and TRIBE_ZERO_OFFSET.fullmatch(str(tz).strip()):
            if not utc_default_zone:
                logger.warning("tribe_record_withheld id=%s reason=publisher_timezone_utc_default", str(e.get("id",""))[:180])
                continue
            tz=utc_default_zone;reinterpret=True
        zone, tz_name=tribe_timezone(tz) if tz else (None, None)
        if reinterpret:
            # Local wall clock in the reviewed zone; strict helper rejects DST gaps/overlaps.
            start=timestamp(e.get("start_date") or e.get("utc_start_date"),tz)
            end=e.get("end_date") or e.get("utc_end_date")
            start=start.astimezone(timezone.utc).isoformat() if start else None
            end=timestamp(end,tz).astimezone(timezone.utc).isoformat() if end else None
        else:
            start=e.get("utc_start_date");end=e.get("utc_end_date")
            if start:start=timestamp(start,"UTC").isoformat()
            if end:end=timestamp(end,"UTC").isoformat()
        if not start:
            # Reuse the existing parser only with explicit publisher timezone.
            if not tz:raise ValueError("timezone_unresolved")
            parsed=parser._parse_event(e,zone)
            if not parsed:continue
            start=parsed["dtstart"].isoformat();end=parsed["dtend"].isoformat() if parsed.get("dtend") else None
        venue=e.get("venue") or {}; venue=venue if isinstance(venue,dict) else {}
        if strict_public and re.search(r"\b(zoom|online|virtual)\b", plain(venue.get("venue")), re.I):continue
        street=address({"street":venue.get("address"),"city":venue.get("city"),"state":venue.get("state") or venue.get("stateprovince") or venue.get("province"),"zip":venue.get("zip")})
        r=record(e.get("title"),start,end,venue.get("venue"),street,venue.get("city"),e.get("url"),e.get("id"),
                 ", ".join(x.get("name","") for x in e.get("categories",[]) if isinstance(x,dict)),venue.get("geo_lat"),venue.get("geo_lng"),tz, publisher_geo=strict_public)
        if r:
            if retain_description:
                from roomquest.event_description import description
                value = e.get("description")
                if value is not None and not isinstance(value, str):
                    raise ValueError("invalid_wordpress_description")
                # Existing JSON publication contract is 2,000 characters.
                # Missing publisher prose stays empty; never copy title/category.
                r["description"] = description(value)
            if strict_public and tz:
                r["timezone"] = tz_name
            out.append(r)
    return out


def parse_jsonld(payload,base=""):
    from roomquest.jsonld_adapter import parse
    return parse(payload, base)


def parse_squarespace(data,base):
    from roomquest.squarespace import parse_registered
    return parse_registered(data, base)


def parse_open_data(data,config):
    if not isinstance(data,list):raise ValueError("unsupported_open_data_payload")
    mapping=config.get("map") or {};out=[]
    if not all(k in mapping for k in ("title","start")):raise ValueError("unsupported_open_data_mapping")
    for e in data:
        get=lambda k:e.get(mapping[k]) if k in mapping else None
        lat,lng=get("lat"),get("lon")
        geo=get("geo")
        if isinstance(geo,dict):lat,lng=geo.get("latitude"),geo.get("longitude")
        point=get("latlon")
        if isinstance(point,str):
            match=re.fullmatch(r"\s*([-+0-9.]+)\s*,\s*([-+0-9.]+)\s*",point)
            if match:lat,lng=match.groups()
            match=re.fullmatch(r"\s*POINT\s*\(\s*([-+0-9.]+)\s+([-+0-9.]+)\s*\)\s*",point,re.I)
            if match:lng,lat=match.groups()
        # Keep the dataset's actual URL if a public structured-data record has
        # no individual link. Never synthesize a publisher/event detail path.
        r=record(get("title"),get("start"),get("end"),get("venue"),get("address"),get("city"),get("url") or config.get("publisher_url"),get("id"),get("category"),lat,lng,config.get("timezone"))
        if r:out.append(r)
    return out


def parse_ics(payload, source):
    from roomquest.ics_adapter import parse
    return parse(payload, source)


def collect(source,profile,fetch):
    """At most five requests/500 facts; truncation is a failure, never healthy empty."""
    if profile["type"] == "tribe":
        from roomquest.wordpress_adapter import collect as collect_wordpress
        return collect_wordpress(source, fetch)
    if profile["type"] == "squarespace":
        from roomquest.squarespace import collect as collect_squarespace
        return collect_squarespace(source, fetch)
    if profile["type"] == "jsonld":
        from roomquest.jsonld_adapter import collect as collect_jsonld
        return collect_jsonld(source, fetch)
    kind=profile["type"];base=source["feed_url"];config=profile.get("config") or {}
    if kind not in SUPPORTED_TYPES:raise ValueError("unsupported_mapsee_adapter")
    deadline=monotonic()+35;records=[]
    for page in range(1,MAX_PAGES+1):
        if monotonic()>deadline:raise ValueError("collection_deadline")
        now=datetime.now(timezone.utc)
        if kind=="localist":url=base.rstrip("/")+"/api/2/events?"+urlencode({"pp":100,"page":page,"days":60,"distinct":"true"})
        elif kind=="opendata":
            local_now=now.astimezone(ZoneInfo(config["timezone"])) if config.get("timezone") else now
            where=str(config.get("where") or "").replace("{now}",local_now.strftime("%Y-%m-%dT%H:%M:%S")).replace("{today}",local_now.date().isoformat())
            params={"$limit":500,"$offset":(page-1)*500}
            if where:params["$where"]=where
            if config.get("order"):params["$order"]=config["order"]
            url=base+("&" if "?" in base else "?")+urlencode(params)
        else:url=base
        payload=fetch(url,"text/calendar" if kind=="ics" else "application/json,text/html")
        if kind=="ics":records=parse_ics(payload,profile);break
        data=json.loads(payload)
        if kind=="localist":
            records.extend(parse_localist(data));last=page>=int((data.get("page") or {}).get("total",1))
        else:
            records.extend(parse_open_data(data,{**config,"publisher_url":base}));last=len(data)<500
        if len(records)>MAX_RECORDS:raise ValueError("source_record_limit")
        if last:break
        if page==MAX_PAGES:raise ValueError("pagination_limit")
    unique={}
    for r in records:
        key=(r.get("id") or r["title"],r["starts_at"])
        if key in unique and any(unique[key].get(k)!=r.get(k) for k in ("title","venue_name","venue_address","lat","lng")):
            raise ValueError("conflicting_event_occurrence")
        unique[key]=r
    if len(unique)>MAX_RECORDS:raise ValueError("source_record_limit")
    result=sorted(unique.values(),key=lambda e:(e["starts_at"],e["title"]))
    if result and not any(e.get("venue_name") or e.get("venue_address") for e in result):raise ValueError("venue_extraction_unavailable")
    return result

