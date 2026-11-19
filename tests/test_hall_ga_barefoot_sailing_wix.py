"""First-party Barefoot Sailing Wix source: native calendar+permalink guards."""
from datetime import datetime, timezone
from pytest import raises

from roomquest import gainesville_direct_feeds as g

BASE = "https://www.barefootsailingclub.org"
A = BASE + "/event-details/dorton-cup-championship-4"
B = BASE + "/event-details/larc-fall-race-4-1"
ALOC = "Aqualand Marina Store parking lot, 6800 Lights Ferry Rd, Flowery Branch, GA 30542, USA"
BLOC = "LLSC Clubhouse, 6206 Commodore Dr, Flowery Branch, GA 30542, USA"
A_DATE = "Nov 21, 2026, 10:00 AM"
B_DATE = "Nov 22, 2026, 12:00 PM – 5:00 PM"

def card(title, day, location, link=""):
    return (f'<li data-hook="event-list-item">'
            f'<div data-hook="ev-list-item-title">{title}</div>'
            f'<div data-hook="date">{day}</div>'
            f'<div data-hook="location">{location}</div>'
            + (f'<a href="{link}">Details</a>' if link else "")
            + '</li>')

def detail(title, day, location, description=""):
    return (f'<div data-hook="event-title">{title}</div>'
            f'<div data-hook="event-full-date">{day}</div>'
            f'<div data-hook="event-full-location">{location}</div>'
            f'<div data-hook="event-description">{description}</div>')

def source():
    return dict(source_key=g.SAILING, feed_url=g.SOURCES[g.SAILING][0],
                kind="html", platform_adapter="html", timezone=g.ZONE)

def values():
    calendar = ('<script id="wix-warmup-data">{"timeZoneId":"America\\/New_York"}</script>'
                + card("Dorton Cup Championship", A_DATE, ALOC, A)
                + card("LARC Fall Race #4", B_DATE, BLOC, B)
                + card("Save the Date", "Nov 28, 2026, 12:00 PM", BLOC)
                + card("TBD Sailing", "December 2026 – date TBD", "Lake Lanier"))
    pages = {
        g.SOURCES[g.SAILING][0]: calendar,
        A: detail("Dorton Cup Championship", A_DATE, ALOC, "NEW START TIME: 10am Skippers Meeting, 12PM Start"),
        B: detail("LARC Fall Race #4", B_DATE, BLOC)
    }
    return pages

def test_timed_events_and_complete_description_no_fake_pins():
    pages = values()
    seen = []
    def fetch(url, accept):
        assert accept == "text/html"
        seen.append(url)
        return pages[url]
    rows = g.collect(source(), fetch, now=datetime(2026,11,19,tzinfo=timezone.utc))
    assert len(rows) == 2
    assert {r["event_url"] for r in rows} == {A, B}
    assert any("Skippers Meeting" in r["description"] for r in rows)
    assert all(r["venue_address"].startswith(("6800 ", "6206 ")) for r in rows)
    assert all(r["lat"] is None and r["lng"] is None for r in rows)
    assert len(seen) == 3
    assert len({r["id"] for r in rows}) == 2
    assert any(r.get("ends_at") for r in rows)

def test_missing_official_timezone_blocks_all():
    pages = values()
    pages[g.SOURCES[g.SAILING][0]] = pages[g.SOURCES[g.SAILING][0]].replace("America\\/New_York", "GMT")
    with raises(ValueError, match="publisher_timezone_unverified"):
        g.collect(source(),lambda url, accept: pages[url],now=datetime(2026,11,19,tzinfo=timezone.utc))

def test_mismatched_event_detail_holds_batch():
    pages = values()
    pages[A] = pages[A].replace("Aqualand Marina Store parking lot", "Unverified Event Hall")
    with raises(ValueError, match="publisher_event_detail_conflict"):
        g.collect(source(),lambda url, accept: pages[url],now=datetime(2026,11,19,tzinfo=timezone.utc))

def test_strict_event_link_identity_and_source_guards():
    assert g.event_url(g.SAILING,A)
    assert not g.event_url(g.SAILING,A+"?ref=other")
    assert not g.event_url(g.SAILING,"https://other.org/event-details/dorton-cup-championship-4")
    with raises(ValueError, match="unregistered_gainesville_direct_source"):
        g.collect({**source(),"timezone":"UTC"},lambda url,accept:values()[url])
