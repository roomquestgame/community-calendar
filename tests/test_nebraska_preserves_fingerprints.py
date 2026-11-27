from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

from roomquest import nebraska_preserves as module
from roomquest import preview_worker


NOW = datetime(2026, 11, 27, 12, tzinfo=ZoneInfo(module.ZONE))


def source(key, publisher_name="Original provider label"):
    return dict(source_key=key, feed_url=module.SOURCES[key][0], timezone=module.ZONE,
                kind="html", platform_adapter="html", publisher_name=publisher_name)


def prairie(end="11 AM"):
    return f'''<main><div class="x-text-content-text-primary">Calendar</div><div class="x-col">
      <div class="x-text-headline"><div class="x-text-content-text-primary">Prairie Walk</div>
      <div class="x-text-content-text-subheadline">Sunday, November 29, 2026, 9 AM - {end}</div></div>
    </div></main>'''


def glacier(end="11 AM"):
    return f'''<main><h2>Upcoming Events</h2><h3>Join us for Preserve Hike</h3>
      <p>Location: 14810 State Street, Bennington</p>
      <p>Dates/Times: Sunday, November 29, 2026, 9 AM - {end}</p><h2>News</h2></main>'''


def collect(key, payload, publisher="Original provider label"):
    return module.collect(source(key, publisher), lambda *_: payload, now=NOW)


def test_both_preserve_parsers_retain_only_event_owned_publisher_facts():
    prairie_row, = collect("prairie_pines_events_ne", prairie())
    glacier_row, = collect("glacier_creek_preserve_events_ne", glacier())
    pf = prairie_row["collector_event_content_v1"]["facts"]
    assert "venue_name" not in pf and "venue_address" not in pf
    gf = glacier_row["collector_event_content_v1"]["facts"]
    assert gf["venue_address"] == "14810 State Street, Bennington"
    assert gf["venue_address"] != glacier_row["venue_address"]
    assert all(row["collector_event_content_v1"]["event_id"] == row["id"]
               for row in (prairie_row, glacier_row))


def test_provider_label_rename_changes_neither_id_nor_content():
    for key, payload in (("prairie_pines_events_ne", prairie()),
                         ("glacier_creek_preserve_events_ne", glacier())):
        first, = collect(key, payload)
        renamed, = collect(key, payload, "Renamed provider label")
        assert first["id"] == renamed["id"]
        assert first["collector_event_content_v1"] == renamed["collector_event_content_v1"]


def test_end_time_edit_changes_content_without_changing_occurrence_id():
    for key, before, after in (("prairie_pines_events_ne", prairie(), prairie("12 PM")),
                               ("glacier_creek_preserve_events_ne", glacier(), glacier("12 PM"))):
        first, = collect(key, before)
        changed, = collect(key, after)
        assert first["id"] == changed["id"]
        assert first["collector_event_content_v1"] != changed["collector_event_content_v1"]


def test_normal_path_keeps_envelope_and_admin_samples_strip(monkeypatch):
    row, = collect("prairie_pines_events_ne", prairie())
    calls = {}
    monkeypatch.setattr(module, "collect", lambda *args, **kwargs: [deepcopy(row)])
    monkeypatch.setattr(preview_worker, "fetch_publisher", lambda *args, **kwargs: "")
    monkeypatch.setattr(preview_worker, "supabase_rpc",
                        lambda name, payload: calls.setdefault(name, payload) and 0)
    preview_worker._process_claimed_source(source("prairie_pines_events_ne"))
    staged = calls["community_collector_record_staged_events"]["p_events"]
    preview_call = next(value for name, value in calls.items()
                        if name.startswith("community_collector_record_preview"))
    assert staged[0]["collector_event_content_v1"] == row["collector_event_content_v1"]
    assert "collector_event_content_v1" not in preview_call["p_samples"][0]
