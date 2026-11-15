"""Synthetic native-calendar and guarded-transport checks; no publisher I/O."""
import base64
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from html import escape
import json
from urllib.parse import urlencode, urlsplit
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pytest

from roomquest import preview_worker as w
from roomquest import raleigh_next_social as c

NOW = datetime(2026, 11, 15, 13, tzinfo=timezone.utc)
SERIES = "11111111-1111-4111-8111-111111111111"


def source(key):
    return dict(source_key=key, feed_url=c.SOURCES[key][0], kind="html", platform_adapter="html", timezone=c.ZONE)


def instance(**changes):
    claims = dict(instanceId=c.WIX_INSTANCE, appDefId=c.WIX_APP, metaSiteId=c.WIX_METASITE, demoMode=False)
    claims.update(changes)
    return "S" * 43 + "." + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")


def native(number=1):
    start = datetime(2026, 11, 19, 19, tzinfo=ZoneInfo(c.ZONE)) + timedelta(days=7 * (number-1))
    end = start + timedelta(hours=2)
    return dict(id=f"22222222-2222-4222-8222-{number:012x}", instanceId=c.WIX_INSTANCE,
        title="Neighborhood Trivia", slug="neighborhood-trivia-" + start.strftime("%Y-%m-%d-%H-%M"),
        status=0, registration={"restrictedTo": 0}, about="", description="",
        location=dict(name="3709 Neil St", address="3709 Neil St, Raleigh, NC 27607, USA", type=0, tbd=False,
            coordinates={"lat": 35.7930166, "lng": -78.6869027},
            fullAddress=dict(city="Raleigh", country="US", subdivision="NC", postalCode="27607",
                geocode={"latitude": 35.7930166, "longitude": -78.6869027})),
        scheduling={"config": dict(scheduleTbd=False, startDate=start.isoformat(), endDate=end.isoformat(),
            timeZoneId=c.ZONE, endDateHidden=False,
            recurrences={"categoryId": SERIES, "status": 2 if number == 1 else 1, "occurrences": []})})


def packet_url(row):
    return "https://www.raleighbrewing.com/event-details/" + row["slug"]


def suggestion(row):
    instant = datetime.fromisoformat(row["scheduling"]["config"]["startDate"])
    return dict(slug=row["slug"], shortStartDateTime=instant.strftime("%a, %b %d, %I:%M %p").replace(", 0", ", "))


def wix_page(widget, *, detail=False, url=None, extra=""):
    state = {"appsWarmupData": {c.WIX_APP: {"EventsPageInitialState" if detail else "widgetcomp-ltyv4rsv": widget}}}
    return (f'<link rel="canonical" href="{url or c.SOURCES[c.BREWING][0]}">'
        '<script id="wix-warmup-data" type="application/json">' + json.dumps(state) + '</script>' + extra)


def brewery_listing(rows):
    return wix_page(dict(instance={"instanceId": c.WIX_INSTANCE},
        events={"hasMore": False, "filterType": 2, "events": rows}))


def brewery_detail(row, *, total=3, suggestions=(), body=None, token=None, schema_changes=None):
    config = row["scheduling"]["config"]
    schema = dict(**{"@type": "Event"}, name=row["title"], description="A short native teaser.",
        startDate=config["startDate"], endDate=config["endDate"],
        eventStatus="https://schema.org/EventScheduled", eventAttendanceMode="https://schema.org/OfflineEventAttendanceMode",
        location={"@type": "Place", "url": packet_url(row), "name": row["location"]["name"], "address": row["location"]["address"]})
    schema.update(schema_changes or {})
    widget = dict(instance={"instanceId": c.WIX_INSTANCE, "instance": token or instance()},
        event={"event": row}, upcomingOccurrencesCount=total, upcomingOccurrencesSuggestions=list(suggestions),
        siteSettings={"locale": "en-US"})
    body = "<p>Bring a team for a welcoming evening of local trivia, music questions and prizes.</p>" if body is None else body
    extra = '<script type="application/ld+json">' + json.dumps(schema) + '</script>'
    extra += '<section data-hook="about-section"><div data-id="content-viewer">' + body + '</div></section>'
    return wix_page(widget, detail=True, url=packet_url(row), extra=extra)


