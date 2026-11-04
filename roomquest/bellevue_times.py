"""Bounded, first-page-only Bellevue Times collection.

The custom Bellevue Community Calendar exposes occurrence wall times in links
and human-readable schedules on each list card. Both must agree. All cards on
the first page must be accounted for; later pages are outside collection scope.
The backend must not infer cancellation from absence on this limited page.
Network/robots decisions belong to the shared transport, without alternatives.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from hashlib import sha256
import json
import re
import sys
from time import monotonic
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import record, timestamp

SOURCE_KEY = "bellevue_times_ne"
HOST = "bellevuetimes.com"
CALENDAR = "https://bellevuetimes.com/events/"
TZ = ZoneInfo("America/Chicago")
PAGE_SIZE = 30
COLLECTION_SCOPE = "first_page"
MAX_SECONDS = 30
LOOKAHEAD_DAYS = 60
MAX_DESCRIPTION = 2000
MAX_PUBLISHER_CATEGORIES = 20
MAX_PUBLISHER_CATEGORY_LENGTH = 100
_CLOCK = r"\d{1,2}(?::\d{2})?\s*[ap]m"
_MONTHS = {}
for _number, _month in enumerate(("January February March April May June July "
                                 "August September October November December").split(), 1):
    _MONTHS[_month.casefold()] = _number
    _MONTHS[_month[:3].casefold()] = _number
_WEEKDAYS = "Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split()
_DATE = re.compile(r"(?:(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*)?"
                   r"([A-Za-z]+)\.?\s+(\d{1,2}),\s*(20\d{2})", re.I)
_PARADE_SLUG = "nebraskas-official-veterans-day-parade"
_PARADE_OCCURRENCE = "20261107T100000"
_STREET = (r"\d{1,6}\s+(?:[A-Za-z0-9.'’\-]+\s+){1,7}"
           r"(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Circle|Cir|Parkway|Pkwy|"
           r"Boulevard|Blvd|Lane|Ln|Court|Ct|Way|Highway|Hwy)\b\.?"
           r"(?:,?\s+(?:Suite|Ste|Unit|#)\s*\w[\w-]*)?")
_ADDRESS = re.compile(rf"(?P<street>{_STREET})\s*,\s*(?P<city>[A-Za-z]+(?:\s+[A-Za-z]+){{0,3}})"
                      r"\s*,\s*(?:NE|Nebraska)\s+(?P<zip>\d{5}(?:-\d{4})?)\b", re.I)
_LOCAL_ADDRESS = re.compile(rf"(?P<street>{_STREET})\s*,\s*"
                            r"(?P<city>[A-Za-z]+(?:\s+[A-Za-z]+){0,3})(?=\s*[,.;]|\s*$)", re.I)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _key(value):
    return clean(value).casefold()


class EventHold(ValueError):
    """An identified event lacks usable evidence; never repair it by guessing."""


@dataclass(frozen=True)
class Venue:
    name: str
    address: str
    city: str
    evidence: tuple[str, ...]


# Exact publisher venue/city aliases reviewed 2026-11-04. These are addresses,
# not coordinates or a source-wide default. See BELLEVUE_TIMES.md for evidence.
VENUES = {
    "bellevue public library · bellevue": Venue(
        "Bellevue Public Library", "2206 Longo Drive, Suite 100, Bellevue, NE 68005", "Bellevue",
        ("https://www.bellevue.net/176/Library", "https://www.bellevue.net/m/directory/department?did=24")),
    "beardmore event center · bellevue": Venue(
        "Beardmore Event Center of Bellevue", "3750 Raynor Parkway, Bellevue, NE 68123", "Bellevue",
        ("https://www.beardmoreeventcenter.com/contact-us",)),
    "snap! productions · bellevue": Venue(
        "SNAP! Productions", "2221 Thurston Circle, Bellevue, NE 68005", "Bellevue",
        ("https://www.snapproductions.com/events/avenue-q",)),
    "kroc center · omaha": Venue(
        "The Salvation Army Omaha Kroc Center", "2825 Y Street, Omaha, NE 68107", "Omaha",
        ("https://omahakroc.org/",)),
    "bellevue little theatre · bellevue": Venue(
        "Bellevue Little Theatre", "203 West Mission Avenue, Bellevue, NE 68005", "Bellevue",
        ("https://www.theblt.org/",)),
}
PARADE_VENUE = Venue(
    "Nebraska’s Official Veterans Day Parade — grandstand",
    "209 West Mission Avenue, Bellevue, NE 68005", "Bellevue",
    ("https://business.bellevuenebraska.com/events/details/nebraska-s-official-veterans-day-parade-2025-2646",
     "https://www.sarpychamber.org/list/member/fraternal-order-of-eagles-3912-43079515"))


@dataclass(frozen=True)
class Card:
    slug: str
    occurrence: str
    url: str
    title: str
    schedule: str
    venue: str
    summary: str
    category: str
    image_url: str | None = None
    publisher_categories: tuple[str, ...] = ()

    @property
    def identity(self):
        # Preserve the occurrence even when the slug would exceed the shared
        # 180-character ID cap. The hash covers the entire canonical slug.
        slug = self.slug
        if len(slug) > 125:
            slug = slug[:100] + ":" + sha256(slug.encode()).hexdigest()[:16]
        return f"bellevue_times:{slug}:{self.occurrence}"


@dataclass(frozen=True)
class Page:
    cards: tuple[Card, ...]
    total: int


def source_identity(source):
    if (source.get("source_key") != SOURCE_KEY or source.get("kind") != "html"
            or source.get("platform_adapter") != "html"):
        raise ValueError("unregistered_html_source")
    if source.get("feed_url") != CALENDAR:
        raise ValueError("unregistered_html_calendar")
    if source.get("timezone") not in (None, "", TZ.key):
        raise ValueError("bellevue_times_timezone_mismatch")


def _publisher_url(raw):
    raw = str(raw or "")
    if not raw or re.search(r"[\x00-\x20\\]", raw):
        raise ValueError
    url = urljoin(CALENDAR, raw)
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != HOST or parsed.fragment
            or "%" in parsed.path or any(part in {".", ".."} for part in raw.split("/"))):
        raise ValueError
    return parsed


def event_identity(href):
    """Use canonical slug + occurrence, with return-navigation tracking removed."""
    try:
        parsed = _publisher_url(href)
        match = re.fullmatch(r"/events/([a-z0-9]+(?:-[a-z0-9]+)*)/", parsed.path)
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        fields = dict(pairs)
        if (not match or len(pairs) != len(fields) or not fields.get("occurrence")
                or any(key != "occurrence" and not re.fullmatch(r"bcc_return_[a-z_]+", key) for key in fields)
                or not re.fullmatch(r"20\d{6}T\d{6}", fields["occurrence"])):
            raise ValueError
        datetime.strptime(fields["occurrence"], "%Y%m%dT%H%M%S")
        canonical = "https://" + HOST + parsed.path + "?" + urlencode({"occurrence": fields["occurrence"]})
        return match.group(1), fields["occurrence"], canonical
    except (TypeError, ValueError):
        raise ValueError("bellevue_times_event_url_unverified") from None


def _image_url(card):
    image = card.select_one(".bcc-card-image[style]")
    match = re.fullmatch(r"\s*background-image\s*:\s*url\(['\"]?([^)'\"]+)['\"]?\)\s*;?\s*",
                         str(image.get("style", ""))) if image else None
    if not match:
        return None
    try:
        parsed = _publisher_url(match.group(1))
        if (parsed.path.startswith("/wp-content/uploads/") and not parsed.query
                and re.search(r"\.(?:jpe?g|png|webp|gif)$", parsed.path, re.I)):
            return parsed.geturl()
    except ValueError:
        pass
    return None


def _publisher_categories(card):
    """Keep explicit card badges as evidence, separately from classification."""
    labels, seen = [], set()
    for term in card.select(".bcc-terms .bcc-term, .bcc-terms .bcc-primary-term"):
        label = clean(term.get_text(" ", strip=True))[:MAX_PUBLISHER_CATEGORY_LENGTH].rstrip()
        key = label.casefold()
        if not label or key in seen:
            continue
        seen.add(key)
        labels.append(label)
        if len(labels) == MAX_PUBLISHER_CATEGORIES:
            break
    return tuple(labels)


def parse_listing(html):
    """Verify the complete first page, without treating it as the full calendar."""
    soup = BeautifulSoup(html, "html.parser")
    lists, paginations = soup.select("main.bcc-event-list"), soup.select(".bcc-list-pagination")
    if len(lists) != 1 or len(paginations) != 1:
        raise ValueError("bellevue_times_listing_structure_unverified")
    counts = paginations[0].select(".bcc-pagination-count")
    currents = paginations[0].select('.bcc-page-number.is-current[aria-current="page"]')
    if len(counts) != 1 or len(currents) != 1 or clean(currents[0].get_text()) != "1":
        raise ValueError("bellevue_times_listing_count_unverified")
    count = re.fullmatch(r"Showing (\d{1,5})[–-](\d{1,5}) of (\d{1,5}) upcoming events",
                         clean(counts[0].get_text(" ", strip=True)))
    if not count:
        raise ValueError("bellevue_times_listing_count_unverified")
    first, last, total = map(int, count.groups())
    cards = lists[0].find_all("article", class_="bcc-event-card", recursive=False)
    expected = min(PAGE_SIZE, total)
    if len(cards) != expected or first != (1 if total else 0) or last != expected:
        raise ValueError("bellevue_times_listing_count_mismatch")
    # Next/numbered links are outside scope and never dereferenced. Their
    # availability is unrelated to completeness of these first-page cards.
    results, seen = [], set()
    for card in cards:
        links, schedules = card.select("h2 a[href]"), card.select(".bcc-card-date")
        venues, summaries = card.select(".bcc-card-venue"), card.select(".bcc-card-summary")
        if len(links) != 1 or len(schedules) != 1 or len(venues) > 1 or len(summaries) > 1:
            raise ValueError("bellevue_times_listing_card_unverified")
        slug, occurrence, url = event_identity(links[0]["href"])
        title = clean(links[0].get_text(" ", strip=True))
        if not title:
            raise ValueError("bellevue_times_listing_card_unverified")
        if url in seen:
            raise ValueError("bellevue_times_listing_identity_repeated")
        seen.add(url)
        primary = card.select_one(".bcc-primary-term")
        results.append(Card(slug, occurrence, url, title, clean(schedules[0].get_text(" ", strip=True)),
                            clean(venues[0].get_text(" ", strip=True)) if venues else "",
                            clean(summaries[0].get_text(" ", strip=True)) if summaries else "",
                            clean(primary.get_text(" ", strip=True)) if primary else "",
                            _image_url(card), publisher_categories=_publisher_categories(card)))
    return Page(tuple(results), total)


def _day(value):
    match = _DATE.fullmatch(clean(value))
    try:
        if not match:
            raise ValueError
        weekday, month, day, year = match.groups()
        result = date(int(year), _MONTHS[month.casefold()], int(day))
        if weekday and weekday.casefold() != _WEEKDAYS[result.weekday()].casefold():
            raise ValueError
        return result
    except (KeyError, TypeError, ValueError):
        raise ValueError("bellevue_times_event_date_invalid") from None


def _clock(value):
    compact = re.sub(r"\s+", "", value).upper()
    try:
        return datetime.strptime(compact, "%I:%M%p" if ":" in compact else "%I%p").time()
    except ValueError:
        raise ValueError("bellevue_times_event_clock_invalid") from None


def parse_schedule(value, occurrence):
    """Occurrence supplies start only; the displayed line corroborates it."""
    try:
        wall = datetime.strptime(occurrence, "%Y%m%dT%H%M%S")
        start = timestamp(wall.isoformat(), TZ.key)
    except (TypeError, ValueError):
        raise EventHold("bellevue_times_occurrence_time_unverified") from None
    parts = [clean(part) for part in clean(value).split("·")]
    day = _day(parts[0])
    if day != wall.date():
        raise EventHold("bellevue_times_occurrence_date_conflict")
    if len(parts) == 1:
        if wall.time() == time(0):
            raise EventHold("bellevue_times_date_only_midnight")
        return start, None
    end_day, end_clock = day, None
    if len(parts) == 2:
        match = re.fullmatch(rf"({_CLOCK})(?:\s*[-–—]\s*({_CLOCK}))?", parts[1], re.I)
        if not match:
            raise ValueError("bellevue_times_event_schedule_invalid")
        start_clock, end_clock = match.groups()
    elif len(parts) == 3:
        match = re.fullmatch(rf"({_CLOCK})\s*[-–—]\s*(.+)", parts[1], re.I)
        if not match or not re.fullmatch(_CLOCK, parts[2], re.I):
            raise ValueError("bellevue_times_event_schedule_invalid")
        start_clock, end_date = match.groups()
        end_day, end_clock = _day(end_date), parts[2]
    else:
        raise ValueError("bellevue_times_event_schedule_invalid")
    if _clock(start_clock) != wall.time():
        raise EventHold("bellevue_times_occurrence_start_conflict")
    try:
        end = timestamp(datetime.combine(end_day, _clock(end_clock)).isoformat(), TZ.key) if end_clock else None
    except ValueError as exc:
        if str(exc) in {"timezone_ambiguous", "timezone_nonexistent"}:
            raise EventHold("bellevue_times_event_end_unverified") from exc
        raise
    if end is not None and end <= start:
        raise EventHold("bellevue_times_event_end_unverified")
    return start, end


def _check_observed_time_conflict(card, start, end):
    # Specific observed publisher error: Nov 4 Spanish Storytime says 10–11 AM
    # in same-date prose but ends 11 PM in the schedule. This is corroboration,
    # never a date/time source. Broad prose scans would misread LEGO weekdays,
    # ages, and Bluey Bash's shorter meet-and-greet as event schedules.
    if card.slug != "spanish-storytime":
        return
    match = re.search(r"\b(Wednesday),\s*(Nov)\.?\s+(4),\s*(10)\s*[-–—]\s*(11)\s*(AM)\b",
                      card.summary, re.I)
    if not match or start.date() != date(2026, 11, 4):
        return
    if start.time() != time(10) or end is None or end.date() != start.date() or end.time() != time(11):
        raise EventHold("bellevue_times_spanish_storytime_time_conflict")


def _is_parade(card):
    return (card.slug == _PARADE_SLUG and card.occurrence == _PARADE_OCCURRENCE
            and _key(card.title) == "nebraska’s official veterans day parade")


def resolve_venue(card):
    """Prefer an event's explicit street; otherwise use one exact reviewed alias."""
    venue = VENUES.get(_key(card.venue))
    if _is_parade(card) and _key(card.venue) == "mission ave · bellevue":
        venue = PARADE_VENUE
    if venue is None:
        raise EventHold("bellevue_times_event_venue_unreviewed")
    text = card.summary
    street_matches = list(re.finditer(_STREET, text, re.I))
    for match in street_matches:
        # A contact/registration/donation address is not evidence of the event
        # location. Likewise, an unexplained street must not quietly disappear
        # and cause fallback to the host library's reviewed venue address.
        context = text[max(0, match.start() - 120):match.end() + 100]
        before = text[max(0, match.start() - 120):match.start()]
        if (re.search(r"\b(?:contact|questions|mailing|office|register|registration|send|donate|donation)\b", context, re.I)
                or (match.start() != 0 and not re.search(
                    r"\b(?:at|location|venue)\s*:?\s+[^.!?;]{0,100}$", before, re.I))):
            raise EventHold("bellevue_times_event_address_context_unverified")
    addresses = {(clean(m["street"]), clean(m["city"]), m["zip"]) for m in _ADDRESS.finditer(text)}
    if len({_key(m.group()) for m in street_matches}) > 1:
        raise EventHold("bellevue_times_event_address_conflict")
    if len(addresses) > 1:
        raise EventHold("bellevue_times_event_address_conflict")
    if addresses:
        street, city, postal = next(iter(addresses))
        return Venue(venue.name, f"{street}, {city}, NE {postal}", city, (card.url,)), "publisher_event_street_pending_geocode"
    local = {(clean(m["street"]), clean(m["city"])) for m in _LOCAL_ADDRESS.finditer(text)}
    if len(local) > 1:
        raise EventHold("bellevue_times_event_address_conflict")
    if local:
        street, city = next(iter(local))
        # The observed OESC card omits state/ZIP. Complete only an exact street
        # + city match to the reviewed venue, never a new or conflicting street.
        if _key(street) != _key(venue.address.split(",")[0]) or _key(city) != _key(venue.city):
            raise EventHold("bellevue_times_event_address_incomplete")
        return venue, "publisher_event_street_reviewed_address_pending_geocode"
    if street_matches or re.search(r"\boff[- ](?:site|campus)\b", text, re.I):
        raise EventHold("bellevue_times_event_address_incomplete")
    # Library-sponsored programs may explicitly meet at the Senior Center.
    # That named alternate venue is not the reviewed Longo Drive library even
    # when the summary omits the words "off-site" and provides no street.
    if (_key(card.venue) == "bellevue public library · bellevue"
            and re.search(r"\b(?:meets?|held|takes?\s+place)\s+at\s+(?:the\s+)?"
                          r"Bellevue\s+Senior\s+Center\b", text, re.I)):
        raise EventHold("bellevue_times_named_alternate_venue_requires_address")
    return venue, "reviewed_venue_alias_pending_geocode"


