"""Reviewed Atlantic City-area venue schedules through the guarded transport.

The venue websites supply every date, clock and description.  Fixed addresses
are venue-specific resolutions, never discovery-center coordinates.  Season
ranges only expand when the publisher explicitly names the recurring weekday.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
import json
import re
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record, timestamp

ZONE = "America/New_York"
MAX_DESCRIPTION = 12000
MAX_RECORDS = 500
ANCHOR = "anchor_rock_club_nj"
TENNESSEE = "tennessee_avenue_beer_hall_nj"
SOMERS_BREW = "somers_point_brewing_nj"
SEASIDE = "seaside_wellness_atlantic_city_nj"
JOSIE = "josie_kellys_public_house_nj"
CAROLINES = "carolines_by_the_bay_nj"
SMITHVILLE = "historic_smithville_events_nj"
SOURCES = {
    ANCHOR: ("https://www.anchorrockclub.com/events-calendar", ("www.anchorrockclub.com",)),
    TENNESSEE: ("https://tennaveac.com/new-events", ("tennaveac.com",)),
    SOMERS_BREW: ("https://somerspointbrewing.com/", ("somerspointbrewing.com",)),
    SEASIDE: ("https://seasidewellnessac.com/events.html", ("seasidewellnessac.com",)),
    JOSIE: ("https://josiekellys.com/events/", ("josiekellys.com",)),
    CAROLINES: ("https://carolinesnj.com/specials", ("carolinesnj.com",)),
    SMITHVILLE: ("https://historicsmithvillenj.com/", ("historicsmithvillenj.com",)),
}
VENUES = {
    # Publisher calendar/info page, reviewed November 14, 2026.
    ANCHOR: ("Anchor Rock Club", "247 S New York Ave, Atlantic City, NJ 08401", "Atlantic City"),
    TENNESSEE: ("Tennessee Avenue Beer Hall", "133 S Tennessee Ave, Atlantic City, NJ 08401", "Atlantic City"),
    SOMERS_BREW: ("Somers Point Brewing Company", "705 W New York Avenue, Somers Point, NJ 08244", "Somers Point"),
    # Official Caesars directions: caesarsrewards.custhelp.com/app/answers/detail/a_id/61
    SEASIDE: ("The Pool at Harrah's Resort", "777 Harrah's Blvd, Atlantic City, NJ 08401", "Atlantic City"),
    JOSIE: ("Josie Kelly's Public House", "908 Shore Road, Somers Point, NJ 08244", "Somers Point"),
    CAROLINES: ("Caroline's By The Bay", "450 Bay Avenue, Somers Point, NJ 08244", "Somers Point"),
    SMITHVILLE: ("Historic Smithville", "615 E Moss Mill Road, Smithville, NJ 08205", "Smithville"),
}
JOSIE_API = "https://josiekellys.com/wp-json/tribe/events/v1/events"
EXCLUDED = re.compile(r"\b(?:cancell?ed|postponed|closed|private\s+(?:event|party)|members?[- ]only)\b", re.I)


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 2000:
        return False
    try:
        parsed = urlsplit(value)
        root = urlsplit(SOURCES[key][0])
        if (parsed.scheme != "https" or parsed.netloc != root.netloc or parsed.username
                or parsed.password or parsed.port not in (None, 443) or parsed.fragment
                or parsed.query and key != SMITHVILLE
                or re.search(r"[\s\\<>]|%2e|%2f|%5c", value, re.I)
                or ".." in parsed.path.split("/")):
            return False
    except ValueError:
        return False
    if key == SMITHVILLE:
        return bool(re.fullmatch(r"/[1-9]\d{0,5}-[a-z0-9-]+", parsed.path)
                    and re.fullmatch(r"date=20\d{2}-\d{2}-\d{2}-\d{2}-\d{2}", parsed.query))
    pattern = {ANCHOR: r"/shows/[a-z0-9-]+", TENNESSEE: r"/new-events/[a-z0-9-]+",
               JOSIE: r"/event/[a-z0-9-]+/(?:20\d{2}-\d{2}-\d{2}/)?"}.get(key)
    return bool(re.fullmatch(pattern, parsed.path)) if pattern else value == SOURCES[key][0]


def photo_url(key, value):
    if not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443)
                or parsed.netloc != parsed.hostname or parsed.fragment or ".." in parsed.path.split("/")
                or re.search(r"[\s\\<>]|%2e|%2f|%5c", value, re.I)
                or not re.search(r"\.(?:jpe?g|png|webp)$", parsed.path, re.I)):
            return None
        valid = (
            key == ANCHOR and parsed.hostname == "cdn.prod.website-files.com"
            and parsed.path.startswith("/60e473b45793a20c12c8d64e/")
            or key == TENNESSEE and parsed.hostname == "images.squarespace-cdn.com"
            and parsed.path.startswith("/content/v1/5d3e03db3e493d0001bd8051/")
            or key == JOSIE and parsed.hostname == "josiekellys.com" and parsed.path.startswith("/wp-content/uploads/")
            or key == SEASIDE and parsed.hostname == "seasidewellnessac.com" and parsed.path.startswith("/img/")
            or key == SMITHVILLE and parsed.hostname == "historicsmithvillenj.com" and parsed.path.startswith("/images/")
        )
        return value if valid else None
    except ValueError:
        return None


def _text(node):
    return plain(node.get_text(" ", strip=True)) if node else ""


def narrative(value):
    """Keep the complete event narrative; refuse over-limit records, never clip."""
    soup = BeautifulSoup(str(value or ""), "html.parser")
    for node in soup.select("script,style,template,noscript,nav"):
        node.decompose()
    text = "\n".join(re.sub(r"[\t\r\f\v ]+", " ", line).strip()
                     for line in soup.get_text("\n").splitlines() if line.strip())
    if not text:
        raise ValueError("atlantic_city_description_missing")
    if len(text) > MAX_DESCRIPTION:
        raise ValueError("atlantic_city_description_limit")
    return text


def _clock(day, value):
    value = re.sub(r"\s+", "", value).upper()
    if value == "NOON":
        value = "12PM"
    if value == "MIDNIGHT":
        value = "12AM"
    fmt = "%I:%M%p" if ":" in value else "%I%p"
    return timestamp(datetime.combine(day, datetime.strptime(value, fmt).time()), ZONE)


def _row(key, title, start, end, url, identity, body, *, image=None, category=""):
    if EXCLUDED.search(title):
        return None
    if not event_url(key, url):
        raise ValueError("atlantic_city_event_identity")
    body = narrative(body)
    if end is not None and end <= start:
        raise ValueError("atlantic_city_schedule_conflict")
    venue, address, city = VENUES[key]
    row = record(title, start.isoformat(), end.isoformat() if end else None,
                 venue, address, city, url, identity, category, tz=ZONE,
                 retain_until_end=True)
    if row is not None:
        row.update(description=body, attendance_mode="in_person", timezone=ZONE,
                   location_provenance="reviewed_venue_street_address_pending_geocode")
        if candidate := photo_url(key, image):
            row["image_url"] = candidate
    return row


def _within(start, end, now):
    return start < now + timedelta(days=60) and (end or start + timedelta(hours=3)) > now


def _anchor(soup, now):
    if not soup.select_one(".collection-list"):
        raise ValueError("anchor_rock_calendar_changed")
    cards = soup.select(".collection-list .w-dyn-item")
    if len(cards) > 150:
        raise ValueError("source_record_limit")
    for card in cards:
        title = _text(card.select_one("#event-title"))
        if not title or EXCLUDED.search(title):
            continue
        canceled = card.select_one(".canclled")
        if canceled is not None and "w-condition-invisible" not in canceled.get("class", []):
            continue
        start = timestamp(datetime.strptime(_text(card.select_one("#event-start")), "%B %d, %Y %I:%M %p"), ZONE)
        if not _within(start, None, now):
            continue
        link = card.select_one("a#event-location[href]")
        if link is None:
            raise ValueError("anchor_rock_event_link_missing")
        url = urljoin(SOURCES[ANCHOR][0], link["href"])
        body = card.select_one("#event-desc")
        # Some cards contain the default hidden ALL/FREE controls; only the
        # actual event narrative belongs in the description.
        poster = card.select_one(".poster-div[style]")
        match = re.search(r"background-image\s*:\s*url\([\"']?([^\"')]+)", poster.get("style", "")) if poster else None
        yield _row(ANCHOR, title, start, None, url, urlsplit(url).path, body,
                   image=match[1] if match else None)


def _tennessee(soup, now):
    if soup.select_one(".eventlist") is None:
        raise ValueError("tennessee_calendar_changed")
    for card in soup.select("article.eventlist-event--upcoming"):
        title_node = card.select_one(".eventlist-title-link[href]")
        if title_node is None:
            raise ValueError("tennessee_event_identity")
        title = _text(title_node)
        if EXCLUDED.search(title):
            continue
        body = narrative(card.select_one(".eventlist-description"))
        url = urljoin(SOURCES[TENNESSEE][0], title_node["href"])
        clocks = card.select(".eventlist-meta-date .event-time-12hr")
        if len(clocks) == 2:
            start = _clock(date.fromisoformat(clocks[0]["datetime"]), _text(clocks[0]))
            end = _clock(date.fromisoformat(clocks[1]["datetime"]), _text(clocks[1]))
        else:
            first = card.select_one(".event-time-localized-start, .event-time-12hr-start")
            last = card.select_one(".event-time-localized-end, .event-time-12hr-end")
            if first is None:
                raise ValueError("tennessee_event_time_missing")
            start = _clock(date.fromisoformat(first["datetime"]), _text(first))
            end = _clock(date.fromisoformat(last["datetime"]), _text(last)) if last else None
        export = card.select_one("a.eventlist-meta-export-google[href]")
        if export:
            values = parse_qs(urlsplit(export["href"]).query).get("dates", [])
            if len(values) != 1:
                raise ValueError("tennessee_schedule_conflict")
            exported = values[0].split("/")
            expected = (start, end)
            if len(exported) != 2 or any(
                instant is not None and datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc) != instant
                for raw, instant in zip(exported, expected)
            ):
                raise ValueError("tennessee_schedule_conflict")
        image = card.select_one(".eventlist-description img[data-src], .eventlist-description img[src]")
        candidate = image.get("data-src") or image.get("src") if image else None
        if end and end.date() - start.date() > timedelta(days=1):
            # The publisher encodes football seasons as multi-month events.
            # Its newer venue site publishes different per-occurrence clocks.
            # Hold these ambiguous spans; neither endpoint supplies a reliable
            # weekly clock. Single dated events below remain collectable.
            continue
        elif _within(start, end, now):
            yield _row(TENNESSEE, title, start, end, url, urlsplit(url).path, body, image=candidate)


def _somers_brew(soup, now):
    text = _text(soup)
    if not re.search(r"705\s+W\s+New York Avenue", text, re.I):
        raise ValueError("somers_brewing_venue_changed")
    local = now.astimezone(ZoneInfo(ZONE))
    # The reviewed page's monthly header scopes the recurring advertisement.
    # Do not roll an unchanged November page into December or another year.
    month = re.search(r"\b([A-Z][a-z]+) Hours\s*[–—-]\s*Open", text)
    if not month or month[1] != local.strftime("%B"):
        return
    paragraphs = soup.select("p")
    for weekday, label, pattern, clock_start, clock_end in (
        (2, "DJ Trivia", r"WEDNESDAYS\s*[–—-]\s*DJ TRIVIA", "7PM", None),
        (3, "Live Music", r"THURSDAYS\s*[–—-]\s*LIVE MUSIC", "6PM", "8PM"),
    ):
        matches = [p for p in paragraphs if re.search(pattern, _text(p), re.I)]
        if len(matches) != 1:
            raise ValueError("somers_brewing_schedule_changed")
        body = narrative(matches[0])
        if (weekday == 2 and not re.search(r"Signups at 7\s*pm", plain(body), re.I)
                or weekday == 3 and not re.search(r"6\s*[-–]\s*8\s*pm", plain(body), re.I)):
            raise ValueError("somers_brewing_schedule_changed")
        day = local.date()
        stop = date(local.year, local.month, calendar.monthrange(local.year, local.month)[1])
        while day <= stop:
            if day.weekday() == weekday:
                start = _clock(day, clock_start)
                end = _clock(day, clock_end) if clock_end else None
                if _within(start, end, now):
                    yield _row(SOMERS_BREW, label, start, end, SOURCES[SOMERS_BREW][0],
                               f"{weekday}:{day}", body)
            day += timedelta(days=1)


def _seaside(soup, now):
    program = soup.select_one(".pool-program#harrahs")
    if program is None or "Atlantic City, NJ" not in _text(program):
        raise ValueError("seaside_wellness_venue_changed")
    lead = _text(program.select_one(".pool-lead"))
    season = re.search(r"Running Saturdays and Sundays, ([A-Za-z]+ \d{1,2}) through ([A-Za-z]+ \d{1,2}), (20\d{2})", lead)
    if not season:
        raise ValueError("seaside_wellness_season_missing")
    start_day = datetime.strptime(season[1] + " " + season[3], "%B %d %Y").date()
    end_day = datetime.strptime(season[2] + " " + season[3], "%B %d %Y").date()
    local = now.astimezone(ZoneInfo(ZONE)).date()
    shared = "\n".join(narrative(node) for node in program.select(".pool-lead,.id-notice,.pool-cta,.pool-footnote"))
    for day_block in program.select(".pool-day"):
        weekday_name = _text(day_block.select_one(".pool-day-name"))
        if weekday_name not in ("Saturday", "Sunday"):
            raise ValueError("seaside_wellness_schedule_changed")
        weekday = 5 if weekday_name == "Saturday" else 6
        for item in day_block.select(".pool-class"):
            title = _text(item.select_one("h4"))
            body = narrative(item) + "\n" + shared
            day = max(start_day, local)
            stop = min(end_day, local + timedelta(days=59))
            while day <= stop:
                if day.weekday() == weekday:
                    start = _clock(day, _text(item.select_one(".pool-time")))
                    if _within(start, None, now):
                        yield _row(SEASIDE, title, start, None, SOURCES[SEASIDE][0],
                                   f"{weekday}:{title}:{day}", body)
                day += timedelta(days=1)
    # One-off sound bowl sessions share a page with Wildwood. Select only the
    # explicitly named Harrah's session; never transplant the other venue.
    feature = soup.select_one(".feature-event-body")
    if feature:
        for item in feature.select(".fe-session"):
            doors = _text(item.select_one(".fe-s-doors"))
            if "The Pool at Harrah's" not in doors:
                continue
            shown = _text(item.select_one(".fe-s-label"))
            day = datetime.strptime(shown, "%A · %B %d, %Y").date()
            if not shown.startswith(day.strftime("%A")):
                raise ValueError("seaside_wellness_schedule_conflict")
            start = _clock(day, _text(item.select_one(".fe-s-time")))
            end = _clock(day, "8PM") if re.search(r"Ends 8:00\b", doors) and start.hour == 19 else None
            if _within(start, end, now):
                # Keep the full event section, including both date locations,
                # pricing and booking conditions, exactly as the host explains it.
                body = narrative(feature)
                yield _row(SEASIDE, _text(feature.select_one(".fe-title")), start, end,
                           SOURCES[SEASIDE][0], "sound-bowl:" + day.isoformat(), body)


def _josie(source, fetch, deadline_at):
    """Reuse the deployed WordPress collector and its bounded pagination."""
    from roomquest.wordpress_adapter import collect as collect_wordpress
    raw_by_id = {}

    def reviewed_fetch(url, accept):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "josiekellys.com" or parsed.path != urlsplit(JOSIE_API).path:
            raise ValueError("josie_calendar_endpoint_changed")
        payload = json.loads(fetch(url, accept))
        if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
            raise ValueError("unsupported_wordpress_payload")
        accepted = []
        for item in payload["events"]:
            title = plain(item.get("title"))
            if (item.get("status") != "publish" or EXCLUDED.search(title)
                    or item.get("event_status") in ("cancelled", "canceled", "postponed")
                    or any(item.get(flag) in (True, 1, "1", "true") for flag in ("all_day", "virtual", "is_virtual", "hide_from_listings"))):
                continue
            if not event_url(JOSIE, item.get("url")) or item.get("timezone") != ZONE:
                raise ValueError("josie_event_identity_changed")
            for field in ("start_date", "end_date"):
                if timestamp(item.get(field), ZONE) != timestamp(item.get("utc_" + field), "UTC"):
                    raise ValueError("josie_schedule_conflict")
            body = narrative(item.get("description"))
            venue = item.get("venue") or {}
            if venue and (not isinstance(venue, dict) or "josie" not in plain(venue.get("venue")).casefold()):
                continue
            # The publisher's own venue calendar has empty venue=[] for its
            # on-site music. Its contact footer supplies this exact street.
            venue = {"venue": VENUES[JOSIE][0], "address": "908 Shore Road", "city": "Somers Point",
                     "state": "NJ", "zip": "08244"}
            item = {**item, "venue": venue}
            # TEC uses start=end when the host has supplied only a start time.
            # Leave the end unknown instead of publishing a zero-length event.
            if item.get("start_date") == item.get("end_date"):
                item = {**item, "end_date": None, "utc_end_date": None}
            raw_by_id[str(item["id"])] = (body, item)
            accepted.append(item)
        return json.dumps({**payload, "events": accepted})

    rows = collect_wordpress({**source, "feed_url": JOSIE_API}, reviewed_fetch, deadline_at=deadline_at)
    for row in rows:
        body, raw = raw_by_id[row["id"]]
        row.update(description=body, timezone=ZONE, attendance_mode="in_person",
                   location_provenance="reviewed_venue_street_address_pending_geocode")
        image = raw.get("image")
        if isinstance(image, dict) and (candidate := photo_url(JOSIE, image.get("url"))):
            row["image_url"] = candidate
        yield row


def _carolines(soup, now):
    local = now.astimezone(ZoneInfo(ZONE)).date()
    cards = soup.select(".onespecial")
    if not cards and not soup.find(string=re.compile("Happy Hour Specials")):
        raise ValueError("carolines_calendar_changed")
    for card in cards:
        heading = _text(card.select_one("h2"))
        match = re.fullmatch(r"(\w+) (\w+) (\d{1,2})(?:st|nd|rd|th)", heading)
        if not match:
            raise ValueError("carolines_schedule_changed")
        # This live seven-day specials view omits the year. Only accept its
        # unique current-week date with a matching displayed weekday.
        candidates = []
        for year in (local.year - 1, local.year, local.year + 1):
            day = datetime.strptime(f"{match[2]} {match[3]} {year}", "%B %d %Y").date()
            if local - timedelta(days=1) <= day <= local + timedelta(days=7) and day.strftime("%A") == match[1]:
                candidates.append(day)
        if len(candidates) != 1:
            continue
        for item in card.select(".row"):
            body = _text(item.select_one(".col-sm-8"))
            if not re.search(r"\b(?:trivia|bingo|karaoke|open mic|live music)\b", body, re.I):
                continue
            clocks = re.split(r"\s+[-–]\s+", _text(item.select_one(".col-sm-4")))
            if len(clocks) != 2:
                raise ValueError("carolines_schedule_changed")
            start, end = (_clock(candidates[0], value) for value in clocks)
            if end <= start:
                end += timedelta(days=1)
            if _within(start, end, now):
                title = body.split("|")[0].strip()
                yield _row(CAROLINES, title, start, end, SOURCES[CAROLINES][0],
                           f"{title}:{candidates[0]}", body)


def _smithville(soup, fetch, now):
    """iCagenda's occurrence URLs carry the year its visible cards omit."""
    cards = []
    for page in range(1, 6):
        if soup.select_one(".ic-list-events") is None:
            raise ValueError("smithville_calendar_changed")
        cards.extend(soup.select(".ic-list-events .ic-event"))
        next_links = [a for a in soup.select(".ic-pagination a[href]")
                      if a.get("href") == f"/?page={page + 1}"]
        if not next_links:
            break
        if page == 5:
            raise ValueError("pagination_limit")
        soup = BeautifulSoup(fetch(SOURCES[SMITHVILLE][0] + f"?page={page + 1}", "text/html"), "html.parser")
    if len(cards) > 100:
        raise ValueError("source_record_limit")
    details = {}
    for card in cards:
        link = card.select_one(".ic-event-title h2 a[href]")
        if link is None:
            raise ValueError("smithville_event_identity_missing")
        title = _text(link)
        if EXCLUDED.search(title):
            continue
        url = urljoin(SOURCES[SMITHVILLE][0], link["href"])
        if not event_url(SMITHVILLE, url):
            raise ValueError("smithville_event_identity_changed")
        encoded = parse_qs(urlsplit(url).query)["date"][0]
        start = timestamp(datetime.strptime(encoded, "%Y-%m-%d-%H-%M"), ZONE)
        visible_time = _text(card.select_one(".ic-single-starttime"))
        # Greetings and all-day placeholders are not timed public events.
        # No midnight occurrence or guessed duration is manufactured for them.
        hospitality = title.casefold() == "hospitality night" and not visible_time
        if not visible_time and not hospitality:
            continue
        if hospitality:
            # Its listing carries a midnight placeholder. Resolve the explicit
            # evening clocks below before deciding whether today has ended.
            if not now.astimezone(ZoneInfo(ZONE)).date() <= start.date() <= (now + timedelta(days=60)).date():
                continue
        elif not _within(start, None, now):
            continue
        shown_day = _text(card.select_one(".ic-single-next"))
        parsed_day = datetime.strptime(shown_day + " " + str(start.year), "%A, %B %d %Y").date()
        if (parsed_day != start.date() or not shown_day.startswith(start.strftime("%A"))
                or visible_time and _clock(start.date(), visible_time) != start):
            raise ValueError("smithville_schedule_conflict")
        path = urlsplit(url).path
        if path not in details:
            if len(details) >= 12:
                raise ValueError("smithville_detail_limit")
            detail = BeautifulSoup(fetch(url, "text/html"), "html.parser")
            if _text(detail.select_one(".ic-event-header h1")) != title:
                raise ValueError("smithville_detail_identity_conflict")
            body = narrative(detail.select_one(".ic-full-description"))
            # Only events explicitly situated at the reviewed village address
            # inherit that address; an individual shop must supply its own.
            if not (re.search(r"615\s+E\.?\s+Moss Mill R(?:d|oad)", plain(body), re.I)
                    or hospitality and "at Historic Smithville" in body):
                continue
            times = {_text(item) for item in detail.select("#detail-date-list li.alldates")}
            img = detail.select_one(".ic-image img[src]")
            image = urljoin(SOURCES[SMITHVILLE][0], img["src"]) if img else None
            details[path] = (body, times, image)
        body, published_times, image = details[path]
        expected = f"{shown_day} {visible_time}".strip()
        if expected not in published_times:
            raise ValueError("smithville_occurrence_missing_in_detail")
        end = None
        if hospitality:
            clocks = re.search(r"\b(\d{1,2}(?::\d{2})?\s*[AP]M)\s*[-–]\s*(\d{1,2}(?::\d{2})?\s*[AP]M)\b", plain(body), re.I)
            if not clocks:
                continue
            start, end = _clock(start.date(), clocks[1]), _clock(start.date(), clocks[2])
        if _within(start, end, now):
            yield _row(SMITHVILLE, title, start, end, url, path + ":" + encoded, body, image=image)


