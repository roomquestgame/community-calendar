"""Demand-scoped HTML collection from Iowa's official MyCountyParks pages.

The publisher's Outlook export discards times, and its map coordinates can be
those of a parent park instead of an off-site event. Read the listing's own
schedule and the detail page's Location address; let the shared address cache
resolve coordinates. Network policy, robots checks and pacing belong to fetch.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import re
import sys
from time import monotonic
from urllib.parse import urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from roomquest.mapsee_adapter import record, timestamp
from roomquest.publisher_evidence import attach

ROOT = "https://www.mycountyparks.com"
TZ = ZoneInfo("America/Chicago")
PAGE_SIZE = 25
MAX_LISTING_PAGES = 4
MAX_EVENT_PAGES = 25
LOOKAHEAD_DAYS = 60
MAX_DESCRIPTION = 2000
MAX_COST_TEXT = 240

# Names and URL slugs observed in the publisher's own county directory.
_COUNTY_NAMES = (
    "Adair|Adams|Allamakee|Appanoose|Audubon|Benton|Black Hawk|Boone|Bremer|"
    "Buchanan|Buena Vista|Butler|Calhoun|Carroll|Cass|Cedar|Cerro Gordo|Cherokee|"
    "Chickasaw|Clarke|Clay|Clayton|Clinton|Crawford|Dallas|Davis|Decatur|Delaware|"
    "Des Moines|Dickinson|Dubuque|Emmet|Fayette|Floyd|Franklin|Fremont|Greene|"
    "Grundy|Guthrie|Hamilton|Hancock|Hardin|Harrison|Henry|Howard|Humboldt|Ida|"
    "Iowa|Jackson|Jasper|Jefferson|Johnson|Jones|Keokuk|Kossuth|Lee|Linn|Louisa|"
    "Lucas|Lyon|Madison|Mahaska|Marion|Marshall|Mills|Mitchell|Monona|Monroe|"
    "Montgomery|Muscatine|O'Brien|Osceola|Page|Palo Alto|Plymouth|Pocahontas|Polk|"
    "Pottawattamie|Poweshiek|Ringgold|Sac|Scott|Shelby|Sioux|Story|Tama|Taylor|"
    "Union|Van Buren|Wapello|Warren|Washington|Wayne|Webster|Winnebago|Winneshiek|"
    "Woodbury|Worth|Wright"
).split("|")
COUNTIES = {name.replace("'", "").replace(" ", "_").lower(): name for name in _COUNTY_NAMES}
_MONTHS = {name: index for index, name in enumerate(
    "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), 1)}
_CLOCK = r"\d{1,2}(?::\d{2})?\s*[AP]M"
_SCHEDULE = re.compile(
    rf"^([A-Z]{{3}})\s+(\d{{1,2}})\s+(20\d{{2}})\s+({_CLOCK})"
    rf"(?:\s*[-–—]\s*({_CLOCK}))?$", re.I)
_EVENT_PATH = re.compile(r"^/County/([^/]+)/Park/([^/]+)/Events/([1-9]\d{0,7})/([^/]+)/?$", re.I)
_VARIANT = re.compile(r"^(.*?)\s+[-–—]\s+(INCLUDES CARVING TOOL|NO CARVING TOOL)\s*$", re.I)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _key(value):
    return re.sub(r"[\W_]+", "", clean(value).casefold())


def _county_key(value):
    matches = [key for key, name in COUNTIES.items() if _key(value) in {_key(key), _key(name)}]
    if len(matches) != 1:
        raise ValueError("mycountyparks_county_unregistered")
    return matches[0]


def registered_calendar_url(county):
    name = COUNTIES[_county_key(county)]
    return ROOT + "/County/" + name.replace("'", "").replace(" ", "-") + "/Events"


def source_for_county(county_slug):
    """One known publisher county; backend enrollment and demand are separate."""
    key = _county_key(county_slug)
    return {"source_key": "mycountyparks_ia_" + key, "kind": "html",
            "platform_adapter": "html", "feed_url": registered_calendar_url(key)}


def source_county(source):
    match = re.fullmatch(r"mycountyparks_ia_([a-z]+(?:_[a-z]+)*)", str(source.get("source_key", "")))
    if source.get("kind") != "html" or source.get("platform_adapter") != "html" or not match:
        raise ValueError("unregistered_html_source")
    key = match.group(1)
    if key not in COUNTIES:
        raise ValueError("mycountyparks_county_unregistered")
    if source.get("feed_url") != registered_calendar_url(key):
        raise ValueError("unregistered_html_calendar")
    return key


def listing_url(county, *, page_number=1, today=None):
    key = _county_key(county)
    if not isinstance(page_number, int) or isinstance(page_number, bool) or not 1 <= page_number <= MAX_LISTING_PAGES:
        raise ValueError("mycountyparks_pagination_limit")
    begin = today or datetime.now(TZ).date()
    if not isinstance(begin, date) or isinstance(begin, datetime):
        raise ValueError("mycountyparks_listing_date_invalid")
    return registered_calendar_url(key) + "?" + urlencode({
        "EventSearchModel.CountyName": COUNTIES[key],
        "EventSearchModel.StartDate": begin.isoformat(),
        "EventSearchModel.EndDate": (begin + timedelta(days=LOOKAHEAD_DAYS)).isoformat(),
        "EventSearchModel.PageNumber": page_number,
        "EventSearchModel.CountyId": 0,
        "EventSearchModel.ParkId": 0,
    })


def event_identity(href, county):
    """Resolve a public event link without relaxing origin, county or path."""
    key = _county_key(county)
    try:
        raw = str(href or "")
        if re.search(r"[\x00-\x20\\]", raw):
            raise ValueError
        url = urljoin(ROOT + "/", raw)
        parsed = urlsplit(url)
        match = _EVENT_PATH.fullmatch(parsed.path)
        if (parsed.scheme != "https" or parsed.hostname != "www.mycountyparks.com"
                or parsed.username or parsed.password or parsed.port not in (None, 443)
                or parsed.query or parsed.fragment or "%" in parsed.path or not match
                or any(part in {".", ".."} for part in parsed.path.split("/"))
                or _key(match.group(1)) != _key(COUNTIES[key])):
            raise ValueError
        return url, match.group(3)
    except (TypeError, ValueError):
        raise ValueError("mycountyparks_event_url_unverified") from None


def parse_schedule(value):
    """Read only the publisher's date line, never prose or the broken export."""
    match = _SCHEDULE.fullmatch(clean(value))
    if not match or match.group(1).upper() not in _MONTHS:
        raise ValueError("mycountyparks_event_schedule_invalid")
    try:
        day = date(int(match.group(3)), _MONTHS[match.group(1).upper()], int(match.group(2)))
        clocks = []
        for raw in (match.group(4), match.group(5)):
            if raw is None:
                clocks.append(None)
                continue
            normalized = re.sub(r"\s+", "", raw).upper()
            fmt = "%I:%M%p" if ":" in normalized else "%I%p"
            wall = datetime.combine(day, datetime.strptime(normalized, fmt).time())
            # Shared timestamp validates ambiguous/nonexistent local wall times.
            clocks.append(timestamp(wall.isoformat(), TZ.key))
        start, end = clocks
    except (TypeError, ValueError, OverflowError) as exc:
        if str(exc) in {"timezone_ambiguous", "timezone_nonexistent"}:
            raise
        raise ValueError("mycountyparks_event_schedule_invalid") from exc
    if end == start:
        # Some publisher listings repeat the start as the end (Floyd 29962).
        # That provides no usable duration; retain the start and unknown end.
        end = None
    if end is not None and end < start:
        # A time-only range gives no evidence for an overnight or multi-day end.
        raise ValueError("mycountyparks_event_end_invalid")
    return start, end


