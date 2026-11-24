"""Complete, publisher-declared Wix CMS event collections.

Wix custom collections are not Wix Events.  A rendered list is commonly only
the first "Load more" page.  This adapter therefore requires all three public
pieces of evidence before it emits anything:

* a typed Wix CMS schema on the submitted calendar page;
* the site's standard sitemap index and one same-host dynamic sitemap for the
  schema's item-page prefix; and
* CMS records whose item links account for every URL in that sitemap.

No Wix API, token, vendor endpoint or booking-system page is requested.
"""
from datetime import date, datetime, timedelta, timezone
from html import unescape
from html import escape
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import record
from roomquest.registered_native_content import attach


MAX_HTML = 3_000_000
MAX_EVENTS = 500
MAX_DAYS = 60
NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
UUID = re.compile(r"^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$", re.I)
POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.I)
CLOCK = r"\d{1,2}(?::\d{2})?\s*(?:am|pm)"


def _fail(reason):
    raise ValueError("wix_custom_" + reason)


def _plain(value):
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def _html(payload):
    if (not isinstance(payload, str) or len(payload.encode("utf-8")) > MAX_HTML
            or not payload.lstrip("\ufeff \t\r\n").startswith("<")):
        _fail("payload_invalid")
    return BeautifulSoup(payload, "html.parser")


def _warmup(payload):
    soup = _html(payload)
    tags = soup.select('script#wix-warmup-data[type="application/json"]')
    if len(tags) != 1:
        _fail("warmup_missing")
    try:
        data = json.loads(tags[0].string or tags[0].get_text())
        binding = data["appsWarmupData"]["dataBinding"]
    except (KeyError, TypeError, ValueError, RecursionError):
        _fail("warmup_invalid")
    if not isinstance(binding, dict):
        _fail("warmup_invalid")
    return soup, binding


def _contract(url, payload):
    soup, binding = _warmup(payload)
    schemas = binding.get("schemas")
    if not isinstance(schemas, dict):
        _fail("schema_missing")
    path = urlsplit(url).path.rstrip("/") or "/"
    matches = []
    for collection, schema in schemas.items():
        fields = schema.get("fields") if isinstance(schema, dict) else None
        if not isinstance(collection, str) or not isinstance(fields, dict):
            continue
        display = schema.get("displayField")
        if display not in fields or fields[display].get("type") != "text":
            continue
        links = []
        for name, field in fields.items():
            try:
                pattern = field["calculator"]["config"]["pattern"]
            except (KeyError, TypeError):
                continue
            if field.get("type") == "pagelink" and isinstance(pattern, str):
                prefix = pattern.split("{", 1)[0].rstrip("/")
                if prefix == path and pattern.endswith("{" + display + "}"):
                    links.append(name)
        required = {"time", "eventDate", "startDate", "endDate", "occurrenceDate"}
        if len(links) == 1 and "time" in fields and required.intersection(fields):
            matches.append((collection, display, links[0], path))
    if len(matches) != 1:
        _fail("schema_ambiguous")
    collection, title_field, link_field, prefix = matches[0]
    base = urlsplit(url)
    details = []
    for node in soup.select("a[href]"):
        candidate = urljoin(url, node.get("href", ""))
        part = urlsplit(candidate)
        if (part.scheme == "https" and part.netloc == base.netloc and not part.query
                and not part.fragment and part.path.startswith(prefix + "/")):
            details.append(candidate)
    if not details:
        _fail("detail_missing")
    return {"collection": collection, "title": title_field, "link": link_field,
            "prefix": prefix, "first_detail": details[0], "soup": soup}


def supports_listing(url, payload):
    """Return True only for a typed custom collection; malformed matches fail later."""
    try:
        _contract(url, payload)
        return True
    except (ValueError, KeyError, TypeError):
        return False


