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


def test_synthetic_boplex_style_page_discovery_requires_a_valid_ical_response():
    website = "https://www.boplex.com/our-venues/bojangles-coliseum"
    calendar = "https://www.boplex.com/events"
    feed = "https://www.boplex.com/events/?ical=1"
    pages = {
        website: '<title>Bojangles Coliseum</title><p>Charlotte</p><a href="/events">All Events</a>',
        calendar: '<h1>Events</h1><a href="/events/?ical=1">Subscribe</a>',
        feed: 'BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:checkers-1\nDTSTART:20261121T190000Z\nSUMMARY:Game\nEND:VEVENT\nEND:VCALENDAR',
    }
    seen = []
    result = discover(lead(), fetch=factory(pages,seen))
    assert result == {"p_outcome":"verified","p_website_url":website,
                      "p_feed_url":feed,"p_proof":"name_city_official_page",
                      "p_reason":"reusable_ical"}
    assert [x[0] for x in seen] == [website,calendar,feed]


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
    assert result["p_feed_url"] is None
    assert result["p_reason"]=="calendar_not_found"
    assert len(seen)==2  # Weekly promotions are not a validated event feed.


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



def test_tec_endpoint_is_automatically_probed_only_when_website_has_tec_evidence():
    source = lead("Broadway Comedy Club", "https://www.broadwaycomedyclub.com/",
                  "https://www.broadwaycomedyclub.com/shows/november-2026",
                  "318 W 53rd St, New York, NY")
    host = "https://www.broadwaycomedyclub.com"
    api = host + "/wp-json/tribe/events/v1/events"
    pages = {
        host + "/": '<title>Broadway Comedy Club</title><div class="tribe-events">Upcoming Events</div>',
        api: '{"events":[{"id":31,"title":"Comedy Show","start_date":"2026-11-22 19:00:00"}],"total":1}',
    }
    seen = []
    def fetch(url, accept, **opts):
        seen.append(url)
        assert opts["respect_robots"] is True
        assert opts["allowed_hosts"] == ("www.broadwaycomedyclub.com",)
        return pages[url]
    result = discover(source, fetch=fetch)
    assert result["p_feed_url"] == api
    assert result["p_reason"] == "reusable_wordpress"
    assert seen == [host + "/", api]


def test_single_event_ical_download_is_not_promoted_as_calendar():
    source = lead()
    calls=[]
    def fetch(url,accept,**opts):
        calls.append(url)
        return ('<h1>Bojangles Coliseum Charlotte</h1>'
                '<a href="/events/checkers.ics">Add to Calendar</a>')
    result = discover(source, fetch=fetch)
    assert result["p_feed_url"] is None
    assert len(calls) == 1


def test_dated_html_events_collection_is_submitted_for_adapter_review():
    source=lead("Broadway Comedy Club", "https://www.broadwaycomedyclub.com/",
                "https://www.broadwaycomedyclub.com/shows/a-show",
                "318 W 53rd St, New York, NY")
    homepage=('<h1>Broadway Comedy Club</h1><h2>All Events</h2>'
              '<time datetime="2026-11-20">Nov 20</time><a href="/shows/first-comedy-show">First</a>'
              '<time datetime="2026-11-21">Nov 21</time><a href="/shows/second-comedy-show">Second</a>'
              '<time datetime="2026-11-22">Nov 22</time><a href="/shows/third-comedy-show">Third</a>')
    result=discover(source,fetch=lambda url,accept,**opts: homepage)
    assert result["p_feed_url"] == "https://www.broadwaycomedyclub.com/"
    assert result["p_reason"] == "html_listing_found"


def test_dynamic_calendar_without_verified_full_feed_stays_pending_review():
    site="https://www.boplex.com/our-venues/bojangles-coliseum"
    pages={
      site: '<h1>Bojangles Coliseum Charlotte</h1><a href="/events">All Events</a>',
      "https://www.boplex.com/events": '<h1>Upcoming Events</h1><div id="dynamic-calendar"></div>',
    }
    calls=[]
    result=discover(lead(),fetch=factory(pages,calls))
    assert result["p_feed_url"] is None
    assert result["p_reason"] == "calendar_not_found"
    assert len(calls)==2



def test_multiple_full_calendar_links_are_held_not_arbitrarily_selected():
    html=('<h1>Bojangles Coliseum Charlotte</h1>'
          '<a href="/events/first.ics">Subscribe to Sports Calendar</a>'
          '<a href="/events/second.ics">Subscribe to Concert Calendar</a>')
    calls=[]
    result=discover(lead(),fetch=lambda url,accept,**opts:
                    (calls.append(url) or html))
    assert result["p_feed_url"] is None
    assert result["p_reason"] == "multiple_calendar_links"
    assert len(calls) == 1  # Don't choose an arbitrary partial calendar.


def test_calendar_link_403_does_not_erase_first_party_website_confirmation():
    source=lead()
    calendar="https://www.boplex.com/events/?ical=1"
    def fetch(url,accept,**opts):
        if url==calendar:
            raise PreviewError("publisher_http_403")
        return ('<h1>Bojangles Coliseum Charlotte</h1>'
                '<a href="/events/?ical=1">Subscribe to Calendar</a>')
    result=discover(source,fetch=fetch)
    assert result["p_outcome"]=="verified"
    assert result["p_feed_url"] is None
    assert result["p_reason"]=="calendar_access_denied"


def test_discovery_keeps_venue_specific_query_selectors_and_validates_response():
    source=lead("Resident Culture Brewing (Plaza Midwood)",
                "https://residentculturebrewing.com/",
                "https://residentculturebrewing.com/events/",
                "2101 Central Ave, Charlotte, NC 28205")
    homepage=('<h1>Resident Culture Brewing</h1>'
              '<a href="/events/?fwp_event_location=plaza-midwood">Events Calendar</a>')
    listing="https://residentculturebrewing.com/events/?fwp_event_location=plaza-midwood"
    def fetch(url,accept,**opts):
        if url==source["website"]:
            return homepage
        if url == listing:
            return ('<h1>Events Calendar</h1>'
                    '<div class="tribe-events">All events</div>')
        assert url == "https://residentculturebrewing.com/wp-json/tribe/events/v1/events"
        return '{"error":"api_not_enabled"}'
    result=discover(source,fetch=fetch)
    assert result["p_feed_url"] is None  # TEC hint requires a real API response.
    assert result["p_reason"]=="calendar_not_found"


def test_probe_budget_never_trawls_many_calendar_pages():
    source=lead()
    urls=[]
    homepage=('<h1>Bojangles Coliseum Charlotte</h1>'
              + "".join(f'<a href="/events-page-{i}">View All Events</a>'
                        for i in range(20)))
    def fetch(url,accept,**opts):
        urls.append(url)
        return homepage if url==source["website"] else "<h1>Events</h1>"
    discover(source,fetch=fetch)
    assert len(urls)<=5  # Website + no more than four bounded requests.
