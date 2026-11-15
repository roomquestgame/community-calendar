"""Complete native manifests, exact anonymous reads, and event-specific evidence."""
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from roomquest import preview_worker as worker
from roomquest import raleigh_followup_performance as p

NOW = datetime(2026, 11, 15, 13, 30, tzinfo=timezone.utc)
START = datetime(2026, 11, 20, 19, tzinfo=p.ZoneInfo(p.ZONE))
FULL = "The full publisher program and participation narrative. " * 55 + "Final native admission condition."


@pytest.fixture(autouse=True)
def future_clock(monkeypatch):
    monkeypatch.setattr(worker, "_future_datetime", lambda value: value.astimezone(timezone.utc))


def source(key):
    return dict(source_key=key, feed_url=p.SOURCES[key][0], kind="html", platform_adapter="html", timezone=p.ZONE)


def public_instance(**changes):
    # Entirely synthetic signature/payload; no captured publisher token.
    data = dict(instanceId=p.WIX_INSTANCE_ID, appDefId=p.WIX_APP_ID, metaSiteId=p.WIX_METASITE_ID,
                demoMode=False, signDate=NOW.isoformat())
    data.update(changes)
    return "S" * 43 + "." + base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")


def wix_event(number=1, start=START):
    address = "3801 Hillsborough St, Raleigh, NC 27607, USA Ste. 123"
    return dict(id=f"00000000-0000-0000-0000-{number:012}", title=f"Native Show {number}", slug=f"native-show-{number}",
        scheduling={"config": {"scheduleTbd": False, "timeZoneId": p.ZONE,
            "startDate": start.astimezone(timezone.utc).isoformat(),
            "endDate": (start + timedelta(hours=2)).astimezone(timezone.utc).isoformat()}},
        instanceId=p.WIX_INSTANCE_ID, description="A short list teaser.", about="Legacy shorter about field.",
        mainImage={"url": "https://static.wixstatic.com/media/native.jpg"},
        location={"name": "ComedyWorx", "tbd": False, "address": address,
            "coordinates": {"lat": 35.7939074, "lng": -78.6883566},
            "fullAddress": {"city": "Raleigh", "subdivision": "NC", "country": "US", "postalCode": "27607-0168",
                "streetAddress": {"number": "3801", "name": "Hillsborough Street", "apt": "123"},
                "formattedAddress": address, "geocode": {"latitude": 35.7939074, "longitude": -78.6883566}}})


def wix_listing(rows, more=False, token=None):
    widget = dict(instance={"instance": token or public_instance()}, component={"id": p.WIX_COMPONENT_ID,
        "settings": {"recurringFilter": 2}}, events={"events": rows, "hasMore": more, "filterType": 2})
    data = {"appsWarmupData": {p.WIX_APP_ID: {"widget" + p.WIX_COMPONENT_ID: widget}}}
    return '<script id="wix-warmup-data" type="application/json">' + json.dumps(data) + '</script>'


def wix_detail(event, body=FULL, canonical=None, schema_start=None):
    item = p._packet(p.COMEDYWORX, event)
    data = {"appsWarmupData": {p.WIX_APP_ID: {"EventsPageInitialState": {"event": {"event": event}}}}}
    schema = {"@type": "Event", "name": event["title"], "eventStatus": "https://schema.org/EventScheduled",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "startDate": schema_start or p.timestamp(item["native_start"]).astimezone(p.ZoneInfo(p.ZONE)).isoformat(),
        "endDate": p.timestamp(item["native_end"]).astimezone(p.ZoneInfo(p.ZONE)).isoformat(), "description": "A teaser."}
    return ('<link rel="canonical" href="' + (canonical or item["url"]) + '">'
        '<script id="wix-warmup-data" type="application/json">' + json.dumps(data) + '</script>'
        '<script type="application/ld+json">' + json.dumps(schema) + '</script>'
        '<div data-hook="about-section"><h2>About the event</h2><div data-id="content-viewer"><p>' + body +
        '</p></div><button>Read More</button></div>')


def chapel_event(number=1, start=START, end=None, title=None):
    def native(dt):
        return dt.replace(tzinfo=None).isoformat() + "Z" if dt else None
    return dict(id=number, identifier=f"native-concert-{number}", what=title or f"Native Concert {number}",
        when=native(start), end_when=native(end), is_deleted=False, is_published=True,
        is_season_ticket=False, is_festival=False, sells_time_slots=False)