def occurrence_page(rows, total=3):
    return json.dumps(dict(events=rows, total=total, dates={"events": {
        row["id"]: {"startDateISOFormatNotUTC": row["scheduling"]["config"]["startDate"],
                    "endDateISOFormatNotUTC": row["scheduling"]["config"]["endDate"]} for row in rows}}))


def preview(title, start, end, venue, street, city, url, identity, **kwargs):
    return dict(id=identity, title=title, starts_at=start, ends_at=end, venue_name=venue,
        venue_address=street, venue_city=city, event_url=url, lat=kwargs.get("lat"), lng=kwargs.get("lng"))


@patch.object(c, "record", side_effect=preview)
def test_incomplete_html_uses_exact_paged_native_manifest_and_hydrates_every_detail(_):
    rows = [native(number) for number in (1, 2, 3)]
    body = "Full publisher narrative with event instructions and accessibility details. " * 80
    pages = {c.SOURCES[c.BREWING][0]: brewery_listing(rows[:1])}
    pages.update({packet_url(row): brewery_detail(row, suggestions=[suggestion(rows[1])], body="<p>" + body + "</p>") for row in rows})
    fetched, api_calls = [], []
    def fetch(url, accept):
        assert accept == "text/html"
        fetched.append(url)
        return pages[url]
    def read_api(**request):
        assert request["event_id"] == rows[0]["id"]
        assert request["public_instance"] == instance()
        api_calls.append(request["offset"])
        return occurrence_page(rows[:2] if request["offset"] == 0 else rows[2:])
    checkpoint = None
    for _ in range(8):
        before = len(fetched) + len(api_calls)
        result = c.collect_chunk(source(c.BREWING), fetch, read_public_events=read_api, checkpoint=checkpoint, now=NOW)
        checkpoint = result["checkpoint"]
        assert len(fetched) + len(api_calls) - before <= 3
        assert instance() not in json.dumps(checkpoint)
        c._checkpoint(checkpoint, c.BREWING, NOW)
        if result["complete"]:
            break
        assert result["events"] == []
    assert result["complete"] and api_calls == [0, 2]
    assert len(result["events"]) == 3 and all(row["description"] == body.strip() for row in result["events"])
    assert all(packet_url(row) in fetched for row in rows)
    assert fetched.count(packet_url(rows[0])) == 2  # Fresh public instance after a chunk boundary.
    progress = checkpoint["api_progress"][SERIES]
    assert progress["offset"] == progress["total"] == len(progress["ids"]) == len(progress["urls"]) == 3
    assert checkpoint["outcomes"] == {packet_url(row): "accepted" for row in rows}
    assert c.checkpoint_complete(checkpoint)
    corrupt = deepcopy(checkpoint)
    corrupt["api_progress"][SERIES]["offset"] = 2
    assert not c.checkpoint_complete(corrupt)
    c._seal(corrupt)
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        c._checkpoint(corrupt, c.BREWING, NOW)
    corrupt = deepcopy(checkpoint)
    corrupt["outcomes"].pop(packet_url(rows[2]))
    assert not c.checkpoint_complete(corrupt)


@patch.object(c, "record", side_effect=preview)
def test_complete_explicit_html_occurrences_need_no_api_and_blank_body_is_held(_):
    rows = [native(1), native(2)]
    pages = {c.SOURCES[c.BREWING][0]: brewery_listing(rows[:1])}
    pages.update({packet_url(row): brewery_detail(row, total=2, suggestions=[suggestion(rows[1])],
        body="" if row is rows[1] else None) for row in rows})
    result = c.collect_chunk(source(c.BREWING), lambda url, _: pages[url], now=NOW,
        read_public_events=lambda **_: pytest.fail("complete HTML must not need another operation"))
    assert result["complete"] and len(result["events"]) == 1
    assert result["checkpoint"]["outcomes"][packet_url(rows[1])] == "raleigh_direct_description_missing"
    assert result["checkpoint"]["api_progress"] == {}


def api_state():
    first = c._brewing_packet(native())
    return dict(queue=[first], series_counts={SERIES: 3}, series_urls={SERIES: [first["url"]]}, excluded_urls=[],
        api_progress={SERIES: dict(seed_id=first["native_id"], total=3, offset=0, urls=[], ids=[])})


