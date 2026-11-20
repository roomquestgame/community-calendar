"""Focused, offline first-party discovery and no-unsafe-enrollment checks."""
import pytest

from roomquest.venue_discovery import discover, aggregator, venue_proof
from roomquest.preview_worker import PreviewError


def lead(name="Bojangles Coliseum", website="https://www.boplex.com/our-venues/bojangles-coliseum",
         event="https://www.boplex.com/events/checkers-vs-bruins-feb-6",
         address="2700 E Independence Boulevard, Charlotte, NC 28205"):
    return dict(name=name, website=website, event_url=event, address=address, origin="findlocal")


def factory(pages, seen):
    def fetch(url, accept, **kwargs):
        seen.append((url, kwargs))
        assert kwargs["respect_robots"] is True
        assert kwargs["allowed_hosts"] == ("www.boplex.com",)
        if url not in pages:
            raise AssertionError("Unexpected publisher request: " + url)
        return pages[url]
    return fetch


def test_boplex_shares_a_real_ical_feed_but_not_single_event_calendar():
    website = "https://www.boplex.com/our-venues/bojangles-coliseum"
    calendar = "https://www.boplex.com/events"
    feed = "https://www.boplex.com/events/?ical=1"
    pages = {
        website: '<title>Bojangles Coliseum</title><p>Charlotte</p><a href="/events">All Events</a>',
        calendar: '<h1>Events</h1><a href="/events/?ical=1">Subscribe</a>',
    }
    seen = []
    result = discover(lead(), fetch=factory(pages,seen))
    assert result == {"p_outcome":"verified","p_website_url":website,
                      "p_feed_url":feed,"p_proof":"name_city_official_page"}
    assert [x[0] for x in seen] == [website,calendar]


def test_brewery_name_branch_suffix_accepts_its_verified_site_and_events_page():
    source = lead(
        "Resident Culture Brewing (Plaza Midwood)",
        "https://residentculturebrewing.com/",
        "https://residentculturebrewing.com/events/",
        "2101 Central Ave, Charlotte, NC 28205",
    )
    seen = []
    def fetch(url,accept,**opts):
        seen.append(url)
        assert opts["respect_robots"] is True
        assert opts["allowed_hosts"] == ("residentculturebrewing.com",)
        return ('<h1>Resident Culture Brewing</h1><p>Taprooms</p>'
                if url.endswith("/") and not url.endswith("/events/")
                else "<h1>Events and calendar</h1><p>Weekly trivia nights</p>")
    result = discover(source,fetch=fetch)
    assert result["p_outcome"]=="verified"
    assert result["p_proof"]=="publisher_event_owner"
    assert result["p_feed_url"]=="https://residentculturebrewing.com/events/"
    assert len(seen)==2


def test_brand_without_calendar_remains_a_permanent_website_candidate():
    source = lead("Broadway Comedy Club", "https://www.broadwaycomedyclub.com/",
                  "https://www.broadwaycomedyclub.com/shows/nov-2026",
                  "318 W 53rd St, New York, NY 10019")
    seen = []
    result = discover(source,fetch=lambda url,accept,**opts:
                      (seen.append(url) or "<title>Broadway Comedy Club</title><h2>Comedy shows</h2>"))
    assert result["p_outcome"]=="verified"
    assert result["p_feed_url"] is None
    assert seen==["https://www.broadwaycomedyclub.com/"]


def test_an_unverified_site_with_feed_links_is_not_promoted():
    source = lead()
    result = discover(source,fetch=lambda url,accept,**opts:
                      '<a href="/events/?ical=1">Subscribe</a><p>Wrong Venue</p>')
    assert result=={"p_outcome":"review","p_reason":"publisher_identity_unverified"}


def test_things_to_do_official_event_source_can_resolve_first_party_root():
    source=lead("Example Venue",None,"https://www.examplevenue.com/event/show",
                "400 Main Street, San Francisco, CA 94110")
    source["origin"]="things_to_do"
    seen=[]
    def fetch(url,accept,**opts):
        seen.append(url)
        assert opts["allowed_hosts"]==("www.examplevenue.com",)
        return "<h1>Example Venue</h1><p>400 Main Street San Francisco</p>"
    result=discover(source,fetch=fetch)
    assert result["p_outcome"]=="verified"
    assert result["p_website_url"]=="https://www.examplevenue.com/"
    assert seen==["https://www.examplevenue.com/"]


def test_ticketing_aggregators_never_become_official_venues():
    assert aggregator("https://tickets.eventbrite.com/event/123")
    for source in (
        lead(website=None,event="https://www.eventbrite.com/e/example"),
        lead(website="https://ticketmaster.com/venue/123"),
        lead(website="http://127.0.0.1/private"),
    ):
        assert discover(source,fetch=lambda *a,**kw: pytest.fail("must not fetch"))["p_outcome"]=="review"


def test_no_following_untrusted_child_or_multiple_feeds():
    source=lead()
    homepage=('<h1>Bojangles Coliseum Charlotte</h1>'
              '<a href="https://other-calendar.example/some.ics">foreign calendar</a>'
              '<a href="/events/?ical=1">our feed</a>')
    result=discover(source,fetch=lambda u,a,**kw: homepage if u==source["website"] else "")
    assert result["p_outcome"]=="verified"
    assert result["p_feed_url"] is None  # Empty child is NOT a valid calendar


def test_robots_error_propagates_to_private_disposition_layer():
    with pytest.raises(PreviewError,match="robots_denied"):
        discover(lead(),fetch=lambda *args,**kwargs:
                 (_ for _ in ()).throw(PreviewError("robots_denied")))


def test_named_venue_and_city_page_proof():
    html="<h1>Ovens Auditorium</h1><p>Charlotte's historic performing arts center</p>"
    assert venue_proof(html,"https://www.boplex.com/our-venues/ovens-auditorium",
                       lead("Ovens Auditorium","https://www.boplex.com/our-venues/ovens-auditorium",
                            address="2900 E Independence Boulevard, Charlotte, NC 28205"))=="name_city_official_page"
