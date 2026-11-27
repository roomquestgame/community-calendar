from copy import deepcopy
from datetime import datetime, timezone
import json

from roomquest import nebraska_final as module
from roomquest import preview_worker


NOW = datetime(2026, 11, 27, 12, tzinfo=timezone.utc)


def source(key, publisher="Original provider label"):
    return dict(source_key=key, feed_url=module.SOURCES[key][0], timezone=module.ZONE,
                kind="html", platform_adapter="html", publisher_name=publisher)


def localhop_payload(key, narrative="Library program details."):
    event_id = "event1"
    return {"results": [{
        "objectId": "instance1", "status": "publish", "allDay": False,
        "actualStartDate": {"iso": "2026-11-29T15:00:00+00:00"},
        "actualEndDate": {"iso": "2026-11-29T16:00:00+00:00"},
        "organization": {"objectId": module.GROUPS[key][0]},
        "addressLatLng": {"latitude": 40.81, "longitude": -96.68},
        "event": {"objectId": event_id, "name": "Library Lab", "status": "publish",
                  "virtual": False, "description": f"<p>{narrative}</p>",
                  "categories": [{"name": "Learning"}],
                  "image": {"url": "https://events.example/lab.jpg"},
                  "address": {"place": "Main Library", "address1": "123 Main St",
                              "city": "Lincoln" if key == module.LINCOLN else "Gretna",
                              "state": "NE", "postalCode": "68508"}}
    }]}


def localhop_rows(key, narrative="Library program details.", publisher="Original provider label"):
    embed = 'window.AppConfig.ParseAppId = "ABCDEFGHIJKLMNOPQRST";'
    payload = json.dumps(localhop_payload(key, narrative))
    return module.collect(source(key, publisher), lambda *_: embed,
                          fetch_localhop=lambda *_: payload, now=NOW)


def skyybox_rows(publisher="Original provider label"):
    pages = {
        module.SOURCES[module.SKYYBOX][0]: "6720 S 168th St Every Tuesday trivia starts at 7 pm",
        "https://midwestpubtrivia.com/locations-dates/": "Skyybox Grill and Bar Tuesday 7:00 PM",
    }
    return module.collect(source(module.SKYYBOX, publisher), lambda url, *_: pages[url], now=NOW)


def postscript_rows(narrative="Meet the author.", publisher="Original provider label"):
    item = {"id": "book1", "name": "Author Night", "description": narrative,
            "repeatPeriod": "noRepeat", "isAllDay": False, "timeZone": module.ZONE,
            "location": "", "categories": ["Books"], "image": "https://postscript.press/book.jpg",
            "start": {"type": "datetime", "date": "2026-11-29", "time": "18:00:00"},
            "end": {"date": "2026-11-29", "time": "19:00:00"}}
    widget = {"data": {"widgets": {module.WIDGET: {"data": {
        "app": "event-calendar", "settings": {"events": [item]}}}}}}
    def fetch(url, accept):
        return f'<div class="elfsight-app-{module.WIDGET}"></div>' if url == module.SOURCES[module.POSTSCRIPT][0] else json.dumps(widget)
    return module.collect(source(module.POSTSCRIPT, publisher), fetch, now=NOW)


def elleinad_rows(narrative="Storytime and craft.", publisher="Original provider label"):
    event = {"@type": "Event", "name": "Turkey Storytime",
             "startDate": "2026-11-29T10:00:00-06:00", "endDate": "2026-11-29T11:00:00-06:00",
             "eventStatus": "https://schema.org/EventScheduled", "description": narrative,
             "keywords": "Books, Children", "image": "https://parks.example/story.jpg",
             "location": {"name": "Elleinad Books", "address": {
                 "streetAddress": "4724 Prescott Ave", "addressLocality": "Lincoln",
                 "addressRegion": "NE", "postalCode": "68506"}}}
    def fetch(url, accept):
        payload = [event] if "turkey-storytime" in url else []
        return '<script type="application/ld+json">' + json.dumps(payload) + "</script>"
    return module.collect(source(module.ELLEINAD, publisher), fetch, now=NOW)


