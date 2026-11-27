from copy import deepcopy
from datetime import datetime, timedelta
import json
from unittest.mock import patch
from zoneinfo import ZoneInfo

from roomquest import nebraska_event_listings as module
from roomquest import preview_worker


NOW = datetime(2026, 11, 27, 12, tzinfo=ZoneInfo(module.ZONE))


def source(key, publisher_name="Original provider label"):
    return dict(source_key=key, feed_url=module.SOURCES[key], timezone=module.ZONE,
                kind="html", platform_adapter="html", publisher_name=publisher_name)


def meetup_page(description="Learn new games."):
    item = {
        "@type": "Event", "name": "Tabletop Night",
        "url": "https://www.meetup.com/playing-games-at-spielbound/events/123456789/",
        "startDate": "2026-11-29T18:00:00-06:00", "endDate": "2026-11-29T20:00:00-06:00",
        "eventStatus": "https://schema.org/EventScheduled",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "location": {"name": "Spielbound Board Game Cafe", "address": {
            "streetAddress": "3229 Harney St", "addressLocality": "Omaha"}},
        "description": f"<p>{description}</p>", "keywords": "Games, Community",
        "image": {"url": "https://images.example/event.jpg"},
    }
    return '<script type="application/ld+json">' + json.dumps([item]) + "</script>"


def quiz_page(label="Trivia"):
    return f'''<main><div class="venue-card"><a href="https://americaspubquiz.com/event/test-2026-11-29-1">Event</a>
      <div class="card-title">Blue Sky Bar &amp; Patio</div>
      <div class="venue-card-show-type">{label}</div><div class="h5">7:00 pm</div>
      <address><p>10730 Pacific St, #150</p><p>Omaha, NE</p></address></div></main>'''


def audubon_page(title="Prairie Walk"):
    return f'''<main><div class="event-card-item"><div class="event-card-item-center">Spring Creek Prairie Audubon Center</div>
      <div class="event-card-item-location">Denton, NE</div><div class="event-card-item-title">{title}</div>
      <a href="https://www.audubon.org/events/prairie-walk?category=in-person">In person</a>
      <a class="card-link" href="https://act.audubon.org/a/prairie-walk">Details</a>
      <div class="event-month">Nov</div><div class="event-day">29</div>
      <div class="event-time">9:00 am - 11:00 am</div></div></main>'''


def collect(key, payload, publisher="Original provider label"):
    return module.collect(source(key, publisher), lambda *_: payload, now=NOW)


def test_each_parser_path_retains_only_original_event_facts():
    meetup, = collect(module.SPIEL, meetup_page())
    quiz, = collect(module.QUIZ, quiz_page())
    audubon, = collect(module.AUDUBON, audubon_page())
    mf = meetup["collector_event_content_v1"]["facts"]
    assert mf["description"] == "Learn new games."
    assert mf["venue_address"] == "3229 Harney St"
    assert mf["publisher_categories"] == ["Games", "Community"]
    assert mf["source_image_url"] == "https://images.example/event.jpg"
    qf = quiz["collector_event_content_v1"]["facts"]
    assert qf["venue_address"] == "10730 Pacific St, #150, Omaha, NE"
    assert qf["venue_city"] == "Omaha"
    af = audubon["collector_event_content_v1"]["facts"]
    assert af["venue_city"] == "Denton, NE"
    assert "venue_address" not in af  # Reviewed display enrichment is not publisher input.
    assert all(row["collector_event_content_v1"]["event_id"] == row["id"]
               for row in (meetup, quiz, audubon))


def test_provider_label_rename_reuses_envelope_and_ids_for_every_path():
    for key, payload in ((module.SPIEL, meetup_page()), (module.QUIZ, quiz_page()),
                         (module.AUDUBON, audubon_page())):
        first, = collect(key, payload)
        renamed, = collect(key, payload, "Renamed provider label")
        assert renamed["id"] == first["id"]
        assert renamed["collector_event_content_v1"] == first["collector_event_content_v1"]


def test_event_detail_edits_change_content_but_preserve_occurrence_ids():
    cases = ((module.SPIEL, meetup_page(), meetup_page("Bring a favorite game.")),
             (module.QUIZ, quiz_page(), quiz_page("Music Bingo")),
             (module.AUDUBON, audubon_page(), audubon_page("Sunset Prairie Walk")))
    for key, before, after in cases:
        original, = collect(key, before)
        changed, = collect(key, after)
        assert changed["id"] == original["id"]
        assert changed["collector_event_content_v1"] != original["collector_event_content_v1"]


def test_normal_path_keeps_envelope_and_admin_samples_strip(monkeypatch):
    row, = collect(module.SPIEL, meetup_page())
    calls = {}
    monkeypatch.setattr(module, "collect", lambda *args, **kwargs: [deepcopy(row)])
    monkeypatch.setattr(preview_worker, "fetch_publisher", lambda *args, **kwargs: "")
    monkeypatch.setattr(preview_worker, "supabase_rpc",
                        lambda name, payload: calls.setdefault(name, payload) and 0)
    preview_worker._process_claimed_source(source(module.SPIEL))
    staged = calls["community_collector_record_staged_events"]["p_events"]
    preview_call = next(value for name, value in calls.items()
                        if name.startswith("community_collector_record_preview"))
    samples = preview_call["p_samples"]
    assert staged[0]["collector_event_content_v1"] == row["collector_event_content_v1"]
    assert "collector_event_content_v1" not in samples[0]


def test_rejects_narrative_over_live_fingerprint_limit():
    try:
        collect(module.SPIEL, meetup_page("x" * (module.MAX_DESCRIPTION + 1)))
    except ValueError as exc:
        assert str(exc) == "publisher_description_limit"
    else:
        raise AssertionError("oversized publisher narrative was accepted")
