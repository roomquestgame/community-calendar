"""Occurrence-specific Eataly narratives and durable guarded pagination."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import Mock

import pytest

from roomquest import new_york_food_expansion as ny


def source():
    return dict(source_key=ny.EATALY, feed_url=ny.SOURCES[ny.EATALY][0],
                kind="html", platform_adapter="html", timezone=ny.ZONE)


def product(sku="2000000000001", *, count=1, body=None, store="ENY 1", punctuation=False, ticket_variants=False):
    start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)
    slug = "hands-on%3A-ravioli-%7C-pasta%E2%80%9D" if punctuation else "pasta"
    url = f"https://www.eataly.com/p/{slug}-{sku}.html"
    title = "Hands-on Pasta Workshop"
    table, fields = [], []
    for n in range(count):
        offset = 0 if ticket_variants else n
        instance = str(int(sku) + offset + 10) if count > 1 else sku
        ticket = str(1000001 + (n if ticket_variants else 0))
        place = ny.VENUES[store]
        full = body if body is not None else f"<p>Occurrence {n + 1}. " + "Complete class narrative. " * 100 + "Final allergy information.</p>"
        event = dict(id=instance + "-" + ticket, name=title, longDescription=full,
                     shortDescription="Learn with our chef.",
                     c_url=f"/p/{slug}-{sku}.html?eventInstanceId={instance}&eventTicketClassId={ticket}",
                     c_eventId=instance, c_eventSeriesId=sku if count > 1 else "",
                     c_eventInstanceId=instance, c_eventTicketClassId=ticket,
                     c_eventStatus="live", c_eventOnlineFlag=False, c_eventStoreId=store,
                     c_eventStartDate=(start + timedelta(days=offset)).isoformat(),
                     c_eventEndDate=(start + timedelta(days=offset, hours=2)).isoformat(),
                     c_eventVenueName=place[0], c_eventVenueAddress=place[1].split(",")[0],
                     c_eventVenueCity="New York", c_eventVenueRegion="NY", c_eventVenueCountry="US",
                     c_eventVenuePostalCode=place[1][-5:],
                     c_eventVenueLatitude=str(ny.NATIVE_POINT_VARIANTS.get(store, {}).get(place[1].split(",")[0].casefold(), ny.POINTS[store])[0]),
                     c_eventVenueLongitude=str(ny.NATIVE_POINT_VARIANTS.get(store, {}).get(place[1].split(",")[0].casefold(), ny.POINTS[store])[1]))
        fields.append(event)
        obj = {}
        table.append(obj)
        for k, value in event.items():
            index = len(table)
            table.extend([k, value])
            obj["_" + str(index)] = index + 1
    first = fields[0]
    schema = {"@type": "Product", "sku": first["id"], "name": title,
              "description": first["longDescription"], "url": "https://www.eataly.com" + first["c_url"]}
    payload = ('<script>window.__reactRouterContext.streamController.enqueue(' + json.dumps(json.dumps(table)) + ')</script>'
               '<script id="product-schema" type="application/ld+json">' + json.dumps(schema) + '</script>')
    return dict(url=url, sku=sku, title=title), payload, fields


def catalog(items, next_page=False):
    data = {"@type": "CollectionPage", "mainEntity": {"itemListElement": [
        {"item": {"@type": "Product", "name": item["title"], "sku": item["sku"], "url": item["url"]}}
        for item in items]}}
    return ('<script id="category-schema" type="application/ld+json">' + json.dumps(data) + '</script>'
            '<a href="/c/events-new-york">Events</a>'
            + ('<a href="/c/classes-new-york?page=2#main-content">Next</a>' if next_page else ''))


def test_all_native_series_occurrences_keep_their_full_narrative_and_identity():
    item, payload, native = product(count=3)
    rows, holds = ny._detail(item, payload, datetime.now(timezone.utc))
    assert not holds and len(rows) == 3
    for row, event in zip(rows, native):
        assert row["source_native_event_id"] == event["c_eventInstanceId"]
        assert row["starts_at"] == event["c_eventStartDate"]
        assert row["description"] == "Learn with our chef.\n" + ny._body(event["longDescription"])
        assert row["description"].endswith("Final allergy information.")
        assert len(row["description"]) > 2000
        assert row["venue_address"] == "200 5th Avenue, New York, NY 10010"
        assert (row["lat"], row["lng"]) == ny.POINTS["ENY 1"]
        assert row["event_url"].endswith("eventTicketClassId=1000001")


def test_original_facts_ignore_provider_label_and_exclude_reviewed_venue_enrichment():
    item, payload, native = product(store="ELF 1")
    first = ny._detail(item, payload, datetime.now(timezone.utc))[0][0]
    renamed = {**source(), "publisher_name": "Renamed provider label"}
    assert ny._source(renamed) == ny.EATALY
    again = ny._detail(item, payload, datetime.now(timezone.utc))[0][0]
    facts = first["collector_event_content_v1"]["facts"]
    assert again["collector_event_content_v1"] == first["collector_event_content_v1"]
    assert facts["venue_address"].casefold() in ny.NATIVE_STREETS["ELF 1"]
    assert facts["venue_address"] != first["venue_address"]
    assert (facts["source_latitude"], facts["source_longitude"]) == tuple(
        float(native[0][name]) for name in ("c_eventVenueLatitude", "c_eventVenueLongitude"))
    assert first["event_url"] != facts["event_url"]


def test_publisher_narrative_change_changes_facts_not_occurrence_id():
    item, first_payload, _ = product(body="Original complete class narrative.")
    changed_payload = first_payload.replace(
        "Original complete class narrative.", "Changed complete publisher class narrative.")
    first = ny._detail(item, first_payload, datetime.now(timezone.utc))[0][0]
    changed = ny._detail(item, changed_payload, datetime.now(timezone.utc))[0][0]
    assert changed["id"] == first["id"]
    assert changed["collector_event_content_v1"] != first["collector_event_content_v1"]


def test_native_punctuation_and_catalog_pagination_fragment_are_safe():
    item, payload, _ = product(punctuation=True)
    assert ny.event_url(ny.EATALY, item["url"])
    queue, pages = ny._listing(catalog([item], next_page=True), ny.SOURCES[ny.EATALY][0])
    assert queue == [item]
    assert pages[-1] == ny.SOURCES[ny.EATALY][0] + "?page=2"
    assert len(ny._detail(item, payload, datetime.now(timezone.utc))[0]) == 1
    for bad in (item["url"] + "?admin=1", item["url"].replace("pasta", "%2fadmin"),
                item["url"].replace("www.eataly.com", "evil.invalid"),
                item["url"] + "?eventInstanceId=1000000&eventTicketClassId=1000001&eventInstanceId=1000002"):
        assert not ny.event_url(ny.EATALY, bad)
    assert ny.photo_url(ny.EATALY, "https://www.eataly.com/on/demandware.static/image.jpg") is None


def test_checkpoint_resumes_without_partial_publication_or_duplicate_product_fetches():
    first, one, _ = product()
    second, two, _ = product("2000000000002", store="ELF 1")
    pages = {ny.SOURCES[ny.EATALY][0]: catalog([first], next_page=True),
             ny.SOURCES[ny.EATALY][0] + "?page=2": catalog([second]),
             ny.EVENTS_URL: catalog([first]), first["url"]: one, second["url"]: two}
    fetch = Mock(side_effect=lambda url, accept: pages[url])
    now = datetime.now(timezone.utc)
    state = None
    for _ in range(8):
        result = ny.collect_chunk(source(), fetch, checkpoint=state, now=now, max_details=1)
        state = result["checkpoint"]
        ny._checkpoint(state, now)
        if result["complete"]:
            break
        assert result["events"] == []
    assert result["complete"] and len(result["events"]) == 2
    for item in (first, second):
        assert [call.args[0] for call in fetch.call_args_list].count(item["url"]) == 1
    for field, value in (("description", "Truncated"), ("lat", 0), ("starts_at", "2026-01-01T10:00:00Z")):
        altered = deepcopy(state)
        altered["events"][0][field] = value
        with pytest.raises(ValueError, match="checkpoint_invalid"):
            ny.collect_chunk(source(), fetch, checkpoint=altered, now=now)


def test_checkpoint_rejects_tampered_facts_and_replays_legacy_prefix():
    first, one, _ = product()
    second, two, _ = product("2000000000002", store="ELF 1")
    pages = {ny.SOURCES[ny.EATALY][0]: catalog([first], next_page=True),
             ny.SOURCES[ny.EATALY][0] + "?page=2": catalog([second]),
             ny.EVENTS_URL: catalog([first]), first["url"]: one, second["url"]: two}
    fetch = Mock(side_effect=lambda url, accept: pages[url])
    now = datetime.now(timezone.utc)
    partial = ny.collect_chunk(source(), fetch, now=now, max_details=1)
    while not partial["checkpoint"]["events"]:
        partial = ny.collect_chunk(source(), fetch, checkpoint=partial["checkpoint"], now=now, max_details=1)
    tampered = deepcopy(partial["checkpoint"])
    tampered["events"][0]["collector_event_content_v1"]["facts"]["description"] = "Tampered facts."
    tampered["row_hashes"][tampered["events"][0]["id"]] = ny._hash(tampered["events"][0])
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        ny._checkpoint(tampered, now)
    legacy = deepcopy(partial["checkpoint"])
    for row in legacy["events"]:
        row.pop("collector_event_content_v1")
        legacy["row_hashes"][row["id"]] = ny._hash(row)
    state = legacy
    for _ in range(10):
        result = ny.collect_chunk(source(), fetch, checkpoint=state, now=now, max_details=1)
        state = result["checkpoint"]
        if result["complete"]:
            break
    assert result["complete"]
    assert all("collector_event_content_v1" not in row for row in result["events"])


def test_blank_or_over_limit_full_description_is_held_without_using_intro_as_replacement():
    for body, reason in (("", "description_missing"), ("x" * 12001, "description_limit")):
        item, payload, _ = product(body=body)
        with pytest.raises(ValueError, match=reason):
            ny._detail(item, payload, datetime.now(timezone.utc))


def test_native_venue_conflict_is_held_and_unknown_sources_never_fetch():
    item, payload, _ = product()
    payload = payload.replace("200 5th Avenue", "999 Another Street")
    rows, holds = ny._detail(item, payload, datetime.now(timezone.utc))
    assert not rows and holds[0]["reason"] == "new_york_food_venue_unresolved"
    invalid = source()
    invalid["feed_url"] = "https://www.eataly.com/c/classes-boston"
    fetch = Mock()
    with pytest.raises(ValueError, match="unregistered"):
        ny.collect_chunk(invalid, fetch)
    fetch.assert_not_called()


def test_parent_sku_and_selected_description_cannot_be_rebound():
    item, payload, _ = product()
    bad = dict(item, sku="2000000009999")
    with pytest.raises(ValueError, match="detail_changed"):
        ny._detail(bad, payload, datetime.now(timezone.utc))
    payload = payload.replace('"description": "<p>Occurrence 1.', '"description": "<p>Changed narrative.')
    with pytest.raises(ValueError, match="detail_changed"):
        ny._detail(item, payload, datetime.now(timezone.utc))


def test_ticket_classes_deduplicate_only_when_complete_event_semantics_agree():
    item, payload, _ = product(count=2, ticket_variants=True, body="The complete shared class narrative.")
    rows, holds = ny._detail(item, payload, datetime.now(timezone.utc))
    assert len(rows) == 1 and not holds
    item, payload, _ = product(count=2, ticket_variants=True)
    with pytest.raises(ValueError, match="detail_changed"):
        ny._detail(item, payload, datetime.now(timezone.utc))
