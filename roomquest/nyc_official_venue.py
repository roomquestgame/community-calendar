"""Independent official NYC facility evidence; never fetch the event-page proxy."""
from __future__ import annotations

import json
import re
from urllib.parse import urlencode

HOST = "data.cityofnewyork.us"
API = "https://" + HOST + "/resource/ji82-xba5.json"
VERSION = "nyc_official_venue_v1"
HOSTS = ("www.nyc.gov", "comptroller.nyc.gov", "portal.311.nyc.gov", "council.nyc.gov")
BOROUGHS = {"Bx": "Bronx", "Bk": "Brooklyn", "Mn": "Manhattan", "Qn": "Queens", "SI": "Staten Island"}
FIELDS = ("uid", "facname", "addressnum", "streetname", "boro", "city", "zipcode")
ROOM = re.compile(
    r"^(?:multi[- ]use room|dance room|gymnasium|fitness room|computer room|"
    r"arts and crafts room|golden age classroom|classroom|ballroom|rock climbing wall room)"
    r"[^,]{0,40}? in (.+(?:recreation center|play center|community center|field house))$", re.I)


class DirectoryConflict(ValueError):
    pass


def facility_name(claim):
    name = claim.get("venue_name")
    if not isinstance(name, str):
        return None
    if claim.get("raw_address") == name:
        match = ROOM.fullmatch(name)
        if match:
            return match.group(1)
    return name


def valid_scope(claim, scope):
    if not isinstance(scope, dict) or scope.get("scope_version") != VERSION:
        return False
    identity = claim.get("location_identity")
    if not isinstance(identity, dict):
        return False
    name = claim.get("venue_name")
    event = claim.get("event_url")
    facility = facility_name(claim)
    borough = BOROUGHS.get(identity.get("borough"))
    return bool(
        claim.get("provider") == "nyc_event_calendar"
        and identity.get("adapter") == "nyc_event_calendar"
        and identity.get("source_key") == "nyc_event_calendar_public"
        and isinstance(event, str) and event.startswith("https://www.nycgovparks.org/events/")
        and event == identity.get("event_url")
        and claim.get("publisher_name") == "NYC Gov"
        and name == identity.get("name") == scope.get("venue")
        and claim.get("raw_address") == identity.get("address")
        and isinstance(facility, str) and 3 <= len(facility) <= 120
        and scope.get("evidence_venue") == facility
        and borough and scope.get("locality") == borough
        and scope.get("country") == "US" and scope.get("region") == "NY"
        and isinstance(scope.get("hosts"), (list, tuple))
        and tuple(scope["hosts"]) == HOSTS
    )


def directory_url(name):
    # Escaped literal only; no caller-selected query, host or dataset.
    where = "upper(facname)='" + name.upper().replace("'", "''") + "'"
    return API + "?" + urlencode({"$select": ",".join(FIELDS), "$where": where, "$limit": "21"})


def address_candidate(claim, scope, rows):
    if not isinstance(rows, list) or len(rows) >= 21:
        raise DirectoryConflict("directory_incomplete")
    candidates = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("directory_contract")
        if str(row.get("facname") or "").casefold() != scope["evidence_venue"].casefold():
            continue
        borough = str(row.get("boro") or "").strip().lower()
        if borough == "the bronx":
            borough = "bronx"
        if borough != scope["locality"].lower():
            continue
        if not all(isinstance(row.get(k), str) and row[k].strip() for k in FIELDS):
            continue
        record = {k: row[k] for k in FIELDS}
        if (not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", record["uid"])
                or not re.fullmatch(r"[0-9]{1,6}[A-Za-z]?(?:-[0-9]{1,6}[A-Za-z]?)?", record["addressnum"])
                or not re.fullmatch(r"[^,/@&\x00-\x1f\x7f]{2,100}", record["streetname"])
                or not re.fullmatch(r"[A-Za-z .'-]{2,60}", record["city"])
                or not re.fullmatch(r"\d{5}", record["zipcode"])):
            continue
        address = (record["addressnum"] + " " + record["streetname"] + ", "
                   + record["city"] + ", NY " + record["zipcode"])
        candidate = {"address": address, "evidence_url": API + "?uid=" + record["uid"],
                     "evidence_name": claim["venue_name"], "method": "venue_contact",
                     "country_code": "US", "directory_record": record}
        candidates.setdefault(address.casefold(), candidate)
    if len(candidates) > 1:
        raise DirectoryConflict("directory_conflict")
    return next(iter(candidates.values())) if candidates else None


def resolve_official(claim, *, fetch, deadline_at):
    scope = claim.get("research_scope")
    if not valid_scope(claim, scope):
        raise ValueError("official_scope_invalid")
    cached = claim.get("verified_candidate")
    if (isinstance(cached, dict) and isinstance(cached.get("name"), str)
            and cached["name"].casefold() == claim["venue_name"].casefold()
            and isinstance(cached.get("address"), str)
            and isinstance(cached.get("evidence_url"), str)
            and cached["evidence_url"].startswith("https://")):
        return {"address": cached["address"], "evidence_url": cached["evidence_url"],
                "evidence_name": claim["venue_name"], "method": "venue_contact", "country_code": "US"}
    raw = fetch(directory_url(scope["evidence_venue"]), "application/json",
                respect_robots=True, deadline_at=deadline_at, allowed_hosts=(HOST,),
                follow_redirects=False)
    if not isinstance(raw, (str, bytes)) or len(raw) > 128000:
        raise ValueError("directory_response_bound")
    return address_candidate(claim, scope, json.loads(raw))
