"""Complete official calendars for Raleigh's larger performance venues.

Only the existing injected, paced, robots-aware GET transport performs I/O.
Month ranges are discovery evidence; actual detail showtimes create events.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from time import monotonic
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record, timestamp

ZONE = "America/New_York"
LENOVO = "lenovo_center_nc"
MMC = "martin_marietta_center_nc"
IMPROV = "raleigh_improv_nc"
KOKA = "koka_booth_amphitheatre_nc"
SOURCES = {
    LENOVO: ("https://www.lenovocenter.com/events/all", "html", "html"),
    MMC: ("https://www.martinmariettacenter.com/events", "html", "html"),
    IMPROV: ("https://improv.com/raleigh/calendar/", "html", "html"),
    KOKA: ("https://www.boothamphitheatre.com/tickets/", "html", "html"),
}
VENUES = {
    LENOVO: ("Lenovo Center", "1400 Edwards Mill Road, Raleigh, NC 27607", "Raleigh"),
    MMC: ("Martin Marietta Center for the Performing Arts", "2 East South Street, Raleigh, NC 27601", "Raleigh"),
    IMPROV: ("Raleigh Improv", "1224 Parkside Main Street, Cary, NC 27519", "Cary"),
    KOKA: ("Koka Booth Amphitheatre", "8003 Regency Parkway, Cary, NC 27518", "Cary"),
}
LABELS = {key: venue[0] for key, venue in VENUES.items()}
ALLOWED_HOSTS = {key: (urlsplit(spec[0]).hostname,) for key, spec in SOURCES.items()}
CHECKPOINT_KEYS = set(SOURCES)
FESTIVAL_URL = "https://www.boothamphitheatre.com/nc-chinese-lantern-festival/"
MAX_RECORDS = 200
MAX_MANIFEST = 200
CHECKPOINT_MANIFEST_LIMITS = {key: MAX_MANIFEST for key in SOURCES}
CHECKPOINT_EVENT_LIMITS = {key: MAX_RECORDS for key in SOURCES}
MAX_BYTES = 850_000
MAX_FETCHES = 10
MAX_LIST_PAGES = 20
MIN_SECONDS = 10
PROVENANCE = "reviewed_publisher_street_pending_geocode"
HOLD_CODES = {"raleigh_performance_description_missing", "raleigh_performance_description_limit",
              "raleigh_performance_schedule_unresolved", "raleigh_performance_venue_unresolved",
              "raleigh_performance_outside_window", "raleigh_performance_nonpublic"}
ERROR_CODES = HOLD_CODES | {"unregistered_raleigh_performance_source", "raleigh_performance_calendar_changed",
    "raleigh_performance_detail_changed", "raleigh_performance_record_limit", "raleigh_performance_checkpoint_invalid",
    "raleigh_performance_checkpoint_size_limit", "raleigh_performance_checkpoint_required", "collection_deadline"}
NONPUBLIC = re.compile(r"\b(?:cancelled|canceled|postponed|private\s+(?:event|party)|closed)\b", re.I)
MONTHS = {name.lower(): n for n, name in enumerate(("", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December")) if n}
MONTHS.update({key[:3]: value for key, value in list(MONTHS.items())})
MONTHS["sept"] = 9
WEEKDAYS = {name.lower(): n for n, name in enumerate(("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"))}
MMC_ROOMS = {"Fletcher Opera Theater", "A.J. Fletcher Opera Theater", "Raleigh Memorial Auditorium",
             "Meymandi Concert Hall", "Kennedy Theatre", "Kennedy Theater", "Martin Marietta Center for the Performing Arts"}


def _hash(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _source(source):
    key = source.get("source_key")
    if key not in SOURCES or (source.get("feed_url"), source.get("kind"), source.get("platform_adapter"),
                             source.get("timezone")) != (*SOURCES[key], ZONE):
        raise ValueError("unregistered_raleigh_performance_source")
    return key


def _safe_url(value):
    if not isinstance(value, str) or len(value) > 1000 or re.search(r"[\s\\<>]", value):
        return None
    try:
        p = urlsplit(value)
        decoded = unquote(p.path)
        if (p.scheme != "https" or p.username or p.password or p.port not in (None, 443) or p.fragment
                or ".." in decoded.split("/") or re.search(r"[\\\x00-\x1f]", decoded)):
            return None
        return p
    except ValueError:
        return None


def event_url(key, value):
    p = _safe_url(value)
    if not p or key not in SOURCES or p.netloc != urlsplit(SOURCES[key][0]).netloc or p.query:
        return False
    if key in {LENOVO, MMC}:
        return bool(re.fullmatch(r"/events/detail/[a-zA-Z0-9-]+/?", p.path))
    if key == IMPROV:
        # Native Improv slugs encode punctuation, including an English/Spanish
        # slash within a slug. The exact host and route remain source scoped.
        return bool(re.fullmatch(r"/raleigh/(?:comic/[A-Za-z0-9+%._()-]+|event/[A-Za-z0-9+%._()-]+/[1-9]\d*)/", p.path))
    return value == FESTIVAL_URL or bool(re.fullmatch(r"/event/[a-z0-9-]+(?:/[a-z0-9-]+){0,2}/", p.path))


def photo_url(key, value):
    p = _safe_url(value)
    if not p:
        return None
    if key == IMPROV:
        okay = p.hostname == "i.ticketweb.com" and p.path.startswith("/i/") or p.hostname == "i.improv.com" and p.path.startswith("/wp-content/uploads/")
    elif key == KOKA:
        okay = p.hostname == "www.boothamphitheatre.com" and p.path.startswith("/wp-content/uploads/")
    else:
        okay = p.hostname == urlsplit(SOURCES[key][0]).hostname and p.path.startswith("/assets/img/")
    return value if okay else None


def _body(value):
    if value is not None and not isinstance(value, str):
        raise ValueError("raleigh_performance_detail_changed")
    text = description(value, limit=12001)
    if len(text) > 12000:
        raise ValueError("raleigh_performance_description_limit")
    generic_link = re.fullmatch(r"For more information,?\s*(?:please\s+)?visit\s+(?:https?://)?(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?:/[^\s]*)?\s*\.?", plain(text), re.I)
    if not text or not re.search(r"[A-Za-z]{2}", text) or generic_link:
        raise ValueError("raleigh_performance_description_missing")
    return text


def _within(start, end, now):
    return start < now + timedelta(days=60) and (end or start + timedelta(hours=3)) > now


def _clock(day, text):
    match = re.fullmatch(r"\s*(1[0-2]|0?[1-9])(?::([0-5]\d))?\s*([AP])\.?M\.?\s*", text, re.I)
    if not match:
        raise ValueError("raleigh_performance_schedule_unresolved")
    hour = int(match[1]) % 12 + (12 if match[3].lower() == "p" else 0)
    return timestamp(f"{day.isoformat()}T{hour:02}:{int(match[2] or 0):02}:00", ZONE)


def _span(node):
    """Read publisher month/day/year components, without assuming a year."""
    if node is None:
        return None
    months = [MONTHS[plain(n.get_text()).lower().strip(".")] for n in node.select(".m-date__month")]
    days = [int(re.sub(r"\D", "", n.get_text())) for n in node.select(".m-date__day")]
    years = [int(re.sub(r"\D", "", n.get_text())) for n in node.select(".m-date__year")]
    if not years or not months or not days:
        return None
    if len(months) > 2 or len(days) > 2 or len(years) > 2:
        raise ValueError("raleigh_performance_calendar_changed")
    first_year, last_year = years[0], years[-1]
    if len(years) == 1 and len(months) == 2 and months[0] > months[1]:
        first_year -= 1  # Native final year identifies a cross-year range.
    first = date(first_year, months[0], days[0])
    last = date(last_year, months[-1], days[-1])
    if last < first:
        raise ValueError("raleigh_performance_calendar_changed")
    return [first.isoformat(), last.isoformat()]


def _packet(key, url, title, span=None, image=None, room=None):
    title = plain(title)
    if not event_url(key, url) or not 1 <= len(title) <= 180:
        raise ValueError("raleigh_performance_calendar_changed")
    if span is not None and (not isinstance(span, list) or len(span) != 2 or date.fromisoformat(span[0]) > date.fromisoformat(span[1])):
        raise ValueError("raleigh_performance_calendar_changed")
    out = dict(url=url, title=title, span=span)
    if photo := photo_url(key, image):
        out["image"] = photo
    if room:
        out["room"] = plain(room)
    return out


def _range_in_window(span, now):
    if span is None:
        return True
    return date.fromisoformat(span[0]) <= (now + timedelta(days=60)).astimezone(ZoneInfo(ZONE)).date() and date.fromisoformat(span[1]) >= now.astimezone(ZoneInfo(ZONE)).date() - timedelta(days=1)


def _arena_listing(key, payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    cards = soup.select(".eventItem")
    queue, native = [], []
    for card in cards:
        link = card.select_one("h3.title a[href]")
        if not link:
            raise ValueError("raleigh_performance_calendar_changed")
        url = urljoin(SOURCES[key][0], link["href"])
        title = plain(link.get_text(" "))
        span = _span(card.select_one(".date"))
        native.append((url, span))
        if NONPUBLIC.search(title) or not _range_in_window(span, now):
            continue
        image = card.select_one(".thumb img[src]")
        room = card.select_one(".location")
        queue.append(_packet(key, url, title, span, image.get("src") if image else None,
                             room.get_text(" ", strip=True) if room else None))
    if len({url for url, _ in native}) != len(native):
        raise ValueError("raleigh_performance_calendar_changed")
    known = [date.fromisoformat(span[0]) for _, span in native if span]
    if key == MMC and known != sorted(known):
        raise ValueError("raleigh_performance_calendar_changed")
    stop = (now + timedelta(days=60)).astimezone(ZoneInfo(ZONE)).date()
    beyond = bool(native) and all(span and date.fromisoformat(span[0]) > stop for _, span in native)
    return queue, native, beyond


def _improv_listing(payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    listing = soup.select_one(".cal-list")
    if listing is None:
        raise ValueError("raleigh_performance_calendar_changed")
    month_years = {}
    for link in soup.select("a.month[href]"):
        match = re.fullmatch(r"/raleigh/calendar/([a-z]{3})-(\d{4})/", link["href"])
        if match:
            month_years.setdefault(MONTHS[match[1]], set()).add(int(match[2]))
    queue = []
    for card in listing.select("a.item[href]"):
        heading, month_node, day_node = card.select_one("h3"), card.select_one(".dates dt"), card.select_one(".dates dd")
        if not heading or not month_node or not day_node:
            raise ValueError("raleigh_performance_calendar_changed")
        title = plain(heading.get_text(" "))
        if NONPUBLIC.search(title):
            continue
        span = None
        month = MONTHS.get(plain(month_node.get_text(" ")).lower().strip("."))
        days = re.match(r"^(\d{1,2})(?:-(\d{1,2}))?", plain(day_node.get_text(" ")))
        if month and days and len(month_years.get(month, set())) == 1:
            year = next(iter(month_years[month]))
            span = [date(year, month, int(days[1])).isoformat(), date(year, month, int(days[2] or days[1])).isoformat()]
        if not _range_in_window(span, now):
            continue
        image = card.select_one(".img[data-src]")
        item = _packet(IMPROV, urljoin(SOURCES[IMPROV][0], card["href"]), title, span,
                       image.get("data-src") if image else None)
        count = re.fullmatch(r"(\d+) shows", plain(card.select_one(".times").get_text(" "))) if card.select_one(".times") else None
        if count:
            item["published_show_count"] = int(count[1])
        queue.append(item)
    if len({item["url"] for item in queue}) != len(queue):
        raise ValueError("raleigh_performance_calendar_changed")
    return queue


def _koka_listing(payload):
    soup = BeautifulSoup(payload, "html.parser")
    if soup.select('[rel="next"],.rhp-next:not(.disabled),.tribe-events-c-nav__next:not([disabled])'):
        raise ValueError("raleigh_performance_calendar_changed")
    links = soup.select("a#eventTitle[href]")
    if not links:
        raise ValueError("raleigh_performance_calendar_changed")
    queue, seen = [], set()
    for link in links:
        url = link["href"]
        title = plain(link.get_text(" "))
        if NONPUBLIC.search(title):
            continue
        if re.fullmatch(r"https://www\.boothamphitheatre\.com/event/\d{4}-nc-chinese-lantern(?:-2)?/", url):
            url, title = FESTIVAL_URL, "NC Chinese Lantern Festival"
        if url in seen:
            continue
        seen.add(url)
        queue.append(_packet(KOKA, url, title))
    return queue


def _schema_events(soup):
    out = []
    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            if node.get("@type") in ("Event", "MusicEvent", "ComedyEvent"):
                out.append(node)
            if "@graph" in node:
                walk(node["@graph"])
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            walk(json.loads(script.string or script.get_text()))
        except (ValueError, TypeError):
            raise ValueError("raleigh_performance_detail_changed") from None
    return out


def _row(key, item, start, end, body, image=None):
    if not start or start.tzinfo is None or end and (end.tzinfo is None or end <= start):
        raise ValueError("raleigh_performance_schedule_unresolved")
    identity = "raleigh:" + sha256(f'{key}:{item["url"]}:{start.astimezone(timezone.utc).isoformat()}'.encode()).hexdigest()
    venue, street, city = VENUES[key]
    row = record(item["title"], start.isoformat(), end.isoformat() if end else None,
        venue, street, city, item["url"], identity, tz=ZONE, retain_until_end=True)
    if row is None:
        raise ValueError("raleigh_performance_outside_window")
    row.update(description=_body(body), timezone=ZONE, attendance_mode="in_person",
               location_provenance=PROVENANCE, location_evidence_url=SOURCES[key][0])
    if item.get("room"):
        row["venue_room"] = item["room"]
    if photo := photo_url(key, image or item.get("image")):
        row["image_url"] = photo
    return row


def _show_day(showing, item):
    node = showing.select_one(".showings_date")
    if node is None:
        raise ValueError("raleigh_performance_schedule_unresolved")
    span = _span(node)
    if span and span[0] == span[1]:
        day = date.fromisoformat(span[0])
    else:
        explicit = []
        for link in showing.select("a[title]"):
            match = re.search(r"\bfor ([A-Za-z]+) (\d{1,2}) (\d{4}) at\b", link["title"])
            if match:
                explicit.append(date(int(match[3]), MONTHS[match[1].lower()], int(match[2])))
        if len(set(explicit)) == 1:
            day = explicit[0]
        else:
            month_node, day_node = node.select_one(".m-date__month"), node.select_one(".m-date__day")
            if not item.get("span") or not month_node or not day_node:
                raise ValueError("raleigh_performance_schedule_unresolved")
            first, last = map(date.fromisoformat, item["span"])
            candidates = [date(year, MONTHS[plain(month_node.get_text()).lower().strip(".")], int(plain(day_node.get_text())))
                          for year in range(first.year, last.year + 1)]
            candidates = [candidate for candidate in candidates if first <= candidate <= last]
            if len(candidates) != 1:
                raise ValueError("raleigh_performance_schedule_unresolved")
            day = candidates[0]
    weekday = node.select_one(".m-date__weekday")
    if weekday:
        word = re.sub(r"[^A-Za-z]", "", weekday.get_text()).lower()
        matches = [number for name, number in WEEKDAYS.items() if name.startswith(word)]
        if word and (len(matches) != 1 or matches[0] != day.weekday()):
            raise ValueError("raleigh_performance_schedule_unresolved")
    return day


def _arena_detail(key, item, payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    headings = {plain(n.get_text(" ")) for n in soup.select("h1")}
    if item["title"] not in headings:
        raise ValueError("raleigh_performance_detail_changed")
    if NONPUBLIC.search(" ".join(headings)):
        raise ValueError("raleigh_performance_nonpublic")
    bodies = soup.select(".event_description")
    if len(bodies) != 1:
        raise ValueError("raleigh_performance_description_missing")
    body = _body(str(bodies[0]))
    if key == MMC and item.get("room") and item["room"] not in MMC_ROOMS:
        raise ValueError("raleigh_performance_venue_unresolved")
    showings = soup.select('.event_showings [id^="showing_"]') or soup.select('[id^="showing_"]')
    if not showings:
        raise ValueError("raleigh_performance_schedule_unresolved")
    rows, starts = [], set()
    for showing in showings:
        if NONPUBLIC.search(plain(showing.get_text(" "))):
            continue
        day = _show_day(showing, item)
        clock = showing.select_one(".time.cell")
        if not clock:
            raise ValueError("raleigh_performance_schedule_unresolved")
        start = _clock(day, plain(clock.get_text(" ")))
        if start in starts:
            raise ValueError("raleigh_performance_detail_changed")
        starts.add(start)
        if _within(start, None, now):
            rows.append(_row(key, item, start, None, body))
    return rows


def _improv_detail(item, payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    canonical = soup.select_one('link[rel="canonical"]')
    if (not canonical or not event_url(IMPROV, canonical.get("href"))
            or unquote(canonical.get("href")) != unquote(item["url"])):
        raise ValueError("raleigh_performance_detail_changed")
    body_nodes = soup.select(".bio-text")
    if len(body_nodes) != 1:
        raise ValueError("raleigh_performance_description_missing")
    body = _body(str(body_nodes[0]))
    schemas = _schema_events(soup)
    if not schemas:
        raise ValueError("raleigh_performance_schedule_unresolved")
    rows, starts = [], set()
    for event in schemas:
        if NONPUBLIC.search(plain(event.get("name"))):
            continue
        start, end = timestamp(event.get("startDate")), timestamp(event.get("endDate"))
        if not start or start.tzinfo is None or start.utcoffset() != start.astimezone(ZoneInfo(ZONE)).utcoffset():
            raise ValueError("raleigh_performance_schedule_unresolved")
        # A comic's detail can also list a separately named holiday engagement.
        # Its own native calendar card is a distinct manifest entry. Bind this
        # packet to its published date span before checking its named shows.
        if item.get("span") and not (date.fromisoformat(item["span"][0]) <= start.astimezone(ZoneInfo(ZONE)).date() <= date.fromisoformat(item["span"][1])):
            continue
        if plain(event.get("name")) != item["title"]:
            raise ValueError("raleigh_performance_detail_changed")
        location = event.get("location") or {}
        address = location.get("address") or {}
        if (location.get("name") != "Raleigh Improv" or address.get("streetAddress") != "1224 Parkside Main Street"
                or address.get("addressLocality") != "Cary" or address.get("addressRegion") != "NC" or address.get("postalCode") != "27519"):
            raise ValueError("raleigh_performance_venue_unresolved")
        if start in starts:
            raise ValueError("raleigh_performance_detail_changed")
        starts.add(start)
        if _within(start, end, now):
            rows.append(_row(IMPROV, item, start, end, body, event.get("image")))
    if item.get("published_show_count") and len(starts) != item["published_show_count"]:
        raise ValueError("raleigh_performance_detail_changed")
    return rows


def _festival_detail(item, payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    main = soup.select_one('[data-elementor-type="wp-page"]')
    if not main:
        raise ValueError("raleigh_performance_detail_changed")
    overview = [n for n in main.select(".elementor-widget-text-editor") if plain(n.get_text(" ")).startswith("Experience the magic of the North Carolina Chinese Lantern Festival")]
    if len(overview) != 1:
        raise ValueError("raleigh_performance_description_missing")
    text = plain(overview[0].get_text(" "))
    match = re.search(r"([A-Za-z]+) (\d{1,2}), (\d{4}) through ([A-Za-z]+) (\d{1,2}), (\d{4})", text)
    if not match or not re.search(r"Open daily,\s*6[–-]10 PM.*Closed Christmas Day", text):
        raise ValueError("raleigh_performance_schedule_unresolved")
    first, last = date(int(match[3]), MONTHS[match[1].lower()], int(match[2])), date(int(match[6]), MONTHS[match[4].lower()], int(match[5]))
    holiday = [n for n in main.select("details") if n.select_one("summary") and plain(n.select_one("summary").get_text(" ")) == "Holiday Hours"]
    if len(holiday) != 1:
        raise ValueError("raleigh_performance_schedule_unresolved")
    holiday_text = plain(holiday[0].get_text(" "))
    if (not re.search(r"Thanksgiving Day and Christmas Eve:\s*Gates:\s*6\s*[–-]\s*9 PM", holiday_text)
            or "No Twilight Session" not in holiday_text or "Christmas Day: Closed" not in holiday_text
            or "New Years Eve and New Years Day: Normal Business Hours" not in holiday_text):
        raise ValueError("raleigh_performance_schedule_unresolved")
    # Preserve the whole event overview and all ticket/session narratives.
    # The separate venue FAQ is not the event description; retain its complete
    # Holiday Hours answer because it materially changes the dated schedule.
    overview_html = BeautifulSoup(str(main), "html.parser")
    for node in overview_html.select(".e-n-accordion,nav,button"):
        node.decompose()
    for node in overview_html.select("h2"):
        if plain(node.get_text(" ")) == "Know Before You Go":
            node.decompose()
    body = _body(str(overview_html) + "\n" + str(holiday[0]))
    picture = overview_html.select_one('img[src*="/wp-content/uploads/"]')
    image = picture.get("src") if picture else None
    # Thanksgiving is the fourth Thursday in November at this US venue.
    november = date(first.year, 11, 1)
    thanksgiving = november + timedelta(days=(3 - november.weekday()) % 7 + 21)
    day = max(first, now.astimezone(ZoneInfo(ZONE)).date() - timedelta(days=1))
    stop = min(last, (now + timedelta(days=60)).astimezone(ZoneInfo(ZONE)).date())
    rows = []
    while day <= stop:
        if (day.month, day.day) != (12, 25):
            start = _clock(day, "6 PM")
            end = _clock(day, "9 PM" if day == thanksgiving or (day.month, day.day) == (12, 24) else "10 PM")
            if _within(start, end, now):
                rows.append(_row(KOKA, item, start, end, body, image))
        day += timedelta(days=1)
    return rows


def _koka_detail(item, payload, now):
    if item["url"] == FESTIVAL_URL:
        return _festival_detail(item, payload, now)
    soup = BeautifulSoup(payload, "html.parser")
    dates = set()
    for link in soup.select('a[href*="calendar.google.com/calendar/render"]'):
        args = parse_qs(urlsplit(link["href"]).query)
        if args.get("dates"):
            dates.add(args["dates"][0])
    if len(dates) != 1:
        raise ValueError("raleigh_performance_schedule_unresolved")
    match = re.fullmatch(r"(\d{8}T\d{6}Z)/(\d{8}T\d{6}Z)", next(iter(dates)))
    if not match:
        raise ValueError("raleigh_performance_schedule_unresolved")
    start, end = (datetime.strptime(text, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc) for text in match.groups())
    if not _within(start, end, now):
        return []
    if end - start > timedelta(hours=24) or start.astimezone(ZoneInfo(ZONE)).time().isoformat() == "00:00:00":
        raise ValueError("raleigh_performance_schedule_unresolved")
    nodes = soup.select(".rhp-event-description,.rhp-event__description")
    if len(nodes) != 1:
        raise ValueError("raleigh_performance_description_missing")
    return [_row(KOKA, item, start, end, _body(str(nodes[0])))]


def _mmc_page(offset):
    return "https://www.martinmariettacenter.com/events/events_ajax/" + str(offset) + "?" + urlencode(dict(
        category=0, venue=0, team=0, exclude="", per_page=12, came_from_page="event-list-page"))


def _refresh_manifest(state):
    state["manifest_count"] = len(state["queue"])
    state["manifest_hash"] = _hash(state["queue"])
    if len(state["queue"]) > MAX_MANIFEST or len(state["events"]) > MAX_RECORDS:
        raise ValueError("raleigh_performance_record_limit")


def _seal(state):
    _refresh_manifest(state)
    state["payload_hash"] = _hash({k: v for k, v in state.items() if k != "payload_hash"})
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError("raleigh_performance_checkpoint_size_limit")
    return state


def _checkpoint(value, key, now):
    if value is None:
        return None
    try:
        if not isinstance(value, dict) or value["payload_hash"] != _hash({k: v for k, v in value.items() if k != "payload_hash"}):
            raise ValueError
        started = timestamp(value["started_at"])
        if (type(value["version"]) is not int or value["version"] != 1 or value["source_key"] != key
                or not started or started.utcoffset() != timedelta(0) or started > now + timedelta(seconds=60)
                or value["window_start"] != started.astimezone(ZoneInfo(ZONE)).date().isoformat()
                or value["phase"] not in {"listing", "details"} or type(value["listing_complete"]) is not bool
                or value["listing_complete"] != (value["phase"] == "details")
                or not isinstance(value["queue"], list) or len(value["queue"]) > MAX_MANIFEST
                or type(value["manifest_count"]) is not int or value["manifest_count"] != len(value["queue"])
                or value["manifest_hash"] != _hash(value["queue"])
                or type(value["cursor"]) is not int or not 0 <= value["cursor"] <= len(value["queue"])
                or value["phase"] == "listing" and (key != MMC or value["cursor"] or value["events"])
                or not isinstance(value["events"], list) or len(value["events"]) > MAX_RECORDS
                or not isinstance(value["diagnostics"], list) or len(value["diagnostics"]) > MAX_MANIFEST
                or type(value["listing_pages"]) is not int or not 1 <= value["listing_pages"] <= MAX_LIST_PAGES
                or type(value["next_offset"]) is not int or value["next_offset"] != 12 * value["listing_pages"]):
            raise ValueError
        if now - started > timedelta(hours=4):
            return None
        for item in value["queue"]:
            _packet(key, item["url"], item["title"], item["span"], item.get("image"), item.get("room"))
        if len({item["url"] for item in value["queue"]}) != len(value["queue"]):
            raise ValueError
        seen = set()
        for row in value["events"]:
            expected = "raleigh:" + sha256(f'{key}:{row["event_url"]}:{timestamp(row["starts_at"]).astimezone(timezone.utc).isoformat()}'.encode()).hexdigest()
            if (row["id"] in seen or row["id"] != expected or not event_url(key, row["event_url"])
                    or _body(row["description"]) != row["description"]
                    or (row["venue_name"], row["venue_address"], row["venue_city"]) != VENUES[key]
                    or row.get("lat") is not None or row.get("lng") is not None
                    or row.get("timezone") != ZONE or row.get("attendance_mode") != "in_person"
                    or row.get("location_provenance") != PROVENANCE or row.get("location_evidence_url") != SOURCES[key][0]
                    or row.get("image_url") and photo_url(key, row["image_url"]) != row["image_url"]):
                raise ValueError
            seen.add(row["id"])
        for diagnostic in value["diagnostics"]:
            if not event_url(key, diagnostic["event_url"]) or diagnostic["reason"] not in HOLD_CODES or diagnostic["disposition"] != "held":
                raise ValueError
        if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_BYTES:
            raise ValueError
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        raise ValueError("raleigh_performance_checkpoint_invalid") from None
    return deepcopy(value)


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None, max_fetches=MAX_FETCHES):
    key = _source(source)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("raleigh_performance_checkpoint_invalid")
    current = current.astimezone(timezone.utc)
    state = _checkpoint(checkpoint, key, current)
    fetched = 0
    def read(url, accept):
        nonlocal fetched
        if fetched >= max_fetches or deadline_at is not None and monotonic() + MIN_SECONDS >= deadline_at:
            raise ValueError("collection_deadline")
        fetched += 1
        return fetch(url, accept)
    if state is None:
        payload = read(SOURCES[key][0], "text/html")
        native, beyond = [], False
        if key in {LENOVO, MMC}:
            queue, native, beyond = _arena_listing(key, payload, current)
            soup = BeautifulSoup(payload, "html.parser")
            more = soup.select_one("#loadMoreEvents")
            if key == MMC and more and (more.get("data-offset") != "12" or more.get("data-increment") != "12"
                    or len(native) != 12 or any(more.get("data-" + field) != "0" for field in ("category", "venue", "team"))):
                raise ValueError("raleigh_performance_calendar_changed")
            if key == LENOVO and more:
                raise ValueError("raleigh_performance_calendar_changed")
            if not native and not soup.select_one("#eventsList,.event_list"):
                raise ValueError("raleigh_performance_calendar_changed")
            pending_listing = key == MMC and bool(more) and not beyond
        else:
            queue = _improv_listing(payload, current) if key == IMPROV else _koka_listing(payload)
            pending_listing = False
        state = dict(version=1, source_key=key, started_at=current.isoformat(),
            window_start=current.astimezone(ZoneInfo(ZONE)).date().isoformat(),
            phase="listing" if pending_listing else "details", listing_complete=not pending_listing,
            queue=queue, cursor=0, manifest_count=len(queue), manifest_hash=_hash(queue),
            listing_pages=1, next_offset=12, listing_seen=[url for url, _ in native],
            listing_last_day=next((span[0] for _, span in reversed(native) if span), None), events=[], diagnostics=[])
    anchor = timestamp(state["started_at"])
    before = (state["phase"], state["listing_pages"], state["cursor"])
    while state["phase"] == "listing":
        if state["listing_pages"] >= MAX_LIST_PAGES:
            raise ValueError("raleigh_performance_record_limit")
        try:
            payload = read(_mmc_page(state["next_offset"]), "application/json")
        except ValueError as exc:
            if str(exc) == "collection_deadline":
                break
            raise
        try:
            html = json.loads(payload)
            if not isinstance(html, str):
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError("raleigh_performance_calendar_changed") from None
        queue, native, beyond = _arena_listing(key, html, anchor)
        if len(native) > 12 or set(state["listing_seen"]) & {url for url, _ in native}:
            raise ValueError("raleigh_performance_calendar_changed")
        first_day = next((span[0] for _, span in native if span), None)
        if first_day and state["listing_last_day"] and first_day < state["listing_last_day"]:
            raise ValueError("raleigh_performance_calendar_changed")
        state["listing_last_day"] = next((span[0] for _, span in reversed(native) if span), state["listing_last_day"])
        state["queue"].extend(queue)
        state["listing_seen"].extend(url for url, _ in native)
        state["listing_pages"] += 1
        state["next_offset"] += 12
        _refresh_manifest(state)
        if not native or beyond:
            state.update(phase="details", listing_complete=True)
    while state["phase"] == "details" and state["cursor"] < len(state["queue"]):
        item = state["queue"][state["cursor"]]
        try:
            payload = read(item["url"], "text/html")
            rows = (_arena_detail(key, item, payload, anchor) if key in {LENOVO, MMC} else
                    _improv_detail(item, payload, anchor) if key == IMPROV else _koka_detail(item, payload, anchor))
            existing = {row["id"] for row in state["events"]}
            if any(row["id"] in existing for row in rows):
                raise ValueError("raleigh_performance_detail_changed")
            state["events"].extend(rows)
        except ValueError as exc:
            if str(exc) == "collection_deadline":
                break
            if str(exc) not in HOLD_CODES:
                raise
            state["diagnostics"].append(dict(event_url=item["url"], title=item["title"], reason=str(exc), disposition="held"))
        state["cursor"] += 1
        _refresh_manifest(state)
    complete = state["phase"] == "details" and state["listing_complete"] and state["cursor"] == len(state["queue"])
    if not complete and before == (state["phase"], state["listing_pages"], state["cursor"]) and checkpoint is not None:
        raise ValueError("collection_deadline")
    _seal(state)
    return dict(complete=complete, events=deepcopy(sorted(state["events"], key=lambda row: (row["starts_at"], row["id"]))) if complete else [], checkpoint=state)


def collect(source, fetch, *, deadline_at=None, now=None):
    result = collect_chunk(source, fetch, deadline_at=deadline_at, now=now)
    if not result["complete"]:
        raise ValueError("raleigh_performance_checkpoint_required")
    return result["events"]
