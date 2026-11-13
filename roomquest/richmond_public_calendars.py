"""Public HandsOn Connect shifts and RunSignup club-calendar races."""

from datetime import datetime, timedelta, timezone
from html import unescape
import json
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record


ZONE = "America/New_York"
CFENGAGE = "cfengage_volunteer_richmond_va"
ROAD_RUNNERS = "richmond_road_runners_runsignup_va"
CF_HOST = "www.cfengage.org"
RACE_HOST = "runsignup.com"
SOURCES = {
    CFENGAGE: (f"https://{CF_HOST}/calendar", (CF_HOST,)),
    ROAD_RUNNERS: (
        "https://richmondroadrunnersclub.rsupartner.com/upcoming-rrrc-races-events-volunteer-opportunities",
        ("richmondroadrunnersclub.rsupartner.com", RACE_HOST),
    ),
}
CF_API = f"https://{CF_HOST}/search/getOpportunitiesCalendar"
STREET = re.compile(
    r"\b[1-9][0-9]{1,5}\s+(?:[A-Za-z][\w'’-]*\s+){1,7}"
    r"(?:Street|Road|Avenue|Boulevard|Drive|Lane|Court|Way|St|Rd|Ave|Blvd|Dr|Ln)\b(?=[.,;)]|$|\s+(?:Richmond|Henrico|Ashland|Highland Springs|North Chesterfield)\b)",
    re.IGNORECASE,
)
PUBLIC_OPPORTUNITY = re.compile(r"https://www\.cfengage\.org/opportunity/[A-Za-z0-9]{15,18}")
RACE_URL = re.compile(r"https://runsignup\.com/Race/[A-Z]{2}/[^/?#]+/[^/?#]+/?")
RACE_ID = re.compile(r"/races/race([1-9][0-9]{0,9})-")
NON_EVENT = re.compile(r"\b(?:mailing list|interest list|notifications?|donations? only)\b", re.I)


def calendar_form(now=None):
    today = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(ZONE)).date()
    return {
        "searchvo_startfrom": today.isoformat(),
        "searchvo_endfrom": (today + timedelta(days=21)).isoformat(),
    }


def volunteer_shifts(payload):
    days = json.loads(payload).get("items")
    if not isinstance(days, list) or len(days) > 23:
        raise ValueError("invalid_handson_calendar")
    rows = {}
    for day in days:
        if day.get("overMaxToReturn"):
            raise ValueError("handson_calendar_truncated")
        for shift in day["occurrences"]:
            if (shift.get("locationType") != "Address"
                    or shift.get("locationState") != "VA"
                    or shift.get("timezone") != ZONE
                    or shift.get("opportunityType") != "Project"
                    or not str(shift.get("volunteersStillNeeded", "")).isdigit()
                    or int(shift["volunteersStillNeeded"]) == 0):
                continue
            url = shift.get("opportunityLink") or ""
            if not PUBLIC_OPPORTUNITY.fullmatch(url):
                continue
            # This surface withholds many street addresses. Take a single
            # publicly stated street from the event text, never the host's HQ.
            description = BeautifulSoup(shift.get("description") or "", "html.parser").get_text(" ", strip=True)
            streets = set(STREET.findall(description))
            city = plain(shift.get("locationCity"))
            zip_code = str(shift.get("locationZipCode") or "")
            if len(streets) != 1 or not city or not re.fullmatch(r"\d{5}", zip_code):
                continue
            organizer = plain(unescape(shift.get("organizationServedName") or ""))
            starts, ends = shift.get("startDateTimeISO"), shift.get("endDateTimeISO")
            if not organizer or not starts or not ends:
                continue
            street = f"{streets.pop()}, {city}, VA {zip_code}"
            row = record(unescape(shift["opportunityName"]), starts, ends, organizer, street,
                         city, url, shift["occurrenceId"], "volunteering", tz=ZONE)
            if row:
                from roomquest.event_description import description as narrative
                row['description'] = narrative(shift.get('description'))
                rows[row["id"], row["starts_at"]] = row
    return list(rows.values())