def compact_capture(payload):
    """Return a replay-equivalent bounded Wix CMS response, or the input.

    Wix application shells repeat megabytes of JavaScript on every detail.
    The durable HTML checkpoint needs only the already-validated typed schema,
    selected CMS fields, visible detail links and publisher venue evidence.
    This keeps one capture below the existing shared 12 MB ceiling without a
    second queue, worker, fetch path or looser request limit.
    """
    if 'id="wix-warmup-data"' not in payload and "id='wix-warmup-data'" not in payload:
        return payload
    try:
        soup, binding = _warmup(payload)
    except (ValueError, KeyError, TypeError):
        return payload
    schemas = binding.get("schemas") if isinstance(binding.get("schemas"), dict) else {}
    stores = binding.get("dataStore", {}).get("recordsByCollectionId", {})
    if not schemas and not stores:
        return payload
    keep = {"_id", "title", "pastEvent", "time", "eventDate", "startDate", "endDate",
            "occurrenceDate", "excludeDates", "dates", "shortProjectDescription",
            "longProjectDescription", "mainProjectImage"}
    compact_stores = {}
    if isinstance(stores, dict):
        for collection, records in stores.items():
            if not isinstance(records, dict):
                continue
            link_fields = set()
            schema = schemas.get(collection, {}) if isinstance(schemas, dict) else {}
            for name, field in schema.get("fields", {}).items() if isinstance(schema, dict) else ():
                if isinstance(field, dict) and field.get("type") == "pagelink":
                    link_fields.add(name)
            compact_stores[collection] = {}
            for identity, item in records.items():
                if not isinstance(item, dict):
                    continue
                selected = {name: value for name, value in item.items()
                            if name in keep or name in link_fields}
                # A short native summary is sufficient evidence; retaining the
                # duplicate rich-content document would defeat compaction.
                if _plain(selected.get("shortProjectDescription")):
                    selected.pop("longProjectDescription", None)
                compact_stores[collection][identity] = selected
    data = {"appsWarmupData": {"dataBinding": {"schemas": schemas,
             "dataStore": {"recordsByCollectionId": compact_stores}}}}
    meta = soup.select('meta[property="og:site_name"][content]')
    footer = soup.select("footer")
    links = []
    for node in soup.select("a[href]")[:1000]:
        links.append('<a href="%s">%s</a>' % (
            escape(node.get("href", ""), quote=True), escape(node.get_text(" ", strip=True))))
    shell = ["<html><head>"]
    if len(meta) == 1:
        shell.append('<meta property="og:site_name" content="%s">' %
                     escape(meta[0].get("content", ""), quote=True))
    shell.append('</head><body><script id="wix-warmup-data" type="application/json">')
    shell.append(json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/"))
    shell.append("</script>")
    shell.extend(links)
    if len(footer) == 1:
        shell.append("<footer>%s</footer>" % escape(footer[0].get_text(" ", strip=True)))
    shell.append("</body></html>")
    result = "".join(shell)
    return result if len(result.encode("utf-8")) <= MAX_HTML else payload


def _xml(payload, root_name):
    if (not isinstance(payload, str) or len(payload.encode("utf-8")) > MAX_HTML
            or "<!DOCTYPE" in payload.upper() or "<!ENTITY" in payload.upper()):
        _fail("sitemap_invalid")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        _fail("sitemap_invalid")
    if root.tag != NS + root_name:
        _fail("sitemap_invalid")
    return root


def _sitemap_child(base_url, payload):
    root = _xml(payload, "sitemapindex")
    base = urlsplit(base_url)
    candidates = []
    for node in root.findall(NS + "sitemap"):
        loc = node.findtext(NS + "loc")
        part = urlsplit(loc or "")
        if (part.scheme == "https" and part.netloc == base.netloc and not part.query
                and not part.fragment and re.fullmatch(r"/dynamic-[a-z0-9_%.-]+-sitemap\.xml",
                                                       part.path, re.I)):
            candidates.append(loc)
    if len(candidates) != 1:
        _fail("sitemap_ambiguous")
    return candidates[0]


def _manifest(base_url, prefix, payload):
    root = _xml(payload, "urlset")
    base = urlsplit(base_url)
    result = []
    for node in root.findall(NS + "url"):
        loc = node.findtext(NS + "loc")
        part = urlsplit(loc or "")
        if (part.scheme != "https" or part.netloc != base.netloc or part.query or part.fragment
                or not part.path.startswith(prefix + "/") or part.path == prefix + "/"):
            _fail("manifest_scope_invalid")
        result.append(loc)
    if not result or len(result) > MAX_EVENTS or len(set(result)) != len(result):
        _fail("manifest_limit")
    return result


def _records(contract, payload):
    _soup, binding = _warmup(payload)
    try:
        records = binding["dataStore"]["recordsByCollectionId"][contract["collection"]]
    except (KeyError, TypeError):
        _fail("records_missing")
    if not isinstance(records, dict) or len(records) > MAX_EVENTS:
        _fail("records_invalid")
    result = {}
    for identity, item in records.items():
        if (not UUID.fullmatch(str(identity)) or not isinstance(item, dict)
                or str(item.get("_id", "")).casefold() != str(identity).casefold()):
            _fail("record_identity_invalid")
        result[str(identity).casefold()] = item
    return result


def _rich_text(value):
    found = []
    def walk(node, depth=0):
        if depth > 20:
            return
        if isinstance(node, dict):
            text = node.get("textData", {}).get("text") if isinstance(node.get("textData"), dict) else None
            if isinstance(text, str):
                found.append(text)
            for child in node.values():
                walk(child, depth + 1)
        elif isinstance(node, list):
            for child in node[:1000]:
                walk(child, depth + 1)
    walk(value)
    return _plain(" ".join(found))


def _image(value):
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"wix:image://v1/([^/#?]+\.(?:jpe?g|png|webp))/[^#]*#.*", value, re.I)
    return "https://static.wixstatic.com/media/" + match[1] if match else None