@pytest.mark.parametrize("mutation", ["total", "duplicate", "empty", "different_series", "date_conflict", "private", "cancelled"])
def test_api_manifest_changes_never_certify_a_complete_series(mutation):
    state = api_state()
    rows = [native(1), native(2)]
    data = json.loads(occurrence_page(rows))
    if mutation == "total":
        data["total"] = 2
    elif mutation == "duplicate":
        data["events"] = [rows[0], rows[0]]
    elif mutation == "empty":
        data["events"] = []
    elif mutation == "different_series":
        data["events"][1]["scheduling"]["config"]["recurrences"]["categoryId"] = "33333333-3333-4333-8333-333333333333"
    elif mutation == "date_conflict":
        data["dates"]["events"][rows[1]["id"]]["startDateISOFormatNotUTC"] = "2026-11-26T18:00:00-05:00"
    elif mutation == "private":
        data["events"][1]["registration"]["restrictedTo"] = 1
    elif mutation == "cancelled":
        data["events"][1]["status"] = 3
    with pytest.raises(ValueError, match="occurrences_incomplete"):
        c._occurrence_page(state, SERIES, json.dumps(data), NOW)


def test_duplicate_id_across_api_pages_is_rejected():
    state = api_state()
    c._occurrence_page(state, SERIES, occurrence_page([native(1), native(2)]), NOW)
    with pytest.raises(ValueError, match="occurrences_incomplete"):
        c._occurrence_page(state, SERIES, occurrence_page([native(2)]), NOW)


@pytest.mark.parametrize("status", [None, 3, 4])
def test_conflicting_native_status_cannot_be_overridden_by_scheduled_json_ld(status):
    row = native()
    row["status"] = status
    entry = c._brewing_packet(row)
    with pytest.raises(ValueError, match="raleigh_next_social_nonpublic"):
        c._brewing_detail(api_state(), entry, brewery_detail(row), NOW)


@patch.object(c, "record", side_effect=preview)
def test_missing_api_or_403_does_not_fall_back_to_guessed_dates(_):
    row = native()
    pages = {c.SOURCES[c.BREWING][0]: brewery_listing([row]), packet_url(row): brewery_detail(row, suggestions=[])}
    with pytest.raises(ValueError, match="occurrences_incomplete"):
        c.collect_chunk(source(c.BREWING), lambda url, _: pages[url], now=NOW)
    reader = Mock(side_effect=w.PreviewError("publisher_http_403"))
    with pytest.raises(w.PreviewError, match="publisher_http_403"):
        c.collect_chunk(source(c.BREWING), lambda url, _: pages[url], now=NOW, read_public_events=reader)
    reader.assert_called_once()


def hotel_context():
    return '<script>Static.SQUARESPACE_CONTEXT = ' + json.dumps(dict(
        website=dict(id=c.HOTEL_SITE, timeZone=c.ZONE, location=dict(addressTitle="The Longleaf Hotel",
            addressLine1="300 North Dawson Street", addressLine2="Raleigh NC 27603", mapLat=35.7845, mapLng=-78.6422)),
        collection=dict(id=c.HOTEL_COLLECTION, fullUrl="/events", permissionType=1))) + ';</script>'


def hotel_event(*, title="Evening Music", days=0):
    start = datetime(2026, 11, 18, 20, tzinfo=timezone.utc)
    end = start + timedelta(days=days, hours=2)
    return dict(kind="native", native_id="a" * 24, title=title,
        url="https://www.thelongleafhotel.com/events/evening-music", start=start.isoformat(), end=end.isoformat(),
        venue="The Longleaf Hotel", street="300 North Dawson Street, Raleigh, NC 27603",
        lat=35.7845, lng=-78.6422, image=None)


