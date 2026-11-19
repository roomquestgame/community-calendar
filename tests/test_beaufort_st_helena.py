"""St. Helena official first-party bounded iCalendar safety tests."""
from datetime import datetime, timezone
from unittest.mock import patch
from test_beaufort_library_branches import source, fixture
from roomquest import beaufort_library_branches as b


def test_st_helena_url_and_old_branch_stability():
    key=b.ST_HELENA_KEY
    assert b.SOURCES[key][:5] == (80,"St. Helena Branch Library",
                                   "6355 Jonathan Francis Sr. Rd",
                                   "St. Helena Island","29920")
    assert b.collection_url(key,datetime(2026,11,19,tzinfo=timezone.utc)) == (
        "https://beaufort.librarycalendar.com/events/feed/ical?"
        "branches%5B80%5D=80&start=2026-11-19&end=2027-01-18")
    assert b.source_valid(source(key))
    for old in b.SOURCES:
        if old != key:
            assert b.collection_url(old)==b.feed_url(old)
    assert b.event_url(key,"https://beaufort.librarycalendar.com/event/chess-club-3935")
    assert not b.event_url(key,"https://invalid.example/event/chess-club-3935")


def test_st_helena_bounded_fetch_and_event_provenance():
    key=b.ST_HELENA_KEY
    payload,row=fixture(key,title="Chess Club",narrative="Join chess club for friendly games.")
    calls=[]
    def fetch(url,accept):
        calls.append((url,accept))
        return payload
    with patch("roomquest.ics_adapter.parse",return_value=[row]):
        records=b.collect(source(key),fetch)
    assert len(records)==1
    assert len(calls)==1
    assert calls[0][1]=="text/calendar"
    assert "&start=" in calls[0][0] and "&end=" in calls[0][0]
    assert records[0]["venue_address"].startswith("6355 Jonathan Francis Sr. Rd")
    assert records[0]["category"]=="hang_out"
    assert records[0]["lat"]==32.3879972
    assert records[0]["lng"]==-80.5713595
    assert records[0]["description"]=="Join chess club for friendly games."
