"""Strict WordPress event-detail structures without Event JSON-LD.

These are reusable structural contracts, not publisher host exceptions.  Each
reader requires an individual canonical detail, one title and an explicit
publisher-authored schedule.  It never substitutes post publication dates.
"""
from datetime import date, datetime, timedelta, timezone
import json
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import record
from roomquest.registered_native_content import attach


MONTHS = {name.casefold(): number for number, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"), 1)}
POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.I)
CLOCK = r"\d{1,2}(?::\d{2})?\s*(?:am|pm)"


def _plain(value):
    return re.sub(r"\s+", " ", value or "").strip()


def _meta(soup, property_name):
    nodes = soup.select(f'meta[property="{property_name}"][content]')
    return _plain(nodes[0].get("content")) if len(nodes) == 1 else ""


def _time(raw):
    compact = _plain(raw).replace(".", ":").replace(" ", "").upper()
    return datetime.strptime(compact, "%I:%M%p" if ":" in compact else "%I%p").time()


def _moments(day, raw):
    raw = _plain(raw).replace(".", ":")
    full = re.fullmatch(r"(" + CLOCK + r")\s*[-–—]\s*(" + CLOCK + r")", raw, re.I)
    short = re.fullmatch(r"(\d{1,2}(?::\d{2})?)\s*[-–—]\s*(" + CLOCK + r")", raw, re.I)
    if full:
        a, b = full[1], full[2]
    elif short:
        half = re.search(r"(am|pm)\s*$", short[2], re.I)
        if not half:
            return None
        a, b = short[1] + half[1], short[2]
    else:
        one = re.fullmatch("(" + CLOCK + ")", raw, re.I)
        if not one:
            return None
        a, b = one[1], None
    zone = ZoneInfo("Europe/London")
    try:
        start = datetime.combine(day, _time(a)).replace(tzinfo=zone)
        end = datetime.combine(day, _time(b)).replace(tzinfo=zone) if b else None
    except ValueError:
        return None
    for value in (start, end):
        if value is not None and (value.utcoffset() != value.replace(fold=1).utcoffset()
                or value.astimezone(timezone.utc).astimezone(zone) != value):
            return None
    if end is not None and end <= start:
        return None
    return start, end


def _date(raw):
    clean = re.sub(r"(?<=\d)(?:st|nd|rd|th)\b", "", _plain(raw), flags=re.I)
    clean = re.sub(r"^[A-Za-z]+\s+", "", clean, flags=re.I)
    match = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\s+(20\d{2})", clean, re.I)
    if not match:
        return None
    month = MONTHS.get(match[2].casefold()) or next(
        (number for name, number in MONTHS.items() if name.startswith(match[2].casefold())), None)
    try:
        return date(int(match[3]), month, int(match[1])) if month else None
    except ValueError:
        return None


def _row(source, soup, url, title, day, raw_time, venue, address="", description=""):
    times = _moments(day, raw_time)
    if not title or not venue or times is None:
        return None
    start, end = times
    row = record(title, start.isoformat(), end.isoformat() if end else None, venue,
                 address, "London", url, url + "#wordpress-visible", tz="Europe/London")
    if row is None:
        return []
    row["timezone"] = "Europe/London"
    images = soup.select('meta[property="og:image"][content]')
    attach(row, source, description_value=description,
           image_value=images[0].get("content") if len(images) == 1 else None,
           evidence_url=url)
    return [row]


