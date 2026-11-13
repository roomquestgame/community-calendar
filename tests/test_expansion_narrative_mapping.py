"""Publisher content retained by the reviewed expansion adapters, without extra I/O."""
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import Mock

from icalendar import Calendar, Event
import pytest

from roomquest import firespring, nebraska_event_listings, rockhouse, squarespace_events_html


@pytest.mark.parametrize("container", ["eventlist-description", "eventlist-excerpt"])
def test_squarespace_cards_keep_their_own_narrative_without_detail_requests(container):
    module = squarespace_events_html
    key = "pageturners_lounge_omaha_ne"
    listing = module.SOURCES[key][0]
    source = dict(source_key=key, feed_url=listing, kind="html", platform_adapter="html",
                  timezone=module.ZONE)
    now = datetime.now(timezone.utc)
    day = (now + timedelta(days=3)).date().isoformat()
    payload = f'''<main><nav>Book a private party</nav>
      <article class="eventlist-event eventlist-event--upcoming">
        <a class="eventlist-title-link" href="/event-calendar/literary-pub-quiz">Literary Pub Quiz</a>
        <time class="event-date" datetime="{day}">Event date</time>
        <time class="event-time-12hr-start" datetime="{day}">7:00 PM</time>
        <time class="event-time-12hr-end" datetime="{day}">9:30 PM</time>
        <div class="{container}"><p>Test your literary knowledge with friends.</p>
          <style>.card {{ color: red; }}</style><p>Teams of four or fewer. No cover.</p></div>
        <a href="/event-calendar/literary-pub-quiz">View Event</a>
      </article></main>'''
    fetch = Mock(return_value=payload)
    row, = module.collect(source, fetch, now=now)
    fetch.assert_called_once_with(listing, "text/html")
    assert row["title"] == "Literary Pub Quiz"
    assert row["venue_address"] == "5004 Dodge St, Omaha, NE 68132"
    assert "literary knowledge" in row["description"]
    assert "Teams of four or fewer. No cover." in row["description"]
    assert all(text not in row["description"] for text in ("private party", "View Event", "color:"))


def test_eleanor_keeps_loaded_event_body_without_tags_or_neighbor_navigation():
    module = squarespace_events_html
    listing = module.SOURCES[module.ELEANOR][0]
    source = dict(source_key=module.ELEANOR, feed_url=listing, kind="html", platform_adapter="html",
                  timezone=module.ELEANOR_ZONE)
    now = datetime.now(timezone.utc)
    day = (now + timedelta(days=3)).date().isoformat()
    path = "/event-details/northernnightsnorthernlights"
    fetch = Mock(side_effect=[f'<main><a class="summary-title-link" href="{path}">Author discussion</a></main>',
        f'''<main><h1 class="eventitem-title">Northern Lights, Northern Lives</h1>
        <time class="event-time-12hr-start" datetime="{day}">6:30 PM</time>
        <time class="event-time-12hr-end" datetime="{day}">8:00 PM</time>
        <div class="eventitem-column-content"><div class="sqs-layout">
          <p>Join a discussion and book release with an author and photographer.</p>
          <p>Meet at Eleanor’s, 801 Boush Street.</p></div>
          <div class="eventitem-content-footer">Posted In: featured Tagged: featured</div></div>
        <nav>Next concert</nav></main>'''])
    row, = module.collect(source, fetch, now=now)
    assert fetch.call_count == 2
    assert row["id"] == path
    assert row["event_url"] == "https://www.eleanorsnfk.com" + path
    assert row["venue_address"] == module.ELEANOR_SHOP[1]
    assert "author and photographer" in row["description"]
    assert "801 Boush Street" in row["description"]
    assert "Posted In" not in row["description"] and "Next concert" not in row["description"]


@pytest.mark.parametrize(("text", "expected"), [("  NERD   nite  ", ""), ("No cover.", "No cover.")])
def test_squarespace_omits_title_only_copy_but_keeps_short_useful_text(text, expected):
    module = squarespace_events_html
    key = "pageturners_lounge_omaha_ne"
    source = dict(source_key=key, feed_url=module.SOURCES[key][0], kind="html", platform_adapter="html",
                  timezone=module.ZONE)
    now = datetime.now(timezone.utc)
    day = (now + timedelta(days=3)).date().isoformat()
    fetch = Mock(return_value=f'''<main><article class="eventlist-event eventlist-event--upcoming">
      <a class="eventlist-title-link" href="/event-calendar/nerd-nite">Nerd Nite</a>
      <time class="event-date" datetime="{day}">Event date</time>
      <time class="event-time-12hr-start" datetime="{day}">7:00 PM</time>
      <div class="eventlist-excerpt"><p>{text}</p></div></article></main>''')
    row, = module.collect(source, fetch, now=now)
    assert row["description"] == expected


