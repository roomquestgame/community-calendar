"""Santa Cruz Chess Club's explicitly published 2026 recurring meetups.

Two club meetings have both original start AND end clocks, plus corroborated venue
streets. Saturday's 11am gathering has no publisher end time and is held.
Only the remaining 2026 weekly dates are materialized; no 2027 recurrence is guessed.
"""
from __future__ import annotations

from datetime import datetime, date, time, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import re

from bs4 import BeautifulSoup
from roomquest.event_description import description
from roomquest.mapsee_adapter import record
from roomquest.publisher_evidence import attach

KEY = "santa_cruz_chess_club_weekly_ca"
URL = "https://www.santacruzchessclub.com/"
ABBOTT_URL = "https://www.abbottsquaremarket.com/contact"
SURF_URL = "https://www.surfcitybilliards.com/"
SOURCES = {KEY: (URL, "html", "html")}
ALLOWED_HOSTS = {KEY: ("www.santacruzchessclub.com", "santacruzchessclub.com",
                        "www.abbottsquaremarket.com", "abbottsquaremarket.com",
                        "www.surfcitybilliards.com", "surfcitybilliards.com")}
ZONE = "America/Los_Angeles"
MAX_HTML = 400000
MAX_RECORDS = 24
MAX_DESCRIPTION = 6000
VENUES = (
    # weekday, owner's exact schedule, street number, address, official verification page
    (1, "Tuesday 6-9pm at Abbott Square!", "725 Front Street", "Abbott Square Market",
     "725 Front St, Santa Cruz, CA 95060", ABBOTT_URL),
    (3, "Thursday 6-9pm at Surf City Billiards!", "931 Pacific Ave", "Surf City Billiards",
     "931 Pacific Ave, Santa Cruz, CA 95060", SURF_URL),
)
CANCELLED = re.compile(r"\b(?:cancelled|canceled|suspended|not meeting|temporarily closed)\b", re.I)


def event_url(value):
    p = urlsplit(value)
    return (value == URL and p.scheme == "https"
            and p.hostname == "www.santacruzchessclub.com" and p.port in (None, 443)
            and not p.username and not p.password and not p.query and not p.fragment)


def _text(payload, *, club=False):
    if not isinstance(payload, str) or not (50 <= len(payload) <= MAX_HTML):
        raise ValueError("chess_html_invalid")
    soup = BeautifulSoup(payload, "html.parser")
    if club and (not soup.title or "Santa Cruz Chess Club" not in soup.title.get_text(" ", strip=True)):
        raise ValueError("chess_owner_identity_missing")
    return soup.get_text(" ", strip=True)


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY
            or (source.get("feed_url"), source.get("kind"),
                source.get("platform_adapter")) != SOURCES[KEY]
            or source.get("timezone") != ZONE):
        raise ValueError("chess_source_identity_mismatch")
    text = _text(fetch(URL, "text/html"), club=True)
    if ("2026 Chess Schedule" not in text or "Updated July 2026" not in text
            or "About the Club" not in text or "Location Details" not in text
            or "We are meeting three times a week" not in text
            or CANCELLED.search(text)):
        raise ValueError("chess_schedule_not_current")
    for day, label, numbered, name, postal, official in VENUES:
        if label not in text or numbered not in text:
            raise ValueError("chess_publisher_schedule_or_venue_drift")
        official_text = _text(fetch(official, "text/html"))
        official_match = ("725 Front Street" if day == 1 else "931 Pacific Ave")
        if (official_match.lower() not in official_text.lower()
                or "Santa Cruz" not in official_text
                or (day == 3 and "95060" not in official_text)):
            raise ValueError("chess_official_venue_street_missing")
    # The original club's about text, not generic generated promotional copy.
    about = text.split("About the Club", 1)[1].split("Location Details", 1)[0].strip()
    if not (100 <= len(about) <= 2000) or "free" not in about.lower() or "board" not in about.lower():
        raise ValueError("chess_original_narrative_missing")
    instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    local_today = instant.astimezone(ZoneInfo(ZONE)).date()
    final_date = min(local_today + timedelta(days=56), date(2026, 12, 30))
    result = []
    for offset in range((final_date - local_today).days + 1):
        d = local_today + timedelta(days=offset)
        for weekday, label, numbered, venue_name, postal, evidence in VENUES:
            if d.weekday() != weekday:
                continue
            # Do not assert a meeting on major venue holiday-closure dates.
            if (d.month, d.day) in {(11, 26), (12, 24), (12, 31)}:
                continue
            start = datetime.combine(d, time(18), tzinfo=ZoneInfo(ZONE))
            end = datetime.combine(d, time(21), tzinfo=ZoneInfo(ZONE))
            if start.astimezone(timezone.utc) < instant - timedelta(hours=3):
                continue
            narrative = description(about + "\n\n" + label + "\n" + numbered,
                                    limit=MAX_DESCRIPTION)
            if len(narrative) < 150:
                raise ValueError("chess_original_narrative_missing")
            row = record("Santa Cruz Chess Club — " + ("Tuesday" if weekday == 1 else "Thursday") +
                         " Casual Chess", start.isoformat(), end.isoformat(), venue_name,
                         postal, "Santa Cruz", URL,
                         f"santa-cruz-chess-club-{weekday}-{d.isoformat()}",
                         "chess, tabletop games, social games, hobby club",
                         None, None, ZONE, retain_until_end=True)
            if row is None:
                continue
            row.update(description=narrative, timezone=ZONE,
                       publisher_categories=["Chess", "Tabletop Games", "Social Club"],
                       location_provenance="club_original_schedule_plus_official_venue_street",
                       location_evidence_url=evidence, schedule_evidence_url=URL)
            result.append(attach(row, KEY, evidence_url=URL))
    if len(result) > MAX_RECORDS:
        raise ValueError("chess_record_limit")
    return result
