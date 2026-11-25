import json

from bs4 import BeautifulSoup

from roomquest import wordpress_visible_event as wp
from roomquest.registration_formats import source_key
from roomquest.registered_native_content import CAPABILITY


FEED = "https://venue.example/whats-on/"


def source():
    return {"feed_url": FEED, "source_key": source_key(FEED), "kind": "html",
            "platform_adapter": "html", "registered_html_calendar_version": 1,
            CAPABILITY: 1}


def shell(body, *, description="Publisher description"):
    return BeautifulSoup(
        '<meta property="og:site_name" content="Example Venue">'
        f'<meta property="og:description" content="{description}">'
        '<meta property="og:image" content="https://venue.example/image.jpg">'
        f'<main>{body}</main>', "html.parser")


def test_embedded_booking_sessions_cross_check_visible_wordpress_fields():
    sessions = [{"session_id": 22, "session_status": "Active",
                 "start_date": "2026-12-06", "start_time": "10:30:00",
                 "end_time": "16:30:00"}]
    body = ('<header class="page--header--event"><h1>Marbling Course</h1>'
            '<div class="page--header__introduction">Learn marbling.</div>'
            '<div class="page--header__event-details">'
            '<div class="event-detail"><p class="event-detail__title">Date</p>'
            '<p class="event-detail__info">Sunday 6 December 2026</p></div>'
            '<div class="event-detail"><p class="event-detail__title">Time</p>'
            '<p class="event-detail__info">10.30am–4.30pm</p></div>'
            '<div class="event-detail"><p class="event-detail__title">Where</p>'
            '<p class="event-detail__info">Studio<br>Museum - 1 High Street, SW4 0QW</p>'
            '</div></div></header>')
    soup = shell(body)
    soup.append(BeautifulSoup('<footer><address>1 High Street London SW4 0QW</address></footer>',
                              "html.parser"))
    soup.append(BeautifulSoup('<script id="json-data" type="application/json">' +
                              json.dumps(sessions) + '</script>', "html.parser"))
    rows = wp.read(source(), soup, FEED + "marbling/")
    assert len(rows) == 1
    assert rows[0]["starts_at"] == "2026-12-06T10:30:00+00:00"
    assert rows[0]["venue_name"] == "Studio"
    assert rows[0]["id"].endswith(":22")


def test_yearless_event_header_uses_exact_listing_date_filter_evidence():
    detail = shell(
        '<header class="entry-header"><h1 class="entry-title">Workshop</h1>'
        '<p class="eventdates">Saturday 12th December, 6pm</p>'
        '<p class="eventvenue">Example Hall</p></header>'
        '<div class="venueinfo">Venue information Example Hall 1 High Street London SW4 0QW '
        'Get directions</div>',
        description="Workshop information")
    evidence = {"display": "Saturday 12th December, 6pm", "date": "2026-12-12"}
    [row] = wp.read(source(), detail, FEED + "workshop/", listing=evidence)
    assert row["starts_at"] == "2026-12-12T18:00:00+00:00"


def test_listing_evidence_requires_one_matching_publisher_date():
    listing = BeautifulSoup(
        '<select><option value="?date=2026-12-12">12 December 2026</option></select>'
        '<article class="type-events"><h2 class="entry-title">'
        '<a href="/whats-on/workshop/">Workshop</a></h2>'
        '<p class="eventdates">Saturday 12th December, 6pm</p></article>', "html.parser")
    assert wp.listing_evidence(listing, FEED)[FEED + "workshop/"]["date"] == "2026-12-12"


def test_nested_heading_time_and_room_leave_street_for_shared_resolver():
    soup = shell(
        '<header><h1>Artist Talk<div class="date-range">FRI 11 DEC 2026, 6:30-8pm</div>'
        '</h1></header><div class="article-info"><span>Free event</span>'
        '<span>Clore Studio</span></div><div class="article-body">A conversation.</div>')
    [row] = wp.read(source(), soup, FEED + "artist-talk/")
    assert row["title"] == "Artist Talk"
    assert row["ends_at"] == "2026-12-11T20:00:00+00:00"
    assert row["venue_name"] == "Example Venue — Clore Studio"
    assert row["venue_address"] == ""


def test_landmark_widget_compacts_repeated_name_to_named_physical_address():
    detail = shell(
        '<header class="entry-header"><h1 class="entry-title">Concert</h1>'
        '<p class="eventdates">Saturday 12th December, 6pm</p>'
        '<p class="eventvenue">Tower of London — The Chapel</p></header>'
        '<div class="venueinfo">Venue information Tower of London — The Chapel '
        'Tower of London London EC3N 4AB United Kingdom Get directions</div>',
        description="Saturday 12 December 2026, 6pm concert")
    [row] = wp.read(source(), detail, FEED + "concert/")
    assert row["venue_address"] == "Tower of London, London, EC3N 4AB, United Kingdom"


def test_unbounded_visible_recurrence_is_an_explicit_non_discrete_exclusion():
    soup = shell('<header><h1>Garden Trail<div class="date-range">'
                 'EVERY SAT &amp; SUN, 12-6PM</div></h1></header>')
    assert wp.read(source(), soup, FEED + "trail/") == []
