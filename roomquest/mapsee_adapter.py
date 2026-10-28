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
from pathlib import Path
import re
from time import monotonic
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

MAX_RECORDS = 500
MAX_PAGES = 5
SUPPORTED_TYPES = {"ics", "jsonld", "tribe", "localist", "squarespace", "opendata"}


@lru_cache(maxsize=1)
def profiles():
    path = Path(__file__).with_name("mapsee_sources.json")
    return {x["source_key"]: x for x in json.loads(path.read_text())["sources"]}


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


def record(title, start, end, venue, street, city, url, identity, category="", lat=None, lng=None, tz=None):
    from roomquest.preview_worker import _preview
    if not plain(title):raise ValueError("event_title_missing")
    if not start:raise ValueError("event_time_missing")
    begins=timestamp(start,tz);ends=timestamp(end,tz)
    if ends and ends<begins:raise ValueError("invalid_event_end")
    if not re.search(r"\b[0-9]{1,6}\s+[A-Za-z]",plain(street)) or not re.search(r",[^,]+,\s*[A-Z]{2}\b",plain(street)):
        lat=lng=None
    if str(lat) in {"0","0.0"} and str(lng) in {"0","0.0"}:lat=lng=None
    out = _preview(plain(title), begins, ends, plain(venue) or plain(street),
                   lat,lng,url,str(identity or ""),plain(category),plain(street),plain(city),allow_ongoing=True)
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


def parse_tribe(data):
    # The same upstream Tribe parser used by Udell, with UTC dates and complete
    # event addresses retained rather than inferred from the publisher's city.
    from scrapers.lib.tribe_events import TribeEventsScraper
    parser=TribeEventsScraper();out=[]
    if not isinstance(data,dict) or not isinstance(data.get("events"),list):
        raise ValueError("unsupported_wordpress_payload")
    for e in data["events"]:
        if not isinstance(e,dict):raise ValueError("unsupported_wordpress_payload")
        if e.get("status") in {"cancelled","canceled","trash"}:continue
        tz=e.get("timezone"); start=e.get("utc_start_date");end=e.get("utc_end_date")
        if start:start=timestamp(start,"UTC").isoformat()
        if end:end=timestamp(end,"UTC").isoformat()
        if not start:
            # Reuse the existing parser only with explicit publisher timezone.
            if not tz:raise ValueError("timezone_unresolved")
            parsed=parser._parse_event(e,ZoneInfo(tz))
            if not parsed:continue
            start=parsed["dtstart"].isoformat();end=parsed["dtend"].isoformat() if parsed.get("dtend") else None
        venue=e.get("venue") or {}; venue=venue if isinstance(venue,dict) else {}
        street=address({"street":venue.get("address"),"city":venue.get("city"),"state":venue.get("state") or venue.get("province"),"zip":venue.get("zip")})
        r=record(e.get("title"),start,end,venue.get("venue"),street,venue.get("city"),e.get("url"),e.get("id"),
                 ", ".join(x.get("name","") for x in e.get("categories",[]) if isinstance(x,dict)),venue.get("geo_lat"),venue.get("geo_lng"),tz)
        if r:out.append(r)
    return out


def parse_jsonld(payload,base=""):
    from scrapers.lib.jsonld import extract_jsonld_blocks, extract_events_from_blocks
    from urllib.parse import urljoin
    blocks=extract_jsonld_blocks(payload)
    if not blocks:raise ValueError("unsupported_jsonld_payload")
    events=extract_events_from_blocks(blocks);out=[]
    if not events and not re.search(r"\bno (?:upcoming )?events(?: found| scheduled)?\b",payload,re.I):
        raise ValueError("unsupported_jsonld_event_shape")
    for e in events:
        if str(e.get("eventStatus","")).endswith(("EventCancelled","EventPostponed")):continue
        v=e.get("location") or {};v=next((x for x in v if isinstance(x,dict)),{}) if isinstance(v,list) else v
        if not isinstance(v,dict) or v.get("@type")=="VirtualLocation":continue
        a=v.get("address") or {};g=v.get("geo") or {};g=g if isinstance(g,dict) else {}
        r=record(e.get("name"),e.get("startDate"),e.get("endDate"),v.get("name"),address(a),a.get("addressLocality","") if isinstance(a,dict) else "",
                 urljoin(base,e.get("url") or e.get("@id") or ""),e.get("@id") or e.get("url"),e.get("keywords",""),g.get("latitude"),g.get("longitude"))
        if r:out.append(r)
    return out