def chapel_detail(event, body=FULL, **changes):
    item = p._packet(p.CHAPEL, event)
    schema = {"@type": "Event", "name": item["title"], "url": item["url"], "description": body,
        "eventStatus": "https://schema.org/EventScheduled", "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "organizer": {"name": "Chapel of Bones", "url": p.CHAPEL_ORGANIZER},
        "startDate": event["when"][:-1] + "-05:00",
        "location": {"name": "Chapel of Bones", "address": {"streetAddress": "658 Maywood Avenue",
            "addressLocality": "Raleigh", "addressRegion": "NC", "postalCode": "27603", "addressCountry": "US"}},
        "image": ["https://static-o.tickpick.com/cdn-cgi/image/width=1280/native.png"]}
    if event["end_when"]:
        schema["endDate"] = event["end_when"][:-1] + "-05:00"
    schema.update(changes)
    return '<script type="application/ld+json">' + json.dumps([schema]) + '</script>'


CHAPEL_PAGE = ('<script src="https://www.tickpick.com/organizer/api/widgets/tickpick-events-widget.js"></script>'
              '<script>TickPickWidgets.createEventsWidget({companyId: "chapel-of-bones"});</script>')


def test_exact_source_and_event_routes():
    assert p._source(source(p.COMEDYWORX)) == p.COMEDYWORX
    with pytest.raises(ValueError, match="unregistered"):
        p._source(dict(source(p.CHAPEL), timezone="America/Chicago"))
    for url in ["https://evil.test/event-details/show", "https://www.comedyworx.com/event-details/%2e%2e/private",
                "https://www.tickpick.com/organizer/event/native-1?account=1", "http://www.tickpick.com/organizer/event/native-1"]:
        assert not p.event_url(p.CHAPEL, url)


def test_chapel_post_is_only_the_exact_anonymous_calendar_read():
    for page, bootstrap in [(1, True), (1, False), (2, False)]:
        url, body = p.chapel_calendar_request(page=page, bootstrap=bootstrap)
        assert p.valid_chapel_calendar_request(url, body)
        data = json.loads(body)
        assert data["param"] == "chapel-of-bones"
        assert not p.valid_chapel_calendar_request(url.replace("www.tickpick.com", "evil.test"), body)
        assert not p.valid_chapel_calendar_request(url + "?redirect=1", body)
        assert not p.valid_chapel_calendar_request(url, body.replace(b"chapel-of-bones", b"other-company"))
        assert not p.valid_chapel_calendar_request(url, json.dumps(dict(data, purchase=True)).encode())
    with pytest.raises(ValueError, match="invalid_chapel"):
        p.chapel_calendar_request(page=2, bootstrap=True)
    with pytest.raises(ValueError, match="invalid_chapel"):
        p.chapel_calendar_request(page=True)


def test_wix_get_is_exact_and_public_instance_has_no_logged_in_identity():
    url = p.comedyworx_calendar_url(18)
    assert p.valid_comedyworx_calendar_request(url, public_instance())
    for value in [public_instance(uid="logged-in-user"), public_instance(permissions="OWNER"),
                  public_instance(instanceId="another-site"), public_instance(demoMode=True), "not-a-token"]:
        assert not p.valid_comedyworx_calendar_request(url, value)
    for changed in [url + "&offset=18", url.replace("offset=18", "offset=018"), url.replace("draft=false", "draft=true"),
                    url.replace("filter=1", "filter=2"), url.replace("www.comedyworx.com", "events.wixapps.net")]:
        assert not p.valid_comedyworx_calendar_request(changed, public_instance())


def test_wix_full_rendered_about_and_native_point_are_preserved():
    native = wix_event()
    item = p._packet(p.COMEDYWORX, native)
    row = p._detail(p.COMEDYWORX, item, wix_detail(native), NOW)
    assert row["description"] == FULL
    assert row["description"] != native["about"]
    assert row["venue_address"] == "3801 Hillsborough St Ste. 123, Raleigh, NC 27607-0168"
    assert (row["lat"], row["lng"]) == (35.7939074, -78.6883566)
    assert row["location_provenance"] == "publisher_event_geo"
    assert row["location_evidence_url"] == item["url"]


def test_wix_uses_schema_show_start_and_never_a_doors_note():
    native = wix_event()
    item = p._packet(p.COMEDYWORX, native)
    row = p._detail(p.COMEDYWORX, item, wix_detail(native, body=FULL + " Doors open at 6:30 PM."), NOW)
    assert p.timestamp(row["starts_at"]) == START
    with pytest.raises(ValueError, match="schedule_unresolved"):
        p._detail(p.COMEDYWORX, item, wix_detail(native, schema_start=(START + timedelta(hours=1)).isoformat()), NOW)


def test_wix_native_fractional_edit_seconds_do_not_override_public_schedule():
    native = wix_event()
    native["scheduling"]["config"]["endDate"] = (START + timedelta(hours=2, microseconds=760000)).astimezone(timezone.utc).isoformat()
    html = wix_detail(native).replace('21:00:00.760000-05:00', '21:00:00-05:00')
    row = p._detail(p.COMEDYWORX, p._packet(p.COMEDYWORX, native), html, NOW)
    assert p.timestamp(row["ends_at"]) == START + timedelta(hours=2)