def _image_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme == "https" and parsed.hostname == "content.mycountyparks.com"
                and parsed.port in (None, 443) and not parsed.username and not parsed.password
                and parsed.path.startswith("/Production/RelatedItem/Content/")
                and not parsed.query and not parsed.fragment):
            return value
    except ValueError:
        pass
    return None


@dataclass(frozen=True)
class ListingEvent:
    event_id: str
    url: str
    county: str
    title: str
    start: datetime
    end: datetime | None
    image_url: str | None = None


def parse_listing(html, county, *, page_number=1):
    key = _county_key(county)
    if not isinstance(page_number, int) or isinstance(page_number, bool) or not 1 <= page_number <= MAX_LISTING_PAGES:
        raise ValueError("mycountyparks_pagination_limit")
    soup = BeautifulSoup(html, "html.parser")
    containers = soup.select("#partialViewContainer")
    if len(containers) != 1:
        raise ValueError("mycountyparks_listing_structure_unverified")
    container = containers[0]
    counts = container.select("input#hdnTotalCount[value]")
    if len(counts) != 1 or not re.fullmatch(r"\d{1,5}", str(counts[0].get("value", ""))):
        raise ValueError("mycountyparks_listing_count_unverified")
    total = int(counts[0]["value"])
    declared_counties = {_key(tag.get("data-countyname")) for tag in soup.select("#countyData[data-countyname]")}
    if declared_counties and declared_counties != {_key(COUNTIES[key])}:
        raise ValueError("mycountyparks_listing_county_mismatch")
    if total == 0 and not declared_counties:
        # A blank partial or another county's empty page is not evidence that
        # this registered county has no events. Full county GET pages declare it.
        raise ValueError("mycountyparks_listing_county_unverified")
    grids = container.select(".auto-grid-4")
    if len(grids) > 1:
        raise ValueError("mycountyparks_listing_structure_unverified")
    cards = grids[0].find_all("div", class_="swiper-slide", recursive=False) if grids else []
    expected = max(0, min(PAGE_SIZE, total - (page_number - 1) * PAGE_SIZE))
    if len(cards) != expected or (total and not cards):
        raise ValueError("mycountyparks_listing_count_mismatch")
    if total == 0 and container.select("a.event-link"):
        raise ValueError("mycountyparks_listing_count_mismatch")
    results, seen = [], set()
    for card in cards:
        links = card.select("a.event-link[href]")
        if len(links) != 1:
            raise ValueError("mycountyparks_listing_card_unverified")
        link = links[0]
        if _key(link.get("data-county")) != _key(COUNTIES[key]):
            raise ValueError("mycountyparks_listing_county_mismatch")
        url, event_id = event_identity(link["href"], key)
        title_tag, date_tag = link.find("h3"), link.select_one("p.date")
        title = clean(title_tag.get_text(" ", strip=True)) if title_tag else ""
        if not title or date_tag is None:
            raise ValueError("mycountyparks_listing_card_unverified")
        start, end = parse_schedule(date_tag.get_text(" ", strip=True))
        if event_id in seen:
            raise ValueError("mycountyparks_listing_identity_repeated")
        seen.add(event_id)
        image = link.find("img", src=True)
        results.append(ListingEvent(event_id, url, key, title, start, end,
                                   _image_url(image["src"]) if image else None))
    return results, total


