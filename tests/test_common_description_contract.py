"""Shared description bounds and same-occurrence HTML alternative."""
from datetime import datetime, timedelta, timezone
from icalendar import Calendar, Event
import pytest
from roomquest.event_description import description, calendar_description
from roomquest.ics_adapter import parse

@pytest.mark.parametrize("n", [0, 600, 2000, 2001, 12000, 12001])
def test_shared_bound_after_sanitizing(n):
    assert description("<nav>menu</nav><p>" + "🎵" * n + "</p>") == "🎵" * min(n, 12000)

def event(primary, alternate, fmt="text/html"):
    e = Event()
    e.add("uid", "same-event")
    e.add("summary", "Workshop")
    e.add("dtstart", datetime.now(timezone.utc) + timedelta(days=2))
    e.add("location", "Workshop hall")
    e.add("geo", (37.5, -78.4))
    e.add("url", "https://publisher.example/event/one")
    if primary is not None:
        e.add("description", primary)
    if alternate is not None:
        e.add("x-alt-desc", alternate, parameters={"FMTTYPE": fmt})
    return e

@pytest.mark.parametrize("primary", [None, "Workshop", "https://publisher.example/event/one", "Bring tools."])
def test_alternate_is_same_occurrence_authentic_prose(primary):
    e = event(primary, "<p>Bring tools. Learn practical woodworking skills.</p>")
    assert calendar_description(e, "Workshop") == "Bring tools. Learn practical woodworking skills."

def test_conflicting_or_non_html_alternate_preserves_primary():
    assert calendar_description(event("Bring tools.", "<p>Different subject.</p>"), "Workshop") == "Bring tools."
    assert calendar_description(event("", "Different subject.", "text/plain"), "Workshop") == ""

def test_ordinary_ics_sanitizes_before_bounding_and_preserves_identity():
    e = event("<nav>" + "x" * 13000 + "</nav><p>" + "y" * 3000 + "</p>", None)
    cal = Calendar()
    cal.add("version", "2.0")
    cal.add_component(e)
    row, = parse(cal.to_ical().decode(), {"source_key": "fixture", "url": "https://publisher.example/calendar.ics"})
    assert row["description"] == "y" * 3000
    assert row["id"] == "same-event"
    assert row["event_url"] == "https://publisher.example/event/one"