def test_detail_identity_and_conflicting_native_coordinate_pairs_fail_closed():
    native = wix_event()
    item = p._packet(p.COMEDYWORX, native)
    with pytest.raises(ValueError, match="detail_changed"):
        p._detail(p.COMEDYWORX, item, wix_detail(native, canonical="https://www.comedyworx.com/event-details/another-show"), NOW)
    native["location"]["coordinates"]["lat"] = 40.7
    with pytest.raises(ValueError, match="venue_unresolved"):
        p._detail(p.COMEDYWORX, item, wix_detail(native), NOW)


def test_wix_full_pagination_resumes_without_staging_or_persisting_public_token():
    events = [wix_event(n, START + timedelta(hours=n)) for n in range(1, 20)]
    listing = wix_listing(events[:18], True)
    urls = {p.SOURCES[p.COMEDYWORX][0]: listing}
    urls.update({p._packet(p.COMEDYWORX, e)["url"]: wix_detail(e) for e in events})
    calls = []
    def api(**request):
        calls.append(request["offset"])
        assert request["request_kind"] == "comedyworx_page"
        assert p.valid_comedyworx_public_instance(request["public_instance"])
        return json.dumps(dict(events=events[18:], total=19, hasMore=False))
    first = p.collect_chunk(source(p.COMEDYWORX), lambda url, accept: urls[url], read_public_events=api, now=NOW, max_fetches=1)
    assert not first["complete"] and first["events"] == [] and first["checkpoint"]["phase"] == "listing"
    assert public_instance() not in json.dumps(first["checkpoint"])
    state = first["checkpoint"]
    for _ in range(10):
        result = p.collect_chunk(source(p.COMEDYWORX), lambda url, accept: urls[url], read_public_events=api,
                                 now=NOW, checkpoint=state, max_fetches=4)
        state = result["checkpoint"]
        assert public_instance() not in json.dumps(state)
        if result["complete"]:
            break
        assert result["events"] == []
    assert result["complete"] and len(result["events"]) == 19
    assert calls == [18]
    assert state["listing_total"] == state["listing_raw_count"] == 19
    assert state["cursor"] == state["manifest_count"] == len(state["queue"])
    assert p.checkpoint_complete(state)
    assert not p.checkpoint_complete(dict(state, listing_total=20))
    assert not p.checkpoint_complete(dict(state, listing_pages=0))
    assert not p.checkpoint_complete(dict(state, events=[]))
    assert all(row["description"] == FULL for row in result["events"])


@pytest.mark.parametrize("mode", ["duplicate", "short_total", "unfinished"])
def test_wix_pagination_does_not_silently_accept_a_partial_manifest(mode):
    events = [wix_event(n, START + timedelta(hours=n)) for n in range(1, 19)]
    response = dict(events=[deepcopy(events[0])], total=19, hasMore=False)
    if mode == "short_total":
        response = dict(events=[wix_event(19, START + timedelta(days=2))], total=20, hasMore=False)
    elif mode == "unfinished":
        response = dict(events=[], total=19, hasMore=True)
    with pytest.raises(ValueError, match="calendar_changed"):
        p.collect_chunk(source(p.COMEDYWORX), lambda url, accept: wix_listing(events, True),
                        read_public_events=lambda **kwargs: json.dumps(response), now=NOW)


def test_chapel_literal_z_listing_is_wall_clock_and_detail_offset_controls_utc():
    event = chapel_event(end=START + timedelta(hours=2))
    row = p._detail(p.CHAPEL, p._packet(p.CHAPEL, event), chapel_detail(event), NOW)
    assert p.timestamp(row["starts_at"]) == START
    assert row["starts_at"].startswith("2026-11-21T00:00:00")
    assert row["venue_address"] == "658 Maywood Avenue, Raleigh, NC 27603"
    assert row["lat"] is row["lng"] is None
    with pytest.raises(ValueError, match="schedule_unresolved"):
        p._detail(p.CHAPEL, p._packet(p.CHAPEL, event), chapel_detail(event, startDate=event["when"]), NOW)


@pytest.mark.parametrize("body,expected", [
    ("All ages. 7PM Doors / 8PM Music", (20, 0)),
    ("Doors: 7:00pm Show: 8:00pm Advance tickets available.", (20, 0)),
    ("DOORS 7PM / SHOWTIME 7:30PM ALL AGES", (19, 30)),
    ("All Ages / Doors 7PM / Event 7:30PM", (19, 30)),
    ("Doors @ 7pm/ Show @ 8pm 18+ only", (20, 0)),
])
def test_explicit_chapel_show_clock_supersedes_only_a_matching_doors_clock(body, expected):
    event = chapel_event()
    row = p._detail(p.CHAPEL, p._packet(p.CHAPEL, event), chapel_detail(event, body=body), NOW)
    local = p.timestamp(row["starts_at"]).astimezone(p.ZoneInfo(p.ZONE))
    assert (local.hour, local.minute) == expected
    assert row["ends_at"] is None
    assert row["description"] == body