def excluded_product(title, description=""):
    product = re.search(r"\b(?:permit|membership|annual pass|season pass)\b", title, re.I)
    gathering = re.search(r"\b(?:workshop|class|clinic|training|orientation|meeting|hike|festival|picnic|dinner|presentation|talk|seminar|session|open house)\b", title, re.I)
    if product and not gathering:
        return True
    return bool(re.search(r"\b(?:permit|membership|pass)\s+is\s+(?:good|valid)\s+for\s+(?:the\s+)?(?:whole|entire)\s+(?:calendar\s+)?year\b", description, re.I))


def cancelled(title, description=""):
    if re.search(r"\b(?:cancelled|canceled|postponed)\b", title, re.I):
        return True
    for paragraph in re.split(r"[\n.!?]+", description):
        text = clean(paragraph).lstrip("* -")
        if re.match(r"^(?:sorry[, :]+)?(?:cancelled|canceled|postponed)\b", text, re.I):
            return True
        actual = re.search(
            r"\b(?:this|the|our)\s+(?:event|program|camp|workshop|class)\s+"
            r"(?:has\s+been|is|was)\s+(?:cancelled|canceled|postponed)\b", text, re.I)
        if actual and not re.search(r"\b(?:if|unless|may|might|would|could|should)\b", text[:actual.start()], re.I):
            return True
    return False


def _section_text(main, heading_name):
    headings = [tag for tag in main.find_all(re.compile(r"^h[23]$"))
                if clean(tag.get_text(" ", strip=True)).casefold() == heading_name.casefold()]
    if len(headings) != 1:
        return ""
    parts = []
    for node in headings[0].next_siblings:
        if isinstance(node, Tag) and (node.name in {"hr", "h1", "h2", "h3"}):
            break
        value = clean(node.get_text(" ", strip=True) if isinstance(node, Tag) else node)
        if value:
            parts.append(value)
    return "\n\n".join(parts)


