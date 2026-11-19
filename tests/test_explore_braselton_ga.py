"""Explore Braselton Wix: exact original event evidence, safe hold behavior."""
from datetime import datetime, timezone
from roomquest.explore_braselton_ga import (
    KEY, URL, ZONE, collect, event_url, event_detail, image_candidate, listing_urls,
)

NOW = datetime(2026, 11, 19, 16, tzinfo=timezone.utc)
TREE = "https://www.explorebraselton.com/event-details/tree-lighting-celebration"
OTHER = "https://www.explorebraselton.com/event-details/brunch-with-santa-2026"
IMAGE = "https://static.wixstatic.com/media/abcdef123.webp"

def html(*, day="Nov 20, 2026", clock="6:00 PM – 8:00 PM",
         venue="Historic Downtown Braselton", street="9924 Davis St",
         city="Braselton", postal="30517", title="Tree Lighting Celebration",
         url=TREE, text="Publisher's complete event program and music lineup.",
         canonical=True):
    link = f'<link rel="canonical" href="{url}">' if canonical else ""
    return f"""<html><head>{link}
    <meta property="og:image" content="{IMAGE}"></head>
    <body><h1>{title}</h1>
    <h2>Time &amp; Location</h2>
    <section>{day}, {clock} {venue}, {street}, {city}, GA {postal}, USA</section>
    <h2>About the event</h2><p>{text}</p>
    <h2>Share this event</h2><footer>P.O. Box 306, Braselton, Georgia</footer></body></html>"""

def profile(**extra):
    return dict({"source_key":KEY, "feed_url":URL, "kind":"html",
                 "platform_adapter":"html", "timezone":ZONE}, **extra)

def test_exact_publisher_url_timing_street_and_description():
    ev = event_detail(html(), TREE, now=NOW)
    assert ev is not None
    assert ev["title"] == "Tree Lighting Celebration"
    assert "2026-11-20T23:00:00+00:00" in ev["starts_at"]
    assert "2026-11-21T01:00:00+00:00" in ev["ends_at"]
    assert ev["venue_address"] == "9924 Davis St, Braselton, GA 30517"
    assert ev["event_url"] == TREE
    assert "complete event program" in ev["description"]
    assert ev["image_url"] == IMAGE
    assert ev["location_provenance"] == "publisher_event_detail_street"

def test_hold_missing_true_event_fields_and_wrong_cities():
    fixtures = [
        {"day":"Nov 20"}, {"day":"Nov 20, 2025"},
        {"clock":"6:00 PM"}, {"clock":"10:00 PM – 8:00 PM"},
        {"city":"Gainesville"}, {"postal":"32606"},
        {"street":"Downtown"}, {"title":"Cancelled Tree Lighting"},
        {"canonical":False},
    ]
    for replacements in fixtures:
        assert event_detail(html(**replacements), TREE, now=NOW) is None, replacements
    assert event_detail(html(url=OTHER), TREE, now=NOW) is None
    assert event_detail(html(), "https://evil.example/event-details/tree-lighting-celebration", now=NOW) is None

def test_safe_url_image_and_listing_identity():
    for value in (
        "http://www.explorebraselton.com/event-details/tree-lighting-celebration",
        "https://www.explorebraselton.com/event-details/tree-lighting-celebration?utm=1",
        "https://example.com/event-details/tree-lighting-celebration",
        "https://www.explorebraselton.com@evil.example/event-details/tree-lighting-celebration",
        "https://www.explorebraselton.com/event-list"
    ):
        assert not event_url(value)
    assert event_url(TREE)
    assert image_candidate(IMAGE) == IMAGE
    assert image_candidate("https://evil.example/media/abcdef123.webp") is None
    assert image_candidate("https://static.wixstatic.com/media/abc.webp?token=bad") is None
    listing = ('<a href="/event-details/tree-lighting-celebration">One</a>'
               '<a href="/event-details/tree-lighting-celebration">Duplicate</a>'
               '<a href="https://evil.example/event-details/other">Other</a>'
               '<a href="/event-details/brunch-with-santa-2026">Two</a>')
    assert listing_urls(listing) == [TREE, OTHER]

def test_collector_does_not_fabricate_fields_or_skip_source_gate():
    index = '<a href="/event-details/tree-lighting-celebration">Tree lighting</a>'
    seen = []
    def fetch(url, accept):
        seen.append(url)
        return index if url == URL else html()
    events = collect(profile(), fetch, now=NOW)
    assert len(events) == 1
    assert seen == [URL, TREE]
    assert events[0].get("lat") is None and events[0].get("lng") is None
    for bad in (
        {"source_key":"wrong"}, {"timezone":"UTC"},
        {"feed_url":"https://example.com/events"},
        {"kind":"json"}, {"platform_adapter":"wordpress"},
    ):
        source = profile()
        source.update(bad)
        try:
            collect(source, fetch, now=NOW)
            assert False, "wrong source cannot collect"
        except ValueError as exc:
            assert str(exc) == "unregistered_explore_braselton_source"
