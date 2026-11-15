"""Atlantic County Fair Events' complete public GoDaddy calendar.

The visible calendar deliberately abbreviates descriptions. Its own published
GoDaddy data script contains the complete DraftJS blocks, which are decoded as
data without executing JavaScript. The current craft-bazaar detail contributes
every native content section as well. All three requests use the ordinary
guarded worker callback; no denied calendar, API, authentication or proxy is used.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import json
import re
from time import monotonic
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.atlantic_city_reviewed_posters import _literal_objects
from roomquest.atlantic_city_venues import narrative
from roomquest.mapsee_adapter import record


ZONE = "America/New_York"
FAIR = "atlantic_county_4h_fair_nj"
SOURCES = {FAIR: ("https://acfairevents.com/", "html", "html")}
ALLOWED_HOSTS = {FAIR: ("acfairevents.com", "img1.wsimg.com")}
CHECKPOINT_KEYS = frozenset()
SITE = "aceb05a0-0562-4756-87f0-5d662f332bcf"
PAGE = "53bdd38f-8df2-4cc1-bc1e-3d3e8707f6d6"
WIDGET = "c16684ed-7616-4f95-a66e-262b39562cc6"
VENUE = "Atlantic County 4-H Fairgrounds"
ADDRESS = "3210 State Highway 50, Mays Landing, NJ 08330"
CITY = "Mays Landing"
# NJ Office of GIS exact canonical address, score100 PointAddress. These
# literals bind the destination to this source, name and complete street only.
REVIEWED_VENUE_POINTS = {
    (FAIR, "Atlantic County 4-H Fairgrounds", "3210 State Highway 50, Mays Landing, NJ 08330"):
        (39.516678000003, -74.660746500001),
}
MAX_DESCRIPTION = 12000
MAX_EVENTS = 80
MAX_RECORDS = 160
UUID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}")
MONTHS = {name: n for n, names in enumerate((
    (), ("Jan", "January"), ("Feb", "February"), ("Mar", "March"),
    ("Apr", "April"), ("May",), ("Jun", "June"), ("Jul", "July"),
    ("Aug", "August"), ("Sep", "September"), ("Oct", "October"),
    ("Nov", "November"), ("Dec", "December"))) for name in names}
NONPUBLIC = re.compile(r"\b(?:cancell?ed|postponed|private event|members?[- ]only|sold[- ]out)\b", re.I)


def event_url(key, value):
    if key != FAIR or not isinstance(value, str) or len(value) > 300:
        return False
    try:
        p = urlsplit(value)
        return (p.scheme == "https" and p.netloc == "acfairevents.com" and not p.query and not p.fragment
                and (p.path == "/" or re.fullmatch(r"/20\d{2}-holiday-craft-bazaar", p.path) is not None))
    except ValueError:
        return False


def photo_url(key, value):
    # The detail's gift-box picture is generic stock, not event artwork.
    return None


def reviewed_venue_location(key, venue, address):
    return REVIEWED_VENUE_POINTS.get((key, venue, address))


def _source(source):
    if (not isinstance(source, dict) or source.get("source_key") != FAIR
            or tuple(source.get(k) for k in ("feed_url", "kind", "platform_adapter")) != SOURCES[FAIR]
            or source.get("timezone") != ZONE):
        raise ValueError("unregistered_atlantic_remaining_fair_source")


def _get(fetch, url, accept, deadline_at):
    if deadline_at is not None and monotonic() + 2 >= deadline_at:
        raise ValueError("collection_deadline")
    payload = fetch(url, accept)
    if not isinstance(payload, str) or not payload or len(payload) > 3_000_000:
        raise ValueError("atlantic_fair_payload_changed")
    return payload


def _plain(value):
    # Native DraftJS strings are already plain text. Never HTML-parse them.
    return " ".join(value.split()) if isinstance(value, str) else ""


def _description(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("atlantic_city_description_missing")
    if len(value) > MAX_DESCRIPTION:
        raise ValueError("atlantic_city_description_limit")
    if re.search(r"(?:\.\.\.|…)\s*$", value):
        raise ValueError("atlantic_fair_description_incomplete")
    return value


def _draft(raw):
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        raise ValueError("atlantic_fair_description_shape_changed") from None
    blocks = obj.get("blocks") if isinstance(obj, dict) else None
    if (not isinstance(blocks, list) or not blocks or len(blocks) > 200
            or not isinstance(obj.get("entityMap"), dict)):
        raise ValueError("atlantic_fair_description_shape_changed")
    lines = []
    for block in blocks:
        if (not isinstance(block, dict) or not isinstance(block.get("text"), str)
                or block.get("type") not in {"unstyled", "paragraph", "unordered-list-item", "ordered-list-item",
                                              "header-one", "header-two", "header-three", "blockquote"}):
            raise ValueError("atlantic_fair_description_shape_changed")
        # Preserve every character other than equivalent whitespace, including
        # literal angle brackets and all final registration/eligibility text.
        text = _plain(block["text"])
        if text:
            lines.append(text)
    return _description("\n".join(lines))


def _days(value):
    value = re.sub(r"(?<=\d)(?:st|nd|rd|th)\b", "", _plain(value), flags=re.I)
    m = re.fullmatch(r"([A-Za-z]+)\s+(\d{1,2})(?:\s*(?:&|and)\s*(\d{1,2}))?,\s*(20\d{2})", value)
    if not m or m[1] not in MONTHS:
        raise ValueError("atlantic_fair_date_changed")
    try:
        days = [date(int(m[4]), MONTHS[m[1]], int(m[2]))]
        if m[3]:
            days.append(date(int(m[4]), MONTHS[m[1]], int(m[3])))
        if days != sorted(set(days)):
            raise ValueError
        return days
    except ValueError:
        raise ValueError("atlantic_fair_date_changed") from None


def _clock(value):
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", _plain(value), re.I)
    if not m or not 1 <= int(m[1]) <= 12 or int(m[2] or 0) > 59:
        raise ValueError("atlantic_fair_clock_changed")
    return time(int(m[1]) % 12 + (12 if m[3].lower() == "pm" else 0), int(m[2] or 0))


def _clocks(start, end):
    if not isinstance(start, str) or not isinstance(end, str):
        raise ValueError("atlantic_fair_clock_changed")
    span = re.split(r"\s*[-–]\s*", start)
    if len(span) == 2 and not end.strip():
        start, end = span
    elif len(span) != 1:
        raise ValueError("atlantic_fair_clock_changed")
    begins, ends = _clock(start), _clock(end) if end.strip() else None
    if ends and ends <= begins:
        raise ValueError("atlantic_fair_clock_changed")
    return begins, ends


def _page(raw, url):
    soup = BeautifulSoup(raw, "html.parser")
    if [x.get("href") for x in soup.select('link[rel="canonical"]')] != [url]:
        raise ValueError("atlantic_fair_page_identity")
    return soup


def _script_url(value):
    try:
        p = urlsplit(value)
        return (p.scheme == "https" and p.netloc == "img1.wsimg.com" and not p.query and not p.fragment
                and re.fullmatch(r"/blobby/go/" + SITE + r"/gpub/[a-f0-9]{16}/script\.js", p.path) is not None)
    except (ValueError, TypeError):
        return False


def _data_script(soup):
    # This publisher emits its bootstrap before UX and its literal public
    # widget data after UX. Enforce that observed layout; never guess a CDN URL.
    scripts = [urljoin(SOURCES[FAIR][0], x["src"]) for x in soup.select("script[src]")]
    sites = [(i, u) for i, u in enumerate(scripts) if _script_url(u)]
    ux = [i for i, u in enumerate(scripts) if re.fullmatch(
        r"https://img1\.wsimg\.com/ceph-p3-01/website-builder-data-prod/static/widgets/UX\.\d+\.\d+\.\d+\.js", u)]
    if (len(sites) != 2 or len({u for _, u in sites}) != 2 or len(ux) != 1
            or not sites[0][0] < ux[0] < sites[1][0]):
        raise ValueError("atlantic_fair_manifest_changed")
    return sites[1][1]


def _manifest(soup, script):
    widgets = soup.select('[data-ux="Widget"][id="' + WIDGET + '"]')
    objects = [o for o in _literal_objects(script) if o.get("id") == WIDGET and "manualEvents" in o]
    if len(widgets) != 1 or len(objects) != 1:
        raise ValueError("atlantic_fair_manifest_changed")
    obj = objects[0]
    if (any(obj.get(k) != v for k, v in {"websiteId": SITE, "pageId": PAGE,
            "id": WIDGET, "widgetId": WIDGET, "env": "production", "renderMode": "PUBLISH"}.items())
            or obj.get("isManual") is not True or obj.get("visitorMode") is not True
            or obj.get("detachedMode") is not False or obj.get("icalURL") != ""):
        raise ValueError("atlantic_fair_manifest_changed")
    items = obj["manualEvents"]
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_EVENTS:
        raise ValueError("atlantic_fair_manifest_changed")
    cards = widgets[0].select('[data-aid="CALENDAR_BIGGER_SCREEN_CONTAINER"]')
    if len(cards) != len(items):
        raise ValueError("atlantic_fair_manifest_incomplete")
    ids = set()
    for item, card in zip(items, cards):
        if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                or not UUID.fullmatch(item["id"]) or item["id"] in ids
                or any(not isinstance(item.get(k), str) for k in ("date", "title", "desc", "start", "end", "location"))):
            raise ValueError("atlantic_fair_event_identity")
        ids.add(item["id"])
        if not item["title"].strip() or len(item["title"]) > 180:
            raise ValueError("atlantic_fair_event_identity")
        for aid, field in (("CALENDAR_EVENT_DATE", "date"), ("CALENDAR_EVENT_TITLE", "title")):
            values = card.select('[data-aid="' + aid + '"]')
            if len(values) != 1 or _plain(values[0].get_text(" ")) != _plain(item[field]):
                raise ValueError("atlantic_fair_manifest_incomplete")
        clocks = card.select('[data-aid="CALENDAR_EVENT_TIME"]')
        if (len(clocks) != 1 or _clocks(clocks[0].get_text(" "), "")
                != _clocks(item["start"], item["end"])):
            raise ValueError("atlantic_fair_manifest_incomplete")
        if _plain(item["location"]).upper() != "ATLANTIC COUNTY FAIRGROUNDS":
            raise ValueError("atlantic_fair_venue_changed")
    return items


def _craft(soup, item, days, clocks, fetch, deadline_at):
    years = {d.year for d in days}
    if len(years) != 1:
        raise ValueError("atlantic_fair_date_changed")
    year = days[0].year
    expected = SOURCES[FAIR][0] + str(year) + "-holiday-craft-bazaar"
    urls = {urljoin(SOURCES[FAIR][0], x["href"]) for x in soup.select("a[href]")
            if _plain(x.get_text(" ")) == f"{year} Holiday Craft Bazaar"}
    if urls != {expected} or not event_url(FAIR, expected):
        raise ValueError("atlantic_fair_detail_missing")
    detail = _page(_get(fetch, expected, "text/html", deadline_at), expected)
    headings = detail.select('[data-aid="CONTENT_SECTION_TITLE_RENDERED"]')
    if len(headings) != 1 or _plain(headings[0].get_text(" ")) != f"{year} Holiday Craft Bazaar":
        raise ValueError("atlantic_fair_detail_identity")
    heads = detail.select('[data-aid^="CONTENT_HEADLINE"][data-aid$="_RENDERED"]')
    bodies = detail.select('[data-aid^="CONTENT_DESCRIPTION"][data-aid$="_RENDERED"]')
    if not 2 <= len(heads) <= 20 or len(heads) != len(bodies):
        raise ValueError("atlantic_fair_description_shape_changed")
    sections = []
    for n, (head, body) in enumerate(zip(heads, bodies), 1):
        if head.get("data-aid") != f"CONTENT_HEADLINE{n}_RENDERED" or body.get("data-aid") != f"CONTENT_DESCRIPTION{n}_RENDERED":
            raise ValueError("atlantic_fair_description_shape_changed")
        sections.append((narrative(str(head)), narrative(str(body))))
    if sections[0][0] != "Time Date & Location" or sections[1][0] != "What to Expect":
        raise ValueError("atlantic_fair_detail_identity")
    lines = sections[0][1].splitlines()
    if (len(lines) != 5 or _days(lines[0] + ", " + str(year)) != days
            or _clocks(lines[1], "") != clocks
            or lines[2:] != ["Atlantic County 4H Fairgrounds", "3210 NJ-50", "Mays Landing, NJ"]):
        raise ValueError("atlantic_fair_detail_schedule_changed")
    # Preserve the native event-level calendar body and every full detail
    # section. The publisher's legacy '2025 Vendors' heading stays verbatim;
    # event year is determined by the current explicit title and dated card.
    text = _draft(item["desc"]) + "\n\n" + "\n\n".join(h + "\n" + b for h, b in sections)
    return expected, _description(text)


def collect(source, fetch, *, deadline_at=None, now=None):
    _source(source)
    current = now or datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise ValueError("atlantic_fair_timezone_required")
    soup = _page(_get(fetch, SOURCES[FAIR][0], "text/html", deadline_at), SOURCES[FAIR][0])
    script = _get(fetch, _data_script(soup), "application/javascript", deadline_at)
    items = _manifest(soup, script)
    rows = []
    zone = ZoneInfo(ZONE)
    point = reviewed_venue_location(FAIR, VENUE, ADDRESS)
    if point is None:
        raise ValueError("atlantic_fair_venue_changed")
    for item in items:
        days, clocks = _days(item["date"]), _clocks(item["start"], item["end"])
        occurrences = [(datetime.combine(d, clocks[0], zone),
                        datetime.combine(d, clocks[1], zone) if clocks[1] else None) for d in days]
        occurrences = [(s, e) for s, e in occurrences
                       if s < current + timedelta(days=60) and (e or s) > current]
        if not occurrences or NONPUBLIC.search(item["title"]):
            continue
        url, body = SOURCES[FAIR][0], _draft(item["desc"])
        if item["title"] == "Holiday Craft Bazaar":
            url, body = _craft(soup, item, days, clocks, fetch, deadline_at)
        for start, end in occurrences:
            row = record(item["title"], start.isoformat(), end.isoformat() if end else None,
                         VENUE, ADDRESS, CITY, url, FAIR + ":" + item["id"] + ":" + start.date().isoformat(),
                         "", *point, tz=ZONE, publisher_geo=True, retain_until_end=True)
            if row is not None:
                row.update(description=_description(body), timezone=ZONE, attendance_mode="in_person",
                           location_provenance="reviewed_nj_ogis_point_address")
                rows.append(row)
    if len(rows) > MAX_RECORDS or len({(r["id"], r["starts_at"]) for r in rows}) != len(rows):
        raise ValueError("atlantic_fair_record_limit")
    return sorted(rows, key=lambda r: (r["starts_at"], r["title"]))