def _location(main):
    headings = [tag for tag in main.find_all("h2") if clean(tag.get_text()).casefold() == "location"]
    if len(headings) != 1:
        raise ValueError("mycountyparks_event_location_unverified")
    paragraph = headings[0].find_next_sibling("p")
    if paragraph is None or paragraph.find("strong") is None:
        raise ValueError("mycountyparks_event_venue_requires_address")
    venue = clean(paragraph.find("strong").get_text(" ", strip=True))
    lines = [clean(line) for line in paragraph.get_text("\n", strip=True).splitlines() if clean(line)]
    state_postal = r"(?:IA|Iowa)(?:\s+IA)?\s+(\d{5}(?:-\d{4})?)"
    # A complete numeric street line may also end in city/state/ZIP. Only the
    # separately published city line supplies the city used for normalization.
    city_matches = [(index, re.fullmatch(r"([A-Za-z][A-Za-z .'-]*?)[,\s]+" + state_postal, line, re.I))
                    for index, line in enumerate(lines) if index > 0]
    city_matches = [(index, match) for index, match in city_matches if match]
    if not venue or not city_matches:
        raise ValueError("mycountyparks_event_venue_requires_address")
    if len({(clean(match.group(1)).casefold(), match.group(2)) for _, match in city_matches}) != 1:
        raise ValueError("mycountyparks_event_venue_requires_address")
    index, match = city_matches[0]
    city, postal = clean(match.group(1)).strip(" ,"), match.group(2)
    street_parts = lines[1:index]
    if not street_parts:
        raise ValueError("mycountyparks_event_venue_requires_address")
    for part_index, part in enumerate(street_parts):
        suffix = re.search(r"\b" + state_postal + r"$", part, re.I)
        if suffix:
            # Story repeats its full city suffix; Linn can publish an explicit
            # empty city field (", , IA ZIP"). Neither may contradict the ZIP
            # or replace a different named city from this Location paragraph.
            before_state = part[:suffix.start()].rstrip()
            if before_state.endswith(","):
                before_state = before_state[:-1].rstrip()
            if "," in before_state:
                embedded_city = clean(before_state.rsplit(",", 1)[1])
                if embedded_city and embedded_city.casefold() != city.casefold():
                    raise ValueError("mycountyparks_event_venue_requires_address")
            repeated = re.fullmatch(r"(.+?)(?:[,\s]+" + re.escape(city) + r",?\s+|,\s*,\s*)"
                                    + state_postal, part, re.I)
            if suffix.group(1) != postal or repeated is None:
                raise ValueError("mycountyparks_event_venue_requires_address")
            street_parts[part_index] = repeated.group(1).rstrip(" ,")
    # Mitchell publishes "1879-3 Highway 9". Preserve the complete bounded
    # numeric house number; this is address evidence, never a coordinate.
    if not re.match(r"^\d{1,6}(?:[A-Za-z]|-\d{1,6})?\s+[A-Za-z0-9]", street_parts[0]):
        raise ValueError("mycountyparks_event_venue_requires_address")
    street = ", ".join(street_parts)
    return venue, f"{street}, {city}, IA {postal}", city


def _registration(main):
    sidebar = main.select_one("#sidebar-affix")
    text = clean(sidebar.get_text(" ", strip=True)) if sidebar else ""
    if re.search(r"Join Waiting List", text, re.I):
        return "Waitlist"
    if re.search(r"(?:no longer accepting registrations|registration is no longer available)", text, re.I):
        return "Closed"
    if re.search(r"Reservations are not required", text, re.I):
        return "Not required"
    if re.search(r"Register Now", text, re.I):
        return "Available"
    if re.search(r"Please call to place your reservation", text, re.I):
        return "By phone"
    return None


def _active_within_window(event, now):
    end = event.end or event.start + timedelta(hours=3)
    return end > now and event.start <= now + timedelta(days=LOOKAHEAD_DAYS)


def _bounded_text(value, limit):
    text = clean(value)
    if limit <= 0:
        return ""
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _description_with_suffix(summary, suffix):
    """Keep required registration details intact within the staging limit."""
    if len(suffix) > MAX_DESCRIPTION:
        raise ValueError("mycountyparks_registration_details_too_large")
    if not suffix:
        return summary[:MAX_DESCRIPTION]
    prefix = summary[:max(0, MAX_DESCRIPTION - len(suffix) - 2)].rstrip()
    return prefix + "\n\n" + suffix if prefix else suffix


