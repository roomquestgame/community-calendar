"""Resolve the documented Communico event identity without another HTTP request.

Communico /feeds exports omit VEVENT.URL, but each finite VEVENT UID is the
publisher's numeric /event/{id} identity. Restrict that contract to the hosted
platform and the reviewed Library District custom hostname. Other ICS feeds
retain their existing fallback, and explicit non-feed URLs retain precedence.
"""
from __future__ import annotations

from base64 import b64decode
from binascii import Error as Base64Error
import json
import re
from urllib.parse import parse_qs, urlsplit


def _feed_origin(value):
    if not isinstance(value, str) or len(value) > 1000:
        return None
    try:
        url = urlsplit(value)
        host = (url.hostname or "").lower()
        if (url.scheme != "https" or url.username or url.password
                or url.port not in (None, 443) or url.fragment or url.path != "/feeds"
                or not (host == "events.thelibrarydistrict.org"
                        or re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.libnet\.info", host))):
            return None
        query = parse_qs(url.query, keep_blank_values=True, strict_parsing=True,
                         max_num_fields=2)
        if set(query) != {"data"} or len(query["data"]) != 1:
            return None
        data = json.loads(b64decode(query["data"][0], validate=True))
        if (not isinstance(data, dict) or data.get("feedType") != "ical"
                or not isinstance(data.get("filters"), dict)):
            return None
        return "https://" + host
    except (ValueError, TypeError, UnicodeError, Base64Error):
        return None


def detail_url(feed_url, uid, current_url=None):
    """Return a page only for a numeric publisher UID with no real page already.

    No UID is inferred from the title, date, query or feed's filters. The caller
    must supply the original VEVENT UID, before any local recurrence suffix.
    """
    if not isinstance(uid, str) or not re.fullmatch(r"[1-9][0-9]{4,9}", uid):
        return None
    origin = _feed_origin(feed_url)
    if origin is None:
        return None
    if current_url and _feed_origin(current_url) != origin:
        return None
    return origin + "/event/" + uid
