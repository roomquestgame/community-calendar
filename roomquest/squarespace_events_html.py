"""Read dated Squarespace event-list cards on registered venue calendars."""
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import re
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

from lxml import html

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record

ZONE = "America/Chicago"
ELEANOR = "municipal_91c26eb4ef4205c03947decd"
ELEANOR_ZONE = "America/New_York"
ELEANOR_SHOP = ("Eleanor’s Norfolk", "801 Boush Street Unit B, Norfolk, VA 23510")
ELEANOR_GALLERY = ("Baron and Ellin Gordon Art Galleries", "4509 Monarch Way, Norfolk, VA 23508")
ELEANOR_SHOP_EVENTS = {
    "anarchiststudygroupnov26",
    "buy-nothing-book-swap",
    "northernnightsnorthernlights",
    "scapegoatclarefollman",
}
SOURCES = {
    "pageturners_lounge_omaha_ne": (
        "https://www.pageturnersomaha.com/event-calendar",
        "Pageturners Lounge", "5004 Dodge St, Omaha, NE 68132", "5004 Dodge", "Omaha",
    ),
    "blue_sky_bar_patio_omaha_ne": (
        "https://www.blueskyomaha.com/upcoming-events",
        "Blue Sky Bar & Patio", "10730 Pacific St, Omaha, NE 68114", "10730 Pacific", "Omaha",
    ),
    "saro_cider_lincoln_ne": (
        "https://www.sarocider.com/upcoming-events",
        "Saro Cider Lincoln Taproom", "1746 N St, Lincoln, NE 68508", "1746 N St", "Lincoln",
    ),
    "thor_trails_squarespace_ne": ("https://www.thortrails.org/events", "", "", "", ""),
    ELEANOR: ("https://www.eleanorsnfk.com/events", *ELEANOR_SHOP, "801 Boush", "Norfolk"),
}
REQUIRE_CARD_LOCATION = {"saro_cider_lincoln_ne"}
HAS_CLASS = "contains(concat(' ', normalize-space(@class), ' '), $class_name)"


def elements(node, class_name, tag="*"):
    return node.xpath(f".//{tag}[{HAS_CLASS}]", class_name=f" {class_name} ")


def narrative(node, *class_names, title=""):
    for name in class_names:
        containers = elements(node, name)
        if containers:
            text = description(html.tostring(containers[0], encoding="unicode", with_tail=False))
            if text and plain(text).casefold() != plain(title).casefold():
                return text
    return ""


def event_time(node):
    day = date.fromisoformat(node.get("datetime", ""))
    text = plain(node.text_content())
    format_string = "%I:%M %p" if re.search(r"[ap]m$", text, re.I) else "%H:%M"
    return datetime.combine(day, datetime.strptime(text.upper(), format_string).time())


def first_time(card, *class_names):
    for name in class_names:
        nodes = elements(card, name, "time")
        if nodes:
            return event_time(nodes[0])
    return None


def trail_location(card):
    for node in card.xpath(".//a[@href and normalize-space(.)='(map)']"):
        url = urlsplit(node.get("href"))
        if url.scheme not in {"http", "https"} or url.hostname not in {"maps.google.com", "www.google.com"}:
            continue
        for query in parse_qs(url.query).get("q", []):
            parts = re.fullmatch(
                r"(\d{1,6}\s+[^,]+?\s(?:Road|Street|Drive|Avenue|Lane|Boulevard|Trail|Court|Parkway))"
                r"\s+([A-Za-z][A-Za-z .'-]+),\s*(Nebraska|Iowa|South Dakota),\s*(\d{5})\s+United States",
                query,
            )
            if not parts:
                continue
            street, city, state, zip_code = parts.groups()
            state_code = {"Nebraska": "NE", "Iowa": "IA", "South Dakota": "SD"}[state]
            return plain(node.getparent().text_content()).removesuffix("(map)").strip() or street, f"{street}, {city}, {state_code} {zip_code}", city
    return None