def _active(start, end, current):
    expires = end if end is not None else start + timedelta(hours=3)
    return start <= current + timedelta(days=LOOKAHEAD_DAYS) and expires > current


def _log(kind, **fields):
    print(json.dumps({"event": "bellevue_times_" + kind, "source_key": SOURCE_KEY,
                      "collection_scope": COLLECTION_SCOPE, **fields},
                     ensure_ascii=False, sort_keys=True), file=sys.stderr)


def normalize_cards(cards, *, now=None, publisher_total=None):
    """Normalize verified first-page cards; exposed separately for offline audits."""
    if len(cards) > PAGE_SIZE:
        raise ValueError("bellevue_times_first_page_limit")
    current = now or datetime.now(TZ)
    if current.tzinfo is None:
        raise ValueError("bellevue_times_now_timezone_missing")
    resolved, missing, holds, duplicates = [], [], 0, 0
    for card in cards:
        try:
            start, end = parse_schedule(card.schedule, card.occurrence)
            if not _active(start, end, current):
                continue
            _check_observed_time_conflict(card, start, end)
            if re.search(r"\b(?:cancelled|canceled|postponed)\b", card.title, re.I):
                continue
            if not card.venue:
                missing.append((card, start, end))
                continue
            venue, provenance = resolve_venue(card)
            resolved.append((card, start, end, venue, provenance))
        except EventHold as exc:
            holds += 1
            _log("event_held", identity=card.identity, reason=str(exc), event_url=card.url)
    for card, start, end in missing:
        # Only the observed missing-location duplicate may borrow equivalence,
        # and only when its independently located counterpart is in this pull.
        match = any(_is_parade(other) and _key(other.title) == _key(card.title)
                    and start == other_start and end == other_end
                    for other, other_start, other_end, _, _ in resolved)
        if card.slug == _PARADE_SLUG + "-2" and card.occurrence == _PARADE_OCCURRENCE and match:
            duplicates += 1
            _log("duplicate", identity=card.identity, reason="verified_parade_counterpart", event_url=card.url)
        else:
            holds += 1
            _log("event_held", identity=card.identity, reason="bellevue_times_event_venue_unreviewed", event_url=card.url)
    records, seen = [], set()
    # Stable choice for two fully located duplicate cards; recurring dates and
    # distinct venues/end times remain independent occurrences.
    for card, start, end, venue, provenance in sorted(resolved, key=lambda item: (len(item[0].slug), item[0].url)):
        key = (_key(card.title), start, end, _key(venue.name), _key(venue.address))
        if key in seen:
            duplicates += 1
            _log("duplicate", identity=card.identity, reason="identical_title_time_verified_venue", event_url=card.url)
            continue
        seen.add(key)
        item = record(card.title, start.isoformat(), end.isoformat() if end else None,
                      venue.name, venue.address, venue.city, card.url, card.identity,
                      category=card.category, lat=None, lng=None, tz=TZ.key,
                      publisher_geo=False, retain_until_end=True)
        if item is None:
            continue
        item["timezone"] = TZ.key
        item["location_provenance"] = provenance
        item["description"] = card.summary[:MAX_DESCRIPTION]
        item["publisher_categories"] = list(card.publisher_categories)
        if card.image_url:
            # Candidate metadata only: the current HTML publisher leaves the
            # public image null; this adapter does not grant media permission.
            item["image_url"] = card.image_url
        records.append(item)
    _log("normalized", first_page_count=len(cards), publisher_total=publisher_total,
         has_more=publisher_total > len(cards) if publisher_total is not None else None,
         held=holds, duplicates=duplicates, records=len(records))
    if not records and holds:
        raise ValueError("bellevue_times_event_evidence_unavailable")
    return sorted(records, key=lambda item: (item["starts_at"], item["title"], item["id"]))


def collect(source, fetch, *, deadline_at=None, now=None):
    """One complete first page or an error; never request or imply later pages."""
    source_identity(source)
    deadline = min(monotonic() + MAX_SECONDS, deadline_at if deadline_at is not None else float("inf"))
    if monotonic() >= deadline:
        raise ValueError("collection_deadline")
    html = fetch(CALENDAR, "text/html")
    if monotonic() >= deadline:
        raise ValueError("collection_deadline")
    page = parse_listing(html)
    if monotonic() >= deadline:
        raise ValueError("collection_deadline")
    records = normalize_cards(page.cards, now=now, publisher_total=page.total)
    if monotonic() >= deadline:
        raise ValueError("collection_deadline")
    return records
