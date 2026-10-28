"""Build a reproducible, conservative RoomQuest import manifest from Mapsee.

Catalog metadata is evidence of discovery, never publisher permission or venue
coordinates. No network, geocoding, event generation or approval happens here.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

MAPSEE_COMMIT = "aa7ebd98bc43681e04aa1202e4aae7a696001813"
STATES = dict(zip(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split(),
    "Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|District of Columbia|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming".split("|")))
STATE_NAMES = {v.casefold(): k for k, v in STATES.items()}
ENTRY_KEYS = ("sources", "sites", "venues", "portals", "tenants", "instances", "calendars", "recitals", "festivals", "restaurants", "areas")
SUPPORTED = {"ics": "ical", "localist": "localist", "tribe": "wordpress", "jsonld": "jsonld", "squarespace": "squarespace", "opendata": "custom", "drupal_fullcalendar": "custom", "mylisting": "custom"}


def entries(data):
    if isinstance(data, list):
        return [("entries", i, x) for i, x in enumerate(data) if isinstance(x, dict)]
    if isinstance(data, dict):
        return [(key, i, x) for key in ENTRY_KEYS for i, x in enumerate(data.get(key, [])) if isinstance(x, dict)]
    return []


def canonical_url(url):
    """Normalize transport spellings, retaining publisher/calendar selectors."""
    p = urlsplit(url)
    host = (p.hostname or "").lower().removeprefix("www.")
    path = unquote(p.path).rstrip("/") or "/"
    query = sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                   if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"})
    return urlunsplit(("https", host, path, urlencode(query), ""))


def country_evidence(e):
    """Require positive US evidence; upstream's bare-city => US guess is unsafe."""
    venue = e.get("venue") if isinstance(e.get("venue"), dict) else {}
    explicit = e.get("default_country") or venue.get("country") or e.get("country")
    if explicit:
        text = str(explicit).casefold()
        return ("US" if text in {"us", "usa", "united states", "united states of america"} else str(explicit), "explicit_country")
    suffix = str(e.get("geocode_suffix") or "").strip(" ,")
    metro = str(e.get("_metro") or "")
    if metro:
        last = metro.rsplit(",", 1)[-1].strip()
        if last.casefold() in {"united states", "us", "usa"}:
            return "US", "declared_metro"
        if "," in metro and last not in STATES and last.casefold() not in STATE_NAMES:
            return last, "declared_metro"
    for token in [suffix.rsplit(",", 1)[-1].strip(), str(venue.get("region") or "")]:
        if token in STATES or token.casefold() in STATE_NAMES:
            return "US", "explicit_state"
    # Parenthesized ', NC' is country evidence; a word like 'Paris' is not.
    name = str(e.get("name") or "")
    if re.search(r",\s*(?:" + "|".join(STATES) + r")\s*[)\]]", name):
        return "US", "name_state"
    url = endpoint(e)
    host = (urlsplit(url).hostname or "").lower()
    if host.endswith((".gov", ".us", ".edu")):
        return "US", "us_domain"
    return "unknown", "country_unverified"


def endpoint(e):
    for k in ("url", "base_url", "collection", "explore_url", "calendar_url", "listing", "home"):
        v = e.get(k)
        if isinstance(v, str) and v.startswith("http"):
            return v
        if isinstance(v, list):
            return next((u for u in v if isinstance(u, str) and u.startswith("http")), "")
    return ""


def priority(e):
    text = " ".join(str(e.get(k) or "") for k in ("name", "_metro", "geocode_suffix", "base_url")).lower()
    if any(s in text for s in ("raleigh", "wake county", "dncr.nc", "durham", "apex, nc", "holly springs, nc")):
        return 0
    if any(s in text for s in ("south hill", "mecklenburg", "chase city")):
        return 1
    if (any(s in text for s in ("richmond", "petersburg", "henrico", "chesterfield", "pamunkey"))
            and not any(s in text for s in ("california", ", ca", "st. petersburg", "richmond hill", "richmond heights"))):
        return 2
    return 3