def race_listing(payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    table = soup.select_one("table.upcoming-races-table")
    if table is None:
        raise ValueError("runsignup_listing_missing")
    races = {}
    for tr in table.select("tr"):
        link = tr.select_one(".race-title a[href]")
        date = tr.select_one(".calendar-race-date")
        if not link or not date or NON_EVENT.search(link.get_text(" ", strip=True)):
            continue
        day = " ".join(date.get_text(" ", strip=True).split()).split(" - ")[0]
        try:
            day = datetime.strptime(day, "%a, %b %d %Y").date()
        except ValueError:
            continue
        if day < now.date() or day > now.date() + timedelta(days=60):
            continue
        url = link["href"]
        logo = tr.select_one("img[src]")
        identity = RACE_ID.search(urlsplit(logo["src"]).path) if logo else None
        register = tr.select_one('a[href^="https://runsignup.com/Race/Register?raceId="]')
        race_id = register["href"].rsplit("=", 1)[-1] if register else identity[1] if identity else ""
        if re.fullmatch(r"[1-9][0-9]{0,9}", race_id) and RACE_URL.fullmatch(url):
            races[race_id] = url
    if len(races) > 18:
        raise ValueError("runsignup_detail_limit")
    return races


def race_street(soup, venue, city, zip_code):
    # The event schema often holds a place name in the streetAddress field.
    # Prefer the actual Location block when the page lists it.
    for heading in soup.select("h2.rsuWebsiteSection__title"):
        if heading.get_text(" ", strip=True) not in {"Location", "Race Location", "Place"}:
            continue
        place = heading.find_next_sibling("p")
        if place is None:
            continue
        lines = list(place.stripped_strings)
        for i, line in enumerate(lines[:-1]):
            if re.fullmatch(r"[1-9]\d{1,5} .{2,95}", line) and lines[i + 1].startswith(f"{city}, VA {zip_code}"):
                return line
    # City of Richmond's official park directory confirms this named venue.
    if (venue, city, zip_code) == ("Joseph Bryan Park", "Richmond", "23227"):
        return "4308 Hermitage Road"
    return ""


def race_events(payload, identity, listing_url, now):
    soup = BeautifulSoup(payload, "html.parser")
    nodes = soup.select('script[type="application/ld+json"]')
    if not nodes:
        raise ValueError("runsignup_event_data_missing")
    rows = {}
    for node in nodes:
        try:
            event = json.loads(node.string or "")
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("@type") != "SportsEvent" or event.get("additionalType"):
            continue
        label = plain(event.get("name"))
        if not label or NON_EVENT.search(label) or re.search(r"\b(?:virtual|volunteer|expo)\b", label, re.I):
            continue
        if str(event.get("eventStatus") or "").rsplit("/", 1)[-1] in {"EventCancelled", "EventPostponed"}:
            continue
        starts = event.get("startDate")
        if not starts:
            continue
        start = datetime.fromisoformat(starts)
        if start.tzinfo is None or not now <= start <= now + timedelta(days=60):
            continue
        location = event.get("location") or {}
        if location.get("@type") != "Place":
            continue
        addr = location.get("address") or {}
        city, state, zip_code = (plain(addr.get(k)) for k in ("addressLocality", "addressRegion", "postalCode"))
        if state != "VA" or not city or not re.fullmatch(r"\d{5}", zip_code):
            continue
        venue = plain(addr.get("streetAddress"))
        street = venue if re.match(r"^\d+\s+\w", venue) else race_street(soup, venue, city, zip_code)
        if not street:
            continue
        # The race website assigns three-hour end estimates to untimed finishes.
        row = record(label, start.isoformat(), None, venue, f"{street}, {city}, VA {zip_code}",
                     city, listing_url, f"{identity}:{label}", "running")
        if row:
            from roomquest.event_description import description
            row['description'] = description(event.get('description'))
            rows[row["id"], row["starts_at"]] = row
    return list(rows.values())


def collect(source, fetch, *, deadline_at=None, render_volunteers=None):
    key = source.get("source_key")
    config = SOURCES.get(key)
    if not config or (source.get("feed_url"), source.get("timezone"),
                      source.get("kind"), source.get("platform_adapter")) != (config[0], ZONE, "html", "html"):
        raise ValueError("unregistered_richmond_public_calendar")
    if key == CFENGAGE:
        return volunteer_shifts(render_volunteers())
    now = datetime.now(ZoneInfo(ZONE))
    rows = []
    for identity, url in race_listing(fetch(config[0], "text/html"), now).items():
        payload = fetch(url, "text/html")
        rows.extend(race_events(payload, identity, url, now))
    return sorted(rows, key=lambda row: (row["starts_at"], row["id"]))
