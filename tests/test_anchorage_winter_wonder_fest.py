"""First-party Winter Wonder Fest original daily schedule and release guards."""
from datetime import datetime, timezone
import json
import pytest

from roomquest import anchorage_winter_wonder_fest as ak
from roomquest import preview_worker

NOW = datetime(2026, 11, 19, 18, 30, tzinfo=timezone.utc)
DETAILS = {
    "@context": "https://schema.org", "@type": "Festival",
    "name": "Winter Wonder Fest 2026",
    "description": "Anchorage's first-annual Winter Wonder Fest, a two-day Christmas and holiday festival with live music, holiday cosplay contests, photos with Santa & The Grinch, reindeer, ice sculptures, food trucks and a beer garden.",
    "startDate": "2026-12-05T12:00:00-09:00",
    "endDate": "2026-12-06T18:00:00-09:00",
    "eventStatus": "https://schema.org/EventScheduled",
    "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
    "location": {"@type": "Place", "name": "Dena'ina Center",
                 "address": {"@type": "PostalAddress",
                             "streetAddress": "600 W 7th Ave",
                             "addressLocality": "Anchorage",
                             "addressRegion": "AK",
                             "postalCode": "99501",
                             "addressCountry": "US"}},
    "image": ["/og-promo.png"],
    "organizer": {"@type": "Organization", "name": "Winter Wonder Fest"}
}


def source():
    url, kind, adapter = ak.SOURCES[ak.KEY]
    return {"source_key": ak.KEY, "feed_url": url, "kind": kind,
            "platform_adapter": adapter, "timezone": ak.ZONE}


def page(details=None, schedule=True):
    ld = json.dumps(details if details is not None else DETAILS)
    text = ("December 5 & 6, 2026 Dena'ina Center "
            "12:00 - 6:00 PM · Both Days") if schedule else "December 5 & 6, 2026"
    return f'<html><script type="application/ld+json">{ld}</script><body>{text}</body></html>'


def fetch(html):
    def _fetch(url, accept):
        assert url == ak.FEED
        assert accept == "text/html"
        return html
    return _fetch


def test_exact_two_sessions_with_original_publisher_prose_and_real_point():
    rows = ak.collect(source(), fetch(page()), now=NOW)
    assert len(rows) == 2
    assert [r["id"] for r in rows] == [
        "winter_wonder_fest:2026-12-05", "winter_wonder_fest:2026-12-06"]
    assert [r["starts_at"][:10] for r in rows] == ["2026-12-05", "2026-12-06"]
    assert all(r["venue_address"] == ak.VENUE[1] for r in rows)
    assert all(r["event_url"] == ak.FEED for r in rows)
    assert all(r["category"] == "festival" for r in rows)
    assert all(r["timezone"] == "America/Anchorage" for r in rows)
    assert all(r["lat"] == ak.POINT[0] and r["lng"] == ak.POINT[1] for r in rows)
    assert all(r["description"] == DETAILS["description"] for r in rows)
    assert all(not r.get("image_url") for r in rows)


def test_fail_closed_when_daily_schedule_not_explicit():
    with pytest.raises(ValueError, match="festival_each_day_schedule_unverified"):
        ak.collect(source(), fetch(page(schedule=False)), now=NOW)


@pytest.mark.parametrize("change", [
    {"startDate": "2026-12-05T12:00:00-08:00"},
    {"endDate": "2026-12-06T19:00:00-09:00"},
    {"endDate": "2026-12-07T18:00:00-09:00"},
    {"eventStatus": "https://schema.org/EventCancelled"},
    {"description": ""},
    {"name": "Unrelated Event 2026"},
    {"location": {"name": "Generic Anchorage"},
     "description": DETAILS["description"]},
])
def test_wrong_offsets_date_venue_identity_status_or_prose_held(change):
    meta = dict(DETAILS, **change)
    with pytest.raises(ValueError):
        ak.collect(source(), fetch(page(details=meta)), now=NOW)


def test_invalid_registration_event_url_and_unlicensed_image_blocked():
    assert ak.event_url(ak.KEY, ak.FEED)
    assert not ak.event_url(ak.KEY, "https://example.com/")
    assert not ak.event_url(ak.KEY, ak.FEED + "?other")
    assert ak.photo_url(ak.KEY, "https://winterwonderfestak.com/og-promo.png") is None
    with pytest.raises(ValueError, match="unregistered_winter_wonder_fest"):
        ak.collect(dict(source(), timezone="America/New_York"), fetch(page()), now=NOW)


def test_preview_uses_source_scoped_robots_and_host_guard(monkeypatch):
    def guarded(url, accept, **kw):
        assert kw["respect_robots"] is True
        assert kw["allowed_hosts"] == ("winterwonderfestak.com",)
        return fetch(page())(url, accept)
    monkeypatch.setattr(preview_worker, "fetch_publisher", guarded)
    result = preview_worker.preview_source(source())
    assert result["p_future_count"] == result["p_venue_count"] == 2
