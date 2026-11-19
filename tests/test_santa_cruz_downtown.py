"""Guard original Downtown Santa Cruz authored event and kiosk vs city-center drift."""
from datetime import datetime, timezone
import pytest
from roomquest import santa_cruz_downtown as m
from roomquest.publisher_evidence import family

NOW = datetime(2026, 11, 19, 21, tzinfo=timezone.utc)
SOURCE = {"source_key":m.KEY,"feed_url":m.URL,"kind":"html",
          "platform_adapter":"html","timezone":m.ZONE}
EVENT = """<html><main><h1>The Naughty List</h1>
<p>Category: Event Calendar</p><p>Date and Time Friday, Dec 11, 2026 6pm - 9pm</p>
<p>Location Downtown Santa Cruz</p>
<p>Santa's working on his list, but we already know which one you're on...</p>
<p>Celebrate your status on The Naughty List with a holiday scavenger hunt.</p>
<p>The Naughty List check in location is at the Downtown Info Kiosk: 1130 Pacific Ave. K2</p>
<p>Ticket holders get event wristbands and scavenger clues after showing an ID.</p>
<p>Participants can check-in starting at 5:30pm, and the event begins at 6PM. The event ends at 9pm.</p>
<p>Only ticket buyers are eligible to win the prizes at the raffle at 9pm.</p>
<p>Only those 21 years of age or older may attend this special event.</p>
</main></html>"""
KIOSK = """<html><main><h1>Downtown Information Kiosk</h1>
<p>The Downtown Information Kiosk is located at 1130-K2 Pacific Avenue, Santa Cruz.</p>
</main></html>"""


def fetch(url, accept):
    assert accept == "text/html"
    return {m.URL:EVENT,m.KIOSK:KIOSK}[url]


def test_guarded_publisher_and_checkin_street():
    rows = m.collect(SOURCE, fetch, now=NOW)
    assert len(rows) == 1
    row = rows[0]
    assert row["venue_address"] == m.STREET
    assert row["starts_at"] == "2026-12-12T02:00:00+00:00"
    assert row["ends_at"] == "2026-12-12T05:00:00+00:00"
    assert row.get("latitude") is None and row.get("longitude") is None
    assert "Only ticket buyers" in row["description"]
    assert row["timezone"] == m.ZONE
    assert family(m.KEY,m.URL) == "santa_cruz_downtown"


def test_rejects_owner_identity_and_aggregator_routes():
    assert not m.event_url("https://downtownsantacruz.com/do/first-friday")
    assert not m.event_url(m.URL+"?format=json")
    with pytest.raises(ValueError, match="downtown_source_identity"):
        m.collect({**SOURCE,"feed_url":"https://downtownsantacruz.com/do/first-friday"},fetch,now=NOW)


@pytest.mark.parametrize("payload", [
    EVENT.replace("Dec 11, 2026", "Dec 12, 2026"),
    EVENT.replace("1130 Pacific Ave. K2", "1000 Pacific Ave. K2"),
    EVENT.replace("event begins at 6PM", "event begins at 5PM"),
    EVENT.replace("Only ticket buyers", "Any ticket buyers"),
])
def test_missing_owner_schedule_or_narrative_fails(payload):
    with pytest.raises(ValueError):
        m.collect(SOURCE,lambda u,a: payload if u==m.URL else KIOSK,now=NOW)


def test_kiosk_official_address_is_required():
    with pytest.raises(ValueError, match="downtown_official_kiosk"):
        m.collect(SOURCE,lambda u,a: EVENT if u==m.URL else KIOSK.replace("1130-K2","9999-K2"),now=NOW)