def _labeled_blocks(source, soup, url):
    main = soup.find("main") or soup.find(attrs={"role": "main"})
    blocks = main.select(".page--header__event-details > .event-detail") if main else []
    if not blocks:
        return None
    fields = {}
    for block in blocks:
        labels = block.select(":scope > .event-detail__title")
        values = block.select(":scope > .event-detail__info")
        if len(labels) != 1 or len(values) != 1:
            return None
        key = _plain(labels[0].get_text(" ", strip=True)).casefold()
        if key in fields:
            return None
        fields[key] = _plain(values[0].get_text(" ", strip=True))
    titles = main.select(".page--header--event h1")
    scripts = soup.select('script#json-data[type="application/json"]')
    if (len(titles) == 1 and re.search(r"\b(?:permanent|ongoing|year-round|"
            r"opening hours|museum opening)\b", fields.get("date", ""), re.I)
            and not scripts):
        return []
    if len(titles) != 1 or len(scripts) != 1 or not fields.get("where"):
        return None
    try:
        sessions = json.loads(scripts[0].string or scripts[0].get_text())
    except (TypeError, ValueError, RecursionError):
        return None
    if not isinstance(sessions, list) or not 1 <= len(sessions) <= 300:
        return None
    # The visible summary and embedded booking sessions must agree for a
    # single-session event; multi-session pages use the full embedded list.
    visible_day = _date(fields.get("date", ""))
    visible_time = fields.get("time", "")
    where_node = next((block.select_one(":scope > .event-detail__info") for block in blocks
                       if _plain((block.select_one(":scope > .event-detail__title") or "")
                                 .get_text(" ", strip=True)).casefold() == "where"), None)
    where_lines = [_plain(value) for value in where_node.stripped_strings] if where_node else []
    venue = where_lines[0] if where_lines else ""
    address = fields["where"]
    if POSTCODE.search(address) and not re.search(r"\bLondon\b", address, re.I):
        published = [_plain(node.get_text(" ", strip=True)) for node in soup.select("footer address")
                     if POSTCODE.search(_plain(node.get_text(" ", strip=True)))
                     and re.search(r"\bLondon\b", _plain(node.get_text(" ", strip=True)), re.I)]
        if len(published) == 1 and POSTCODE.search(published[0]).group().replace(" ", "").casefold() == (
                POSTCODE.search(address).group().replace(" ", "").casefold()):
            address = published[0]
    if not POSTCODE.search(address) or not re.search(r"\bLondon\b", address, re.I):
        return None
    rows = []
    for session in sessions:
        if (not isinstance(session, dict) or session.get("session_status") != "Active"
                or not isinstance(session.get("session_id"), int)):
            continue
        try:
            day = date.fromisoformat(session["start_date"])
            start = datetime.strptime(session["start_time"], "%H:%M:%S").strftime("%I:%M%p")
            end = datetime.strptime(session["end_time"], "%H:%M:%S").strftime("%I:%M%p")
        except (KeyError, TypeError, ValueError):
            return None
        if len(sessions) == 1:
            visible = _moments(visible_day, visible_time) if visible_day else None
            embedded = _moments(day, start + "-" + end)
            if not visible or not embedded or visible != embedded:
                return None
        result = _row(source, soup, url, _plain(titles[0].get_text(" ", strip=True)), day,
                      start + "-" + end, venue, address,
                      _plain((main.select_one(".page--header__introduction") or "").get_text(
                          " ", strip=True)) if main.select_one(".page--header__introduction") else "")
        if result:
            result[0]["id"] += ":" + str(session["session_id"])
            # Native proof binds identity too; reattach after session suffix.
            attach(result[0], source,
                   description_value=result[0].get("description", ""), evidence_url=url)
            rows.extend(result)
    return rows


def listing_evidence(soup, base_url):
    """Bind yearless theme cards to the listing's exact dated filter options."""
    available = []
    for option in soup.select('select option[value*="?date="]'):
        match = re.search(r"[?&]date=(20\d{2}-\d{2}-\d{2})(?:&|$)", option.get("value", ""))
        if match:
            try:
                available.append(date.fromisoformat(match[1]))
            except ValueError:
                return {}
    result = {}
    for card in soup.select("article.type-events"):
        links = card.select("h2.entry-title a[href]")
        schedules = card.select(".eventdates")
        if len(links) != 1 or len(schedules) != 1:
            continue
        target = urljoin(base_url, links[0].get("href", ""))
        if urlsplit(target).hostname != urlsplit(base_url).hostname:
            continue
        displayed = _plain(schedules[0].get_text(" ", strip=True))
        explicit = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(20\d{2})\b",
                             displayed, re.I)
        if explicit:
            day = _date("%s %s %s" % (explicit[1], explicit[2], explicit[3]))
        else:
            partial = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\b",
                                displayed, re.I)
            matches = [value for value in available if partial and value.day == int(partial[1])
                       and value.month == (MONTHS.get(partial[2].casefold()) or next(
                           (number for name, number in MONTHS.items()
                            if name.startswith(partial[2].casefold())), -1))]
            day = matches[0] if len(matches) == 1 else None
        result[target] = {"display": displayed, "date": day.isoformat() if day else None}
    return result


