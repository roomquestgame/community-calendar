"""No network or Supabase calls: HTML collector parsing, source isolation, route."""
import io
import json
from datetime import date
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch
import pytest
from roomquest import virginia_state_parks as va
from roomquest import preview_worker as worker
from api.html_demand import handler as HtmlHandler

ID = "2026-10-17-16-00-48-597528-s8b"
PAGE = """<html><body><main><h1>Plantation Discovery Hike</h1>
<h2>Where</h2><div>Program Location:</div><div>Terrace Gardens</div>
<div>Main Park Address:</div><div>Occoneechee State Park, 1192 Occoneechee Park Rd., Clarksville, VA 23927.</div>
<h2>When</h2><div>Nov. 7, 2026. 11:00 a.m. - 12:30 p.m.</div>
<p>Explore the history of the Occoneechee Plantation on this one-mile guided hike around the Plantation Trail and natural history.</p>
</main></body></html>"""
PARK = va.catalog()["oc"]
CAL_LINK = va.ROOT + "/state-parks/event?id=" + ID
SOURCE = {"source_key":"virginia_state_parks_oc", "kind":"html",
          "platform_adapter":"html",
          "feed_url":va.registered_calendar_url(PARK)}


def test_registered_pilot_calendar_uses_official_guid_and_60_day_window():
    official_id = "2013-10-18-21-10-41-00019"
    assert va.registered_calendar_url(PARK) == va.CALENDAR + "?park=" + official_id
    query = parse_qs(urlparse(va.listing_url(PARK, today=date(2026, 11, 3))).query)
    assert query == {"park": [official_id], "start": ["11/03/2026"], "end": ["01/02/2027"]}
    assert "srchloc" not in query
    other = va.catalog()["do"]
    with pytest.raises(ValueError, match="unverified_park_calendar_identifier"):
        va.registered_calendar_url(other)


def test_park_filtered_heading_allows_cards_without_repeated_park_name():
    alt = "2026-10-21-10-44-02-561449-03v"
    html = (f'<h3>Park: Occoneechee State Park</h3>'
        f'<article><a href="/state-parks/event?id={ID}">View Details</a></article>'
        f'<article><a href="/state-parks/event?id={alt}">View Details</a></article>')
    links, total = va.discover(html, PARK)
    assert links == [CAL_LINK, va.ROOT + "/state-parks/event?id=" + alt]
    assert total == 2


def test_out_of_park_meeting_does_not_block_park_events():
    offsite_id = "2026-10-10-15-06-23-053520-hfq"
    calendar_html = (
        '<h3>Park: Occoneechee State Park</h3>'
        f'<article><a href="/state-parks/event?id={offsite_id}">Meeting</a></article>'
        f'<article><a href="/state-parks/event?id={ID}">Hike</a></article>')
    seen = []
    def fake_fetch(url, accept):
        seen.append(url)
        if "/events?" in url:
            return calendar_html
        return PAGE.replace("Terrace Gardens", "Clarksville Town Hall") if offsite_id in url else PAGE
    with patch.object(va, "record", return_value={"id": "hike", "title": "Plantation Discovery Hike"}):
        records = va.collect(SOURCE, fake_fetch)
    assert len(records) == 1
    assert records[0]["title"] == "Plantation Discovery Hike"
    assert len(seen) == 3
    assert "park=2013-10-18-21-10-41-00019" in seen[0]


def test_catalog_contains_46_reviewed_parks():
    assert len(va.catalog()) == 46
    assert PARK["name"] == "Occoneechee State Park"
    assert PARK["address"].startswith("1192 Occoneechee Park")
    assert PARK["lat"] > 36 and PARK["lng"] < -78


def test_extracts_meeting_location_and_known_park_address():
    # Mock only normalized-record conversion to avoid date-dependent test windows.
    with patch.object(va, "record", return_value={"id":"example","lat":PARK["lat"],"lng":PARK["lng"]}) as record:
        result = va.parse_event(PAGE, CAL_LINK, PARK)
    assert result["description"].startswith("Meeting Location: Terrace Gardens\n\n")
    assert "Plantation" in result["description"]
    assert result["location_provenance"] == "owner_reviewed_park_cache"
    assert result["park_code"] == "OC"
    assert record.call_args.args[0] == "Plantation Discovery Hike"
    assert record.call_args.args[3] == "Occoneechee State Park"
    assert record.call_args.args[4] == PARK["address"]
    assert "2026-11-07T11:00:00-05:00" in record.call_args.args[1]
    assert "2026-11-07T12:30:00-05:00" in record.call_args.args[2]