def test_firespring_and_chamber_exports_retain_ics_narrative_and_occurrence_identity():
    start = datetime.now(timezone.utc) + timedelta(days=3)
    event = Event()
    event.add("uid", "publisher-export-id")
    event.add("summary", "Business Toolbox Series")
    event.add("dtstart", start)
    event.add("dtend", start + timedelta(hours=1))
    event.add("location", "Lincoln Chamber\n1128 Lincoln Mall\nLincoln, NE 68508")
    event.add("description", "<p>Hear a panel of professionals discuss workforce development.</p>"
              "<script>unrelated()</script><p>Bring questions for the panel.</p>")
    calendar = Calendar()
    calendar.add("version", "2.0")
    calendar.add_component(event)
    detail = "https://www.lcoc.com/event/13508485-business-toolbox"
    row = firespring.event_record(calendar.to_ical().decode(), detail, "13508485")
    assert row["id"] == "13508485" and row["event_url"] == detail
    assert row["venue_address"] == "1128 Lincoln Mall, Lincoln, NE 68508"
    assert "workforce development" in row["description"]
    assert "Bring questions" in row["description"]
    assert "unrelated" not in row["description"]


def test_rockhouse_preserves_narrative_only_inside_the_already_fetched_event():
    key = "omaha_admiral_events"
    listing, suffix, _, _ = rockhouse.SOURCES[key]
    detail = "https://admiralomaha.com/event/a-show/" + suffix
    source = dict(source_key=key, feed_url=listing, kind="html", platform_adapter="html",
                  timezone=rockhouse.ZONE)
    now = datetime.now(timezone.utc)
    day = (now + timedelta(days=3)).strftime("%A, %B %d, %Y")
    fetch = Mock(side_effect=[f'<body><h1>Upcoming Events</h1><a href="{detail}">A Show</a></body>',
        f'''<body><div id="RhpEventsSingle"><div class="singleEventDetails"><h1>A Show</h1>
        <div>{day}</div><div>Doors: 7 pm // Show: 8 pm</div>
        <div class="singleEventDescription"><p>Acoustic songs and stories from the holiday tour.</p>
        <script>track()</script></div></div></div>
        <footer>Sign up for our email list</footer></body>'''])
    row, = rockhouse.collect(source, fetch, now=now)
    assert fetch.call_count == 2
    assert row["id"] == detail
    assert row["description"] == "Acoustic songs and stories from the holiday tour."
    assert rockhouse.event_description('<div class="singleEventDescription">Other event</div>', "A Show") == ""


def test_meetup_retains_eligible_event_description_without_importing_other_events():
    module = nebraska_event_listings
    now = datetime.now(timezone.utc)
    start = now + timedelta(days=3)
    source = dict(source_key=module.SPIEL, feed_url=module.SOURCES[module.SPIEL],
                  kind="html", platform_adapter="html", timezone=module.ZONE)
    event = {"@type": "Event", "name": "Tabletop Games at Spielbound",
             "url": "https://www.meetup.com/playing-games-at-spielbound/events/123456789/",
             "startDate": start.isoformat(), "endDate": (start + timedelta(hours=2)).isoformat(),
             "eventStatus": "https://schema.org/EventScheduled",
             "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
             "location": {"address": {"streetAddress": "3229 Harney St"}},
             "description": "<p>Learn new tabletop games and meet other players.</p><nav>Another meetup</nav>"}
    virtual = {**event, "name": "Online game", "eventAttendanceMode": "https://schema.org/OnlineEventAttendanceMode"}
    fetch = Mock(return_value='<script type="application/ld+json">' + json.dumps([event, virtual]) + '</script>')
    row, = module.collect(source, fetch, now=now)
    fetch.assert_called_once_with(module.SOURCES[module.SPIEL], "text/html")
    assert row["event_url"] == event["url"]
    assert row["venue_address"] == "3229 Harney St, Omaha, NE 68131"
    assert row["description"] == "Learn new tabletop games and meet other players."