def collect(source, fetch, *, deadline_at=None, now=None):
    source_key = source.get("source_key")
    profile = SOURCES.get(source_key)
    zone = ELEANOR_ZONE if source_key == ELEANOR else ZONE
    if profile is None or (source.get("feed_url"), source.get("timezone"), source.get("kind"),
                           source.get("platform_adapter")) != (profile[0], zone, "html", "html"):
        raise ValueError("unregistered_squarespace_venue")
    if source_key == ELEANOR:
        return collect_eleanor(profile[0], fetch, now)
    listing, venue, address, street_prefix, city = profile
    origin = urlsplit(listing)
    today = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(ZONE)).date()
    document = html.fromstring(fetch(listing, "text/html"))
    if not elements(document, "eventlist-event", "article"):
        raise ValueError("missing_squarespace_event_list")
    events = {}
    for card in elements(document, "eventlist-event--upcoming", "article"):
        titles = elements(card, "eventlist-title-link", "a")
        dates = elements(card, "event-date", "time")
        if not titles or not dates:
            continue
        day = date.fromisoformat(dates[0].get("datetime", ""))
        if not today <= day <= today + timedelta(days=59):
            continue
        title = plain(titles[0].text_content())
        if not title or re.match(r"^(cancelled|canceled|postponed)\b", title, re.I):
            continue
        addresses = elements(card, "eventlist-meta-address")
        if source["source_key"] == "thor_trails_squarespace_ne":
            location = trail_location(card)
            if location is None:
                continue
            venue, address, city = location
        elif source["source_key"] in REQUIRE_CARD_LOCATION:
            maps = [urlsplit(url) for url in card.xpath(".//a/@href")]
            if not any(
                url.hostname in {"maps.google.com", "www.google.com"}
                and any(query.casefold().startswith("1746 n street lincoln")
                        for query in parse_qs(url.query).get("q", []))
                for url in maps
            ):
                continue
        elif addresses and street_prefix.casefold() not in plain(addresses[0].text_content()).casefold():
            continue
        link = urljoin(listing, titles[0].get("href", ""))
        target = urlsplit(link)
        if (target.scheme != "https" or target.netloc != origin.netloc or target.query or target.fragment
                or not target.path.startswith(origin.path + "/")):
            raise ValueError("invalid_squarespace_venue_event_link")
        start = first_time(card, "event-time-localized-start", "event-time-12hr-start")
        end = first_time(card, "event-time-localized-end", "event-time-12hr-end")
        if start is None or start.date() != day:
            continue
        if end is not None and end <= start:
            end = None
        identity = sha256(f"{target.path}:{day.isoformat()}".encode()).hexdigest()
        row = record(title, start.isoformat(), end.isoformat() if end else None, venue, address,
                     city, link, identity, tz=ZONE)
        if row is not None:
            row["description"] = narrative(card, "eventlist-description", "eventlist-excerpt", title=title)
            previous = events.setdefault(row["id"], row)
            if previous != row:
                raise ValueError("conflicting_squarespace_venue_event")
    return sorted(events.values(), key=lambda row: (row["starts_at"], row["id"]))


def collect_eleanor(listing, fetch, now):
    local_now = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(ELEANOR_ZONE)).replace(tzinfo=None)
    stop = local_now + timedelta(days=60)
    document = html.fromstring(fetch(listing, "text/html"))
    links = {}
    for title in elements(document, "summary-title-link", "a"):
        path = title.get("href", "")
        if re.fullmatch(r"/event-details/[a-z0-9-]+", path):
            links[path] = urljoin(listing, path)
    if not links or len(links) > 30:
        raise ValueError("invalid_squarespace_summary_links")

    events = []
    for path, link in links.items():
        detail = html.fromstring(fetch(link, "text/html"))
        titles = elements(detail, "eventitem-title", "h1")
        start = first_time(detail, "event-time-localized-start", "event-time-12hr-start")
        if not titles or start is None or not local_now <= start < stop:
            continue
        title = plain(titles[0].text_content())
        if re.search(r"\b(?:cancelled|canceled|postponed)\b", title, re.I):
            continue
        body = elements(detail, "eventitem-column-content")
        copy = plain(body[0].text_content()).casefold() if body else ""
        normalized_title = title.casefold()
        if "gordon art gallery" in normalized_title:
            venue, address = ELEANOR_GALLERY
        elif ("801 boush" in copy or re.search(r"\b(?:at|to) eleanor[’']s", copy)
              or "at eleanor’s" in normalized_title or path.rsplit("/", 1)[-1] in ELEANOR_SHOP_EVENTS):
            venue, address = ELEANOR_SHOP
        else:
            continue
        end = first_time(detail, "event-time-localized-end", "event-time-12hr-end")
        row = record(title, start.isoformat(), end.isoformat() if end and end > start else None,
                     venue, address, "Norfolk", link, path, tz=ELEANOR_ZONE)
        if row:
            # The sibling content footer contains tags, not event narrative.
            row["description"] = narrative(body[0], "sqs-layout", title=title) if body else ""
            events.append(row)
    return sorted(events, key=lambda row: (row["starts_at"], row["id"]))
