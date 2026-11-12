"""Collect the Chamber's visible upcoming events through its public exports."""
from time import monotonic
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from lxml import html

from roomquest.firespring import event_record

KEY = "lincoln_chamber_weblink_ne"
HOST = "www.lcoc.com"
LISTING = f"https://{HOST}/events"
ZONE = "America/Chicago"


def listing_links(payload):
    document = html.fromstring(payload)
    if not document.xpath("//*[self::h1 or self::h2][normalize-space(.)='Upcoming Events']"):
        raise ValueError("missing_lincoln_chamber_calendar")
    exports, details = {}, {}
    for href in document.xpath("//a/@href"):
        link = urljoin(LISTING, href)
        url = urlsplit(link)
        if url.scheme != "https" or url.netloc != HOST or url.fragment:
            continue
        if url.path == "/ws/event.ics":
            params = parse_qs(url.query)
            ids = params.get("id", [])
            if set(params) == {"id"} and len(ids) == 1 and re.fullmatch(r"\d{1,12}", ids[0]):
                exports[ids[0]] = link
        else:
            detail = re.fullmatch(r"/event/(\d{1,12})-[a-z0-9-]+/?", url.path)
            if detail and not url.query:
                details[detail[1]] = link
    if len(exports) > 20:
        raise ValueError("lincoln_chamber_event_limit")
    return [(identity, link, details.get(identity, LISTING)) for identity, link in exports.items()]


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key"), source.get("feed_url"), source.get("timezone"),
            source.get("kind"), source.get("platform_adapter")) != (KEY, LISTING, ZONE, "html", "html"):
        raise ValueError("unregistered_lincoln_chamber_calendar")
    rows = []
    for identity, link, detail in listing_links(fetch(LISTING, "text/html")):
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError("collection_deadline")
        row = event_record(fetch(link, "text/calendar"), detail, identity)
        if row is not None:
            rows.append(row)
    return sorted(rows, key=lambda row: (row["starts_at"], row["id"]))