def _venue(soup):
    sites = soup.select('meta[property="og:site_name"][content]')
    footers = soup.select("footer")
    if len(sites) != 1 or len(footers) != 1:
        _fail("venue_unresolved")
    name = _plain(sites[0].get("content"))
    text = _plain(footers[0].get_text(" ", strip=True))
    if not name or name.casefold() not in text.casefold():
        _fail("venue_unresolved")
    # Bound the publisher-authored address to the text before charity/company
    # boilerplate.  Require a street number, London and a GB postcode.
    prefix = re.split(r"\b(?:Charity|Company|VAT)\s+No\b", text, maxsplit=1, flags=re.I)[0]
    match = re.search(r"\b(\d{1,5}\s+.+?\bLondon\s+" + POSTCODE.pattern + r")\b", prefix, re.I)
    if not match:
        _fail("venue_unresolved")
    return name, _plain(match[1]) + ", United Kingdom", "London"


def _clock(raw):
    compact = re.sub(r"\s+", "", raw).upper()
    return datetime.strptime(compact, "%I:%M%p" if ":" in compact else "%I%p").time()


def _stamp(day, raw, zone):
    value = datetime.combine(day, _clock(raw)).replace(tzinfo=zone)
    if (value.utcoffset() != value.replace(fold=1).utcoffset()
            or value.astimezone(timezone.utc).astimezone(zone) != value):
        _fail("schedule_invalid")
    return value


