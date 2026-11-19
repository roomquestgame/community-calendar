"""Strict direct-publisher fitness schedule guard: exact class identity and street."""
from datetime import datetime, timezone
import json
import pytest

from roomquest import santa_cruz_goat_fitness as m
from roomquest.publisher_evidence import family

NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)
SOURCE = {"source_key":m.KEY, "feed_url":m.CALENDAR, "kind":"html",
          "platform_adapter":"html", "timezone":m.ZONE}
UID = "20917855"
URL = "https://goatsantacruz.punchpass.com/classes/" + UID
FULL_BODY = ("HYROX Power circuit workouts focus on strength movements and integrated "
             "cardio bursts. The exercises are straightforward and suitable for all "
             "levels; this Power class combines functional strength and cardio. "
             "Bring water and wear supportive training shoes.")

def _data(**overrides):
    e = {"@context":"https://schema.org","@type":"Event",
         "name":"HYROX Power",
         "startDate":"2026-11-19T09:15:00-08:00",
         "endDate":"2026-11-19T10:10:00-08:00",
         "eventStatus":"https://schema.org/EventScheduled",
         "eventAttendanceMode":"https://schema.org/OfflineEventAttendanceMode",
         "organizer":{"name":"GOAT Santa Cruz","url":"https://www.goatsantacruz.com"},
         "location":{"address":{"streetAddress":"1055 17th Ave",
                                 "addressLocality":"Santa Cruz","addressRegion":"CA",
                                 "postalCode":"95062","addressCountry":"US"}}}
    e.update(overrides)
    return e

def _fetch(*, data=None, body=FULL_BODY, label="9:15 am HYROX Power"):
    event = data or _data()
    main = (f'<script type="application/ld+json">{json.dumps(event)}</script>'
            f'<div class="wysiwygified-text"><p>{body}</p></div>')
    calendar = (f'<a href="https://goatsantacruz.punchpass.com/org/10771/'
                f'classes/{UID}?source=cal">{label}</a>')
    calendar += "<div>" + "Official GOAT Santa Cruz calendar " * 100 + "</div>"
    main += "<div>" + "Class registration " * 120 + "</div>"
    def fetch(url, accept):
        if url == m.CALENDAR: return calendar
        if url == URL: return main
        raise AssertionError(url)
    return fetch

def test_publisher_hyrox_exact_street_start_end_narrative_and_no_guessed_pin():
    rows = m.collect(SOURCE,_fetch(),now=NOW)
    assert len(rows)==1
    r=rows[0]
    assert r["event_url"]==URL
    assert r["venue_address"]=="1055 17th Ave, Santa Cruz, CA 95062"
    assert r["starts_at"]=="2026-11-19T17:15:00+00:00"
    assert r["ends_at"]=="2026-11-19T18:10:00+00:00"
    assert r["description"]==FULL_BODY
    assert r["lat"] is None and r["lng"] is None
    assert r["image_url"] is None
    assert family(m.KEY,URL)=="santa_cruz_goat_fitness"

def test_reject_non_owner_street_and_clocks_or_missing_description():
    for e in (
        _data(location={"address":_data()["location"]["address"] | {"streetAddress":"1056 17th Ave"}}),
        _data(organizer={"name":"Other Gym","url":"https://www.goatsantacruz.com"}),
        _data(endDate="2026-11-19T08:15:00-08:00"),
        _data(startDate="2026-11-19T09:15:00-05:00"),
        _data(eventStatus="https://schema.org/EventCancelled"),
    ):
        assert m.collect(SOURCE,_fetch(data=e),now=NOW)==[]
    assert m.collect(SOURCE,_fetch(body="Too brief"),now=NOW)==[]

def test_original_calendar_class_identity_and_source_contract():
    with pytest.raises(ValueError,match="goat_source_identity_mismatch"):
        m.collect(SOURCE|{"feed_url":m.CALENDAR+"?extra=1"},_fetch(),now=NOW)
    assert not m.event_url(URL+"?source=cal")
    assert not m.event_url("https://attacker.example/classes/"+UID)
    assert m.collect(SOURCE,_fetch(label="9:15 am Yoga"),now=NOW)==[]

def test_only_real_dated_future_not_synthetic_repeats():
    assert m.collect(SOURCE,_fetch(),now=datetime(2027,2,20,tzinfo=timezone.utc))==[]