def build(root, existing):
    known = {canonical_url(s["feed_url"]): s for s in existing}
    seen = {}; inventory = []; candidates = []
    for file in sorted(root.glob("*_sources.json")):
        if file.name.endswith(".example.json"):
            continue
        kind = file.name.removesuffix("_sources.json")
        for key, index, e in entries(json.loads(file.read_text())):
            url = endpoint(e); country, evidence = country_evidence(e)
            row = {"file": file.name, "entry": f"{key}/{index}", "name": e.get("name") or e.get("key") or "Unnamed configuration", "type": kind, "country": country, "country_evidence": evidence, "url": url}
            inventory.append(row)
            if country != "US":
                row["disposition"] = "international" if country != "unknown" else "country_unverified"
                continue
            if kind not in SUPPORTED:
                row["disposition"] = "requires_distinct_adapter_or_not_dated_events"
                continue
            if row["name"] in {"?", "Unnamed configuration"}:
                row["disposition"] = "publisher_attribution_unverified"
                continue
            p = urlsplit(url)
            if p.scheme != "https" or not p.hostname or p.username or p.password or p.port not in (None,443) or len(url)>1000:
                row["disposition"] = "unsafe_or_missing_https_endpoint"
                continue
            # Feed must be an advertised publisher endpoint; no keyed sweep or
            # adapter-supplied fallback/venue coordinates are imported.
            canonical = canonical_url(url)
            row["canonical_url"] = canonical
            if canonical in known:
                row["disposition"] = "existing_source"; row["source_key"] = known[canonical]["source_key"]
                continue
            if canonical in seen:
                row["disposition"] = "catalog_duplicate"; row["source_key"] = seen[canonical]
                continue
            source_key = "municipal_mapsee_" + hashlib.md5(canonical.encode()).hexdigest()[:24]
            seen[canonical] = source_key
            row["source_key"] = source_key; row["disposition"] = "candidate"
            config = {k:e[k] for k in ("timezone", "map", "where", "order", "api_url", "listing", "link_pattern", "url_template", "detail_rewrite") if k in e}
            candidates.append({**row,"platform_adapter":SUPPORTED[kind],"priority":priority(e),"config":config})
    candidates.sort(key=lambda e:(e["priority"], e["type"] != "ics", e["name"].casefold(),e["url"]))
    endpoint_counts=Counter(canonical_url(x["url"]) for x in inventory if x["url"])
    old_hosts={urlsplit(s["feed_url"]).hostname.removeprefix("www.") for s in existing}
    shared=[s["source_key"] for s in candidates if urlsplit(s["url"]).hostname.removeprefix("www.") in old_hosts]
    return {"catalog":"tophe112-source/mapsee-aggregator","commit":MAPSEE_COMMIT,
            "license":"MIT (software/catalog; publisher content rights separate)",
            "summary":{"configurations":len(inventory),"by_country":dict(Counter(x["country"] for x in inventory)),"dispositions":dict(Counter(x["disposition"] for x in inventory)),"candidate_adapters":dict(Counter(x["type"] for x in candidates)),
                       "endpoint_rows":sum(endpoint_counts.values()),"unique_endpoints":len(endpoint_counts),"duplicate_endpoint_entries":sum(v-1 for v in endpoint_counts.values()),"candidate_existing_publisher_host_overlap":len(shared)},
            "inventory":inventory,"candidates":candidates}


def main():
    ap=argparse.ArgumentParser();ap.add_argument("--mapsee-root",type=Path,required=True);ap.add_argument("--existing",type=Path,required=True);ap.add_argument("--output",type=Path,required=True)
    a=ap.parse_args();result=build(a.mapsee_root,json.loads(a.existing.read_text()));a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n");print(json.dumps(result["summary"],indent=2))


if __name__=="__main__":
    main()
