"""Fail-closed tests for the publisher's dated Magical Nights event program."""
from datetime import datetime, timezone
from roomquest.lanier_islands_ga import (
    KEY, LIST, DETAIL, parse, collect, event_url, image_candidate
)

NOW = datetime(2026, 11, 19, 18, tzinfo=timezone.utc)
LISTING = '<a href="/events/decorated-car-night/">Magical Nights</a>'
DETAIL_HTML = (
    '<link rel="canonical" href="' + DETAIL + '">'
    '<article><h1>Magical Nights of Lights</h1>'
    '<p>Welcome to Lanier Islands for the 2026 winter light show.</p></article>'
    '<article><h2>Magical Nights of Lights At A Glance</h2><ul>'
    '<li>Dates: Nightly, November 20, 2026 to January 3, 2027, including holidays</li>'
    '<li>Hours: 5 PM to 10 PM</li>'
    '<li>Location: Lanier Islands Resort, 7000 Lanier Islands Parkway, Buford, GA</li>'
    '</ul></article>'
)

def test_strict_identity():
    assert event_url(DETAIL)
    assert not event_url(DETAIL + "?other=1")
    assert not event_url("https://www.lanierislands.com.evil.test/holiday-events/magical-nights-of-lights/")
    assert image_candidate("https://www.lanierislands.com/site/assets/files/198984/mnol_03.jpg")
    assert image_candidate("https://evil.test/image.jpg") is None

def test_explicit_nightly_expansion_and_exact_address():
    rows = parse(LISTING, DETAIL_HTML, now=NOW)
    assert len(rows) == 45
    assert len({x["starts_at"] for x in rows}) == 45
    assert all(x["event_url"] == DETAIL for x in rows)
    assert all(x["venue_address"] == "7000 Lanier Islands Parkway, Buford, GA 30518" for x in rows)
    assert all(x["description"] and "2026 winter light show" in x["description"] for x in rows)
    assert rows[0]["starts_at"].startswith("2026-11-20T17:00:00")
    assert rows[-1]["starts_at"].startswith("2027-01-03T17:00:00")

def test_no_recurrence_guessed_when_evidence_missing():
    assert parse("", DETAIL_HTML, now=NOW) == []
    assert parse(LISTING, DETAIL_HTML.replace("including holidays", "perhaps"), now=NOW) == []
    assert parse(LISTING, DETAIL_HTML.replace("Hours: 5 PM to 10 PM", "Hours: TBD"), now=NOW) == []
    assert parse(LISTING, DETAIL_HTML.replace("7000 Lanier Islands Parkway", "unspecified"), now=NOW) == []
    assert parse(LISTING, DETAIL_HTML.replace(DETAIL, "https://example.com/x"), now=NOW) == []
    assert parse(LISTING, DETAIL_HTML.replace("January 3, 2027", "January 3, 2030"), now=NOW) == []

def test_source_and_timezone_gate():
    source = {"source_key": KEY, "feed_url": LIST, "kind": "html",
              "platform_adapter": "html", "timezone": "America/New_York"}
    def fetch(url, mime):
        assert mime == "text/html"
        return LISTING if url == LIST else DETAIL_HTML
    assert len(collect(source, fetch, now=NOW)) == 45
    for key, bad in [("source_key", "other"), ("timezone", "UTC"),
                     ("feed_url", "https://example.com")]:
        broken = {**source, key: bad}
        try:
            collect(broken, fetch, now=NOW)
        except ValueError:
            pass
        else:
            raise AssertionError(f"missing source gate: {key}")
