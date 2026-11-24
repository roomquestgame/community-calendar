from datetime import datetime, timedelta, timezone
import json

import pytest

from roomquest import wix_custom_collection as wix
from roomquest.registration_formats import source_key
from roomquest.registered_native_content import CAPABILITY


BASE = "https://venue.example/whatson/"
CHILD = "https://venue.example/dynamic-whatson_p_role_0_5000-sitemap.xml"


def source():
    return {"feed_url": BASE, "source_key": source_key(BASE), "kind": "html",
            "platform_adapter": "html", "registered_html_calendar_version": 1,
            CAPABILITY: 1}


def schema():
    fields = {
        "title": {"type": "text"}, "time": {"type": "text"},
        "eventDate": {"type": "date"}, "startDate": {"type": "date"},
        "endDate": {"type": "date"}, "occurrenceDate": {"type": "array"},
        "pastEvent": {"type": "boolean"},
        "link-events-title": {"type": "pagelink", "calculator": {"config": {
            "pattern": "/whatson/{title}"}}},
    }
    return {"displayField": "title", "fields": fields}


def page(records=None, links=()):
    binding = {"schemas": {"Events": schema()}, "dataStore": {
        "recordsByCollectionId": {"Events": records or {}}}}
    warmup = json.dumps({"appsWarmupData": {"dataBinding": binding}})
    anchors = "".join(f'<a href="{link}">Event</a>' for link in links)
    return (f'<html><head><meta property="og:site_name" content="Example Venue"></head>'
            f'<body><script id="wix-warmup-data" type="application/json">{warmup}</script>'
            f'{anchors}<footer>Example Venue 1 High Street London SW4 0QW Charity No: 1</footer>'
            f'</body></html>')


def item(identity, slug, day, clock="7PM"):
    return {"_id": identity, "title": slug.replace("-", " ").title(),
            "link-events-title": "/whatson/" + slug, "eventDate": day,
            "time": clock, "pastEvent": False,
            "shortProjectDescription": "Publisher summary"}


def index():
    return ('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f'<sitemap><loc>{CHILD}</loc></sitemap></sitemapindex>')


def manifest(*urls):
    return ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' +
            "".join(f'<url><loc>{url}</loc></url>' for url in urls) + '</urlset>')


def test_complete_sitemap_and_typed_records_drive_one_shared_stream():
    tomorrow = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    later = (datetime.now(timezone.utc).date() + timedelta(days=2)).isoformat()
    one, two = BASE + "one", BASE + "two"
    a, b = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
    stream = wix.stream(source(), BASE, page(links=(one, two)))
    assert next(stream) == ("https://venue.example/sitemap.xml", "application/xml,text/xml")
    assert stream.send(index()) == (CHILD, "application/xml,text/xml")
    assert stream.send(manifest(one, two)) == (one, "text/html,application/xhtml+xml")
    assert stream.send(page({a: item(a, "one", tomorrow)})) == (
        two, "text/html,application/xhtml+xml")
    with pytest.raises(StopIteration) as done:
        stream.send(page({b: item(b, "two", later, "8PM - 9:30PM")}))
    rows = done.value.value
    assert [row["title"] for row in rows] == ["One", "Two"]
    assert rows[0]["venue_address"] == "1 High Street London SW4 0QW, United Kingdom"
    assert rows[1]["ends_at"] is not None
    assert all(row["registered_native_content"]["evidence_url"] == row["event_url"]
               for row in rows)


def test_compacted_wix_capture_is_replay_equivalent_and_small():
    day = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    identity = "11111111-1111-4111-8111-111111111111"
    raw = page({identity: {**item(identity, "one", day),
                           "longProjectDescription": {"nodes": [{"textData": {
                               "text": "duplicate" * 10000}}]}}}, links=(BASE + "one",))
    compact = wix.compact_capture(raw)
    assert len(compact) < len(raw) / 10
    assert wix._records(wix._contract(BASE, compact), compact)[identity]["title"] == "One"


def test_manifest_must_be_complete_and_same_collection_scope():
    stream = wix.stream(source(), BASE, page(links=(BASE + "one",)))
    next(stream)
    stream.send(index())
    with pytest.raises(ValueError, match="wix_custom_manifest_scope_invalid"):
        stream.send(manifest("https://venue.example/other/one"))


def test_listing_without_typed_date_and_time_fields_is_not_claimed():
    broken = schema()
    broken["fields"] = {"title": {"type": "text"}}
    warmup = json.dumps({"appsWarmupData": {"dataBinding": {"schemas": {"Events": broken}}}})
    html = (f'<script id="wix-warmup-data" type="application/json">{warmup}</script>'
            f'<a href="{BASE}one">One</a>')
    assert wix.supports_listing(BASE, html) is False


def test_weekly_shorthand_range_and_range_exclusions_are_literal():
    today = datetime.now(timezone.utc).date()
    sunday = today + timedelta(days=(6 - today.weekday()) % 7)
    weekly = {"startDate": today.isoformat(), "dates": "EVERY SUNDAY", "time": "1 - 3PM"}
    assert wix._occurrences(weekly, today, today + timedelta(days=7)) == [
        (sunday, "1PM", "3PM")]

    start = today + timedelta(days=1)
    finish = start + timedelta(days=3)
    excluded = start + timedelta(days=1)
    ranged = {"startDate": start.isoformat(), "endDate": finish.isoformat(),
              "dates": "RUN", "time": "7:30PM (MON - SUN)",
              "excludeDates": [f'[{excluded.isoformat()}"']}
    days = [entry[0] for entry in wix._occurrences(ranged, today, finish)]
    assert days == [start, start + timedelta(days=2), finish]
