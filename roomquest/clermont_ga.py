"""First-party Clermont, GA Drupal FullCalendar: dated public community events.

The embedded calendar event is an index, not sufficient venue evidence. Each
timed listing must pass a separate official detail-page street/title/time check.
Town office closures and council-only items are not general Events cards.
"""
from datetime import datetime, timedelta, timezone
import json
import re
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record
from roomquest.publisher_evidence import attach

KEY = "clermont_town_calendar_ga"
URL = "https://clermontga.com/town-calendar"
ZONE = "America/New_York"
HOST = "clermontga.com"
MAX_DAYS = 90
MAX_RECORDS = 80
SLUG = re.compile(r"/event/[a-z0-9][a-z0-9-]{2,95}")
CLOSED = re.compile(r"\b(?:office closed|holiday closure|closed for|cancelled|canceled|postponed)\b", re.I)
CIVIC = re.compile(r"\b(?:council meeting|planning and zoning meeting|public hearing|board meeting)\b", re.I)
PARK = re.compile(r"\bchattahoochee\s+park\s*[-–:]\s*(639\s+main\s+street)\b", re.I)


def event_url(value):
    if not isinstance(value, str) or len(value) > 250:
        return False
    try:
        u = urlsplit(value)
        return (u.scheme == "https" and u.hostname in {HOST, "www." + HOST}
                and u.username is None and u.password is None and u.port in (None, 443)
                and not u.query and not u.fragment and bool(SLUG.fullmatch(u.path)))
    except ValueError:
        return False


def _clock(value):
    if not isinstance(value, str) or not re.fullmatch(r"20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d", value):
        return None
    try:
        moment = datetime.fromisoformat(value).replace(tzinfo=ZoneInfo(ZONE))
        if (moment.astimezone(timezone.utc).astimezone(ZoneInfo(ZONE)).replace(tzinfo=None)
                != moment.replace(tzinfo=None)):
            return None
        if moment.utcoffset() != moment.replace(fold=1).utcoffset():
            return None
        return moment
    except ValueError:
        return None


def _options(payload):
    dom = BeautifulSoup(payload, "html.parser")
    el = dom.select_one('script[data-drupal-selector="drupal-settings-json"][type="application/json"]')
    if el is None:
        raise ValueError("clermont_calendar_settings_missing")
    settings = json.loads(el.string or el.get_text())
    view = settings.get("fullCalendarView")
    if not isinstance(view, list) or len(view) != 1:
        raise ValueError("clermont_calendar_view_changed")
    options = json.loads(view[0].get("calendar_options") or "{}")
    if options.get("timeZone") != ZONE:
        raise ValueError("clermont_calendar_timezone_changed")
    events = options.get("events")
    if not isinstance(events, list) or len(events) > MAX_RECORDS:
        raise ValueError("clermont_calendar_events_invalid")
    return events


def parse(payload, fetch_detail, *, now=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("timezone_unresolved")
    out = {}
    for index in _options(payload):
        if not isinstance(index, dict) or index.get("allDay") is not False:
            continue
        title = plain(index.get("title"))
        if not title or CLOSED.search(title) or CIVIC.search(title):
            continue
        path = index.get("url")
        eid = index.get("eid")
        if not isinstance(path, str) or not SLUG.fullmatch(path):
            continue
        if not isinstance(eid, str) or not re.fullmatch(r"\d{1,8}-D-\d{1,5}", eid):
            continue
        start = _clock(index.get("start"))
        end = _clock(index.get("end"))
        if not start or not end or not (now <= start.astimezone(timezone.utc)
                <= now + timedelta(days=MAX_DAYS)) or not start < end:
            continue
        link = "https://" + HOST + path
        if not event_url(link):
            continue
        detail = BeautifulSoup(fetch_detail(link, "text/html"), "html.parser")
        article_title = detail.select_one(".field--name-title")
        date_field = detail.select_one(".field--name-field-when")
        venue_field = detail.select_one(".field--name-field-location-name .field__item")
        body_field = detail.select_one(".node__content .field--name-body .field__item")
        if not all((article_title, date_field, venue_field, body_field)):
            continue
        if plain(article_title.get_text(" ", strip=True)).casefold() != title.casefold():
            continue
        date_text = plain(date_field.get_text(" ", strip=True))
        date_label = start.strftime("%b %d %Y").replace(" 0", " ")
        if (date_label not in date_text
            or any(f"{m.hour % 12 or 12}:{m.minute:02}" not in date_text for m in (start, end))):
            continue
        venue = plain(venue_field.get_text(" ", strip=True))
        body = body_field.get_text(" ", strip=True)
        if CLOSED.search(body) or not re.search(r"\b(?:parade|festival|tree lighting)\b", title, re.I):
            # Civic meetings and unspecific notices cannot enter general Events.
            continue
        found = PARK.search(body)
        if not found or venue.casefold() != "clermont chattahoochee park":
            continue
        street = "639 Main Street, Clermont, GA"
        row = record(title, start.isoformat(), end.isoformat(), venue,
                     street, "Clermont", link, eid, "Festival", tz=ZONE,
                     retain_until_end=True)
        if row is None:
            continue
        row.update(description=description(str(body_field), limit=12000), timezone=ZONE,
                   location_provenance="publisher_event_description_street",
                   publisher_status="scheduled",
                   publisher_categories=["Community", "Festival"])
        row = attach(row, KEY, facts={"publisher_event_id": eid,
                                     "publisher_venue_address": street,
                                     "publisher_timezone": ZONE})
        identity = (eid, row["starts_at"])
        if identity in out and out[identity] != row:
            raise ValueError("conflicting_event_occurrence")
        out[identity] = row
    return sorted(out.values(), key=lambda x: (x["starts_at"], x["id"]))


def collect(source, fetch, *, deadline_at=None):
    if (source.get("source_key") != KEY or source.get("feed_url") != URL
            or source.get("kind") != "html"
            or source.get("platform_adapter") != "clermont_drupal_calendar"
            or source.get("timezone") != ZONE):
        raise ValueError("unregistered_clermont_source")
    if deadline_at is not None and monotonic() > deadline_at:
        raise ValueError("collection_deadline")
    return parse(fetch(URL, "text/html"), fetch)
