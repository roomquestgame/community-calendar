"""Shared Socrata request and dataset-field mapping for reviewed sources.

The caller supplies its existing bounded transport and event normalization.
Dataset profiles, provenance, source approval, location checks and downstream
publication remain with the caller. This module does not fetch or geocode.
"""
from datetime import timezone
import re
from urllib.parse import urlencode
from zoneinfo import ZoneInfo


def page_url(base, config, page, now):
    """Build the existing bounded Socrata page and dataset-specific filter."""
    local_now = now.astimezone(ZoneInfo(config["timezone"])) if config.get("timezone") else now.astimezone(timezone.utc)
    where = str(config.get("where") or "").replace("{now}", local_now.strftime("%Y-%m-%dT%H:%M:%S")).replace("{today}", local_now.date().isoformat())
    params = {"$limit": 500, "$offset": (page - 1) * 500}
    if where:
        params["$where"] = where
    if config.get("order"):
        params["$order"] = config["order"]
    return base + ("&" if "?" in base else "?") + urlencode(params)


def parse_open_data(data, config, make_record):
    """Map explicitly configured dataset fields through the common record gate."""
    if not isinstance(data, list):
        raise ValueError("unsupported_open_data_payload")
    mapping = config.get("map") or {}
    if not all(k in mapping for k in ("title", "start")):
        raise ValueError("unsupported_open_data_mapping")
    out = []
    for event in data:
        get = lambda key: event.get(mapping[key]) if key in mapping else None
        lat, lng = get("lat"), get("lon")
        geo = get("geo")
        if isinstance(geo, dict):
            lat, lng = geo.get("latitude"), geo.get("longitude")
        point = get("latlon")
        if isinstance(point, str):
            match = re.fullmatch(r"\s*([-+0-9.]+)\s*,\s*([-+0-9.]+)\s*", point)
            if match:
                lat, lng = match.groups()
            match = re.fullmatch(r"\s*POINT\s*\(\s*([-+0-9.]+)\s+([-+0-9.]+)\s*\)\s*", point, re.I)
            if match:
                lng, lat = match.groups()
        row = make_record(get("title"), get("start"), get("end"), get("venue"),
                          get("address"), get("city"), get("url") or config.get("publisher_url"),
                          get("id"), get("category"), lat, lng, config.get("timezone"))
        if row:
            out.append(row)
    return out
