"""Read Sower Books' dated Lit Circle storefront events."""
from datetime import datetime, timedelta
from hashlib import sha256
import re
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from lxml import html

from roomquest.mapsee_adapter import plain, record

KEY = "sower_books_lit_circle_ne"
HOST = "litcircle.org"
URL = f"https://{HOST}/et/bookstores/sower-books"
ZONE = "America/Chicago"
VENUE = "Sower Books"
ADDRESS = "914 N 70th Street, Lincoln, NE 68505"


def collect(source, fetch, *, deadline_at=None, now=None):
    if tuple(source.get(k) for k in ("source_key", "feed_url", "timezone", "kind", "platform_adapter")) != (
        KEY, URL, ZONE, "html", "html",
    ):
        raise ValueError("unregistered_sower_calendar")
    zone = ZoneInfo(ZONE)
    today = (now or datetime.now(zone)).astimezone(zone).date()
    document = html.fromstring(fetch(URL, "text/html"))
    if not document.xpath("//h1[contains(normalize-space(.), 'Sower Books')]"):
        raise ValueError("missing_sower_books_listing")
    results = {}
    for anchor in document.xpath("//a[starts-with(@href,'/et/events/') and .//h2]"):
        path = anchor.get("href")
        if not re.fullmatch(r"/et/events/[a-z0-9-]+", path):
            continue
        title = plain(anchor.xpath(".//h2")[0].text_content())
        if not title or re.search(r"\b(cancelled|canceled|postponed|closed)\b", title, re.I):
            continue
        venue_nodes = anchor.xpath(".//*[local-name()='svg' and contains(@class,'lucide-map-pin')]/parent::*")
        clock_nodes = anchor.xpath(".//*[local-name()='svg' and contains(@class,'lucide-clock')]/parent::*")
        if len(venue_nodes) != 1 or len(clock_nodes) != 1 or plain(venue_nodes[0].text_content()) != VENUE:
            continue
        stamp = plain(clock_nodes[0].text_content())
        try:
            start = datetime.strptime(stamp, "%I:%M %p • %A, %B %d, %Y")
        except ValueError:
            continue
        if not today <= start.date() <= today + timedelta(days=59):
            continue
        url = urljoin(URL, path)
        identity = sha256(f"{url}:{start.isoformat()}".encode()).hexdigest()
        row = record(title, start.isoformat(), None, VENUE, ADDRESS, "Lincoln", url, identity, tz=ZONE)
        if row is not None:
            results[row["id"]] = row
    return sorted(results.values(), key=lambda row: (row["starts_at"], row["id"]))
