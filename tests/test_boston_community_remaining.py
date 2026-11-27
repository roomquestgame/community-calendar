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
    facts = rows[0]["collector_event_content_v1"]["facts"]
    assert facts["venue_name"] == "Connolly House"
    assert facts["venue_address"] == "300 Hammond Street, Chestnut Hill, MA 02467"
    boston_sources.validate_records(rows, source(b.BC))


@pytest.mark.parametrize("changes", [
    {"description": ""}, {"description": "Community science talk"}, {"description": "TBD"},
    {"description": "Research summary"}, {"private": True}, {"experience": "virtual"},
    {"filters": {"event_audience": [{"name": "Students"}]}},
    {"location_name": "Away Arena", "address": "", "geo": {}},
])
def test_bc_does_not_fill_private_blank_placeholder_or_away_events(changes):
    assert b._bc_events([bc_event(**changes)], NOW, []) == []


def test_bc_geocode_conflict_does_not_borrow_reviewed_nearby_venue_point():
    event = bc_event(location_name="Trinity Chapel Annex", address="883 Centre Street, Newton, MA 02459",
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


def greenway(index=0, body=None, *, title=None, venue="Community Pavilion",
             location="600 Atlantic Avenue, Boston, MA 02210"):
    start, end = START + timedelta(days=index), START + timedelta(days=index, hours=1)
    title = title or f"Greenway community workshop {index}"
    url = f"https://www.rosekennedygreenway.org/events/workshop-{index}/"
    card = dict(url=url, title=title, start=start.isoformat(), end=end.isoformat(),
                native_id=str(index + 10), venue=venue, categories=["Community"])
    export = "https://www.google.com/calendar/event?" + urlencode(dict(ctz=b.ZONE, text=title,
        dates=f"{start:%Y%m%dT%H%M%S}/{end:%Y%m%dT%H%M%S}", location=location))
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
    items = [greenway(i) for i in range(9)]
    monkeypatch.setattr(b, "_greenway_manifest", lambda *args: [i[0] for i in items])
    calls = []
    def fetch(url, accept):
        calls.append(url)
        return dict((c["url"], html) for c, html in items)[url]
    first = b.collect_chunk(source(b.GREENWAY), fetch, now=NOW)
    assert not first["complete"] and first["events"] == []
    assert first["checkpoint"]["cursor"] == 8
    boston_sources.validate_checkpoint(source(b.GREENWAY), first["checkpoint"], now=NOW)
    poisoned = deepcopy(first["checkpoint"])
    poisoned["events"][0]["description"] = "Changed checkpoint narrative"
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        b.collect_chunk(source(b.GREENWAY), fetch, checkpoint=poisoned, now=NOW)
    poisoned = deepcopy(first["checkpoint"])
    poisoned["events"][0]["collector_event_content_v1"]["facts"]["description"] = "Tampered facts."
    poisoned["outcomes"][0]["rows_hash"] = b._digest(poisoned["events"][:1])
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        b.collect_chunk(source(b.GREENWAY), fetch, checkpoint=poisoned, now=NOW)
    complete = b.collect_chunk(source(b.GREENWAY), fetch, checkpoint=first["checkpoint"], now=NOW)
    assert complete["complete"] and len(complete["events"]) == 9 and len(calls) == 9
    boston_sources.validate_records(complete["events"], source(b.GREENWAY))
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        b.collect_chunk(source(b.GREENWAY), fetch, checkpoint=first["checkpoint"], now=NOW + timedelta(hours=5))


def test_provider_label_is_excluded_event_changes_update_facts_and_legacy_prefix_stays_legacy(monkeypatch):
    items = [greenway(i) for i in range(9)]
    monkeypatch.setattr(b, "_greenway_manifest", lambda *args: [item[0] for item in items])

    def collect(src, changed=False):
        details = {card["url"]: html for card, html in items}
        if changed:
            details[items[0][0]["url"]] = details[items[0][0]["url"]].replace(
                "guided hands-on workshop", "publisher-updated hands-on workshop")
        fetch = lambda url, accept: details[url]
        first = b.collect_chunk(src, fetch, now=NOW)
        return first, b.collect_chunk(src, fetch, checkpoint=first["checkpoint"], now=NOW)

    first_partial, first = collect(source(b.GREENWAY))
    _, renamed = collect({**source(b.GREENWAY), "publisher_name": "Changed provider label"})
    _, changed = collect(source(b.GREENWAY), changed=True)
    assert renamed["events"][0]["collector_event_content_v1"] == first["events"][0]["collector_event_content_v1"]
    assert changed["events"][0]["collector_event_content_v1"] != first["events"][0]["collector_event_content_v1"]

    legacy = deepcopy(first_partial["checkpoint"])
    for row in legacy["events"]:
        row.pop("collector_event_content_v1")
    legacy["outcomes"] = [{"url": card["url"], "rows_hash": b._digest(
        [row for row in legacy["events"] if row["event_url"] == card["url"]])}
        for card in legacy["manifest"][:legacy["cursor"]]]
    complete = b.collect_chunk(source(b.GREENWAY), lambda url, accept: dict(
        (card["url"], html) for card, html in items)[url], checkpoint=legacy, now=NOW)
    assert complete["complete"]
    assert all("collector_event_content_v1" not in row for row in complete["events"])


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
    assert (row["lat"], row["lng"]) == (42.338845, -71.013235)
    facts = row["collector_event_content_v1"]["facts"]
    assert facts["venue_address"] == "2010 Day Blvd., South Boston, MA, 02127"


def nature_point_fixture(place):
    if place == "castle":
        title = "Arctic Waterbirds at Castle Island"
        meeting = "Meet in front of Sullivan's at 2080 William J Day Blvd, South Boston, MA 02127."
    else:
        title = "Ducks, Herons, & More at Millennium Park"
        meeting = "Meet in the parking lot nearest the canoe launch; use 300 Gardner St, West Roxbury, MA 02132."
    prose = "The naturalist explains seasonal birds, access and the route for all participants. " * 35
    card, detail = nature(title=title, starts=[START], body=f"<p>{prose}</p><p>{meeting}</p>")
    return card, detail, prose.strip(), meeting


def greenway_point_fixture():
    prose = "Walk the park labyrinth with neighbors and learn about its gardens and public art. " * 35
    card, detail = greenway(body=f"<p>{prose}</p>", title="Giving Thanks: Coming Together",
        venue="Armenian Heritage Park", location="Atlantic Avenue & Mercantile Street, Boston, MA")
    return card, detail, prose.strip()


def test_greenway_named_park_point_keeps_native_narrative_and_event_identity(monkeypatch):
    card, detail, prose = greenway_point_fixture()
    monkeypatch.setattr(b, "_greenway_manifest", lambda *args: [card])
    part = b.collect_chunk(source(b.GREENWAY), lambda *args: detail, now=NOW)
    assert part["complete"] and len(part["events"]) == 1
    row = part["events"][0]
    assert row["description"] == prose and len(prose) > 2000
    assert row["venue_name"] == "Armenian Heritage Park"
    assert row["venue_address"] == "115 Atlantic Avenue, Boston, MA 02110"
    assert (row["lat"], row["lng"]) == (42.36092235, -71.0532390073)
    assert row["location_evidence_url"] == "https://www.rosekennedygreenway.org/map/"
    assert row["id"] == "greenway:10" and datetime.fromisoformat(row["starts_at"]) == START
    boston_sources.validate_checkpoint(source(b.GREENWAY), part["checkpoint"], now=NOW)
    boston_sources.validate_records(part["events"], source(b.GREENWAY))


@pytest.mark.parametrize("place,venue,street,point", [
    ("castle", "Sullivan's Castle Island parking lot",
     "2080 William J Day Boulevard, South Boston, MA 02127", (42.338845, -71.013235)),
    ("millennium", "Millennium Park parking lot near canoe launch",
     "300 Gardner Street, West Roxbury, MA 02132", (42.280515, -71.184852)),
])
def test_nature_meeting_point_checkpoint_keeps_native_long_prose_and_identity(
        monkeypatch, place, venue, street, point):
    card, detail, prose, meeting = nature_point_fixture(place)
    monkeypatch.setattr(b, "_nature_manifest", lambda *args: [card])
    part = b.collect_chunk(source(b.NATURE), lambda *args: detail, now=NOW)
    assert part["complete"] and len(part["events"]) == 1
    row = part["events"][0]
    assert row["description"].startswith(prose) and meeting in row["description"]
    assert len(row["description"]) > 2000 and "Short JSON-LD teaser" not in row["description"]
    assert row["venue_name"] == venue and row["venue_address"] == street
    assert (row["lat"], row["lng"]) == point
    assert row["id"] == "nature:100001:" + START.astimezone(timezone.utc).isoformat()
    boston_sources.validate_checkpoint(source(b.NATURE), part["checkpoint"], now=NOW)
    boston_sources.validate_records(part["events"], source(b.NATURE))


@pytest.mark.parametrize("key,place", [(b.NATURE, "castle"), (b.NATURE, "millennium"),
                                      (b.GREENWAY, "armenian")])
@pytest.mark.parametrize("mutation", ["source", "venue", "street", "lat", "lng", "evidence", "provenance", "drop_point"])
def test_reviewed_checkpoint_rejects_poisoned_exact_location(monkeypatch, key, place, mutation):
    card, detail = (greenway_point_fixture() if key == b.GREENWAY else nature_point_fixture(place))[:2]
    monkeypatch.setattr(b, "_greenway_manifest" if key == b.GREENWAY else "_nature_manifest", lambda *args: [card])
    state = b.collect_chunk(source(key), lambda *args: detail, now=NOW)["checkpoint"]
    row = state["events"][0]
    if mutation == "source":
        state["source_key"] = b.NATURE if key == b.GREENWAY else b.GREENWAY
    elif mutation == "venue":
        row["venue_name"] += " Annex"
    elif mutation == "street":
        row["venue_address"] = "999 Other Street, Boston, MA 02115"
    elif mutation in {"lat", "lng"}:
        row[mutation] += 0.001
    elif mutation == "evidence":
        row["location_evidence_url"] = "https://example.org/unreviewed"
    elif mutation == "provenance":
        row["location_provenance"] = "unreviewed point"
    else:
        row["lat"] = row["lng"] = None
    # A rehashed outer row still cannot loosen the independently pinned point.
    state["outcomes"][0]["rows_hash"] = b._digest(state["events"])
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        b.collect_chunk(source(key), lambda *args: pytest.fail("poisoned checkpoint must not fetch"),
                        checkpoint=state, now=NOW)


@pytest.mark.parametrize("key", [b.NATURE, b.GREENWAY])
def test_existing_checkpoint_without_reviewed_points_remains_resumable(monkeypatch, key):
    card, detail = (greenway_point_fixture() if key == b.GREENWAY else nature_point_fixture("castle"))[:2]
    monkeypatch.setattr(b, "_greenway_manifest" if key == b.GREENWAY else "_nature_manifest", lambda *args: [card])
    reviewed = b.REVIEWED_EVENT_POINTS
    monkeypatch.setattr(b, "REVIEWED_EVENT_POINTS", {k: v for k, v in reviewed.items() if k[0] != key})
    legacy = b.collect_chunk(source(key), lambda *args: detail, now=NOW)["checkpoint"]
    assert legacy["events"][0]["lat"] is None
    monkeypatch.setattr(b, "REVIEWED_EVENT_POINTS", reviewed)
    boston_sources.validate_checkpoint(source(key), legacy, now=NOW)
    result = b.collect_chunk(source(key), lambda *args: pytest.fail("complete prefix must not refetch"),
                             checkpoint=legacy, now=NOW)
    assert result["complete"]


@pytest.mark.parametrize("key", [b.GREENWAY, b.NATURE])
@pytest.mark.parametrize("response_seconds,read_checkpoint_seconds,expected_claims", [
    (0.25, 0, 2), (5, 0, 3), (17, 0, 9), (0.25, 17, None),
])
def test_actual_worker_continuation_respects_slow_reads_and_reserve(
        monkeypatch, key, response_seconds, read_checkpoint_seconds, expected_claims):
    from roomquest import preview_worker as worker
    from urllib.parse import urlsplit
    items = []
    for index in range(9):
        card, body = greenway(index) if key == b.GREENWAY else nature(starts=[START])
        if key == b.NATURE:
            card = {**card, "url": card["url"].replace("100001", str(100001 + index))}
        items.append((card, body))
    manifest_name = "_greenway_manifest" if key == b.GREENWAY else "_nature_manifest"
    detail = b._greenway_detail if key == b.GREENWAY else b._nature_detail
    expected = [row for card, body in items for row in detail(card, body, NOW, [])]
    monkeypatch.setattr(b, manifest_name, lambda *args: [card for card, _ in items])
    clock, saved, revision, staged, reads, previews = [0.0], [None], [0], [], [], []
    monkeypatch.setattr(b, "monotonic", lambda: clock[0])
    monkeypatch.setattr(worker, "monotonic", lambda: clock[0])
    src = {**source(key), "fetch_checkpoint_version": 1}
    bodies = {card["url"]: body for card, body in items}

    def fetch(url, accept, **kwargs):
        assert kwargs["respect_robots"] is True
        assert urlsplit(url).hostname in kwargs["allowed_hosts"]
        assert clock[0] + 18 < kwargs["deadline_at"]
        reads.append(url)
        clock[0] += response_seconds
        return bodies[url]

    def rpc(operation, args):
        if operation == "community_collector_read_fetch_checkpoint":
            clock[0] += read_checkpoint_seconds
            return {"revision": revision[0], "checkpoint": saved[0]}
        if operation == "community_collector_write_fetch_checkpoint":
            saved[0] = args["p_checkpoint"]
            revision[0] += 1
            boston_sources.validate_checkpoint(src, saved[0])
            return {"checkpoint_saved": True, "revision": revision[0]}
        if operation == "community_collector_record_staged_events":
            assert saved[0]["cursor"] == saved[0]["manifest_count"]
            boston_sources.validate_records(args["p_events"], src)
            staged.extend(args["p_events"])
            return len(args["p_events"])
        if operation == "community_collector_record_preview_v2":
            assert args["p_error"] is None
            previews.append(args)
            return {"ok": True}
        raise AssertionError(operation)

    monkeypatch.setattr(worker, "fetch_publisher", fetch)
    monkeypatch.setattr(worker, "supabase_rpc", rpc)
    for claim in range(expected_claims or 1):
        clock[0] = claim * 60
        prior_reads = len(reads)
        # Existing production snapshots may already have a three-detail prefix.
        # Resume that old prefix under the new cap without refetching it.
        monkeypatch.setattr(b, "DETAILS_PER_CHUNK", 3 if claim == 0
            and response_seconds == 0.25 and not read_checkpoint_seconds else 8)
        result = worker._process_claimed_source_with_pacing(src,
            {"wait_unbounded": False, "crawl_delay_seconds": 0, "retry_after_seconds": 0},
            deadline_at=clock[0] + 60,
            collection_context={"p_category": "html", "p_ticket": "test-captured-source"})
        assert len(reads) - prior_reads <= 8
        assert result["failed"] == 0
        if result.get("fetch_pending"):
            assert not staged and not previews
        else:
            assert result["complete"] == 1 and claim + 1 == expected_claims
    if expected_claims is None:
        assert not reads and saved[0]["cursor"] == 0 and not staged and not previews
    else:
        assert len(reads) == len(set(reads)) == 9
        assert staged == expected and len(previews) == 1


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
    facts = row["collector_event_content_v1"]["facts"]
    assert facts["venue_name"] == "East End House"
    assert facts["venue_city"] == "Cambridge"
    assert "venue_address" not in facts
    boston_sources.validate_records([row], source(b.CARES))


@pytest.mark.parametrize("organization,title,venue,street,city,zip_code,point", [
    ("Catholic Charities Boston", "Organize Food at Yawkey Center Food Pantry",
     "Catholic Charities Yawkey Center Food Pantry", "185 Columbia Road, Dorchester, MA 02121",
     "Dorchester", "02121", (42.306336, -71.076838)),
    ("Torchlight Recovery", "Help with Daily Operations at Torchlight Recovery Cafe",
     "Torchlight Recovery Cafe", "2 Washington Street, Dorchester, MA 02121",
     "Dorchester", "02121", (42.308499, -71.082661)),
    ("First Congregational Church Food Pantry of Revere", "Unload Deliveries for the FCC Food Pantry of Revere",
     "First Congregational Church Food Pantry", "230 Beach Street, Revere, MA 02151",
     "Revere", "02151", (42.409298, -71.008602)),
    ("Mass Farmers Markets", "Central Square Farmers Market",
     "Central Square Farmers Market", "76 Bishop Allen Drive, Cambridge, MA 02139",
     "Cambridge", "02139", (42.3649, -71.1009)),
    ("Mass Farmers Markets", "Copley Square Farmers Market",
     "Copley Square Farmers Market", "227-230 Dartmouth Street, Boston, MA 02116",
     "Boston", "02116", (42.3495856, -71.0770735)),
    ("Fresh Truck", "Support the Fresh Truck Mobile Market @ Franklin Hill BGCB",
     "Franklin Hill Boys & Girls Club", "42 Shandon Road, Dorchester, MA 02124",
     "Dorchester", "02124", (42.295434, -71.090103)),
    ("Fresh Truck", "Roxbury - Support the Fresh Truck Mobile Market @ ABCD Geneva",
     "ABCD Geneva", "198 Geneva Avenue, Dorchester, MA 02121",
     "Dorchester", "02121", (42.305581, -71.075595)),
    ("Friday Night Supper Program", "Volunteer at Friday Night Supper Program",
     "Friday Night Supper Program at Arlington Street Church", "351 Boylston Street, Boston, MA 02116",
     "Boston", "02116", (42.35203, -71.071219)),
    ("Fresh Truck", "East Boston - Support the Fresh Truck Mobile Market @ Mario Umana Academy",
     "Mario Umana Academy market", "312 Border Street, East Boston, MA 02128",
     "East Boston", "02128", (42.378386, -71.040458)),
    ("Fresh Truck", "Roxbury - Support the Fresh Truck Mobile Market @ Lenox Camden",
     "Lenox Camden market", "32 Kendall Street, Boston, MA 02118",
     "Boston", "02118", (42.335881, -71.082262)),
    ("Fresh Truck", "Dorchester - Support the Fresh Truck Mobile Market @ Elm Hill",
     "Charles Street AME Church market", "13 Elm Hill Avenue, Dorchester, MA 02121",
     "Dorchester", "02121", (42.312876, -71.084335)),
    ("Fresh Truck", "Charlestown - Support the Fresh Truck Mobile Market @ Charlestown BHA",
     "Charlestown BHA market", "38 O'Reilly Way, Charlestown, MA 02129",
     "Charlestown", "02129", (42.377886, -71.058355)),
    ("Fresh Truck", "Dorchester - Support the Fresh Truck Mobile Market @ United Housing Management",
     "United Housing market", "3 Quincy Street, Dorchester, MA 02121",
     "Dorchester", "02121", (42.31617, -71.08221)),
])
def test_cares_reviewed_points_preserve_native_body_identity_and_full_street(
        organization, title, venue, street, city, zip_code, point):
    body = "Help neighbors distribute food and prepare supplies. Meet at " + street + ". " + "Native access details. " * 130
    item = cares_item(organizationServedName=organization, opportunityName=title,
                      description=body, locationCity=city, locationZipCode=zip_code)
    row = cares_parse(item)[0]
    assert (row["lat"], row["lng"]) == point
    assert row["venue_name"] == venue and row["venue_address"] == street
    assert row["description"] == body.strip() and len(row["description"]) > 2000
    assert row["id"] == "cares:" + item["occurrenceId"]
    assert datetime.fromisoformat(row["starts_at"]) == START
    inference_notes = {
        "Lenox Camden market": ("address-range/site inference", "30-40 Kendall", "02120/Mission Hill", "not an exact"),
        "Charles Street AME Church market": ("parking-site inference", "1202101000", "1202102000", "not an exact"),
        "Charlestown BHA market": ("street-segment interpolation", "48 to 30", "10/18", "not an exact"),
        "United Housing market": ("estimated street/site point", "25632", "1202832000", "not an exact", "Quincy Place/Court"),
    }
    if venue in inference_notes:
        assert all(note in row["location_provenance"] for note in inference_notes[venue])
        assert row["location_provenance"] not in row["description"]
    boston_sources.validate_records([row], source(b.CARES))


@pytest.mark.parametrize("venue", ["Chestnut Hill, Mass., Conte Forum", "Chestnut, Hill, Mass., Conte Forum"])
def test_bc_conte_exact_native_labels_use_verified_place_point(venue):
    event = bc_event(location_name=venue, address="", geo={})
    row = b._bc_events([event], NOW, [])[0]
    assert (row["lat"], row["lng"]) == (42.335342, -71.167717)
    assert row["venue_name"] == venue
    assert row["venue_address"] == "2601 Beacon Street, Chestnut Hill, MA 02467"
    assert row["description"] == "Researchers explain the local river ecosystem."
    assert row["id"] == "bc:42:43" and row["location_evidence_url"] == "https://events.bc.edu/conte_forum"


@pytest.mark.parametrize("venue,street,point,evidence", [
    ("Stuart House, 315", "899 Centre Street, Newton, MA 02459",
     (42.341629, -71.193954), "https://events.bc.edu/stuart_house"),
    ("Chestnut Hill, Mass., Alumni Stadium", "2604 Beacon Street, Chestnut Hill, MA 02467",
     (42.334999, -71.166389), "https://events.bc.edu/alumni_stadium"),
    ("MCLE Conference Center", "10 Winter Place, Boston, MA 02108",
     (42.355469, -71.061701), "https://gis.boston.gov/arcgis/rest/services/SAM/Live_SAM_Address/MapServer/1"),
    ("Simboli Chapel", "9 Lake Street, Boston, MA 02135",
     (42.341625, -71.164566), "https://events.bc.edu/Simboli_Hall"),
    ("Trinity Chapel", "883 Centre Street, Newton, MA 02459",
     (42.342777, -71.19355), "https://events.bc.edu/trinity_chapel"),
])
def test_bc_reviewed_named_place_uses_explicit_point_and_keeps_display_street(venue, street, point, evidence):
    native_venue, room = ("Stuart House", "315") if venue == "Stuart House, 315" else (venue, "")
    event = bc_event(location_name=native_venue, room_number=room, address="", geo={})
    row = b._bc_events([event], NOW, [])[0]
    assert (row["lat"], row["lng"]) == point
    assert row["venue_name"] == venue and row["venue_address"] == street
    assert row["location_evidence_url"] == evidence
    assert row["description"] == "Researchers explain the local river ecosystem."
    assert row["id"] == "bc:42:43"
    assert b._bc_events([bc_event(location_name=native_venue, room_number=room,
        address="999 Other Street, Boston, MA 02115", geo={})], NOW, []) == []


@pytest.mark.parametrize("profile", list(b.REVIEWED_EVENT_POINTS))
@pytest.mark.parametrize("changed", ["source", "venue", "street"])
def test_reviewed_point_requires_exact_source_venue_and_street(profile, changed):
    key, venue, street = profile
    if changed == "source":
        key = b.NATURE if key == b.GREENWAY else b.GREENWAY
    elif changed == "venue":
        venue += " Annex"
    else:
        street = "999 " + street.split(" ", 1)[1]
    row = b._row(key, "Community activity", START, START + timedelta(hours=1),
                 "https://www.bostoncares.org/opportunity/a0CUq00007PDnO0MAL", "native-id",
                 "Full publisher instructions for the public activity.", venue, street, "Boston")
    assert row["lat"] is None and row["lng"] is None


def test_bc_conte_conflicting_native_street_remains_held():
    event = bc_event(location_name="Chestnut Hill, Mass., Conte Forum",
                     address="999 Beacon Street, Chestnut Hill, MA 02467", geo={})
    assert b._bc_events([event], NOW, []) == []


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