def _occurrences(item, first, last):
    """Return only explicitly described dates and clocks; skip vague records."""
    raw_time = _plain(item.get("time"))
    days = []
    for field in ("eventDate",):
        if isinstance(item.get(field), str):
            days.append(date.fromisoformat(item[field]))
    if isinstance(item.get("occurrenceDate"), list):
        days.extend(date.fromisoformat(str(value)) for value in item["occurrenceDate"])
    # Some Wix publishers use an array field named excludeDates as the actual
    # occurrence list. Accept it only when the visible dates label enumerates
    # multiple day/month values and there is no range boundary to contradict it.
    if (not days and not item.get("startDate") and not item.get("endDate")
            and isinstance(item.get("excludeDates"), list)
            and len(re.findall(r"\b\d{1,2}\s+[A-Z]{3}\b", _plain(item.get("dates")), re.I)) >= 2):
        days.extend(date.fromisoformat(str(value)) for value in item["excludeDates"])
    schedules = []
    single = re.fullmatch(r"(" + CLOCK + r")", raw_time, re.I)
    span = re.fullmatch(r"(" + CLOCK + r")\s*[-–—]\s*(" + CLOCK + r")", raw_time, re.I)
    shorthand = re.fullmatch(r"(\d{1,2}(?::\d{2})?)\s*[-–—]\s*(" + CLOCK + r")",
                             raw_time, re.I)
    if not span and shorthand:
        half = re.search(r"(am|pm)\s*$", shorthand[2], re.I)
        if half:
            span = (shorthand[0], shorthand[1] + half[1], shorthand[2])
    if days and (single or span):
        for day in days:
            schedules.append((day, single[1] if single else span[1], None if single else span[2]))
        return schedules

    start_raw, end_raw = item.get("startDate"), item.get("endDate")
    label = _plain(item.get("dates"))
    if not isinstance(start_raw, str):
        return []
    start = date.fromisoformat(start_raw)
    finish = date.fromisoformat(end_raw) if isinstance(end_raw, str) else last
    finish = min(finish, last)
    weekday_names = {name[:3].casefold(): i for i, name in enumerate(
        ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"))}
    # "EVERY SUNDAY" and "7:30PM (TUES - SAT) 2:30PM (SAT)" are finite,
    # publisher-written recurrence rules. No unlabeled date range is expanded.
    every = re.fullmatch(r"EVERY\s+([A-Z]+)", label, re.I)
    if every and (single or span):
        wanted = weekday_names.get(every[1][:3].casefold())
        if wanted is None:
            return []
        day = max(start, first)
        while day <= finish:
            if day.weekday() == wanted:
                schedules.append((day, single[1] if single else span[1], None if single else span[2]))
            day += timedelta(days=1)
        return schedules
    parts = re.findall(r"(" + CLOCK + r")\s*\(([A-Z]{3,9})(?:\s*[-–—]\s*([A-Z]{3,9}))?\)",
                       raw_time, re.I)
    if not parts or not end_raw:
        return []
    rules = []
    for clock, a, b in parts:
        left, right = weekday_names.get(a[:3].casefold()), weekday_names.get((b or a)[:3].casefold())
        if left is None or right is None:
            return []
        active = set(range(left, right + 1)) if left <= right else set(range(left, 7)) | set(range(0, right + 1))
        rules.append((clock, active))
    day = max(start, first)
    while day <= finish:
        for clock, active in rules:
            if day.weekday() in active:
                schedules.append((day, clock, None))
        day += timedelta(days=1)
    excluded = set()
    if isinstance(item.get("excludeDates"), list):
        for value in item["excludeDates"]:
            match = re.search(r"20\d{2}-\d{2}-\d{2}", str(value))
            if match:
                excluded.add(date.fromisoformat(match[0]))
    return [entry for entry in schedules if entry[0] not in excluded]


def _project(source, contract, records, manifest, listing_soup, first, last):
    venue, address, city = _venue(listing_soup)
    manifest_set = set(manifest)
    base = source["feed_url"]
    result = {}
    for identity, item in records.items():
        link = item.get(contract["link"])
        event_url = urljoin(base, link) if isinstance(link, str) else ""
        if event_url not in manifest_set:
            _fail("record_scope_invalid")
        title = _plain(item.get(contract["title"]))
        if not title:
            _fail("record_identity_invalid")
        if item.get("pastEvent") is True:
            continue
        try:
            occurrences = _occurrences(item, first, last)
        except (ValueError, TypeError, OverflowError):
            _fail("schedule_invalid")
        for index, (day, begins_raw, ends_raw) in enumerate(occurrences):
            if not first <= day <= last:
                continue
            zone = ZoneInfo("Europe/London")
            begins = _stamp(day, begins_raw, zone)
            ends = _stamp(day, ends_raw, zone) if ends_raw else None
            if ends is not None and ends <= begins:
                _fail("schedule_invalid")
            event_id = "wixcms:" + identity + ":" + day.isoformat() + ":" + str(index)
            row = record(title, begins.isoformat(), ends.isoformat() if ends else None,
                         venue, address, city, event_url, event_id, tz=zone.key)
            if row is None:
                continue
            description = _plain(item.get("shortProjectDescription"))
            if not description:
                description = _rich_text(item.get("longProjectDescription"))
            attach(row, source, description_value=description,
                   image_value=_image(item.get("mainProjectImage")), evidence_url=event_url)
            result[(row["id"], row["starts_at"])] = row
    return sorted(result.values(), key=lambda row: (row["starts_at"], row["id"]))


def stream(source, listing_url, listing, *, deadline_at=None):
    """Yield the exact complete public traversal used by intake and refresh."""
    contract = _contract(listing_url, listing)
    base = urlsplit(listing_url)
    root_url = base._replace(path="/sitemap.xml", query="", fragment="").geturl()
    sitemap_index = yield (root_url, "application/xml,text/xml")
    child = _sitemap_child(listing_url, sitemap_index)
    sitemap = yield (child, "application/xml,text/xml")
    manifest = _manifest(listing_url, contract["prefix"], sitemap)
    records = {}
    pending = [contract["first_detail"]] + [url for url in manifest if url != contract["first_detail"]]
    fetched = set()
    while pending:
        target = pending.pop(0)
        if target in fetched:
            _fail("manifest_incomplete")
        fetched.add(target)
        payload = yield (target, "text/html,application/xhtml+xml")
        records.update(_records(contract, payload))
        known = {urljoin(listing_url, item.get(contract["link"], ""))
                 for item in records.values() if isinstance(item.get(contract["link"]), str)}
        missing = [url for url in manifest if url not in known]
        if not missing:
            break
        pending = [url for url in missing if url not in fetched]
    known = {urljoin(listing_url, item.get(contract["link"], ""))
             for item in records.values() if isinstance(item.get(contract["link"]), str)}
    if known != set(manifest):
        _fail("manifest_incomplete")
    today = datetime.now(timezone.utc).date()
    return _project(source, contract, records, manifest, contract["soup"],
                    today, today + timedelta(days=MAX_DAYS - 1))