def test_conflicting_chapel_hours_are_held_instead_of_invented():
    with pytest.raises(ValueError, match="schedule_unresolved"):
        p._show_clock(START, "Doors 7 PM. Show 8 PM or Show 9 PM.")
    with pytest.raises(ValueError, match="schedule_unresolved"):
        p._show_clock(START, "Doors 6 PM. Show 8 PM.")


def test_monthly_or_weekly_labels_never_expand_unpublished_dates():
    event = chapel_event(title="Monthly art market", end=START + timedelta(hours=2))
    event["is_festival"] = True
    far = chapel_event(2, start=START + timedelta(days=70))
    urls = {p.SOURCES[p.CHAPEL][0]: CHAPEL_PAGE, p._packet(p.CHAPEL, event)["url"]: chapel_detail(event)}
    def api(**kwargs):
        return json.dumps(dict(performer={"id": "chapel-of-bones"}, events=[event, far], total_events=2))
    result = p.collect_chunk(source(p.CHAPEL), lambda url, accept: urls[url], read_public_events=api, now=NOW)
    assert result["complete"] and len(result["events"]) == 1
    assert result["checkpoint"]["outside_window_count"] == 1


def test_chapel_native_pages_must_all_finish_before_any_detail_is_staged():
    events = [chapel_event(1), chapel_event(2, START + timedelta(days=1))]
    urls = {p.SOURCES[p.CHAPEL][0]: CHAPEL_PAGE}
    urls.update({p._packet(p.CHAPEL, e)["url"]: chapel_detail(e) for e in events})
    calls = []
    def api(**kwargs):
        calls.append(kwargs)
        return json.dumps(dict(performer={"id": "chapel-of-bones"}, events=[events[kwargs["page"] - 1]], total_events=2))
    first = p.collect_chunk(source(p.CHAPEL), lambda url, accept: urls[url], read_public_events=api, now=NOW, max_fetches=2)
    assert first["checkpoint"]["phase"] == "listing" and first["events"] == []
    assert first["checkpoint"]["cursor"] == 0
    final = p.collect_chunk(source(p.CHAPEL), lambda url, accept: urls[url], read_public_events=api, now=NOW,
                            checkpoint=first["checkpoint"], max_fetches=3)
    assert final["complete"] and len(final["events"]) == 2
    assert calls == [dict(request_kind="chapel_bootstrap", page=1), dict(request_kind="chapel_page", page=2)]


@pytest.mark.parametrize("body,reason", [("", "description_missing"), ("Native Concert 1", "description_missing"),
                                        ("x" * 12001, "description_limit")])
def test_no_missing_prose_substitution_or_truncation(body, reason):
    event = chapel_event()
    with pytest.raises(ValueError, match=reason):
        p._detail(p.CHAPEL, p._packet(p.CHAPEL, event), chapel_detail(event, body=body), NOW)


def test_checkpoint_rejects_unfinished_capture_claims_or_token_fields():
    event = chapel_event()
    def api(**kwargs):
        return json.dumps(dict(performer={"id": "chapel-of-bones"}, events=[event], total_events=1))
    result = p.collect_chunk(source(p.CHAPEL), lambda url, accept: CHAPEL_PAGE, read_public_events=api, now=NOW, max_fetches=2)
    state = result["checkpoint"]
    assert not result["complete"] and result["events"] == []
    for mutation in [dict(cursor=1), dict(listing_total=2), dict(listing_pages=0), dict(public_instance=public_instance())]:
        invalid = dict(deepcopy(state), **mutation)
        p._seal(invalid)
        with pytest.raises(ValueError, match="checkpoint_invalid"):
            p._checkpoint(invalid, p.CHAPEL, NOW)
    invalid = deepcopy(state)
    invalid["queue"][0]["url"] = "https://evil.test/organizer/event/native-1"
    p._seal(invalid)
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        p._checkpoint(invalid, p.CHAPEL, NOW)


def test_chapel_list_total_overflow_is_visible():
    with pytest.raises(ValueError, match="calendar_changed"):
        p.collect_chunk(source(p.CHAPEL), lambda url, accept: CHAPEL_PAGE,
            read_public_events=lambda **kwargs: json.dumps(dict(performer={"id": "chapel-of-bones"}, events=[], total_events=201)), now=NOW)
