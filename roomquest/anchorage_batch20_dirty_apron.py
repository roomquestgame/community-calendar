"""Anchorage Batch A: first-party Dirty Apron hands-on cooking class calendars.

ONE publisher key includes adult and family feeds. Event JSON omits street and
contains a non-venue generic map point, so every proposed occurrence must have
a first-party detail page naming the class and the studio's exact street. NO
coordinates/images are invented: the events require reviewed Geocodio point
before registration/publication. Collector feature branch only, not enrolled.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from time import monotonic
from urllib.parse import urljoin, urlsplit
import json
import logging
import math
import re

from bs4 import BeautifulSoup
from roomquest.anchorage_sources import _description, NONPUBLIC, VIRTUAL, ZONE
from roomquest.mapsee_adapter import plain, record, timestamp

KEY = "dirty_apron_cooking_classes_ak"
ROOT = "https://www.thedirtyapron.com"
ADULT = ROOT + "/adult-cooking-classes/"
KIDS = ROOT + "/kids-cooking-classes/"
FEEDS = (ADULT, KIDS)
SOURCES = {KEY: (ADULT, "json", "squarespace")}
ALLOWED_HOSTS = {KEY: ("www.thedirtyapron.com",)}
VENUE = ("The Dirty Apron", "3565 Arctic Blvd Suite D3, Anchorage, AK 99503", "Anchorage")
# 2026-11-19 independent US Census Bureau address match (Public_AR_Current).
# Census point is a matched exact street-number interpolation, not a
# surveyed entrance; original publisher's map point independently corroborates.
VENUE_LAT = 61.188366793834
VENUE_LNG = -149.897840114071
VENUE_GEO_EVIDENCE = ("US Census Bureau address geocoder Public_AR_Current; "
                      "matched 3565 ARCTIC BLVD, ANCHORAGE AK 99503; "
                      "street-interpolated address geolocation, reviewed 2026-11-19")
MAX_DESCRIPTION = 12000
MAX_RECORDS = 100
WINDOW_DAYS = 60
MAX_PAGE_SIZE = 350_000
LOG = logging.getLogger(__name__)
REJECT = re.compile(r"\b(?:sold out|closed|cancell?ed|postponed|private|invite.only|booked)\b", re.I)
OFFSITE = re.compile(r"\b(?:off.site|different venue|other location|hosted at|held at (?!the dirty apron))\b", re.I)
PATH = re.compile(r"/(?:adult-cooking-classes|kids-cooking-classes)/[a-z0-9]+(?:-[a-z0-9]+)*/?")


def event_url(key, value):
    if key != KEY or not isinstance(value, str) or len(value) > 1800:
        return False
    try:
        p = urlsplit(value)
        return (p.scheme == "https" and p.hostname == "www.thedirtyapron.com"
                and not p.username and not p.password and p.port in (None, 443)
                and not p.query and not p.fragment and bool(PATH.fullmatch(p.path)))
    except ValueError:
        return False


def photo_url(key, value):
    return None  # Art/photo rights unreviewed.


def _verified_page(url, title, html):
    if not isinstance(html, str) or len(html) > MAX_PAGE_SIZE:
        return False
    soup = BeautifulSoup(html, "html.parser")
    site_title = plain(soup.title.get_text(" ", strip=True) if soup.title else "")
    title = re.sub(r"^SOLD OUT:\s*", "", title, flags=re.I)
    if not site_title or title.casefold() not in site_title.casefold():
        return False
    footer = soup.find("footer")
    footer_text = footer.get_text(" ", strip=True) if footer else ""
    if (not re.search(r"3565\s+Arctic\s+Blvd\s*,?\s*Ste\s+D3", footer_text, re.I)
            or not re.search(r"Anchorage,\s*Alaska\s*99503", footer_text, re.I)
            or "The Dirty Apron" not in site_title):
        return False
    # Source-wide footer is only supporting evidence. The event must be a
    # publisher-hosted, hands-on kitchen class, with no competing offsite venue.
    article = soup.find("article")
    article_text = article.get_text(" ", strip=True) if article else soup.get_text(" ", strip=True)
    return (bool(re.search(r"\b(?:hands.on|cooking class|family class|baking|culinary)\b", article_text, re.I))
            and not OFFSITE.search(article_text[:6000]))


def _row(event, group, fetch, now, deadline):
    if not isinstance(event, dict) or not isinstance(event.get("id"), str):
        raise ValueError("invalid_dirty_apron_event")
    if event.get("workflowState") != 1 or event.get("cancelled") or event.get("allDay") or event.get("allDayEvent"):
        return None
    title = plain(event.get("title"))
    if not title or REJECT.search(title) or NONPUBLIC.search(title) or VIRTUAL.search(title):
        return None
    if not re.search(r"\b(?:class|chef|cooking|macaron|paella|pies|nepal|bread|workshop|gingerbread)\b", title, re.I):
        return None
    raw_start, raw_end = event.get("startDate"), event.get("endDate")
    if any(isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t)
           for t in (raw_start, raw_end)):
        return None
    starts, ends = timestamp(raw_start), timestamp(raw_end)
    if (ends <= starts or ends - starts > timedelta(hours=8)
            or ends <= now or starts > now + timedelta(days=WINDOW_DAYS)):
        return None
    description = _description(event.get("body") or event.get("excerpt"))
    if not description or len(description) > MAX_DESCRIPTION or OFFSITE.search(description):
        return None
    if not re.search(r"\b(?:cooking|hands.on|baking|chef|food|kitchen|bread|pastr|dessert)\b", description, re.I):
        return None
    location = event.get("location") if isinstance(event.get("location"), dict) else {}
    # Any explicit different event address must be reviewed separately.
    if any(plain(location.get(k)) for k in ("addressTitle", "addressLine1", "addressLine2")):
        return None
    full = event.get("fullUrl")
    link = urljoin(group, full) if isinstance(full, str) else ""
    if not event_url(KEY, link) or not urlsplit(link).path.startswith(urlsplit(group).path):
        return None
    if monotonic() >= deadline:
        raise ValueError("collection_deadline")
    if not _verified_page(link, title, fetch(link, "text/html")):
        LOG.warning("dirty_apron_held identity=%s reason=event_site_venue_unverified", event["id"][:80])
        return None
    row = record(title, starts.isoformat(), ends.isoformat(), *VENUE,
                 link, event["id"], "create", tz=ZONE, retain_until_end=True)
    if row is None:
        return None
    row.update(description=description, category="create", timezone=ZONE,
               publisher_categories=["The Dirty Apron", "Cooking Classes"],
               location_provenance=VENUE_GEO_EVIDENCE,
               lat=VENUE_LAT, lng=VENUE_LNG)
    from roomquest.publisher_evidence import attach
    return attach(row, KEY, candidate=None)


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY
            or (source.get("feed_url"), source.get("kind"), source.get("platform_adapter")) != SOURCES[KEY]
            or source.get("timezone") != ZONE):
        raise ValueError("unregistered_dirty_apron_source")
    now = now or datetime.now(timezone.utc)
    deadline = min(monotonic() + 38, deadline_at if deadline_at is not None else float("inf"))
    from roomquest.squarespace import check_pagination
    rows = {}
    for group in FEEDS:
        if monotonic() >= deadline:
            raise ValueError("collection_deadline")
        data = json.loads(fetch(group + "?format=json", "application/json"))
        if not isinstance(data, dict) or not isinstance(data.get("upcoming"), list):
            raise ValueError("invalid_dirty_apron_calendar")
        if (data.get("website") or {}).get("timeZone") != ZONE:
            raise ValueError("publisher_timezone_changed")
        check_pagination(data, upcoming=True)
        if len(data["upcoming"]) > MAX_RECORDS:
            raise ValueError("dirty_apron_record_limit")
        for event in data["upcoming"]:
            row = _row(event, group, fetch, now, deadline)
            if row is None:
                continue
            identity = (row["id"], row["starts_at"])
            if identity in rows and rows[identity] != row:
                raise ValueError("conflicting_dirty_apron_occurrence")
            rows[identity] = row
    return sorted(rows.values(), key=lambda r: (r["starts_at"], r["id"]))
