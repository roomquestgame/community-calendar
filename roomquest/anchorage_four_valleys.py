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
    return (p.scheme == "https" and p.netloc == "fo...[truncated]