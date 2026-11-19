"""Weekly chess can only derive bounded occurrences from the original 2026 owner schedule."""
from datetime import datetime, timezone
import pytest
from roomquest import santa_cruz_chess_club as m
from roomquest.publisher_evidence import family

NOW = datetime(2026, 11, 19, 10, tzinfo=timezone.utc)
SOURCE = {"source_key": m.KEY, "feed_url": m.URL, "kind": "html",
          "platform_adapter": "html", "timezone": m.ZONE}
CLUB = """<html><title>Santa Cruz Chess Club</title><h1>Santa Cruz Chess Club</h1>
<h2>2026 Chess Schedule</h2>
<p>Tuesday 6-9pm at Abbott Square!</p><p>Thursday 6-9pm at Surf City Billiards!</p>
<p>Saturday 11am at 11th Hour Coffee (Center Street Location)!</p>
<p>Updated July 2026</p><h2>About the Club</h2>
<p>We are a free and community member organized club. All skill levels welcome
for fun and casual chess. Bringing your own board is encouraged, but
generally you can just show up and play. We are meeting three times a week
at some of our favorite spots in downtown Santa Cruz!</p>
<h2>Location Details</h2><p>725 Front Street</p><p>Tuesday Nights 6pm to 9pm</p>
<p>931 Pacific Ave</p><p>Thursday Nights 6pm to 9 pm</p>
<p>1001 Center Street</p><p>Saturday Mornings 11am</p></html>"""
ABBOTT = """<html><title>Abbott Square Market</title><p>Contact Us</p>
<p>725 Front Street</p><p>Santa Cruz, CA</p></html>"""
SURF = """<html><title>Surf City Billiards</title><p>931 Pacific Ave</p>
<p>Santa Cruz, Ca 95060</p></html>"""


def fetch(url, accept):
    assert accept == "text/html"
    return {m.URL: CLUB, m.ABBOTT_URL: ABBOTT, m.SURF_URL: SURF}[url]


def test_owner_schedule_true_2026_weekly_recurring_and_addresses():
    rows = m.collect(SOURCE, fetch, now=NOW)
    assert len(rows) >= 8
    assert len({r["id"] for r in rows}) == len(rows)
    assert {r["venue_address"] for r in rows} == {v[4] for v in m.VENUES}
    assert all(r.get("latitude") is None and r.get("longitude") is None for r in rows)
    assert all(r["timezone"] == m.ZONE and r["description"] for r in rows)
    assert any(r["starts_at"] == "2026-11-20T02:00:00+00:00" for r in rows)
    assert not any("2026-11-27" in r["starts_at"] for r in rows)  # Thanksgiving
    assert not any("2027-" in r["starts_at"] for r in rows)
    assert family(m.KEY, m.URL) == "santa_cruz_chess_club"


def test_saturday_no_end_clock_held():
    assert all("Saturday" not in r["title"] for r in m.collect(SOURCE, fetch, now=NOW))


@pytest.mark.parametrize("broken", [
    CLUB.replace("2026 Chess Schedule", "2025 Chess Schedule"),
    CLUB.replace("Tuesday 6-9pm", "Tuesday 7-9pm"),
    CLUB.replace("931 Pacific Ave", "999 Pacific Ave"),
    CLUB.replace("Updated July 2026", "Updated July 2025"),
])
def test_original_schedule_drift_fails(broken):
    with pytest.raises(ValueError):
        m.collect(SOURCE, lambda u, a: broken if u == m.URL else fetch(u,a), now=NOW)


def test_venue_address_evidence_required():
    with pytest.raises(ValueError, match="chess_official_venue_street_missing"):
        m.collect(SOURCE, lambda u,a: SURF.replace("931", "999") if u == m.SURF_URL
                  else fetch(u,a), now=NOW)


def test_source_identity_and_exact_original_url():
    assert m.event_url(m.URL)
    assert not m.event_url(m.URL + "?tracking=1")
    assert not m.event_url("https://santacruzscene.com/series/chess-club")
    with pytest.raises(ValueError, match="chess_source_identity_mismatch"):
        m.collect({**SOURCE,"feed_url":"https://santacruzscene.com/"},fetch,now=NOW)
