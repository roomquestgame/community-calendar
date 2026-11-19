"""Exact owner-origin event dates and real Loft Coffee street; never invented recurrences."""
from datetime import datetime, timezone
import json
import pytest
from roomquest import santa_cruz_dante as m
from roomquest.publisher_evidence import family

NOW = datetime(2026, 11, 19, 16, tzinfo=timezone.utc)
SOURCE = {"source_key":m.KEY, "feed_url":m.INDEX, "kind":"html",
          "platform_adapter":"html", "timezone":m.ZONE}
DATES = ("2026-11-21","2026-12-12")
def event(day, street=m.STREET, *, summary=None, status="https://schema.org/EventScheduled"):
    desc=summary if summary is not None else "Join us for informal Italian conversation and coffee from 11:00 AM–12:00 PM on the second and fourth Saturday of each month. All levels welcome."
    return {"@context":"https://schema.org","@type":"Event",
            "name":"Una tazzina di caffè  @LOFT Coffee",
            "description":desc,"startDate":f"{day}T11:00:00-08:00",
            "endDate":f"{day}T12:00:00-08:00",
            "eventStatus":status,"location":{"@type":"Place","name":m.VENUE,"address":street}}
def fixture(*, dates=DATES, location=m.STREET, status="https://schema.org/EventScheduled", show_full=True):
    links=''.join(f'<a href="{m.PREFIX}una-tazzina-di-caffe-loft-coffee-{day}-11-00">Read</a>' for day in dates)
    links += '<a href="https://www.dantesantacruz.com/event-details/scopa-game-night-at-the-point-at-seascape-1">Scopa</a>'
    pages={m.INDEX:f'<main>{links}</main>'}
    for day in dates:
        payload=event(day,location,status=status)
        summary=payload["description"]
        body=f'<div class="X7JGg">Ci vediamo per un caffè? {summary} This is a free event, aside from any beverages/treats.</div>' if show_full else "<div>Missing owner body</div>"
        pages[m.PREFIX+f'una-tazzina-di-caffe-loft-coffee-{day}-11-00']= (
            '<html><script type="application/ld+json">'+json.dumps(payload)+'</script>'+body+'</html>')
    return lambda url,accept: pages[url]

def test_utc_local_times_original_owner_streets_full_narrative():
    rows=m.collect(SOURCE,fixture(),now=NOW)
    assert len(rows)==2
    assert rows[0]["starts_at"]=="2026-11-21T19:00:00+00:00"
    assert rows[1]["ends_at"]=="2026-12-12T20:00:00+00:00"
    for row in rows:
        assert row["venue_address"]==m.STREET
        assert row["lat"] is None and row["lng"] is None
        assert "This is a free event" in row["description"]
        assert row["publisher_details"]=={}
        assert row["timezone"]==m.ZONE
        assert family(m.KEY,row["event_url"])=="dante_santa_cruz"

@pytest.mark.parametrize("bad",[
  "2701 Cabrillo College Dr, Aptos, CA",
  "10 Pacific Ave, Santa Cruz, CA",
  "Location is TBD"
])
def test_bad_or_shortened_street_is_held(bad):
    with pytest.raises(ValueError,match="dante_event_venue_unverified"):
        m.collect(SOURCE,fixture(location=bad),now=NOW)

def test_complete_owner_description_required():
    with pytest.raises(ValueError,match="dante_full_narrative_missing"):
        m.collect(SOURCE,fixture(show_full=False),now=NOW)

def test_future_dates_are_only_listed_occurrences_no_synthetic_recurrence():
    rows=m.collect(SOURCE,fixture(dates=("2026-12-12",)),now=NOW)
    assert len(rows)==1
    assert rows[0]["starts_at"]=="2026-12-12T19:00:00+00:00"

def test_cancelled_event_not_enrolled():
    rows=m.collect(SOURCE,fixture(status="https://schema.org/EventCancelled"),now=NOW)
    assert rows==[]

def test_bad_source_identity_and_url_fail_closed():
    with pytest.raises(ValueError,match="dante_source_identity_mismatch"):
        m.collect({**SOURCE,"feed_url":"https://evil.example/events"},fixture(),now=NOW)
    assert not m.event_url("https://evil.example/event-details/una-tazzina-di-caffe-loft-coffee-2026-12-12-11-00")
    assert not m.event_url("https://www.dantesantacruz.com/event-details/scopa-game-night-at-the-point-at-seascape-1")
    assert not m.event_url(m.PREFIX+"una-tazzina-di-caffe-loft-coffee-2026-12-12-11-00?tracking=1")

def test_empty_index_is_not_a_calendar():
    rows=m.collect(SOURCE,lambda u,a:"<main>No upcoming</main>",now=NOW)
    assert rows==[]
