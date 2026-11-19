"""The Porch On Main strict first-party MEC parser contracts."""
from datetime import datetime, timezone
from roomquest.porch_on_main_ga import KEY,URL,ZONE,event_url,listing_urls,event_detail,collect

EVENT="https://visittheporch.com/events/lantern-parade-and-tree-lighting/"
NOW=datetime(2026,11,19,tzinfo=timezone.utc)


def detail(title="Lantern Parade and Tree Lighting",start="Nov 20 2026",
           clock="6:30 pm - 8:00 pm",street="5507 Main Street, Flowery Branch, GA 30542",
           canonical=EVENT):
    return (f'<link rel="canonical" href="{canonical}">'
            f'<h1 class="mec-single-title">{title}</h1>'
            f'<div class="mec-single-event-date"><span class="mec-start-date-label">{start}</span></div>'
            f'<div class="mec-single-event-time"><abbr class="mec-events-abbr">{clock}</abbr></div>'
            f'<div class="mec-single-event-location"><dd class="author"><h6>Downtown Flowery Branch</h6></dd>'
            f'<span class="mec-address">{street}</span></div>'
            '<div class="mec-single-event-description mec-events-content"><p>Join the lantern parade.</p></div>')


def test_exact_source_and_occurrence():
    src={"source_key":KEY,"feed_url":URL,"kind":"html","platform_adapter":"html","timezone":ZONE}
    def fetch(u,accept):
        return '<a href="'+EVENT+'">Lantern</a>' if u==URL else detail()
    x=collect(src,fetch,now=NOW)
    assert len(x)==1 and x[0]["event_url"]==EVENT and "lantern" in x[0]["description"].lower()
    assert x[0]["venue_address"].startswith("5507 Main Street")
    assert "2026-11-20T23:30:00+00:00" in x[0]["starts_at"]
    assert listing_urls('<a href="'+EVENT+'">x</a><a href="'+EVENT+'">y</a>')==[EVENT]


def test_holds_unsupported_or_missing_facts():
    for kwargs in ({"start":"Nov 20"}, {"clock":"TBD"},
                   {"clock":"6:30 pm"}, {"street":"Flowery Branch, GA 30542"},
                   {"street":"5507 Main Street, Roswell, GA 30076"},
                   {"title":"CANCELLED Lantern Parade"},
                   {"canonical":"https://other.example"}):
        assert event_detail(detail(**kwargs),EVENT,now=NOW) is None


def test_no_foreign_or_ambiguous_links():
    assert event_url(EVENT)
    assert not event_url(EVENT+"?source=x")
    assert not event_url("https://attacker.example/events/lantern-parade-and-tree-lighting/")