def parse_event(html, event, *, now=None):
    """Parse one listing-linked detail, ignoring parent park map coordinates."""
    if not isinstance(event, ListingEvent):
        raise ValueError("mycountyparks_event_identity_unverified")
    _, linked_id = event_identity(event.url, event.county)
    if linked_id != event.event_id:
        raise ValueError("mycountyparks_event_identity_mismatch")
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one("main#main-content")
    header = main.select_one("header.detail-header") if main else None
    if main is None or header is None:
        raise ValueError("mycountyparks_event_structure_unverified")
    ids = {str(tag.get("data-event-id")) for tag in header.select("[data-event-id]")}
    county_tag = header.select_one("#print[data-county]")
    if (ids != {event.event_id} or county_tag is None
            or _key(county_tag["data-county"]) != _key(COUNTIES[event.county])):
        raise ValueError("mycountyparks_event_identity_mismatch")
    title_tag, date_tag = header.find("h1"), header.select_one("p.date")
    title = clean(title_tag.get_text(" ", strip=True)) if title_tag else ""
    if not title or date_tag is None:
        raise ValueError("mycountyparks_event_structure_unverified")
    for node in main.select("script,style,nav,footer,dialog,iframe,noscript"):
        node.decompose()
    description = _section_text(main, "Event Summary")
    if not description:
        raise ValueError("mycountyparks_event_summary_missing")
    if cancelled(title, description) or excluded_product(title, description):
        return None
    if _key(title) != _key(event.title):
        raise ValueError("mycountyparks_event_title_mismatch")
    start, detail_end = parse_schedule(date_tag.get_text(" ", strip=True))
    if start != event.start or (detail_end is not None and detail_end != event.end):
        # Three observed untimed programs list midnight but show noon in the
        # detail header. Neither time is reliable. Classify only this exact
        # same-date/no-end conflict for withholding; never choose either time.
        if (event.end is None and detail_end is None
                and event.start.date() == start.date()
                and event.start.time().isoformat() == "00:00:00"
                and start.time().isoformat() == "12:00:00"):
            raise ValueError("mycountyparks_event_midnight_noon_conflict")
        raise ValueError("mycountyparks_event_schedule_mismatch")
    current = now or datetime.now(TZ)
    if current.tzinfo is None:
        raise ValueError("mycountyparks_now_timezone_missing")
    if not _active_within_window(event, current):
        return None
    venue, address, city = _location(main)
    category = _section_text(main, "Category")
    cost = _bounded_text(_section_text(main, "Cost"), MAX_COST_TEXT)
    registration = _registration(main)
    item = record(title, start.isoformat(), event.end.isoformat() if event.end else None,
                  venue, address, city, event.url, f"mycountyparks:{event.county}:{event.event_id}",
                  category=category, lat=None, lng=None, tz=TZ.key,
                  publisher_geo=False, retain_until_end=True)
    if item is None:
        return None
    item["timezone"] = TZ.key
    item["location_provenance"] = "publisher_event_street_pending_geocode"
    image = main.select_one("#image-gallery img#current-image[src]")
    image_url = _image_url(image["src"]) if image else event.image_url
    if image_url:
        item["image_url"] = image_url
    extras = [f"Cost: {cost}" if cost else "", f"Registration: {registration}" if registration else ""]
    suffix = "\n\n".join(value for value in extras if value)
    item["description"] = _description_with_suffix(description, suffix)
    item["publisher_categories"] = [category[:100]] if category else []
    attach(item, 'mycountyparks_ia_' + event.county,
           facts={'cost': cost, 'registration': registration}, candidate=image_url)
    variant = _VARIANT.fullmatch(title)
    if variant:
        base, label = clean(variant.group(1)), variant.group(2).upper()
        # Give a singleton option the same identity it has when both are present.
        # Do not use the minimum of currently visible source IDs.
        identity = "\0".join((_key(base), start.isoformat(), event.end.isoformat() if event.end else "",
                               _key(venue), _key(address)))
        item["id"] = f"mycountyparks:{event.county}:options:" + sha256(identity.encode()).hexdigest()[:24]
        item["title"] = base[:180]
        item["_option"] = {"label": label, "url": event.url, "cost": cost,
                           "registration": registration, "source_id": event.event_id}
        item["_summary"] = description
    return item