def hotel_listing(entry):
    start, end = (datetime.fromisoformat(entry[key]) for key in ("start", "end"))
    query = urlencode(dict(action="TEMPLATE", dates=start.strftime("%Y%m%dT%H%M%SZ") + "/" + end.strftime("%Y%m%dT%H%M%SZ"),
        location=entry["street"]))
    clocks = ''.join(f'<time class="event-time-24hr" datetime="{instant.astimezone(ZoneInfo(c.ZONE)).date()}">'
        + instant.astimezone(ZoneInfo(c.ZONE)).strftime("%H:%M") + '</time>' for instant in (start, end))
    return (f'<link rel="canonical" href="{c.SOURCES[c.LONGLEAF][0]}">' + hotel_context()
        + '<div class="eventlist"><article class="eventlist-event--upcoming">'
        + f'<a class="eventlist-title-link" href="{entry["url"]}">{escape(entry["title"])}</a>'
        + f'<span class="sqs-simple-like" data-item-id="{entry["native_id"]}"></span>'
        + '<a class="eventlist-meta-export-google" href="https://www.google.com/calendar/event?' + query + '">Calendar</a>'
        + '<div class="eventlist-meta-time">' + clocks + '</div>'
        + '<div class="eventlist-meta-address">The Longleaf Hotel (map)</div></article></div>')


def hotel_detail(entry, body):
    schema = {"@type": "Event", "name": entry["title"] + " | The Longleaf Hotel", "startDate": entry["start"],
        "endDate": entry["end"], "location": {"name": entry["venue"], "address": entry["street"]}}
    return (f'<link rel="canonical" href="{entry["url"]}">' + hotel_context()
        + '<script type="application/ld+json">' + json.dumps(schema) + '</script><article class="eventitem">'
        + f'<h1 class="eventitem-title">{escape(entry["title"])}</h1><div class="eventitem-column-content">'
        + f'<div data-layout-label="Post Body" id="item-{entry["native_id"]}">{body}</div></div></article>')


@patch.object(c, "record", side_effect=preview)
def test_longleaf_full_body_and_native_point_require_its_actual_event_street(_):
    entry = hotel_event()
    narrative = "The artist performs an evening program with local guests. " * 90
    pages = {c.SOURCES[c.LONGLEAF][0]: hotel_listing(entry), entry["url"]: hotel_detail(entry, '<p>' + narrative + '</p>')}
    first = c.collect_chunk(source(c.LONGLEAF), lambda url, _: pages[url], now=NOW, max_fetches=1)
    assert not first["complete"] and first["events"] == []
    result = c.collect_chunk(source(c.LONGLEAF), lambda url, _: pages[url], now=NOW, checkpoint=first["checkpoint"])
    assert result["complete"] and len(result["events"]) == 1
    row = result["events"][0]
    assert row["description"] == narrative.strip() and row["venue_address"] == entry["street"]
    assert (row["lat"], row["lng"]) == (entry["lat"], entry["lng"])
    assert row["location_provenance"] == "publisher_named_venue_and_matching_street_geo"
    with pytest.raises(ValueError, match="location_changed"):
        c._hotel_detail(entry, hotel_detail(entry, '<p>Full native event prose.</p>').replace(entry["street"], "999 Other Road, Raleigh, NC 27603"))
    with pytest.raises(ValueError, match="calendar_changed"):
        c._hotel_listing(hotel_listing(entry) + '<div class="eventlist-pagination"><a href="?page=2">Next</a></div>', NOW, [])


@patch.object(c, "record", side_effect=preview)
def test_week_promotion_remains_one_explicit_interval_not_repeated_performances(_):
    entry = hotel_event(title="Bottle of the Week: Seasonal Selection", days=6)
    row = c._hotel_detail(entry, hotel_detail(entry, '<p>Every week we share a different seasonal selection.</p>'))
    assert row["starts_at"] == entry["start"] and row["ends_at"] == entry["end"]
    performance = hotel_event(days=3)
    with pytest.raises(ValueError, match="schedule_unresolved"):
        c._hotel_detail(performance, hotel_detail(performance, '<p>The quartet performs an evening program.</p>'))


@pytest.mark.parametrize("body,reason", [("", "description_missing"), ("Long prose. " * 1200, "description_limit")])
def test_longleaf_missing_or_oversize_prose_is_not_replaced_by_teasers(body, reason):
    entry = hotel_event()
    with pytest.raises(ValueError, match=reason):
        c._hotel_detail(entry, hotel_detail(entry, body))


def reply(status=200, **headers):
    value = Mock(status_code=status, encoding="utf-8")
    value.headers = {"Content-Type": "application/json", **headers}
    value.iter_content.return_value = [b'{"events":[],"total":0}']
    return value