def collect(source, fetch, *, deadline_at=None, now=None):
    key = source.get("source_key")
    profile = SOURCES.get(key)
    if profile is None or (source.get("feed_url"), source.get("kind"), source.get("platform_adapter"),
                           source.get("timezone")) != (profile[0], "html", "html", ZONE):
        raise ValueError("unregistered_atlantic_city_venue")
    current = now or datetime.now(timezone.utc)
    if key == JOSIE:
        rows = _josie(source, fetch, deadline_at)
    else:
        soup = BeautifulSoup(fetch(profile[0], "text/html"), "html.parser")
        rows = (_smithville(soup, fetch, current) if key == SMITHVILLE else
                {ANCHOR: _anchor, TENNESSEE: _tennessee, SOMERS_BREW: _somers_brew,
                 SEASIDE: _seaside, CAROLINES: _carolines}[key](soup, current))
    unique = {}
    for row in rows:
        if row is None:
            continue
        identity = (row["id"], row["starts_at"])
        if identity in unique and row != unique[identity]:
            raise ValueError("conflicting_event_occurrence")
        unique[identity] = row
        if len(unique) > MAX_RECORDS:
            raise ValueError("source_record_limit")
    return sorted(unique.values(), key=lambda row: (row["starts_at"], row["id"]))
