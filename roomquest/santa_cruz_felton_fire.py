"""Felton Fire original 2026 Santa's Shelves at the station, two publisher-dated occurrences."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit
from time import monotonic
import re
from bs4 import BeautifulSoup
from roomquest.mapsee_adapter import record

KEY = "felton_fire_santas_shelves_2026_ca"
EVENT = "https://feltonfire.com/santasshelves/"
CONTACT = "https://feltonfire.com/contact/"
SOURCES = {KEY: (EVENT, "html", "html")}
ALLOWED_HOSTS = {KEY: ("feltonfire.com",)}
ZONE = "America/Los_Angeles"
STREET = "131 Kirby Street, Felton, CA 95018"
VENUE = "Felton Fire Station"
TITLE = "Santa's Shelves Craft Faire"
MAX_RECORDS = 2
MAX_DESCRIPTION = 10000
DAYS = (21, 22)

def event_url(url):
    if not isinstance(url,str):
        return False
    parsed=urlsplit(url)
    return parsed.scheme=="https" and parsed.hostname=="feltonfire.com" and parsed.path=="/santasshelves/" and not (parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.port)

def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key")!=KEY or
        (source.get("feed_url"),source.get("kind"),source.get("platform_adapter"))!=SOURCES[KEY] or
        source.get("timezone")!=ZONE):
        raise ValueError("felton_fire_wrong_source")
    if deadline_at and monotonic()>=deadline_at:
        raise ValueError("felton_fire_deadline")
    html=fetch(EVENT,"text/html")
    soup=BeautifulSoup(html,"html.parser")
    sections=soup.select("section.bde-section-1657-104")
    if len(sections)!=1:
        raise ValueError("felton_fire_original_event_section_missing")
    desc=sections[0].get_text("\n",strip=True)
    plain=sections[0].get_text(" ",strip=True)
    if not (300 <= len(desc)<=MAX_DESCRIPTION and
            re.search(r"November\s+21\s*&\s*22,\s*2026\s*[·•]\s*10\s*AM\s*[–-]\s*4\s*PM",plain) and
            "Saturday, November 21 and Sunday, November 22, 2026" in plain and
            "Felton Fire Station" in plain and "Kirby & Gushee St" in plain and
            "Felton Fire Auxiliary" in plain and
            "Silent auction" in plain and "Bake sale" in plain):
        raise ValueError("felton_fire_original_schedule_or_narrative_changed")
    official=BeautifulSoup(fetch(CONTACT,"text/html"),"html.parser").get_text(" ",strip=True)
    if not re.search(r"131\s+Kirby\s+Street,?\s*Felton,?\s*CA\s*95018",official,re.I):
        raise ValueError("felton_fire_official_station_street_missing")
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("felton_fire_naive_clock")
    output=[]
    for day in DAYS:
        local=datetime(2026,11,day,10,0,tzinfo=ZoneInfo(ZONE))
        end=local+timedelta(hours=6)
        start_utc=local.astimezone(timezone.utc)
        if not now-timedelta(hours=3)<=start_utc<=now+timedelta(days=60):
            continue
        key=f"felton-fire-santas-shelves-2026-11-{day:02d}"
        item=record(TITLE,start_utc.isoformat(),end.astimezone(timezone.utc).isoformat(),
                    VENUE,STREET,"Felton",EVENT,key,"Holiday market, Arts, Community",
                    None,None,ZONE,retain_until_end=True)
        if not item:
            raise ValueError("felton_fire_original_occurrence_invalid")
        item.update(description=desc,timezone=ZONE,
                    publisher_categories=["Handmade Gifts","Craft Market","Community Fundraiser"],
                    location_provenance="original_santas_shelves_station_and_official_fire_contact",
                    location_evidence_url=CONTACT,schedule_evidence_url=EVENT)
        from roomquest.publisher_evidence import attach
        output.append(attach(item,KEY,evidence_url=EVENT))
    return output