def network(response, allowed=True):
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.get.return_value = response
    return session, [patch.object(w.requests, "Session", return_value=session),
        patch.object(w, "validate_public_dns"), patch.object(w, "robots_allowed", return_value=allowed),
        patch.object(w, "pace_publisher")]


def read():
    return w.read_raleigh_brewing_occurrences(event_id=native()["id"], offset=0, public_instance=instance())


def test_native_occurrence_get_preserves_full_robots_url_and_existing_transport_guards():
    session, patches = network(reply())
    with patches[0], patches[1] as dns, patches[2] as robots, patches[3] as pace:
        assert json.loads(read()) == {"events": [], "total": 0}
    url = c.brewing_occurrences_url(native()["id"], 0)
    parts = urlsplit(url)
    dns.assert_called_once_with("www.raleighbrewing.com")
    assert robots.call_args.args == (parts.netloc, parts.path + "?" + parts.query)
    pace.assert_called_once()
    session.get.assert_called_once()
    session.post.assert_not_called()
    args, kwargs = session.get.call_args
    assert args == (url,) and kwargs["allow_redirects"] is False and kwargs["stream"] is True
    assert kwargs["headers"] == {"User-Agent": w.robots_checkpoint.PUBLISHER_USER_AGENT,
        "Accept": "application/json", "Authorization": instance()}
    assert "data" not in kwargs and "json" not in kwargs


def test_robots_denial_stops_before_any_event_request():
    session, patches = network(reply(), allowed=False)
    with ExitStack() as stack:
        for item in patches:
            stack.enter_context(item)
        with pytest.raises(w.PreviewError, match="^robots_denied$"):
            read()
    session.get.assert_not_called()
    session.post.assert_not_called()


@pytest.mark.parametrize("status,headers,reason", [(403, {}, "publisher_http_403"),
    (302, {"Location": "https://www.raleighbrewing.com/other"}, "calendar_render_redirect_blocked"),
    (200, {"Content-Type": "text/html"}, "invalid_calendar_render_content_type"),
    (200, {"Content-Length": "3000001"}, "source_unavailable_or_oversized")])
def test_http_denials_redirects_wrong_types_and_oversize_do_not_retry(status, headers, reason):
    session, patches = network(reply(status, **headers))
    with ExitStack() as stack:
        for item in patches:
            stack.enter_context(item)
        with pytest.raises(w.PreviewError, match=reason):
            read()
    session.get.assert_called_once()
    session.post.assert_not_called()


@pytest.mark.parametrize("mutation", ["host", "route", "status", "offset", "extra_query", "fragment",
    "token", "user", "another_instance", "another_site", "robots", "accept", "post", "mixed", "mixed_key"])
def test_public_instance_cannot_cross_scope_or_enable_another_operation(mutation):
    url = c.brewing_occurrences_url(native()["id"], 0)
    options = dict(respect_robots=True, allowed_hosts=("www.raleighbrewing.com",), brewing_instance=instance())
    accept = "application/json"
    if mutation == "host": url = url.replace("www.raleighbrewing.com", "another.example")
    elif mutation == "route": url = url.replace("/occurrences", "/private-attendees")
    elif mutation == "status": url = url.replace("status=0&status=1", "status=3")
    elif mutation == "offset": url = url.replace("offset=0", "offset=100")
    elif mutation == "extra_query": url += "&members=true"
    elif mutation == "fragment": url += "#anything"
    elif mutation == "token": options["brewing_instance"] = "private-token"
    elif mutation == "user": options["brewing_instance"] = instance(uid="signed-in-user")
    elif mutation == "another_instance": options["brewing_instance"] = instance(instanceId=SERIES)
    elif mutation == "another_site": options["brewing_instance"] = instance(metaSiteId=SERIES)
    elif mutation == "robots": options["respect_robots"] = False
    elif mutation == "accept": accept = "text/html"
    elif mutation == "post": options["calendar_json"] = {"write": True}
    elif mutation == "mixed": options["comedyworx_instance"] = instance()
    elif mutation == "mixed_key": options["game_theory_key"] = "another-key"
    with patch.object(w.requests, "Session") as session:
        with pytest.raises(w.PreviewError, match="invalid_raleigh_brewing_request"):
            w._fetch_publisher_request(url, accept, **options)
    session.assert_not_called()