def _entry_header(source, soup, url, evidence=None):
    headers = soup.select("header.entry-header")
    if len(headers) != 1:
        return None
    titles, dates, venues = (headers[0].select(selector) for selector in
                             ("h1.entry-title", ".eventdates", ".eventvenue"))
    descriptions = soup.select('meta[property="og:description"][content]')
    if len(titles) == len(descriptions) == 1 and dates and not venues:
        return []  # Explicit event page, but no publisher location to resolve.
    if not (len(titles) == len(dates) == len(venues) == len(descriptions) == 1):
        return None
    displayed = _plain(dates[0].get_text(" ", strip=True))
    meta = _plain(descriptions[0].get("content"))
    if re.search(r"\b(?:apply before|term time|year-round|opportunities|initiatives|"
                 r"performances across)\b", displayed, re.I):
        return []
    match = re.match(r"^(?:[A-Za-z]+\s+)?"
                     r"(\d{1,2})\s+([A-Za-z]+)\s+(20\d{2}),\s*(" + CLOCK + r")\b",
                     meta, re.I)
    shown = re.match(r"^(?:[A-Za-z]+\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+),\s*(.+)$",
                     displayed, re.I)
    if not shown:
        return None
    if match:
        if ((match[1].lstrip("0"), match[2].casefold(), match[4].replace(" ", "").casefold()) !=
                (shown[1].lstrip("0"), shown[2].casefold(), shown[3].replace(" ", "").casefold())):
            return None
        day = _date(f"{match[1]} {match[2]} {match[3]}")
    elif (isinstance(evidence, dict) and evidence.get("display") == displayed
          and isinstance(evidence.get("date"), str)):
        try:
            day = date.fromisoformat(evidence["date"])
        except ValueError:
            return None
    else:
        return None
    if day and not datetime.now(timezone.utc).date() <= day <= datetime.now(timezone.utc).date() + timedelta(days=59):
        return []
    venue = _plain(venues[0].get_text(" ", strip=True))
    blocks = soup.select(".venueinfo")
    candidates = []
    for block in blocks:
        text = _plain(block.get_text(" ", strip=True))
        if venue.casefold() in text.casefold() and POSTCODE.search(text) and "London" in text:
            before = re.split(r"\bGet directions\b", text, maxsplit=1, flags=re.I)[0]
            candidates.append(before.removeprefix("Venue information ").strip())
    if day is None or len(candidates) != 1:
        return None
    return _row(source, soup, url, _plain(titles[0].get_text(" ", strip=True)), day,
                shown[3], venue, candidates[0], meta)


def _nested_heading(source, soup, url):
    main = soup.find("main") or soup.find(attrs={"role": "main"})
    headings = main.select("header h1") if main else []
    if len(headings) != 1:
        return None
    date_nodes = headings[0].select(":scope > .date-range")
    if len(date_nodes) != 1:
        return None
    date_text = _plain(date_nodes[0].get_text(" ", strip=True))
    if re.match(r"^EVERY\b", date_text, re.I):
        return []
    match = re.fullmatch(r"(?:(?:MON|TUE|TUES|WED|THU|THUR|FRI|SAT|SUN)\s+)?"
                         r"(\d{1,2})\s+([A-Z]+)\s+(20\d{2}),\s*(.+)", date_text, re.I)
    if not match:
        return None
    day = _date(f"{match[1]} {match[2]} {match[3]}")
    clone = BeautifulSoup(str(headings[0]), "html.parser")
    for node in clone.select(".date-range"):
        node.decompose()
    title = _plain(clone.get_text(" ", strip=True))
    site = _meta(soup, "og:site_name")
    locations = {_plain(node.get_text(" ", strip=True)) for node in
                 main.select(".article-info span") if _plain(node.get_text(" ", strip=True))}
    locations = {value for value in locations if not re.search(r"\b(?:free|paid|event)\b", value, re.I)}
    if day is None or not site or len(locations) != 1:
        return None
    body = main.select(".article-body")
    description = _plain(body[0].get_text(" ", strip=True)) if len(body) == 1 else ""
    return _row(source, soup, url, title, day, match[4],
                site + " — " + next(iter(locations)), "", description)


def read(source, soup, url, *, listing=None):
    # A theme may place programme/category landing pages under /events/ and
    # render several child event headers. They are not discrete occurrences.
    if (len(soup.select("h1")) == 1 and len(soup.select("header.entry-header")) > 1
            and len(soup.select(".eventdates")) > 1 and not soup.select(".eventvenue")):
        return []
    for reader in (_labeled_blocks, _entry_header, _nested_heading):
        result = (reader(source, soup, url, listing) if reader is _entry_header
                  else reader(source, soup, url))
        if result is not None:
            return result
    return None