def combine_registration_options(records):
    """Combine only explicit carving-tool alternatives with identical place/time."""
    grouped, ordinary = {}, []
    for item in records:
        if "_option" in item:
            grouped.setdefault(item["id"], []).append(item)
        else:
            ordinary.append(item)
    for identity, values in grouped.items():
        options = [item["_option"] for item in values]
        labels = [option["label"] for option in options]
        if len(labels) != len(set(labels)) or len(labels) > 2:
            raise ValueError("mycountyparks_registration_variants_conflict")
        values.sort(key=lambda item: (int(item["_option"]["source_id"]), item["event_url"]))
        primary = dict(values[0])
        def option_line(option, cost=""):
            facts = "; ".join(value for value in (cost, option["registration"]) if value)
            return option["label"].capitalize() + (": " + facts if facts else "") + " — " + option["url"]

        # Full links and statuses are required. Cost prose is optional and must
        # not displace either of them or exceed the database's description cap.
        ordered = [item["_option"] for item in values]
        heading = "Registration options:\n"
        fixed = heading + "\n".join(option_line(option) for option in ordered)
        if len(fixed) > MAX_DESCRIPTION:
            raise ValueError("mycountyparks_registration_details_too_large")
        remaining = MAX_DESCRIPTION - len(fixed)
        lines = []
        for index, option in enumerate(ordered):
            cost_limit = min(MAX_COST_TEXT, max(0, remaining // (len(ordered) - index) - 2))
            cost = _bounded_text(option["cost"], cost_limit)
            if cost:
                remaining -= len(cost) + 2  # Adding cost adds either ': ' or '; '.
            lines.append(option_line(option, cost))
        suffix = heading + "\n".join(lines)
        primary["description"] = _description_with_suffix(primary["_summary"], suffix)
        primary['publisher_details']['registration_options'] = [
            {'label': option['label'], 'cost': option['cost'], 'registration': option['registration']}
            for option in ordered]
        primary.pop("_option", None)
        primary.pop("_summary", None)
        ordinary.append(primary)
    return sorted(ordinary, key=lambda item: (item["starts_at"], item["title"], item["id"]))


def collect(source, fetch, *, deadline_at=None, today=None, now=None):
    """One registered county per demand; incomplete pages never pass as success."""
    county = source_county(source)
    current = now or datetime.now(TZ)
    if current.tzinfo is None:
        raise ValueError("mycountyparks_now_timezone_missing")
    begin = today or current.astimezone(TZ).date()
    # Production supplies its shorter worker budget; the read-only CLI may
    # deliberately allow more time. An omitted deadline remains bounded.
    deadline = deadline_at if deadline_at is not None else monotonic() + 32

    def request(url):
        if monotonic() >= deadline:
            raise ValueError("collection_deadline")
        result = fetch(url, "text/html")
        if monotonic() >= deadline:
            raise ValueError("collection_deadline")
        return result

    listings, seen, expected_total = [], set(), None
    for page in range(1, MAX_LISTING_PAGES + 1):
        rows, total = parse_listing(request(listing_url(county, page_number=page, today=begin)), county, page_number=page)
        if expected_total is None:
            expected_total = total
            if total > MAX_LISTING_PAGES * PAGE_SIZE:
                raise ValueError("mycountyparks_pagination_limit")
        elif total != expected_total:
            raise ValueError("mycountyparks_listing_total_changed")
        for event in rows:
            if event.event_id in seen:
                raise ValueError("mycountyparks_listing_page_repeated")
            seen.add(event.event_id)
            if _active_within_window(event, current) and not excluded_product(event.title) and not cancelled(event.title):
                listings.append(event)
        if page * PAGE_SIZE >= total:
            break
    if len(seen) != expected_total:
        raise ValueError("mycountyparks_listing_incomplete")
    if len(listings) > MAX_EVENT_PAGES:
        raise ValueError("mycountyparks_detail_limit")
    records, unresolved, time_conflicts = [], 0, 0
    for event in listings:
        html = request(event.url)
        try:
            item = parse_event(html, event, now=current)
        except ValueError as exc:
            reason = str(exc)
            if reason == "mycountyparks_event_venue_requires_address":
                unresolved += 1
                print("mycountyparks_address_unresolved", county, event.event_id, reason, file=sys.stderr)
            elif reason == "mycountyparks_event_midnight_noon_conflict":
                time_conflicts += 1
                print("mycountyparks_time_unresolved", county, event.event_id, reason, file=sys.stderr)
            else:
                raise
            continue
        if item:
            records.append(item)
    if not records:
        if time_conflicts:
            raise ValueError("mycountyparks_event_evidence_unavailable")
        if unresolved:
            raise ValueError("venue_extraction_unavailable")
    print("mycountyparks_collection", county, "listed", expected_total, "details", len(listings),
          "unresolved_addresses", unresolved, "time_conflicts", time_conflicts,
          "records", len(records), file=sys.stderr)
    return combine_registration_options(records)