def parse_squarespace(data,base):
    if isinstance(data,dict) and isinstance(data.get("upcoming"),list):
        data={**data,"items":data["upcoming"]}
    if not isinstance(data,dict) or not isinstance(data.get("items"),list):
        raise ValueError("unsupported_squarespace_payload")
    from urllib.parse import urljoin
    out=[]
    for e in data["items"]:
        v=e.get("location") or {};v=v if isinstance(v,dict) else {}
        street=", ".join(plain(v[k]) for k in ("addressLine1","addressLine2") if v.get(k))
        r=record(e.get("title"),e.get("startDate"),e.get("endDate"),v.get("addressTitle"),street,"",urljoin(base,e.get("fullUrl") or e.get("urlId") or ""),
                 e.get("id"),", ".join(str(x) for x in e.get("categories",[])),v.get("mapLat"),v.get("mapLng"))
        if r:out.append(r)
    return out


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


def parse_ics(payload,source):
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
    result=parse_ics_preview(payload,allow_ongoing=True,include_images=False)
    if not result and unsupported:raise ValueError(unsupported[0])
    # A feed URL is an actual publisher link when its VEVENT omits URL. Never
    # fabricate a detail URL, venue, publisher host, description or image.
    categories={str(e.get("UID", "")): ", ".join(c.to_ical().decode("utf-8",errors="replace") for c in (e.get("CATEGORIES") if isinstance(e.get("CATEGORIES"),list) else [e.get("CATEGORIES")]) if c is not None) for e in events}
    for e in result:
        e.pop("image_url",None)
        e["category"]=categories.get(e["id"].split("__",1)[0],"")
        if not e.get("event_url"):e["event_url"]=source["url"]
        if not e.get("venue_address") and e.get("venue_name"):e["venue_address"]=e["venue_name"]
    return result


def collect(source,profile,fetch):
    """At most five requests/500 facts; truncation is a failure, never healthy empty."""
    kind=profile["type"];base=source["feed_url"];config=profile.get("config") or {}
    if kind not in SUPPORTED_TYPES:raise ValueError("unsupported_mapsee_adapter")
    deadline=monotonic()+35;records=[]
    for page in range(1,MAX_PAGES+1):
        if monotonic()>deadline:raise ValueError("collection_deadline")
        now=datetime.now(timezone.utc)
        if kind=="localist":url=base.rstrip("/")+"/api/2/events?"+urlencode({"pp":100,"page":page,"days":60,"distinct":"true"})
        elif kind=="tribe":url=base.rstrip("/")+"/wp-json/tribe/events/v1/events?"+urlencode({"per_page":100,"page":page,"start_date":now.date().isoformat(),"end_date":(now+timedelta(days=60)).date().isoformat()})
        elif kind=="squarespace":url=base+("&" if "?" in base else "?")+"format=json"
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
        if kind=="jsonld":records=parse_jsonld(payload,base);break
        data=json.loads(payload)
        if kind=="localist":
            records.extend(parse_localist(data));last=page>=int((data.get("page") or {}).get("total",1))
        elif kind=="tribe":
            records.extend(parse_tribe(data));last=not data.get("next_rest_url") and page>=int(data.get("total_pages",1))
        elif kind=="squarespace":
            records.extend(parse_squarespace(data,base));last=not (data.get("pagination") or {}).get("nextPage")
            if not last:raise ValueError("pagination_requires_cursor")
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
