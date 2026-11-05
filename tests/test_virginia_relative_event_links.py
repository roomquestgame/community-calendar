"""Actual DCR link shape reproduced from the 2026-11-03 cloud HTTP check.

No network calls. Record conversion is real in the end-to-end fixture; only
publisher HTTP is replaced with deterministic HTML and future fixture dates.
"""
from datetime import datetime, timedelta
from html import escape

import pytest
from bs4 import BeautifulSoup

from roomquest import virginia_state_parks as va

PARK = va.catalog()["oc"]
HIKE_ID = "2026-10-17-16-00-48-597528-s8b"
MEETING_ID = "2026-08-24-08-35-53-063992-v4f"
SOURCE = {"source_key": "virginia_state_parks_oc", "kind": "html",
          "platform_adapter": "html", "feed_url": va.registered_calendar_url(PARK)}


def listing(*hrefs, count=2, park_name=PARK["name"]):
    # The live DCR page separates the numeric count and park name with <b>.
    return ('<main><h1>Events in Virginia State Parks</h1>'
            f'<h2>Between <b>11/03/2026</b> and <b>01/02/2027</b><br>'
            f'(<b>{count}</b>) Events Found For <b>All</b> Event Types</h2>'
            f'<h3>Park: <b>{park_name}</b></h3>' +
            ''.join(f'<div class="event"><a href="{escape(href, quote=True)}">View Details</a></div>'
                    for href in hrefs) + '</main>')


def test_live_page_relative_links_discover_all_ten_events_and_dedupe_cards():
    ids = [f"2026-11-03-12-00-00-{n:06d}-abc" for n in range(10)]
    html = listing(*(f"event?id={eid}" for eid in ids for _ in range(2)), count=10)
    # This was the production failure: selector yielded no event cards.
    assert not BeautifulSoup(html, 'html.parser').select('a[href*="/state-parks/event"]')
    links, total = va.discover(html, PARK)
    assert total == 20
    assert links == [va.ROOT + '/state-parks/event?id=' + eid for eid in ids]


@pytest.mark.parametrize('href', [
    'event?id=' + HIKE_ID,
    './event?id=' + HIKE_ID,
    '/state-parks/event?id=' + HIKE_ID,
    va.ROOT + '/state-parks/event?id=' + HIKE_ID,
])
def test_relative_root_relative_and_absolute_event_links_resolve_identically(href):
    links, total = va.discover(listing(href, count=1), PARK)
    assert total == 1
    assert links == [va.ROOT + '/state-parks/event?id=' + HIKE_ID]


@pytest.mark.parametrize('href', [
    'https://evil.example/state-parks/event?id=' + HIKE_ID,
    '//evil.example/state-parks/event?id=' + HIKE_ID,
    'http://www.dcr.virginia.gov/state-parks/event?id=' + HIKE_ID,
    'https://user@www.dcr.virginia.gov/state-parks/event?id=' + HIKE_ID,
    'https://www.dcr.virginia.gov:444/state-parks/event?id=' + HIKE_ID,
    'https://www.dcr.virginia.gov:bad/state-parks/event?id=' + HIKE_ID,
    'https://www.dcr.virginia.gov.evil.example/state-parks/event?id=' + HIKE_ID,
    'javascript:alert(1)',
    'event?id=' + HIKE_ID + '&id=' + MEETING_ID,
    'event?id=invalid%2Fid',
    '/other/event?id=' + HIKE_ID,
    'events?park=all',
])
def test_url_normalization_never_relaxes_origin_path_or_event_identity(href):
    html = listing('event?id=' + MEETING_ID, href)
    links, total = va.discover(html, PARK)
    assert total == 1
    assert links == [va.ROOT + '/state-parks/event?id=' + MEETING_ID]


@pytest.mark.parametrize('html', [
    '<html><body>Request blocked</body></html>',
    '<h1>Events</h1>',
    listing(count=10),
    listing(count=0, park_name='Douthat State Park'),
    '<h2>(0) Events Found</h2>',
])
def test_missing_or_unrecognized_event_markup_is_not_a_healthy_empty_source(html):
    with pytest.raises(ValueError, match='park_listing_structure_unverified'):
        va.collect(SOURCE, lambda url, accept: html)


def test_only_explicit_zero_count_for_requested_park_is_a_healthy_empty_result():
    html = listing(count=0)
    assert va.discover(html, PARK) == ([], 0)
    assert va.collect(SOURCE, lambda url, accept: html) == []


def test_detail_limit_does_not_depend_on_duplicate_links():
    ids = [f"2026-11-03-12-00-00-{n:06d}-abc" for n in range(12)]
    links, total = va.discover(listing(*(f'event?id={eid}' for eid in ids), count=12), PARK)
    assert total == 12
    assert len(links) == va.MAX_EVENT_PAGES == 10


def test_relative_link_fix_preserves_meeting_and_park_coordinates_without_record_mock():
    day = (datetime.now(va.TZ) + timedelta(days=2)).strftime('%b. %d, %Y')
    def detail(title, where, description):
        return ('<html><body><main>'
                f'<h1>{title}</h1><h2>Where</h2><div>Program Location:</div><div>{where}</div>'
                '<div>Main Park Address:</div><a>Occoneechee State Park</a>'
                '<span>, 1192 Occoneechee Park Rd., Clarksville, VA 23927.</span>'
                f'<h2>When</h2><div>{day}. 11:00 a.m. - 12:30 p.m.</div>'
                f'<div id="event_description"><p>{description}</p></div></main></body></html>')
    meeting = detail('Friends of Occoneechee State Park Monthly Meeting', 'Clarksville Town Hall',
                     'The Friends group meets at the Clarksville Town Hall (located at '
                     '321 Virginia Ave, Clarksville, VA 23927) in the Chamber Room. Everyone is welcome.')
    hike = detail('Plantation Discovery Hike', 'Terrace Gardens',
                  'Explore the history of the Occoneechee Plantation on this one-mile guided hike around the Plantation Trail.')
    html = listing('event?id=' + MEETING_ID, 'event?id=' + HIKE_ID)
    requested = []
    def fetch(url, accept):
        requested.append(url)
        if '/events?' in url:
            return html
        return meeting if url.endswith(MEETING_ID) else hike
    records = va.collect(SOURCE, fetch)
    assert len(records) == 2
    assert len(requested) == 3
    assert records[0]['venue_name'] == 'Clarksville Town Hall'
    assert records[0]['venue_address'] == '321 Virginia Ave, Clarksville, VA 23927'
    assert records[0]['lat'] is None and records[0]['lng'] is None
    assert 'Chamber Room' in records[0]['description']
    assert records[0]['event_url'] == va.ROOT + '/state-parks/event?id=' + MEETING_ID
    assert records[1]['venue_name'] == PARK['name']
    assert records[1]['lat'] == PARK['lat'] and records[1]['lng'] == PARK['lng']
    assert records[1]['venue_address'] == PARK['address']
    assert 'Terrace Gardens' in records[1]['description']
    assert records[0]['id'] != records[1]['id']
