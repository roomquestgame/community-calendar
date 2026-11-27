"""Full-description, schedule, venue and durable pagination regressions."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from roomquest import boston_nightlife_remaining as b


def source(key):
    url, kind, adapter = b.SOURCES[key]
    return dict(source_key=key, feed_url=url, kind=kind, platform_adapter=adapter, timezone=b.ZONE)


def future():
    return (datetime.now(timezone.utc) + timedelta(days=2)).replace(hour=20, minute=0, second=0, microsecond=0)


def product_fixture(sku="2000000000001", title="Pasta Class", body=None, *, variants=False):
    start = future()
    url = f"https://www.eataly.com/p/pasta-{sku}.html"
    event = dict(c_eventId=sku, c_eventInstanceId=sku, c_eventTicketClassId="1001",
                 c_eventStatus="live", c_eventOnlineFlag=False, c_eventStoreId="EBO 1",
                 c_eventStartDate=start.isoformat(), c_eventEndDate=(start + timedelta(hours=1)).isoformat(),
                 c_eventVenueAddress="800 Boylston Street", c_eventVenueCity="Boston",
                 c_eventVenueRegion="MA", c_eventVenuePostalCode="02199")
    table = []
    for e in [event, dict(event, c_eventTicketClassId="1002")] if variants else [event]:
        obj = {}
        table.append(obj)
        for k, v in e.items():
            key_index = len(table)
            table.extend([k, v])
            obj["_" + str(key_index)] = key_index + 1
    body = body if body is not None else "<p>Native full class narrative. " + "Complete publisher sentence. " * 100 + "</p>"
    schema = dict(name=title, sku=sku + "-1001", description=body)
    payload = ('<script>window.__reactRouterContext.streamController.enqueue(' + json.dumps(json.dumps(table)) + ')</script>'
               '<script id="product-schema" type="application/ld+json">' + json.dumps(schema) + '</script>'
               '<h2 class="heading-title-l">Learn with our chef.</h2>')
    return dict(url=url, title=title, sku=sku), payload


def catalog(items, *, next_page=False):
    data = {"@type": "CollectionPage", "mainEntity": {"itemListElement": [
        {"item": dict(item, name=item["title"], **{"@type": "Product"})} for item in items]}}
    return ('<script id="category-schema" type="application/ld+json">' + json.dumps(data) + '</script>'
            '<a href="/c/events-boston">Events</a>'
            + ('<a href="/c/classes-boston?page=2">Next</a>' if next_page else ''))


def test_eataly_uses_all_jsonld_items_despite_only_partial_visible_cards():
    first, _ = product_fixture()
    second, _ = product_fixture("2000000000002", "Second Class")
    payload = catalog([first, second], next_page=True) + '<a href="/p/pasta-2000000000001.html">First card</a>'
    items, pages = b._eataly_listing(payload, b.SOURCES[b.EATALY][0])
    assert [x["sku"] for x in items] == [first["sku"], second["sku"]]
    assert pages == [b.SOURCES[b.EATALY][0], b.SOURCES[b.EATALY][0] + "?page=2"]


def test_eataly_native_utc_and_complete_description_and_ticket_variant():
    item, payload = product_fixture(variants=True)
    native = b._eataly_detail(item, payload, datetime.now(timezone.utc))[0]
    assert b.timestamp(native["start"]) == future()
    assert native["start"].endswith("+00:00")
    assert len(native["body"]) > 2000
    row = b._row(b.EATALY, native)
    assert row["description"] == native["body"]
    assert row["venue_address"] == "800 Boylston Street, Boston, MA 02199"
    assert (row["lat"], row["lng"]) == b.POINTS["eataly"]


def test_event_only_facts_ignore_provider_label_and_change_with_event_details():
    item, product = product_fixture()
    listing = catalog([item])
    def run(src, detail):
        pages = {b.SOURCES[b.EATALY][0]: listing, b.EATALY_EVENTS: catalog([]), item["url"]: detail}
        return b.collect_chunk(src, lambda url, accept: pages[url],
                               now=datetime.now(timezone.utc))["events"][0]
    first = run(source(b.EATALY), product)
    renamed = run({**source(b.EATALY), "publisher_name": "Renamed provider label"}, product)
    changed = run(source(b.EATALY), product.replace(
        "Complete publisher sentence.", "Publisher changed the class details.", 1))
    assert renamed["collector_event_content_v1"] == first["collector_event_content_v1"]
    assert changed["collector_event_content_v1"] != first["collector_event_content_v1"]


def test_original_locations_are_separate_from_reviewed_publication_locations():
    item, payload = product_fixture()
    native = b._eataly_detail(item, payload, datetime.now(timezone.utc))[0]
    row = b._row(b.EATALY, native)
    facts = row["collector_event_content_v1"]["facts"]
    assert row["venue_address"] == "800 Boylston Street, Boston, MA 02199"
    assert facts["venue_address"] == "800 Boylston Street"
    assert facts["venue_city"] == "Boston"


def test_eataly_blank_long_description_is_held_even_with_summary():
    item, payload = product_fixture(body="")
    with pytest.raises(ValueError, match="description_missing"):
        b._eataly_detail(item, payload, datetime.now(timezone.utc))


def test_paged_checkpoint_does_not_emit_partial_results_and_detects_tampering():
    first, one = product_fixture()
    second, two = product_fixture("2000000000002", "Second Class")
    listing = catalog([first, second])
    calls = []
    def fetch(url, accept):
        calls.append(url)
        return {b.SOURCES[b.EATALY][0]: listing, b.EATALY_EVENTS: catalog([]), first["url"]: one, second["url"]: two}[url]
    now = datetime.now(timezone.utc)
    one_result = b.collect_chunk(source(b.EATALY), fetch, now=now, max_details=1)
    assert not one_result["complete"] and not one_result["events"]
    assert one_result["checkpoint"]["pending_cursor"] == 1
    two_result = b.collect_chunk(source(b.EATALY), fetch, checkpoint=one_result["checkpoint"], now=now, max_details=1)
    assert not two_result["complete"] and not two_result["events"]
    final = b.collect_chunk(source(b.EATALY), fetch, checkpoint=two_result["checkpoint"], now=now, max_details=1)
    assert final["complete"] and len(final["events"]) == 2
    assert calls.count(first["url"]) == calls.count(second["url"]) == 1
    bad = deepcopy(one_result["checkpoint"])
    bad["events"][0]["description"] = "Replacement narrative"
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        b.collect_chunk(source(b.EATALY), fetch, checkpoint=bad, now=now)
    assert b._checkpoint(one_result["checkpoint"], b.EATALY, now + timedelta(hours=4, seconds=1)) is None


def test_checkpoint_rejects_tampered_original_facts_and_preserves_legacy_prefix():
    first, one = product_fixture()
    second, two = product_fixture("2000000000002", "Second Class")
    listing = catalog([first, second])
    pages = {b.SOURCES[b.EATALY][0]: listing, b.EATALY_EVENTS: catalog([]),
             first["url"]: one, second["url"]: two}
    fetch = lambda url, accept: pages[url]
    now = datetime.now(timezone.utc)
    partial = b.collect_chunk(source(b.EATALY), fetch, now=now, max_details=1)
    saved = partial["checkpoint"]
    assert "collector_event_content_v1" in saved["events"][0]
    poison = deepcopy(saved)
    poison["events"][0]["collector_event_content_v1"]["facts"]["description"] = "Tampered facts."
    poison["row_hashes"][poison["events"][0]["id"]] = b._hash(poison["events"][0])
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        b.collect_chunk(source(b.EATALY), fetch, checkpoint=poison, now=now)
    legacy = deepcopy(saved)
    for row in legacy["events"]:
        row.pop("collector_event_content_v1")
        legacy["row_hashes"][row["id"]] = b._hash(row)
    final = b.collect_chunk(source(b.EATALY), fetch, checkpoint=legacy, now=now)
    assert final["complete"] and len(final["events"]) == 2
    assert all("collector_event_content_v1" not in row for row in final["events"])


def trillium_event(**changes):
    start = future()
    event = dict(summary="Community Workshop", description="Short excerpt...",
                 longDescription="<p>Complete native workshop description with every detail.</p>",
                 utcStartTime=int(start.timestamp()), utcEndTime=int((start + timedelta(hours=2)).timestamp()),
                 timezoneStart=start.astimezone(b.ZoneInfo(b.ZONE)).replace(tzinfo=None).isoformat(),
                 timezoneEnd=(start + timedelta(hours=2)).astimezone(b.ZoneInfo(b.ZONE)).replace(tzinfo=None).isoformat(),
                 timezone="US/Eastern", venueName="Trillium Canton", location={"description": "100 Royall St. Canton, MA 02021"},
                 onlineEvent=False, isAllDayEvent=False, url="https://trillium.eventcalendarapp.com/workshop?repeatId=r123")
    return dict(event, **changes)


def test_trillium_requires_clock_agreement_and_maps_full_long_description():
    payload = json.dumps(dict(pages={"total": 1}, errors=[], events=[trillium_event()]))
    item = b._trillium_listing(payload, datetime.now(timezone.utc))[0]
    assert item["body"] == "Complete native workshop description with every detail."
    assert item["venue_key"] == "canton"
    bad = trillium_event(timezoneStart="2026-01-01T03:00:00")
    with pytest.raises(ValueError, match="schedule_changed"):
        b._trillium_listing(json.dumps(dict(pages={"total": 1}, errors=[], events=[bad])), datetime.now(timezone.utc))


def night_detail(title, schedule, body):
    return f'''<main><article class="single-content-event"><h1 class="entry-title">{title}</h1>
      <div class="event-location-time-container"><div class="element-text">{schedule}</div></div>
      <div class="event-location-time-container"><div class="element-text">Everett Taproom</div></div>
      <div class="element-wysiwyg">{body}</div></article></main>'''


def test_weekly_rule_is_publisher_declared_bounded_and_has_no_invented_end():
    item = dict(url="https://nightshiftbrewing.com/events/run-club/", title="Run Club",
                schedule="Every Saturday, 11:30AM", location="Everett Taproom")
    current = datetime.now(timezone.utc)
    now = (current + timedelta(days=(7 - current.weekday()) % 7 or 7)).replace(hour=12, minute=0, second=0, microsecond=0)
    body = "<p>All paces are welcome to our Saturday Run Club at 11:30am.</p>"
    items = b._nightshift_detail(item, night_detail(item["title"], item["schedule"], body), now)
    assert len(items) == 4
    assert all(now < b.timestamp(x["start"]) < now + timedelta(days=28) for x in items)
    assert all(b.timestamp(x["start"]).weekday() == 5 and x["end"] is None for x in items)
    assert all(x["published_schedule"] == item["schedule"] for x in items)
    assert len({b._ident(b.NIGHTSHIFT, x) for x in items}) == len(items)
    assert b._row(b.NIGHTSHIFT, items[0])["schedule_provenance"] == "publisher_declared_weekly_schedule"


def test_conflicting_published_nerd_night_end_is_held():
    item = dict(url="https://nightshiftbrewing.com/events/nerd-night/", title="Nerd Night",
                schedule="Every Sunday, 4:00-9:00PM", location="Everett Taproom")
    with pytest.raises(ValueError, match="schedule_conflict"):
        b._nightshift_detail(item, night_detail(item["title"], item["schedule"], "<p>Join us every Sunday from 4–7 PM for Nerd Night.</p>"), datetime.now(timezone.utc))


def test_waverley_excerpt_hydrates_full_detail_and_matching_street():
    day = future().date()
    common = f'''<time class="event-time-localized-start" datetime="{day}">6:00 PM</time>
      <time class="event-time-localized-end" datetime="{day}">9:00 PM</time>'''
    listing = f'''<div class="eventlist"><article class="eventlist-event--upcoming">
      <a class="eventlist-title-link" href="/events/crokinole">Crokinole</a>{common}
      <div class="eventlist-meta-address">Mighty Squirrel Brewing Co.<a href="https://maps.google.com?q=411%20Waverley%20Oaks%20Road%20Waltham%20MA">(map)</a></div>
      <div class="eventlist-excerpt">Short...</div></article></div>'''
    item = b._waverley_listing(listing, datetime.now(timezone.utc))[0]
    assert "body" not in item
    detail = f'''<h1 class="eventitem-title">Crokinole</h1>{common}
      <div class="eventitem-meta-address"><span class="eventitem-meta-address-line--title">Mighty Squirrel Brewing Co.</span>
      <a href="https://maps.google.com?q=411%20Waverley%20Oaks%20Road%20Waltham%20MA">(map)</a></div>
      <div class="eventitem-column-content"><div class="sqs-layout"><p>Full rules and welcome for new players.</p></div></div>'''
    full = b._waverley_detail(item, detail)[0]
    assert full["body"] == "Full rules and welcome for new players."
    row = b._row(b.WAVERLEY, full)
    assert row["venue_address"] == "411 Waverley Oaks Road, Waltham, MA 02452"
    facts = row["collector_event_content_v1"]["facts"]
    assert facts["venue_address"] == "411 Waverley Oaks Road Waltham MA"
    assert facts["venue_name"] == "Mighty Squirrel Brewing Co."


def test_url_and_scope_restrictions_exclude_transaction_and_disallowed_routes():
    assert not b.event_url(b.EATALY, "https://www.eataly.com/cart")
    assert not b.event_url(b.EATALY, "https://www.eataly.com/p/pasta-2000000000001.html?redirect=elsewhere")
    assert not b._eataly_page_url("https://www.eataly.com/c/classes-chicago?page=2")
    assert not b._eataly_page_url("https://www.eataly.com/c/classes-boston?page=1000")
    assert b.photo_url(b.EATALY, "https://www.eataly.com/on/demandware.static/photo.jpg") is None
    assert not b.event_url(b.TRILLIUM, "https://other.eventcalendarapp.com/workshop")
