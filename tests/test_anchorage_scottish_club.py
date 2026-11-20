"""Alaskan Scottish Club Eagle River: allowlisted original dates and fail-closed tests."""
from datetime import datetime, timezone
from html import escape
from json import dumps
import pytest
from roomquest import anchorage_scottish_club as m

NOW = datetime(2026, 11, 19, 23, 0, tzinfo=timezone.utc)
SRC = {"source_key": m.KEY, "timezone": m.ZONE, "feed_url": m.FEED,
       "kind": "html", "platform_adapter": "html"}

def fixture(slug, *, title=None, address=None, start=None, body=None):
    name, s, e, _ = m.EVENTS[slug]
    name = title if title is not None else name
    loc = {"@type": "Place", "name": m.VENUE[0],
           "address": address if address is not None else
                      "10930 Mausel St, Eagle River, AK 99577, USA",
           "url": m.ROOT + "/event-details/" + slug}
    data = {"@type": "Event", "name": name,
            "startDate": start if start is not None else s, "endDate": e,
            "eventStatus": "https://schema.org/EventScheduled",
            "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
            "location": loc}
    prose = body if body is not None else (
        "A public Celtic community celebration with music, cultural activities "
        "and local family-friendly presentations hosted by the Scottish Club.")
    return ("<html><head><title>" + escape(name) + " | Alaska Scottish Club</title>"
            "<script type='application/ld+json'>" + dumps(data) + "</script></head>"
            "<body><h2 data-hook='about'>About the event</h2><div><p>" +
            escape(prose) + "</p></div></body></html>")

def fetcher(*, replace=None, missing=None):
    def get(url, accept):
        if url == m.FEED:
            return "<html><body>" + "".join(
                "<a href='" + m.ROOT + "/event-details/" + slug + "'>Event</a>"
                for slug in m.EVENTS if slug != missing) + "</body></html>"
        assert m.event_url(m.KEY, url)
        slug = url.rsplit("/", 1)[-1]
        return replace.get(slug, fixture(slug)) if replace else fixture(slug)
    return get

def test_valid_original_occurrences():
    rows = m.collect(SRC, fetcher(), now=NOW)
    assert len(rows) == 2
    assert [r["category"] for r in rows] == ["festival", "arts_culture"]
    assert {r["venue_address"] for r in rows} == {m.VENUE[1]}
    assert all((r["lat"], r["lng"]) == m.POINT for r in rows)
    assert all(r["timezone"] == m.ZONE and r["description"] and not r.get("image_url") for r in rows)
    assert len({r["id"] for r in rows}) == 2

def test_source_mismatch():
    with pytest.raises(ValueError, match="scottish_source_mismatch"):
        m.collect({**SRC, "timezone": "UTC"}, fetcher(), now=NOW)

@pytest.mark.parametrize("url", [
    "https://example.com/event-details/celtic-holiday-market-1",
    m.ROOT + "/event-details/celtic-holiday-market",
    m.ROOT + "/event-details/celtic-holiday-market-1?utm=1",
    "http://www.alaskanscottish.org/event-details/celtic-holiday-market-1",
    m.ROOT + "/event-details/burns-night-2027"])
def test_disallowed_event_links(url):
    assert not m.event_url(m.KEY, url)

def test_missing_original_link():
    with pytest.raises(ValueError, match="scottish_missing_original_event_link"):
        m.collect(SRC, fetcher(missing="st-andrews-day-celebration"), now=NOW)

@pytest.mark.parametrize("field,value,expected", [
    ("title", "Unofficial market", "scottish_identity_invalid"),
    ("address", "11000 Fake Rd, AK", "scottish_unverified_venue"),
    ("start", "2026-11-21T11:00:00+00:00", "scottish_event_identity_changed"),
    ("body", "", "scottish_description_invalid")])
def test_fails_closed_on_changed_public_data(field, value, expected):
    slug = "celtic-holiday-market-1"
    page = fixture(slug, **{field: value})
    with pytest.raises(ValueError, match=expected):
        m.collect(SRC, fetcher(replace={slug: page}), now=NOW)

def test_does_not_truncate_publisher_narrative():
    slug = "celtic-holiday-market-1"
    prose = "Official publisher has full details of the cultural festival. " * 80
    row = m.collect(SRC, fetcher(replace={slug: fixture(slug, body=prose)}), now=NOW)[0]
    assert len(row["description"]) > 3000

def test_expired_returns_no_events():
    assert m.collect(SRC, fetcher(), now=datetime(2026,12,15,tzinfo=timezone.utc)) == []

def test_no_rights_implied():
    assert m.photo_url(m.KEY, "https://static.wixstatic.com/media/photo.jpg") is None

def test_preview_transport_uses_robots_and_exact_host(monkeypatch):
    from roomquest import preview_worker
    original = m.collect
    def guarded(url, accept, **kw):
        assert kw["respect_robots"] is True
        assert kw["allowed_hosts"] == ("www.alaskanscottish.org",)
        return fetcher()(url, accept)
    monkeypatch.setattr(preview_worker, "fetch_publisher", guarded)
    monkeypatch.setattr(m, "collect",
        lambda source, fetch, **kw: original(source, fetch, now=NOW,
                                            deadline_at=kw.get("deadline_at")))
    result = preview_worker.preview_source(SRC)
    assert result["p_future_count"] == result["p_venue_count"] == 2
    assert [r["category"] for r in result["p_events"]] == ["festival", "arts_culture"]