def test_skips_offsite_meeting_with_unresolved_address():
    html=PAGE.replace("Terrace Gardens","Clarksville Town Hall")
    with pytest.raises(ValueError, match="offsite_venue_requires_address"):
        va.parse_event(html,CAL_LINK,PARK)


def test_source_must_match_registered_park_and_exact_url():
    with pytest.raises(ValueError, match="unregistered_html_calendar"):
        va.collect({**SOURCE,"feed_url":"https://evil.example/events"},lambda *_: pytest.fail("no fetch"))
    with pytest.raises(ValueError, match="unregistered_html_source"):
        va.collect({**SOURCE,"platform_adapter":"wordpress"},lambda *_: pytest.fail("no fetch"))
    with pytest.raises(ValueError, match="park_code_missing"):
        va.collect({**SOURCE,"source_key":"virginia_state_parks_zz","feed_url":va.CALENDAR+"?eventtype=all&srchloc=ZZ"},lambda *_: pytest.fail("no fetch"))


def test_discovery_uses_park_context_not_every_link_on_statewide_page():
    other = "2026-10-10-15-06-23-053520-hfq"
    html=f"""<article><h3>Occoneechee State Park</h3>
    <a href="/state-parks/event?id={ID}">View Details</a></article>
    <article><h3>Douthat State Park</h3>
    <a href="/state-parks/event?id={other}">View Details</a></article>"""
    links, total = va.discover(html,PARK)
    assert total==2
    assert links == [CAL_LINK]


def test_exact_html_adapter_dispatch_does_not_use_wordpress_or_ics():
    listing=f'<article><h3>Occoneechee State Park</h3><a href="/state-parks/event?id={ID}">View Details</a></article>'
    paths=[]
    def fetch(url,accept):
        paths.append(url)
        return listing if "/events?" in url else PAGE
    with patch.object(va,"record",return_value={"id":"vsp:oc:"+ID,"title":"Plantation Discovery Hike",
                  "lat":PARK["lat"],"lng":PARK["lng"],"event_url":CAL_LINK}) as mocked, \
         patch("roomquest.wordpress_adapter.collect") as wordpress, \
         patch.object(worker,"fetch_publisher",side_effect=lambda url,accept,**kwargs:fetch(url,accept)):
        result=worker.preview_source(SOURCE)
    assert result["p_future_count"]==1
    assert result["p_events"][0]["description"].startswith("Meeting Location:")
    assert paths==[va.listing_url(PARK),CAL_LINK]
    wordpress.assert_not_called()


class FakeHandler:
    path="/api/html-demand"
    headers={"Content-Length":"0"}
    def reply(self,status,body):
        return status,body


def test_independent_html_route_does_not_accept_legacy_category():
    fake=FakeHandler()
    payload=json.dumps({"category":"ical","ticket":"01234567-0123-0123-0123-0123456789ab"}).encode()
    fake.headers={"Content-Length":str(len(payload))}
    fake.rfile=io.BytesIO(payload)
    with patch("api.html_demand.collect_category") as dispatcher:
        result=HtmlHandler.do_POST(fake)
    assert result[0]==400
    dispatcher.assert_not_called()


def test_html_route_uses_only_its_own_ticket_category():
    fake=FakeHandler()
    ticket="01234567-0123-0123-0123-0123456789ab"
    payload=json.dumps({"category":"html","ticket":ticket}).encode()
    fake.headers={"Content-Length":str(len(payload))}
    fake.rfile=io.BytesIO(payload)
    with patch("api.html_demand.collect_category",return_value={"outcome":"idle"}) as dispatcher:
        status,body=HtmlHandler.do_POST(fake)
    assert status==200
    assert body=={"outcome":"idle"}
    dispatcher.assert_called_once_with("html",ticket)
