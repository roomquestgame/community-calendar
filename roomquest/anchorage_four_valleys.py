"""First-party Four Valleys Community School — Girdwood verified public program.

The Girdwood community calendar contains 600+ mixed community, historical and
recurring entries. Import ONLY the event whose organizer-owned first-party
detail, actual November 2026 occurrence and individually matched street have
been independently validated. Never infer school class repetitions, use
publisher's approximate location marker, or import community submissions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from time import monotonic
from urllib.parse import urlsplit
import json

from bs4 import BeautifulSoup
from roomquest.mapsee_adapter import plain, record

KEY = "four_valleys_girdwood_public_ak"
ROOT = "https://fourvalleys.org"
FEED = ROOT + "/events/"
DETAIL = ROOT + "/events/holiday-wreath-making-class/"
SOURCE_SLUG = "/events/holiday-wreath-making-class"
SOURCES = {KEY: (FEED, "html", "html")}
ALLOWED_HOSTS = {KEY: ("fourvalleys.org",)}
ZONE = "America/Anchorage"
VENUE = ("Girdwood Chapel", "102 Heavenly Valley Drive, Girdwood, AK 99587", "Girdwood")
# US Census Public_AR_Current exact 102 HEAVENLY VALLEY DR address matched;
# interpolated street 2026-11-19, not a rooftop point.
POINT = (60.959899730249, -149.121519216281)
POINT_EVIDENCE = ("US Census Public_AR_Current 102 HEAVENLY VALLEY DR GIRDWOOD "
                  "AK 99587 exact address match 2026-11-19; interpolated street "
                  "coordinate. Publisher's generic 60.9422,-149.1678 ignored.")
TITLE = "Holiday Wreath Making Class"
START = datetime(2026, 11, 22, 22, tzinfo=timezone.utc)
END = datetime(2026, 11, 23, 0, tzinfo=timezone.utc)
MAX_DESCRIPTION = 12000
MAX_INDEX = 2400000
MAX_DETAIL = 400000
WINDOW_DAYS = 60
EXPECTED_IMAGE = ROOT + "/images/holiday-wreath-making.webp"


def event_url(source_key, url):
    if source_key != KEY or not isinstance(url, str):
        return False
    p = urlsplit(url)
    return (p.scheme == "https" and p.netloc == "fourvalleys.org"
            and p.path == "/events/holiday-wreath-making-class/"
            and not p.query and not p.fragment)


def photo_url(source_key, url):
    return None  # Publisher image is a retained candidate; no reproduction rights.


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY or source.get("timezone") != ZONE
            or (source.get("feed_url"), source.get("kind"),
                source.get("platform_adapter")) != SOURCES[KEY]):
        raise ValueError("fvcs_source_mismatch")
    now = now or datetime.now(timezone.utc)
    deadline = min(monotonic() + 38,
                   deadline_at if deadline_at is not None else float("inf"))
    index = fetch(FEED, "text/html")
    if not isinstance(index, str) or not 1000 < len(index) <= MAX_INDEX:
        raise ValueError("fvcs_index_invalid")
    soup = BeautifulSoup(index, "html.parser")
    listing = [
        li for li in soup.select("li.event-item")
        if li.get("data-community") == "false"
        and li.get("data-title") == TITLE.lower()
        and li.get("data-timestamp") == str(int(START.timestamp() * 1000))
        and any(a.get("href") == SOURCE_SLUG
                for a in li.select("a[href]"))
    ]
    if len(listing) != 1:
        raise ValueError("fvcs_original_dated_listing_changed")
    if monotonic() >= deadline:
        raise ValueError("collection_deadline")
    page = fetch(DETAIL, "text/html")
    if not isinstance(page, str) or not 1000 < len(page) <= MAX_DETAIL:
        raise ValueError("fvcs_detail_invalid")
    soup = BeautifulSoup(page, "html.parser")
    h1 = soup.find("h1")
    if not h1 or plain(h1.get_text(" ", strip=True)) != TITLE:
        raise ValueError("fvcs_event_title_changed")
    items = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            obj = json.loads(script.get_text())
        except (ValueError, TypeError):
            raise ValueError("fvcs_invalid_jsonld") from None
        if isinstance(obj, dict) and obj.get("@type") == "Event":
            items.append(obj)
    if len(items) != 1:
        raise ValueError("fvcs_event_jsonld_changed")
    e = items[0]
    if (e.get("name") != TITLE
            or e.get("startDate") != "2026-11-22T22:00:00.000Z"
            or e.get("endDate") != "2026-11-23T00:00:00.000Z"
            or e.get("eventStatus") != "https://schema.org/EventScheduled"
            or e.get("eventAttendanceMode") != "https://schema.org/OfflineEventAttendanceMode"
            or e.get("url") not in (DETAIL, DETAIL.rstrip("/"))):
        raise ValueError("fvcs_original_time_identity_changed")
    org = e.get("organizer") or {}
    loc = e.get("location") or {}
    addr = loc.get("address") or {}
    if (org.get("name") != "Four Valleys Community School"
            or org.get("url") not in (ROOT, ROOT + "/")
            or loc.get("@type") != "Place" or loc.get("name") != VENUE[0]
            or addr.get("streetAddress") != "102 Heavenly Valley Drive"
            or addr.get("addressLocality") != "Girdwood"
            or addr.get("addressRegion") != "AK"
            or addr.get("postalCode") != "99587"
            or addr.get("addressCountry") != "US"):
        raise ValueError("fvcs_unverified_venue")
    description = plain(e.get("description") or "")
    if not 200 <= len(description) <= MAX_DESCRIPTION or "<" in description:
        raise ValueError("fvcs_description_invalid")
    if END <= now or START > now + timedelta(days=WINDOW_DAYS):
        return []
    row = record(TITLE, START.isoformat(), END.isoformat(), *VENUE, DETAIL,
                 "fourvalleys:holiday-wreath-making:2026-11-22",
                 "create", lat=POINT[0], lng=POINT[1],
                 tz=ZONE, retain_until_end=True)
    if row is None:
        return []
    row.update(description=description, category="create", timezone=ZONE,
               location_provenance=POINT_EVIDENCE,
               publisher_categories=["FVCS Arts & Creativity", "Fundraiser"],
               image_rights="unreviewed")
    row.pop("image_url", None)
    if e.get("image") == EXPECTED_IMAGE:
        row["publisher_details"] = {"image_candidate_only": EXPECTED_IMAGE}
    return [row]

