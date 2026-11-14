"""Remaining Boston native narratives, actual venues and complete snapshots."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from html import escape
import json
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import pytest

from roomquest import boston_community_remaining as b, boston_sources


NOW = datetime.now(timezone.utc)
START = (NOW + timedelta(days=7)).astimezone(ZoneInfo(b.ZONE)).replace(hour=10, minute=0, second=0, microsecond=0)


def source(key):
    url, kind, adapter = b.SOURCES[key]
    return dict(source_key=key, feed_url=url, kind=kind, platform_adapter=adapter, timezone=b.ZONE)


def bc_event(**changes):
    event = dict(id=42, title="Community science talk", description="<p>Researchers explain the local river ecosystem.</p>",
        private=False, rejected=False, publish_status="published", status="live", experience="inperson",
        filters={"event_audience": [{"name": "Public"}], "event_types": [{"name": "Lecture"}]},
        location_name="Connolly House", address="300 Hammond Street, Chestnut Hill, MA 02467",
        geo={"street": "300 Hammond Street", "city": "Newton", "state": "MA", "zip": "02467",
             "latitude": 42.331478, "longitude": -71.170242}, localist_url="https://events.bc.edu/event/community-science",
        event_instances=[{"event_instance": {"id": 43, "event_id": 42, "all_day": False,
            "start": START.isoformat(), "end": (START + timedelta(hours=1)).isoformat()}}])
    event.update(changes)
    return {"event": event}


def test_bc_uses_full_native_description_and_actual_geo():
    body = "Native publisher workshop and access instructions. " * 75
    rows = b._bc_events([bc_event(description=f"<p>{body}</p>")], NOW, [])
    assert len(rows) == 1 and rows[0]["description"] == body.strip()
    assert len(rows[0]["description"]) > 2000
    assert rows[0]["venue_address"] == "300 Hammond Street, Chestnut Hill, MA 02467"
    assert rows[0]["lat"] == 42.331478
    boston_sources.validate_records(rows, source(b.BC))


@pytest.mark.parametrize("changes", [
    {"description": ""}, {"description": "Community science talk"}, {"description": "TBD"},
    {"description": "Research summary"}, {"private": True}, {"experience": "virtual"},
    {"filters": {"event_audience": [{"name": "Students"}]}},
    {"location_name": "Away Arena", "address": "", "geo": {}},
])
def test_bc_does_not_fill_private_blank_placeholder_or_away_events(changes):
    assert b._bc_events([bc_event(**changes)], NOW, []) == []


def test_bc_geocode_conflict_does_not_override_reviewed_actual_street():
    event = bc_event(location_name="Trinity Chapel", address="883 Centre Street, Newton, MA 02459",
                     geo={"street": "885 Centre Street", "city": "Newton", "state": "MA", "zip": "02459",
                          "latitude": 42.342777, "longitude": -71.19355})
    row = b._bc_events([event], NOW, [])[0]
    assert row["venue_address"] == "883 Centre Street, Newton, MA 02459"
    assert row["lat"] is None and row["lng"] is None


def test_bc_pagination_must_be_complete():
    def fetch(url, accept):
        return json.dumps({"events": [bc_event()], "page":
            {"current": 1, "total": 1, "total_items": 2, "next_page": None}})
    with pytest.raises(ValueError, match="pagination_incomplete"):
        b.collect(source(b.BC), fetch, now=NOW)


def greenway(index=0, body=None):
    start, end = START + timedelta(days=index), START + timedelta(days=index, hours=1)
    title, url = f"Greenway community workshop {index}", f"https://www.rosekennedygreenway.org/events/workshop-{index}/"
    card = dict(url=url, title=title, start=start.isoformat(), end=end.isoformat(),
                native_id=str(index + 10), venue="Community Pavilion", categories=["Community"])
    export = "https://www.google.com/calendar/event?" + urlencode(dict(ctz=b.ZONE, text=title,
        dates=f"{start:%Y%m%dT%H%M%S}/{end:%Y%m%dT%H%M%S}", location="600 Atlantic Avenue, Boston, MA 02210"))
    detail = (f'<link rel="canonical" href="{url}"><a class="em-a2c-google" href="{escape(export)}">Calendar</a>'
              '<div class="elementor-widget-theme-post-content"><div class="elementor-widget-container">'
              f'{body if body is not None else "<p>Join neighbors for a guided hands-on workshop.</p>"}</div></div>')
    return card, detail


def test_greenway_full_body_uses_explicit_export_times_not_excerpt():
    body = "The complete native event description and workshop requirements. " * 55
    card, detail = greenway(body=f"<p>{body}</p>")
    rows = b._greenway_detail(card, detail, NOW, [])
    assert rows[0]["description"] == body.strip() and len(rows[0]["description"]) > 2000
    assert datetime.fromisoformat(rows[0]["starts_at"]) == START
    with pytest.raises(ValueError, match="time_conflict"):
        b._greenway_detail({**card, "start": (START + timedelta(hours=1)).isoformat()}, detail, NOW, [])


def test_greenway_unknown_location_never_becomes_conservancy_headquarters():
    card, detail = greenway()
    detail = detail.replace("600+Atlantic+Avenue%2C+Boston%2C+MA+02210", "")
    holds = []
    assert b._greenway_detail(card, detail, NOW, holds) == []
    assert holds[0]["reason"] == "boston_remaining_street_unresolved"


def test_durable_snapshot_only_emits_complete_and_rejects_mutations(monkeypatch):
    items = [greenway(i) for i in range(4)]
    monkeypatch.setattr(b, "_greenway_manifest", lambda *args: [i[0] for i in items])
    calls = []
    def fetch(url, accept):
        calls.append(url)
        return dict((c["url"], html) for c, html in items)[url]
    first = b.collect_chunk(source(b.GREENWAY), fetch, now=NOW)
    assert not first["complete"] and first["events"] == []
    assert first["checkpoint"]["cursor"] == 3
    boston_sources.validate_checkpoint(source(b.GREENWAY), first["checkpoint"], now=NOW)
    poisoned = deepcopy(first["checkpoint"])
    poisoned["events"][0]["description"] = "Changed checkpoint narrative"
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        b.collect_chunk(source(b.GREENWAY), fetch, checkpoint=poisoned, now=NOW)
    complete = b.collect_chunk(source(b.GREENWAY), fetch, checkpoint=first["checkpoint"], now=NOW)
    assert complete["complete"] and len(complete["events"]) == 4 and len(calls) == 4
    boston_sources.validate_records(complete["events"], source(b.GREENWAY))
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        b.collect_chunk(source(b.GREENWAY), fetch, checkpoint=first["checkpoint"], now=NOW + timedelta(hours=5))


def nature(body=None, title="Forest discovery workshop", starts=None, address=None):
    starts = starts or [START, START + timedelta(days=7), START + timedelta(days=90)]
    card = dict(url="https://www.massaudubon.org/programs/boston-nature-center/100001-forest-discovery",
                title=title, start=starts[0].isoformat(), venue="Boston Nature Center")
    schema = {"@type": "Event", "name": title, "startDate": starts[0].isoformat(),
        "description": "Short JSON-LD teaser.", "location": {"name": "Boston Nature Center",
        "address": address or {"streetAddress": "500 Walk Hill Street", "addressLocality": "Mattapan",
            "addressRegion": "MA", "postalCode": "02126"}}}
    date_html = "".join('<li class="short-date-time"><span class="icon-date">' + s.strftime("%a, %b %d, %Y") +
        '</span><span class="icon-clock">10:00 am - 11:00 am</span></li>' for s in starts)
    detail = (f'<h1>{escape(title)}</h1><script type="application/ld+json">{json.dumps(schema)}</script>'
        '<div class="overview__content"><div class="attr-description">' +
        (body or "<p>Explore the forest and observe the birds on a guided walk.</p>") + '</div></div>'
        '<div class="instructions-wrapper">What To Expect: Bring a water bottle and warm layers.</div>'
        '<div class="info-card--who">Who: Adults and families</div>'
        '<div class="info-card--admissions">Cost: Adult Members $10; Nonmembers $12</div>'
        f'<div class="info-card--when"><ul>{date_html}</ul></div>')
    return card, detail


def test_nature_preserves_full_html_and_each_explicit_dated_session():
    core = "Explore the native woodland with a naturalist and learn bird identification. " * 35
    card, detail = nature(body=f"<p>{core}</p>")
    rows = b._nature_detail(card, detail, NOW, [])
    assert len(rows) == 2
    assert rows[0]["description"].startswith(core.strip())
    assert "What To Expect" in rows[0]["description"] and "Nonmembers $12" in rows[0]["description"]
    assert "Short JSON-LD teaser" not in rows[0]["description"]
    assert rows[0]["id"] != rows[1]["id"]
    assert rows[0]["venue_address"] == "500 Walk Hill Street, Mattapan, MA 02126"


def test_nature_meeting_directions_override_reused_park_address():
    card, detail = nature(title="Arctic Waterbirds at Castle Island", starts=[START],
        body="<p>Meet at Sullivan's parking lot, 2080 William J Day Blvd, South Boston, MA 02127.</p>",
        address={"streetAddress": "2010 Day Blvd.", "addressLocality": "South Boston", "addressRegion": "MA", "postalCode": "02127"})
    row = b._nature_detail(card, detail, NOW, [])[0]
    assert row["venue_address"] == "2080 William J Day Boulevard, South Boston, MA 02127"
    assert row["lat"] is None


def cares_item(**changes):
    item = dict(opportunityName="Distribute Food at East End House Pantry", organizationServedName="East End House",
        opportunityLink="https://www.bostoncares.org/opportunity/a0CUq00007PDnO0MAL", occurrenceId="a0CUq00007PDnO0MAL",
        description="Help prepare fresh food and pack groceries. Address of Volunteer Opportunity: 105 Spring Street Cambridge, MA 02141.",
        locationCity="Cambridge", locationState="MA", locationZipCode="02141", locationType="Address",
        volunteersStillNeeded="2", scheduledType="Date & Time Specific", timezone=b.ZONE,
        startDateTimeISO=START.strftime("%Y-%m-%dT%H:%M"), endDateTimeISO=(START + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
        startTime="10:00 AM", endTime="11:00 AM")
    item.update(changes)
    return item


def cares_payload(item, **day_changes):
    day = dict(dayDate=START.date().isoformat(), overMaxToReturn=False, events=[], occurrences=[item])
    day.update(day_changes)
    return json.dumps({"code": 200, "items": [day]})


def cares_parse(item, **day_changes):
    return b._cares_events(cares_payload(item, **day_changes), NOW,
        NOW.astimezone(ZoneInfo(b.ZONE)).date(), NOW.astimezone(ZoneInfo(b.ZONE)).date() + timedelta(days=13), [])


def test_cares_preserves_full_native_prose_and_fills_only_actual_venue():
    body = cares_item()["description"] + " Native volunteer access, eligibility and task information." * 55
    row = cares_parse(cares_item(description=body))[0]
    assert row["description"] == body and len(body) > 2000
    assert row["venue_address"] == "105 Spring Street, Cambridge, MA 02141"
    assert row["venue_name"] == "East End House Community Food Pantry"
    boston_sources.validate_records([row], source(b.CARES))


@pytest.mark.parametrize("changes", [{"volunteersStillNeeded": "0"}, {"locationType": None},
    {"locationCity": "Worcester"}, {"description": ""}, {"organizationServedName": "Unknown nonprofit"},
    {"description": "This activity takes place at a different location."}])
def test_cares_unavailable_or_unresolved_items_are_held(changes):
    assert cares_parse(cares_item(**changes)) == []


def test_cares_mobile_market_uses_actual_site_and_exposes_no_false_headquarters():
    row = cares_parse(cares_item(opportunityName="Dorchester - Support the Fresh Truck Mobile Market @ Neponset Health Center",
        organizationServedName="Fresh Truck", locationCity="Dorchester", locationZipCode="02122"))[0]
    assert row["venue_address"] == "10 Minot Street, Dorchester, MA 02122"
    assert cares_parse(cares_item(opportunityName="Fresh Truck unknown mobile market",
        organizationServedName="Fresh Truck", locationCity="Dorchester", locationZipCode="02122")) == []


def test_cares_time_and_completeness_mismatches_fail():
    with pytest.raises(ValueError, match="time_conflict"):
        cares_parse(cares_item(startTime="11:00 AM"))
    with pytest.raises(ValueError, match="pagination_incomplete"):
        cares_parse(cares_item(), overMaxToReturn=True)
    with pytest.raises(ValueError, match="unregistered_boston_remaining_source"):
        b.collect({**source(b.CARES), "feed_url": "https://example.org/calendar"}, lambda *args: "")


def test_cares_callback_is_exact_fourteen_calendar_days():
    calls = []
    def render(**kwargs):
        calls.append(kwargs)
        return cares_payload(cares_item())
    rows = b.collect(source(b.CARES), lambda *args: pytest.fail("No extra GET needed"), now=NOW, render_calendar=render)
    assert len(rows) == 1
    assert set(calls[0]) == {"start_day", "end_day"}
    assert (datetime.fromisoformat(calls[0]["end_day"]) - datetime.fromisoformat(calls[0]["start_day"])).days == 13
