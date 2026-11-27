"""Meaningful regressions for Boston native descriptions, venues and resumes."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import html
import json

import pytest
from bs4 import BeautifulSoup

from roomquest import boston_nightlife as b


def source(key):
    url, kind, adapter = b.SOURCES[key]
    return dict(source_key=key, feed_url=url, kind=kind, platform_adapter=adapter, timezone=b.ZONE)


def future_day():
    return (datetime.now(timezone.utc) + timedelta(days=2)).date()


def square_card(day, body, *, excerpt=False, query="Notch Brewing", name="Notch Brewing"):
    text = f'<div class="eventlist-excerpt">{body}</div>' if excerpt else f'<div class="sqs-layout">{body}</div>'
    return f'''<div class="eventlist"><article class="eventlist-event--upcoming">
      <a class="eventlist-title-link" href="/brighton-events/community-run">Community Run</a>
      <time class="event-time-localized-start" datetime="{day}">7:00 PM</time>
      <time class="event-time-localized-end" datetime="{day}">8:00 PM</time>
      <div class="eventlist-meta-address">{name}<a href="https://maps.google.com?q={query}">(map)</a></div>
      <div class="eventlist-description">{text}</div>
    </article></div>'''


def test_complete_long_narrative_is_retained_and_over_limit_is_held():
    prose = "Native publisher sentence. " * 300
    assert len(prose) > 2000
    assert b._body(f"<p>{prose}</p>") == prose.strip()
    with pytest.raises(ValueError, match="description_limit"):
        b._body("A" * (b.MAX_DESCRIPTION + 1))
    with pytest.raises(ValueError, match="description_missing"):
        b._body('<img alt="Only a poster" src="x.jpg">')
    with pytest.raises(ValueError, match="description_missing"):
        b._body("https://tickets.example/event")


def test_native_text_is_not_parsed_as_html_again_during_record_mapping():
    day = future_day()
    queue = b._manifest(b.NOTCH, square_card(day, "A native &amp;#39; entity and &lt;example&gt; text."), datetime.now(timezone.utc))
    assert b._row(b.NOTCH, queue[0])["description"] == queue[0]["body"]


def test_original_facts_ignore_source_label_and_change_with_event_details():
    day = future_day()
    first_page = square_card(day, "The publisher's own event details.")
    changed_page = square_card(day, "The publisher changed the event details.")
    now = datetime.now(timezone.utc)
    first = b.collect_chunk(source(b.NOTCH), lambda *_: first_page, now=now)
    renamed = b.collect_chunk({**source(b.NOTCH), "publisher_name": "Changed provider label"},
                              lambda *_: first_page, now=now)
    changed = b.collect_chunk(source(b.NOTCH), lambda *_: changed_page, now=now)
    envelope = first["events"][0]["collector_event_content_v1"]
    assert renamed["events"][0]["collector_event_content_v1"] == envelope
    assert changed["events"][0]["collector_event_content_v1"] != envelope
    assert envelope["facts"]["venue_name"] == "Notch Brewing"


def test_brighton_calendar_uses_reviewed_street_and_rejects_another_location():
    day = future_day()
    queue = b._manifest(b.NOTCH, square_card(day, "A complete community run description."), datetime.now(timezone.utc))
    assert queue[0]["venue_key"] == "notch"
    row = b._row(b.NOTCH, queue[0])
    assert row["venue_address"] == "525 Western Avenue, Brighton, MA 02135"
    assert (row.get("lat"), row.get("lng")) != (42.5199017, -70.8908666)
    node = BeautifulSoup(square_card(day, "Text", query="283R Derby Street Salem MA", name="Notch Salem"), "html.parser")
    with pytest.raises(ValueError, match="venue_unresolved"):
        b._square_location(b.NOTCH, node)


def test_squarespace_excerpt_requires_detail_and_blank_full_body_is_held():
    day = future_day()
    excerpt = b._manifest(b.NOTCH, square_card(day, "Short excerpt...", excerpt=True), datetime.now(timezone.utc))[0]
    assert "body" not in excerpt and "held" not in excerpt
    blank = b._manifest(b.NOTCH, square_card(day, ""), datetime.now(timezone.utc))[0]
    assert blank["held"] == "boston_nightlife_description_missing"


def test_multivenue_calendar_never_assigns_missing_address_to_headquarters():
    with pytest.raises(ValueError, match="venue_unresolved"):
        b._square_location(b.CASTLE, BeautifulSoup("<article><h1>Friendsgiving</h1></article>", "html.parser"))
    node = BeautifulSoup('''<div class="eventitem-meta-address">
      <span class="eventitem-meta-address-line--title">Satellite</span><span>877 Cambridge Street</span>
      <a href="https://maps.google.com?q=877%20Cambridge%20Street%20Cambridge%20MA">(map)</a></div>''', "html.parser")
    assert b._square_location(b.REMNANT, node) == "satellite"


@pytest.mark.parametrize("key,venue_key,point", [
    (b.DORCHESTER, "dorchester", (42.322132, -71.0623169)),
    (b.LAMPLIGHTER, "lamp_cx", (42.372213, -71.0753146)),
])
def test_publisher_direction_target_point_requires_exact_source_venue_and_street(key, venue_key, point):
    venue, address, _ = b.VENUES[venue_key]
    assert b.reviewed_venue_location(key, venue, address) == point
    assert b.reviewed_venue_location(b.NOTCH, venue, address) is None
    assert b.reviewed_venue_location(key, venue, address.replace("021", "022")) is None
    if key == b.LAMPLIGHTER:
        assert b.reviewed_venue_location(key, *b.VENUES["lamp_broadway"][:2]) is None


def test_mec_listing_preserves_overnight_clocks_instead_of_midnight_jsonld():
    day = future_day()
    tomorrow = day + timedelta(days=1)
    url = f"https://www.clubcafe.com/club-events/dance-party/?occurrence={day}"
    ld = {"@type": "Event", "url": url, "startDate": str(day), "endDate": str(tomorrow),
          "location": {"address": "209 Columbus Avenue, Boston, MA 02116"}}
    payload = f'''<script type="application/ld+json">{json.dumps(ld)}</script>
      <article class="mec-event-article"><h3 class="mec-event-title"><a href="{url}">Dance Party</a></h3>
      <span class="mec-start-time">10:00 pm</span><span class="mec-end-time">2:00 am</span></article>'''
    item = b._manifest(b.CLUB, payload, datetime.now(timezone.utc))[0]
    assert b.timestamp(item["start"]).hour == 22
    assert b.timestamp(item["end"]).date() == tomorrow
    assert b.timestamp(item["end"]).hour == 2
    assert "body" not in item


def test_aeronaut_scope_missing_narratives_and_stable_occurrences():
    day = str(future_day())
    event = dict(name="Flagons & Dragons", date=day, start="13:00", end="17:00", venue_slug="somerville",
                 description="Professional Dungeon Masters lead Dungeons and Dragons tables.")
    other = dict(event, venue_slug="unreviewed-venue")
    blank = dict(event, name="Unannounced Show", description="")
    queue = b._manifest(b.AERONAUT, json.dumps([event, other, blank]), datetime.now(timezone.utc))
    assert len(queue) == 2
    assert sum(x.get("held") == "boston_nightlife_description_missing" for x in queue) == 1
    assert len({b._identity(b.AERONAUT, x) for x in queue}) == 2


def lamp_fixture():
    day = future_day()
    cards, details = [], {}
    for handle, title in [("knitting", "Knitting Group"), ("book-fair", "Book Fair")]:
        url = "https://lamplighterbrewing.com/products/" + handle
        cards.append(f'''<a data-table-row href="/products/{handle}">
          <div data-index="0">{title}</div><div data-index="1">{day.strftime('%B %d, %Y')}</div>
          <div data-index="2">6 pm - 8 pm</div><div data-index="3">284 Broadway</div></a>''')
        product = dict(handle=handle, title=title, type="Event", description=f"<p>Complete native {title} narrative.</p>")
        details[url] = '<section data-product-root="main" x-data="' + html.escape("Theme_Product({product: " + json.dumps(product) + "})", quote=True) + '"></section>'
    listing = "".join(cards)
    return listing, details


def test_detail_checkpoint_emits_only_complete_batch_and_detects_mutation():
    listing, details = lamp_fixture()
    calls = []
    def fetch(url, accept):
        calls.append(url)
        return listing if url == b.SOURCES[b.LAMPLIGHTER][0] else details[url]
    now = datetime.now(timezone.utc)
    first = b.collect_chunk(source(b.LAMPLIGHTER), fetch, now=now, max_details=1)
    assert not first["complete"] and first["events"] == []
    assert first["checkpoint"]["cursor"] == 1
    second = b.collect_chunk(source(b.LAMPLIGHTER), fetch, now=now, checkpoint=first["checkpoint"], max_details=1)
    assert second["complete"] and len(second["events"]) == 2
    assert all(x["description"].startswith("Complete native") for x in second["events"])
    assert len([url for url in calls if "/products/" in url]) == 2
    bad = deepcopy(first["checkpoint"])
    bad["events"][0]["venue_address"] = "1 Wrong Street, Boston, MA 02108"
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        b.collect_chunk(source(b.LAMPLIGHTER), fetch, now=now, checkpoint=bad)
    bad = deepcopy(first["checkpoint"])
    bad["queue"][0]["start"] = "2030-01-01T00:00:00+00:00"
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        b.collect_chunk(source(b.LAMPLIGHTER), fetch, now=now, checkpoint=bad)
    bad = deepcopy(first["checkpoint"])
    bad["events"][0]["collector_event_content_v1"]["facts"]["description"] = "Tampered facts."
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        b.collect_chunk(source(b.LAMPLIGHTER), fetch, now=now, checkpoint=bad)


def test_checkpoint_keeps_one_protocol_and_does_not_invent_legacy_facts():
    listing, details = lamp_fixture()
    fetch = lambda url, _accept: listing if url == b.SOURCES[b.LAMPLIGHTER][0] else details[url]
    now = datetime.now(timezone.utc)
    first = b.collect_chunk(source(b.LAMPLIGHTER), fetch, now=now, max_details=1)
    assert "collector_event_content_v1" in first["checkpoint"]["events"][0]
    legacy = deepcopy(first["checkpoint"])
    legacy["events"][0].pop("collector_event_content_v1")
    full = b.collect_chunk(source(b.LAMPLIGHTER), fetch, now=now,
                           checkpoint=legacy, max_details=1)
    assert full["complete"]
    assert all("collector_event_content_v1" not in row for row in full["events"])


def test_source_and_media_urls_remain_publisher_scoped():
    s = source(b.NOTCH)
    s["feed_url"] += "?format=json"
    with pytest.raises(ValueError, match="unregistered"):
        b.collect(s, lambda *_: "")
    assert not b.event_url(b.LAMPLIGHTER, "https://lamplighterbrewing.com/cart/add")
    assert not b.event_url(b.CLUB, "https://www.clubcafe.com/club-events/dance/?occurrence=2026-11-20&redirect=x")
    assert b.photo_url(b.NOTCH, "https://images.squarespace-cdn.com/content/v1/wrong-site/photo.jpg") is None


def test_market_closed_all_day_is_excluded_before_clock_validation():
    payload = '''<div data-eventurl="https://bostonpublicmarket.org/bpm-events/market-closed/" data-eventid="1">
    <div class="sugar-calendar-block__event-cell__title">*MARKET CLOSED*</div><div>All-day</div></div>'''
    assert b._manifest(b.MARKET, payload, datetime.now(timezone.utc)) == []


def test_pandemonium_uses_explicit_occurrences_blackouts_and_one_product_read():
    day = future_day()
    def clock(delta, hour):
        d = day + timedelta(days=delta)
        return [d.year, d.month, d.day, hour, 0, 0]
    event = dict(handle="community-game", title="Community Game", vendor="Pandemonium Books & Games",
                 allDay=0, locations=[])
    events = [dict(event, start=clock(i, 18), end=clock(i, 21)) for i in range(3)]
    blackout = dict(event_type="blackout", start=clock(1, 0), end=clock(1, 23),
                    products=[{"externalProductId": 123}], resources=[], locations=[])
    payload = json.dumps(dict(schedule=events, products=[dict(handle="community-game", id=123)], blackouts=[blackout]))
    now = datetime.now(timezone.utc)
    queue = b._manifest(b.PANDEMONIUM, payload, now)
    assert len(queue) == 2
    assert all(x["venue_key"] == "pandemonium" for x in queue)
    product_url = "https://pandemoniumbooks.com/products/community-game"
    product = f'''<link rel="canonical" href="{product_url}"><h1>Community Game</h1>
      <div class="product__description"><p>Learn this game with our community facilitators.</p></div>'''
    calls = []
    def fetch(url, accept):
        calls.append(url)
        if url == b.SOURCES[b.PANDEMONIUM][0]:
            return b.PANDEMONIUM_SCHEDULE
        return product if url == product_url else payload
    result = b.collect_chunk(source(b.PANDEMONIUM), fetch, now=now, max_details=1)
    assert result["complete"] and len(result["events"]) == 2
    assert calls.count(product_url) == 1
    assert {x["venue_address"] for x in result["events"]} == {"4 Pleasant Street, Cambridge, MA 02139"}
    assert {x["description"] for x in result["events"]} == {"Learn this game with our community facilitators."}


def test_blank_detail_requests_are_counted_against_chunk_budget():
    listing, details = lamp_fixture()
    details = {url: payload.replace("Complete native Knitting Group narrative.", "").replace("Complete native Book Fair narrative.", "")
               for url, payload in details.items()}
    calls = []
    def fetch(url, accept):
        calls.append(url)
        return listing if url == b.SOURCES[b.LAMPLIGHTER][0] else details[url]
    result = b.collect_chunk(source(b.LAMPLIGHTER), fetch, max_details=1)
    assert not result["complete"]
    assert result["checkpoint"]["cursor"] == 1
    assert len(result["checkpoint"]["diagnostics"]) == 1
    assert len([url for url in calls if "/products/" in url]) == 1


def test_checkpoint_resets_after_four_hours_and_rejects_future_start():
    listing, details = lamp_fixture()
    def fetch(url, accept):
        return listing if url == b.SOURCES[b.LAMPLIGHTER][0] else details[url]
    now = datetime.now(timezone.utc)
    result = b.collect_chunk(source(b.LAMPLIGHTER), fetch, now=now, max_details=1)
    state = result["checkpoint"]
    assert b._checkpoint(state, b.LAMPLIGHTER, now + timedelta(hours=4, seconds=1)) is None
    assert b._checkpoint(state, b.LAMPLIGHTER, now - timedelta(seconds=59))
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        b._checkpoint(state, b.LAMPLIGHTER, now - timedelta(seconds=61))
