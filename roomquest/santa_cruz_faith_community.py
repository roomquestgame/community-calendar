"""First-party Faith Community Church local programs via original Squarespace events JSON.

Import only individually dated owner-authored community/family/volunteer programs,
not perpetual worship series, unspecified offsite camps, or recurrence inferred
from an event listing. Publisher street proof required on every event.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import json
import re

from bs4 import BeautifulSoup
from roomquest.event_description import description
from roomquest.mapsee_adapter import record
from roomquest.publisher_evidence import attach

KEY = "faith_community_santa_cruz_programs_ca"
URL = "https://www.santacruzfaith.org/events-1?format=json"
OWNER = "https://www.santacruzfaith.org/events-1"
HOST = "www.santacruzfaith.org"
SOURCES = {KEY: (URL, "json", "squarespace")}
ALLOWED_HOSTS = {KEY: (HOST, "santacruzfaith.org")}
ZONE = "America/Los_Angeles"
STREET = "115 S Morrissey Ave, Santa Cruz, CA 95062"
MAX_RECORDS = 20
MAX_JSON = 650000
MAX_OWNER = 950000
MAX_DESCRIPTION = 12000
CATEGORY_EVIDENCE = {
    "Grog Night @Youth Group": ("youth group, social games", ["Youth Group", "Games", "Social"]),
    "H.O.M.E. Donations": ("volunteer, homelessness outreach, clothing donations", ["Volunteer", "Donation Drive"]),
    "BLOOD DRIVE": ("blood donation, community service", ["Blood Donation", "Community Service"]),
    "Jingle Jam": ("family holiday gathering", ["Holiday", "Family Activities"]),
    "Diaper Drive Distribution": ("diaper donations, community support", ["Donation Drive", "Community Assistance"]),
    "Ladies Tea": ("social, tea, gathering", ["Social Gathering", "Tea"]),
    "Kokua Concert": ("live music, concert", ["Live Music", "Concert"]),
}
ALLOWED_TITLES = set(CATEGORY_EVIDENCE)
STREET_PATTERN = re.compile(r"\b115\s+S\.?\s+Morrissey\s+A(?:ve|venue)\b", re.I)
OWNER_ADDRESS = re.compile(r"115\s+S\.?\s+Morrissey\s+A(?:ve|venue)[,\s]+Santa\s+Cruz,\s*CA\s+95062", re.I)

def event_url(value):
    if not isinstance(value, str):
        return False
    p = urlsplit(value)
    return (p.scheme == "https" and p.hostname == HOST and p.port in (None,443)
            and not p.username and not p.password and not p.query and not p.fragment
            and bool(re.fullmatch(r"/events-1/[a-z0-9-]+", p.path)))

def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY
            or (source.get("feed_url"), source.get("kind"), source.get("platform_adapter")) != SOURCES[KEY]
            or source.get("timezone") != ZONE):
        raise ValueError("faith_source_identity_mismatch")
    owner_html = fetch(OWNER, "text/html")
    if not isinstance(owner_html,str) or not (100 <= len(owner_html) <= MAX_OWNER):
        raise ValueError("faith_owner_invalid")
    owner_text = BeautifulSoup(owner_html, "html.parser").get_text(" ", strip=True)
    if not OWNER_ADDRESS.search(owner_text):
        raise ValueError("faith_official_street_missing")
    raw = fetch(URL, "application/json")
    if not isinstance(raw,str) or not (100 <= len(raw) <= MAX_JSON):
        raise ValueError("faith_calendar_invalid")
    try:
        data = json.loads(raw)
    except (ValueError,TypeError) as exc:
        raise ValueError("faith_calendar_invalid") from exc
    if not isinstance(data,dict) or not isinstance(data.get("upcoming"),list):
        raise ValueError("faith_calendar_invalid")
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    out = []
    seen = set()
    for item in data["upcoming"][:100]:
        if not isinstance(item,dict):
            continue
        title = str(item.get("title") or "").strip()
        if title not in ALLOWED_TITLES:
            continue
        if item.get("recordType") != 12 or item.get("workflowState") != 1:
            continue
        ident = item.get("id")
        if not isinstance(ident,str) or not re.fullmatch(r"[0-9a-f]{24}", ident):
            raise ValueError("faith_event_identity_missing")
        url = "https://" + HOST + str(item.get("fullUrl") or "")
        if not event_url(url):
            raise ValueError("faith_event_url_invalid")
        if url in seen:
            continue
        seen.add(url)
        loc = item.get("location")
        if (not isinstance(loc,dict) or not STREET_PATTERN.search(str(loc.get("addressLine1") or ""))
                or "Santa Cruz" not in str(loc.get("addressLine2") or "")
                or "95062" not in str(loc.get("addressLine2") or "")
                or str(loc.get("addressCountry") or "").casefold() not in ("united states","usa")):
            raise ValueError("faith_event_street_missing")
        s_ms, e_ms = item.get("startDate"), item.get("endDate")
        if not isinstance(s_ms,(int,float)) or not isinstance(e_ms,(int,float)):
            raise ValueError("faith_event_time_missing")
        try:
            start = datetime.fromtimestamp(s_ms/1000,timezone.utc).replace(microsecond=0)
            end = datetime.fromtimestamp(e_ms/1000,timezone.utc).replace(microsecond=0)
        except (ValueError,OSError,OverflowError) as exc:
            raise ValueError("faith_event_time_invalid") from exc
        if not now_utc - timedelta(hours=3) <= start <= now_utc + timedelta(days=60):
            continue
        if not timedelta(minutes=30) <= end-start <= timedelta(hours=7):
            raise ValueError("faith_event_duration_invalid")
        local = start.astimezone(ZoneInfo(ZONE))
        if local.year != 2026:
            continue
        html = item.get("body")
        if not isinstance(html,str) or len(html)>100000:
            raise ValueError("faith_description_missing")
        narrative = description(BeautifulSoup(html,"html.parser").get_text(" ",strip=True),limit=MAX_DESCRIPTION)
        if not narrative or not 115 <= len(narrative) <= MAX_DESCRIPTION:
            raise ValueError("faith_description_missing")
        row = record(title,start.isoformat(),end.isoformat(),
                     str(loc.get("addressTitle") or "Faith Community Church").strip(),
                     STREET,"Santa Cruz",url,ident,CATEGORY_EVIDENCE[title][0],
                     None,None,ZONE,retain_until_end=True)
        if row is None:
            continue
        row.update(description=narrative,timezone=ZONE,
                   publisher_categories=CATEGORY_EVIDENCE[title][1],
                   location_provenance="owner_calendar_event_address_and_owner_footer",
                   location_evidence_url=OWNER,schedule_evidence_url=url)
        out.append(attach(row,KEY,evidence_url=url))
        if len(out)>MAX_RECORDS:
            raise ValueError("faith_record_limit")
    return out
