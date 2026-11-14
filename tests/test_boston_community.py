"""Boston regressions for complete prose, publisher clocks and safe snapshots."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from html import escape
import json
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import pytest

from roomquest import boston_community as b


NOW = datetime.now(timezone.utc).replace(microsecond=0)
START = (NOW + timedelta(days=7)).astimezone(ZoneInfo(b.ZONE)).replace(hour=10, minute=30, second=0)
LOCATION = "44 Maple Street, Boston, Massachusetts, 02121, United States"
VENUE = "Maple Street Food Forest"


def source(key=b.FOOD_FOREST):
    url, kind, adapter = b.SOURCES[key]
    return dict(source_key=key, feed_url=url, kind=kind, platform_adapter=adapter, timezone=b.ZONE)


def sq(index=0, *, body="<p>Join neighbors for a garden stewardship workshop.</p>",
       location=LOCATION, venue=VENUE, point=(42.308863, -71.085384), title=None):
    title = title or f"Community workshop {index}"
    start = (START + timedelta(days=index)).astimezone(timezone.utc)
    end = start + timedelta(hours=1)
    url = f"https://www.bostonfoodforest.org/workshops/community-{index}"
    export = "https://www.google.com/calendar/event?" + urlencode(dict(
        action="TEMPLATE", text=title, dates=f"{start:%Y%m%dT%H%M%SZ}/{end:%Y%m%dT%H%M%SZ}", location=location))
    export_link = f'<a href="{escape(export, quote=True)}">Google Calendar</a>'
    map_url = "http://maps.google.com?" + urlencode({"q": location})
    address = (f'<span class="eventitem-meta-address-line eventitem-meta-address-line--title">{escape(venue)}</span>'
               f'<span class="eventitem-meta-address-line">{escape(location)}</span>'
               f'<a class="eventitem-meta-address-maplink" href="{escape(map_url, quote=True)}">Map</a>')
    listing = (f'<article class="eventlist-event--upcoming"><a class="eventlist-title-link" href="{url}">{escape(title)}</a>'
               f'<div class="eventlist-meta-address">{escape(venue)}<a>Map</a></div>'
               f'<div class="eventlist-excerpt">Short listing excerpt.</div>{export_link}</article>')
    detail = (f'<meta property="og:url" content="{url}">'
              f'<meta property="og:latitude" content="{point[0]}"><meta property="og:longitude" content="{point[1]}">'
              f'<div class="eventitem"><h1 class="eventitem-title">{escape(title)}</h1>{export_link}{address}'
              f'<div class="eventitem-column-content"><div class="sqs-layout">{body}</div></div></div>')
    return url, listing, detail


def transport(cards):
    listing = '<div class="eventlist">' + "".join(c[1] for c in cards) + "</div>"
    details = {c[0]: c[2] for c in cards}
    calls = []

    def fetch(url, accept):
        calls.append(url)
        assert "format=" not in url
        return listing if url == b.SOURCES[b.FOOD_FOREST][0] else details[url]

    return fetch, calls


def test_complete_description_is_not_listing_excerpt_or_two_thousand_char_clip():
    text = "Native workshop information and access instructions. " * 70
    fetch, calls = transport([sq(body=f"<p>{text}</p><style>.junk {{display:none}}</style>")])
    rows = b.collect(source(), fetch, now=NOW)
    assert len(rows) == 1
    assert rows[0]["description"] == text.strip()
    assert len(rows[0]["description"]) > 2000
    assert rows[0]["venue_address"] == "44 Maple Street, Boston, MA 02121"
    assert rows[0]["lat"] == 42.308863
    assert len(calls) == 2


def test_description_limit_fails_instead_of_truncating():
    fetch, _ = transport([sq(body="<p>" + "a" * 12001 + "</p>")])
    with pytest.raises(ValueError, match="boston_community_description_limit"):
        b.collect(source(), fetch, now=NOW)


@pytest.mark.parametrize("body", ["", "<style>.only-css{}</style>", "<p>https://example.org</p>"])
def test_no_fabricated_or_link_only_description(body):
    fetch, _ = transport([sq(body=body)])
    result = b.collect_chunk(source(), fetch, now=NOW)
    assert result["complete"] and result["events"] == []
    assert result["diagnostics"][0]["reason"] == "boston_community_description_or_street_missing"


def test_squarespace_new_york_default_is_never_published_as_boston_geo():
    fetch, _ = transport([sq(point=(40.7207559, -74.0007613))])
    row = b.collect(source(), fetch, now=NOW)[0]
    assert row["venue_address"] == "44 Maple Street, Boston, MA 02121"
    assert row["lat"] is None and row["lng"] is None
    assert "geocoding" in row["location_provenance"]


def test_virtual_calendar_event_does_not_inherit_source_hq():
    fetch, _ = transport([sq(location="", venue="Virtual via Zoom")])
    assert b.collect(source(), fetch, now=NOW) == []


def test_late_detail_failure_never_emits_partial_snapshot():
    cards = [sq(i) for i in range(4)]
    fetch, _ = transport(cards)
    first = b.collect_chunk(source(), fetch, now=NOW)
    assert not first["complete"] and first["events"] == []
    assert first["checkpoint"]["cursor"] == 3

    def broken(url, accept):
        if url == cards[3][0]:
            raise TimeoutError("publisher unavailable")
        return fetch(url, accept)

    with pytest.raises(TimeoutError):
        b.collect_chunk(source(), broken, checkpoint=first["checkpoint"], now=NOW)
    assert first["checkpoint"]["cursor"] == 3
    complete = b.collect_chunk(source(), fetch, checkpoint=first["checkpoint"], now=NOW)
    assert complete["complete"] and len(complete["events"]) == 4
    assert complete["checkpoint"]["cursor"] == 4


def test_checkpoint_cannot_inject_nyc_point_or_unvisited_event():
    fetch, _ = transport([sq(i) for i in range(4)])
    state = b.collect_chunk(source(), fetch, now=NOW)["checkpoint"]
    poisoned = deepcopy(state)
    poisoned["events"][0]["lat"] = 40.7207559
    poisoned["events"][0]["lng"] = -74.0007613
    with pytest.raises(ValueError, match="boston_community_checkpoint_invalid"):
        b.collect_chunk(source(), fetch, checkpoint=poisoned, now=NOW)
    poisoned = deepcopy(state)
    poisoned["events"][0]["event_url"] = sq(3)[0]
    with pytest.raises(ValueError, match="boston_community_checkpoint_invalid"):
        b.collect_chunk(source(), fetch, checkpoint=poisoned, now=NOW)


def test_changed_publisher_detail_is_not_accepted_under_old_manifest():
    card = sq()
    # The venue address in the detail export changed after the listing fetch.
    details = card[2].replace("44%20Maple", "99%20Maple").replace("44+Maple", "99+Maple")
    fetch, _ = transport([(card[0], card[1], details)])
    with pytest.raises(ValueError, match="boston_community_detail_changed"):
        b.collect(source(), fetch, now=NOW)


def test_ambiguous_picnic_duration_is_held_instead_of_guessed():
    fetch, _ = transport([sq(title="WORKDAY: Leland Cooperative Garden Work Party/Picnic",
                            body="<p>Work/picnic days 10:30AM-4PM with lunch around 1PM.</p>")])
    part = b.collect_chunk(source(), fetch, now=NOW)
    assert part["complete"] and part["events"] == []
    assert part["diagnostics"][0]["reason"] == "boston_community_schedule_conflict"


def rss_item(*, body="Join neighbors for this public workshop.", clock=None, end=True):
    day = START.strftime("%m/%d/%Y")
    clock = clock or START.strftime("%I:%M%p").lower()
    start_text = START.replace(tzinfo=None).isoformat() + "Z"
    finish = START + timedelta(hours=1)
    times = f'<time datetime="{start_text}">Monday, {day} - {clock}</time>'
    if end:
        times += (f'<time datetime="{finish.replace(tzinfo=None).isoformat()}Z">'
                  f'Monday, {day} - {finish:%I:%M%p}</time>')
    html = (f'<p><b>Event Date:</b></p><div class="date-recur-date">{times}</div>'
            '<p><b>Address:</b></p><p class="address"><span class="address-line1">Meeting Hall</span>'
            '<span class="address-line2">23 Drydock Ave</span><span class="locality">Boston</span>'
            '<span class="administrative-area">MA</span><span class="postal-code">02210</span></p>'
            f'<p>{body}</p><p><b>Publish Date:</b><time datetime="2020-01-01">Old publishing date</time></p>')
    return ("<item><title>Community workshop</title><link>https://www.boston.gov/calendar/community-workshop</link>"
            f"<description>{escape(html)}</description><pubDate>Wed, 1 Jan 2020 12:00:00 EST</pubDate></item>")


def rss(*items):
    return '<rss version="2.0"><channel><title>City of Boston Events</title>' + "".join(items) + "</channel></rss>"


def test_boston_rss_uses_visible_eastern_event_time_and_dedupes_repeated_items():
    body = "The entire official event narrative. " * 100
    item = rss_item(body=body)
    rows = b._city(rss(item, item), NOW, [])
    assert len(rows) == 1
    assert datetime.fromisoformat(rows[0]["starts_at"]) == START
    assert rows[0]["description"] == body.strip()
    assert rows[0]["venue_address"] == "23 Drydock Ave, Boston, MA 02210"


def test_boston_wall_clock_correction_requires_visible_time_agreement():
    with pytest.raises(ValueError, match="boston_community_time_unverified"):
        b._city(rss(rss_item(clock="11:30am")), NOW, [])


def test_missing_end_stays_missing():
    row = b._city(rss(rss_item(end=False)), NOW, [])[0]
    assert row["ends_at"] is None


def test_existing_cyclists_id_and_full_description_preserved():
    prose = "Safe streets meeting agenda and participation details. " * 60
    event = dict(id=17168, title="Boston Cyclists Union Fall Meeting", status="publish", all_day=False,
                 url="https://bostoncyclistsunion.org/event/fall-meeting", description=f"<p>{prose}</p>",
                 start_date=START.strftime("%Y-%m-%d %H:%M:%S"),
                 end_date=(START + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"), timezone=b.ZONE,
                 venue=dict(venue="Boston Public Library", address="700 Boylston Street", city="Boston", state="MA", zip="02116"))
    calls = []

    def fetch(url, accept):
        calls.append(url)
        return json.dumps(dict(events=[event], total=1, total_pages=1))

    rows = b.collect(source(b.CYCLISTS), fetch, now=NOW)
    assert rows[0]["id"] == "17168" and rows[0]["description"] == prose.strip()
    assert calls[0].startswith("https://bostoncyclistsunion.org/wp-json/tribe/events/v1/events?")


def test_foreign_host_and_source_tuple_are_rejected_before_fetch():
    item = source()
    item["feed_url"] = "https://example.com/workshops"
    with pytest.raises(ValueError, match="unregistered_boston_community_source"):
        b.collect(item, lambda *_: pytest.fail("fetch must not run"), now=NOW)
    assert not b.event_url(b.FOOD_FOREST, "https://example.com/workshops/a")
    assert not b.event_url(b.FOOD_FOREST, "https://www.bostonfoodforest.org/workshops/a?format=json")