@pytest.mark.parametrize("key", [c.BREWING, c.LONGLEAF])
@patch.object(c, "record", side_effect=preview)
def test_worker_injects_recurrence_callback_only_for_brewing_and_saves_before_exposing_rows(_, key):
    if key == c.BREWING:
        entry = native()
        pages = {c.SOURCES[key][0]: brewery_listing([entry]), packet_url(entry): brewery_detail(entry, total=1)}
    else:
        entry = hotel_event()
        pages = {c.SOURCES[key][0]: hotel_listing(entry), entry["url"]: hotel_detail(entry, '<p>A complete native program description.</p>')}
    value = c.collect_chunk(source(key), lambda url, _: pages[url], now=NOW)
    calls = []
    def rpc(operation, payload):
        calls.append((operation, payload))
        if operation.endswith("read_fetch_checkpoint"):
            return {"checkpoint": None, "revision": 0}
        if operation.endswith("write_fetch_checkpoint"):
            return {"checkpoint_saved": True, "revision": 1}
        pytest.fail("Unexpected production operation: " + operation)
    def adapter(source_row, fetch, **options):
        assert source_row == source(key) and callable(fetch)
        assert options["checkpoint"] is None and options["deadline_at"] > w.monotonic()
        if key == c.BREWING:
            assert options["read_public_events"](event_id=native()["id"], offset=0, public_instance=instance()) == "public-api-result"
        else:
            assert "read_public_events" not in options
        return value
    with patch.object(w, "supabase_rpc", side_effect=rpc), patch.object(c, "collect_chunk", side_effect=adapter), \
         patch.object(w.robots_checkpoint, "profile", return_value=None), \
         patch.object(w, "read_raleigh_brewing_occurrences", return_value="public-api-result") as read_api, \
         patch.object(w, "fetch_publisher") as network:
        result = w._preview_raleigh_direct_chunk(source(key),
            {"wait_unbounded": False, "crawl_delay_seconds": 0, "retry_after_seconds": 0},
            collection_context={"p_category": "html", "p_ticket": "synthetic-ticket"}, deadline_at=w.monotonic()+50)
    network.assert_not_called()
    assert [operation for operation, _ in calls] == ["community_collector_read_fetch_checkpoint", "community_collector_write_fetch_checkpoint"]
    assert calls[1][1]["p_checkpoint"] == value["checkpoint"] and result["p_events"] == value["events"]
    if key == c.BREWING:
        read_api.assert_called_once()
        assert read_api.call_args.kwargs["public_instance"] == instance()
        assert read_api.call_args.kwargs["deadline_at"] > w.monotonic()
    else:
        read_api.assert_not_called()


@patch.object(c, "record", side_effect=preview)
def test_worker_rejects_claimed_complete_snapshot_with_missing_advertised_occurrences(_):
    entry = native()
    pages = {c.SOURCES[c.BREWING][0]: brewery_listing([entry]), packet_url(entry): brewery_detail(entry, total=3)}
    partial = c.collect_chunk(source(c.BREWING), lambda url, _: pages[url], now=NOW, max_fetches=2,
        read_public_events=lambda **_: pytest.fail("fetch budget must defer API request"))
    assert partial["checkpoint"]["cursor"] == partial["checkpoint"]["manifest_count"] == 1
    assert not c.checkpoint_complete(partial["checkpoint"])
    forged_complete = dict(partial, complete=True, events=partial["checkpoint"]["events"])
    with patch.object(w, "supabase_rpc", return_value={"checkpoint": None, "revision": 0}) as rpc, \
         patch.object(c, "collect_chunk", return_value=forged_complete), \
         patch.object(w.robots_checkpoint, "profile", return_value=None):
        with pytest.raises(w.PreviewError, match="raleigh_direct_checkpoint_invalid"):
            w._preview_raleigh_direct_chunk(source(c.BREWING),
                {"wait_unbounded": False, "crawl_delay_seconds": 0, "retry_after_seconds": 0},
                collection_context={"p_category": "html", "p_ticket": "synthetic-ticket"}, deadline_at=w.monotonic()+50)
    assert rpc.call_count == 1