def zoo_rows(end_delta=7200, publisher="Original provider label"):
    start = int(datetime(2026, 11, 29, 2, tzinfo=timezone.utc).timestamp())
    markup = f'''<ul class="simcal-calendar-list"><li class="simcal-event">
      <span class="simcal-event-title">Blues Band</span>
      <span class="simcal-event-start-time" data-event-start="{start}"></span>
      <span class="simcal-event-end-time" data-event-end="{start + end_delta}"></span>
    </li></ul>'''
    return module.collect(source(module.ZOO_BAR, publisher), lambda *_: markup, now=NOW)


def test_all_six_profiles_capture_only_original_event_facts():
    lincoln, = localhop_rows(module.LINCOLN)
    gretna, = localhop_rows(module.GRETNA)
    skyybox = skyybox_rows()
    postscript, = postscript_rows()
    elleinad, = elleinad_rows()
    zoo, = zoo_rows()
    for row in (lincoln, gretna, postscript, elleinad, zoo, *skyybox):
        assert row["collector_event_content_v1"]["event_id"] == row["id"]
    lf = lincoln["collector_event_content_v1"]["facts"]
    assert lf["description"] == "Library program details."
    assert lf["venue_address"] == "123 Main St, Lincoln, NE 68508"
    assert lf["source_latitude"] == 40.81 and lf["source_longitude"] == -96.68
    sf = skyybox[0]["collector_event_content_v1"]["facts"]
    assert sf["venue_address"] == "6720 S 168th St"
    pf = postscript["collector_event_content_v1"]["facts"]
    assert "venue_name" not in pf and "venue_address" not in pf
    ef = elleinad["collector_event_content_v1"]["facts"]
    assert ef["publisher_categories"] == ["Books", "Children"]
    zf = zoo["collector_event_content_v1"]["facts"]
    assert "venue_name" not in zf and "publisher_categories" not in zf


def test_provider_label_rename_is_stable_for_every_profile():
    cases = (
        (lambda p: localhop_rows(module.LINCOLN, publisher=p)),
        (lambda p: localhop_rows(module.GRETNA, publisher=p)),
        skyybox_rows,
        (lambda p: postscript_rows(publisher=p)),
        (lambda p: elleinad_rows(publisher=p)),
        (lambda p: zoo_rows(publisher=p)),
    )
    for run in cases:
        first = run("Original provider label")
        renamed = run("Renamed provider label")
        assert [row["id"] for row in first] == [row["id"] for row in renamed]
        assert [row["collector_event_content_v1"] for row in first] == [
            row["collector_event_content_v1"] for row in renamed]


def test_event_edits_change_content_while_compatible_ids_are_reused():
    for first, changed in (
        (localhop_rows(module.LINCOLN), localhop_rows(module.LINCOLN, "Updated library details.")),
        (postscript_rows(), postscript_rows("Conversation and signing.")),
        (elleinad_rows(), elleinad_rows("Storytime, craft, and snack.")),
        (zoo_rows(), zoo_rows(10800)),
    ):
        assert [row["id"] for row in first] == [row["id"] for row in changed]
        assert [row["collector_event_content_v1"] for row in first] != [
            row["collector_event_content_v1"] for row in changed]


def test_normal_path_keeps_envelopes_and_admin_samples_strip(monkeypatch):
    row, = postscript_rows()
    calls = {}
    monkeypatch.setattr(module, "collect", lambda *args, **kwargs: [deepcopy(row)])
    monkeypatch.setattr(preview_worker, "fetch_publisher", lambda *args, **kwargs: "")
    monkeypatch.setattr(preview_worker, "supabase_rpc",
                        lambda name, payload: calls.setdefault(name, payload) and 0)
    preview_worker._process_claimed_source(source(module.POSTSCRIPT))
    staged = calls["community_collector_record_staged_events"]["p_events"]
    preview_call = next(value for name, value in calls.items()
                        if name.startswith("community_collector_record_preview"))
    assert staged[0]["collector_event_content_v1"] == row["collector_event_content_v1"]
    assert "collector_event_content_v1" not in preview_call["p_samples"][0]


def test_narrative_above_live_limit_is_rejected():
    try:
        postscript_rows("x" * (module.MAX_DESCRIPTION + 1))
    except ValueError as exc:
        assert str(exc) == "publisher_description_limit"
    else:
        raise AssertionError("oversized narrative was accepted")
