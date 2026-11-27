from copy import deepcopy
from datetime import datetime
import json
from zoneinfo import ZoneInfo

from roomquest import nebraska_recreation as module
from roomquest import preview_worker


NOW = datetime(2026, 11, 27, 12, tzinfo=ZoneInfo(module.ZONE))


def source(key, publisher_name="Original provider label"):
    return dict(source_key=key, feed_url=module.SOURCES[key], timezone=module.ZONE,
                kind="html", platform_adapter="html", publisher_name=publisher_name)


def park_pages(title="Garden Tour"):
    root = f'''<main><div class="events-list-container"><article>
      <a href="{module.SOURCES[module.PARKS]}/garden-tour"><h4>{title}</h4>
      <p class="list-item-address">Sunken Gardens, 2601 D Street</p></a>
    </article></div></main>'''
    detail = '''<main><h1>Garden Tour</h1><ul>
      <li data-start-year="2026" data-start-month="11" data-start-day="29" data-start-hour="10" data-start-mins="0"
          data-end-year="2026" data-end-month="11" data-end-day="29" data-end-hour="11" data-end-mins="0"></li>
    </ul></main>'''
    return root, detail


def run_page(description="Run the lakeside course."):
    event = {"@type": "Event", "name": "ORC Thanksgiving Day Run",
             "url": module.THANKSGIVING, "startDate": "2026-11-29T09:00-06:00",
             "endDate": "2026-11-29T11:00-06:00",
             "eventStatus": "https://schema.org/EventScheduled",
             "description": f"<p>{description}</p>", "keywords": "Running, Community",
             "image": "https://omaharun.org/race.jpg",
             "location": {"name": "Zorinsky Lake Park", "address": {
                 "streetAddress": "3808 S 156th Street", "addressLocality": "Omaha",
                 "addressRegion": "NE"}}}
    return '<script type="application/ld+json">' + json.dumps(event) + "</script>"


def goatz_page(first_hour=6):
    return f'''<main><h1>The Hitchcock Experience</h1><p>Hitchcock Nature Center</p>
      <p>Race Date: Saturday-Sunday, November 29-30, 2026</p>
      <p>Start Time: {first_hour} a.m. 100M; 6 p.m. 50M</p>
      <p>27792 Ski Hill Loop</p></main>'''


def collect(key, payload, *, detail=None, publisher="Original provider label"):
    def fetch(url, accept):
        return detail if detail is not None and url != module.SOURCES[key] else payload
    return module.collect(source(key, publisher), fetch, now=NOW)


def test_each_recreation_parser_retains_publisher_owned_facts_only():
    root, detail = park_pages()
    park, = collect(module.PARKS, root, detail=detail)
    run, = collect(module.RUN, run_page())
    goatz = collect(module.GOATZ, goatz_page())
    pf = park["collector_event_content_v1"]["facts"]
    assert pf["venue_address"] == "Sunken Gardens, 2601 D Street"
    assert pf["venue_address"] != park["venue_address"]
    rf = run["collector_event_content_v1"]["facts"]
    assert rf["description"] == "Run the lakeside course."
    assert rf["venue_address"] == "3808 S 156th Street, Omaha, NE"
    assert rf["publisher_categories"] == ["Running", "Community"]
    assert rf["source_image_url"] == "https://omaharun.org/race.jpg"
    assert len(goatz) == 2
    assert all(row["collector_event_content_v1"]["facts"]["venue_address"] == "27792 Ski Hill Loop"
               for row in goatz)


def test_provider_label_rename_does_not_change_envelopes_or_ids():
    root, detail = park_pages()
    cases = ((module.PARKS, root, detail), (module.RUN, run_page(), None),
             (module.GOATZ, goatz_page(), None))
    for key, payload, extra in cases:
        first = collect(key, payload, detail=extra)
        renamed = collect(key, payload, detail=extra, publisher="Renamed provider label")
        assert [row["id"] for row in renamed] == [row["id"] for row in first]
        assert [row["collector_event_content_v1"] for row in renamed] == [
            row["collector_event_content_v1"] for row in first]


def test_event_edits_change_facts_without_changing_occurrence_id():
    root, detail = park_pages()
    changed_root, _ = park_pages("Evening Garden Tour")
    first, = collect(module.PARKS, root, detail=detail)
    changed, = collect(module.PARKS, changed_root, detail=detail)
    assert first["id"] == changed["id"]
    assert first["collector_event_content_v1"] != changed["collector_event_content_v1"]
    run, = collect(module.RUN, run_page())
    run_changed, = collect(module.RUN, run_page("Bring a warm layer."))
    assert run["id"] == run_changed["id"]
    assert run["collector_event_content_v1"] != run_changed["collector_event_content_v1"]


def test_normal_path_keeps_envelope_and_admin_samples_strip(monkeypatch):
    row, = collect(module.RUN, run_page())
    calls = {}
    monkeypatch.setattr(module, "collect", lambda *args, **kwargs: [deepcopy(row)])
    monkeypatch.setattr(preview_worker, "fetch_publisher", lambda *args, **kwargs: "")
    monkeypatch.setattr(preview_worker, "supabase_rpc",
                        lambda name, payload: calls.setdefault(name, payload) and 0)
    preview_worker._process_claimed_source(source(module.RUN))
    staged = calls["community_collector_record_staged_events"]["p_events"]
    preview_call = next(value for name, value in calls.items()
                        if name.startswith("community_collector_record_preview"))
    assert staged[0]["collector_event_content_v1"] == row["collector_event_content_v1"]
    assert "collector_event_content_v1" not in preview_call["p_samples"][0]


def test_complete_narrative_limit_matches_live_fingerprint_contract():
    try:
        collect(module.RUN, run_page("x" * (module.MAX_DESCRIPTION + 1)))
    except ValueError as exc:
        assert str(exc) == "publisher_description_limit"
    else:
        raise AssertionError("oversized narrative was accepted")
