from copy import deepcopy
from datetime import datetime, timezone
import html
import json
import unittest
from unittest.mock import Mock, patch

from roomquest import new_york_nightlife as ny


NOW = datetime(2026, 11, 14, 20, tzinfo=timezone.utc)


def source(key):
    return dict(source_key=key, feed_url=ny.SOURCES[key][0], kind="html", platform_adapter="html", timezone=ny.ZONE)


def record(title, start, end, venue, address, city, url, identity, **kwargs):
    return dict(id=identity, title=title, starts_at=start, ends_at=end, venue_name=venue,
                venue_address=address, venue_city=city, event_url=url,
                lat=kwargs.get("lat"), lng=kwargs.get("lng"))


def square_card(path="/events/game-jam", title="Game Jam", body="Complete publisher narrative.",
                excerpt=False, location="1186 Broadway Brooklyn, NY, 11221 United States", overnight=False):
    if overnight:
        clocks = ('<time class="event-time-12hr" datetime="2026-11-18">8:00 PM</time>'
                  '<time class="event-time-24hr" datetime="2026-11-18">20:00</time>'
                  '<time class="event-time-12hr" datetime="2026-11-19">12:30 AM</time>'
                  '<time class="event-time-24hr" datetime="2026-11-19">00:30</time>')
    else:
        clocks = ('<time class="event-time-12hr-start" datetime="2026-11-18">7:00 PM</time>'
                  '<time class="event-time-12hr-end" datetime="2026-11-18">10:00 PM</time>'
                  '<time class="event-time-12hr-end" datetime="2026-11-18">22:00</time>')
    place = (f'<li class="eventlist-meta-address">Wonderville <a href="https://maps.google.com?q={html.escape(location)}">(map)</a></li>' if location is not None else "")
    content = (f'<div class="eventlist-excerpt">{body}</div>' if excerpt else
               f'<div class="eventlist-description"><div class="sqs-layout"><p>{body}</p></div></div>')
    return f'<article class="eventlist-event--upcoming"><a class="eventlist-title-link" href="{path}">{title}</a>{clocks}{place}{content}</article>'


def listing(*cards):
    return '<div class="eventlist">' + "".join(cards) + '</div>'


def square_detail(url, title, body, venue="Wonderville", address="1186 Broadway Brooklyn, NY, 11221 United States"):
    return (f'<link rel="canonical" href="{url}"><h1 class="eventitem-title">{title}</h1>'
            '<time class="event-time-12hr-start" datetime="2026-11-18">7:00 PM</time>'
            '<time class="event-time-12hr-end" datetime="2026-11-18">10:00 PM</time>'
            f'<li class="eventitem-meta-address">{venue} <a href="https://maps.google.com?q={address}">(map)</a></li>'
            f'<div class="eventitem-column-content"><div class="sqs-layout"><p>{body}</p></div></div>')


def product_page(handle="mini-painting", body="Complete class details.", variants=None, **overrides):
    product = dict(id=12, handle=handle, title="Mini Painting", type="EVENTS", vendor="Event",
                   description=f"<p>{body}</p>", variants=variants or [
                       dict(id=101, title="MON 11/16/2026 @ 7p-10p", available=True),
                       dict(id=102, title="MON 11/23/2026 @ 7p-10p", available=True),
                       dict(id=103, title="Monthly NOV & DEC Mondays @ 7p-10p (9 Sessions)", available=True),
                       dict(id=104, title="MON 11/30/2026 @ 7p-10p", available=False)])
    product.update(overrides)
    return (f'<link rel="canonical" href="https://twentysidedstore.com/products/{handle}">'
            f'<script type="application/json" data-section-type="static-product">{json.dumps({"product": product})}</script>'
            f'<div class="product-description"><p>{body}</p></div><footer>280 Grand Street Brooklyn, NY 11211</footer>')


def kills_page(events):
    for e in events:
        e.update({"@type": "Event", "location": {"address": {
            "streetAddress": "814 Richmond Terrace", "addressLocality": "Staten Island",
            "addressRegion": "NY", "postalCode": "10301"}}})
    return f'<script type="application/ld+json">{json.dumps(events)}</script>' + ''.join(f'<p>{e["description"]}</p>' for e in events)


class NewYorkNightlifeTests(unittest.TestCase):
    def test_complete_native_body_keeps_more_than_two_thousand_chars_without_detail_fetch(self):
        full = "Every participant, accessibility and equipment detail. " * 65 + "Last paragraph."
        fetch = Mock(return_value=listing(square_card(body=full), square_card(title="Closed for private event")))
        with patch.object(ny, "record", side_effect=record):
            result = ny.collect_chunk(source(ny.WONDER), fetch, now=NOW)
        self.assertTrue(result["complete"])
        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(result["events"][0]["description"], full)
        self.assertGreater(len(full), 2000)
        self.assertEqual(result["events"][0]["venue_address"], "1186 Broadway, Brooklyn, NY 11221")
        fetch.assert_called_once_with(ny.SOURCES[ny.WONDER][0], "text/html")

    def test_overnight_native_clocks_preserve_next_day_and_duplicate_24_hour_clock(self):
        queue = ny._manifest(ny.WONDER, listing(square_card(overnight=True)), NOW)
        self.assertEqual(queue[0]["start"], "2026-11-18T20:00:00-05:00")
        self.assertEqual(queue[0]["end"], "2026-11-19T00:30:00-05:00")
        daytime = ny._manifest(ny.WONDER, listing(square_card()), NOW)[0]
        self.assertEqual(daytime["end"], "2026-11-18T22:00:00-05:00")

    def test_listing_excerpt_requires_full_detail_and_chunks_publish_only_complete_snapshot(self):
        first, second = "/events/first", "/events/second"
        full = "Complete native details. " * 140
        pages = {
            ny.SOURCES[ny.WONDER][0]: listing(square_card(first, "First", "Short...", excerpt=True), square_card(second, "Second", "Short...", excerpt=True)),
            "https://www.wonderville.nyc" + first: square_detail("https://www.wonderville.nyc" + first, "First", full),
            "https://www.wonderville.nyc" + second: square_detail("https://www.wonderville.nyc" + second, "Second", full),
        }
        fetch = Mock(side_effect=lambda url, accept: pages[url])
        with patch.object(ny, "record", side_effect=record):
            one = ny.collect_chunk(source(ny.WONDER), fetch, now=NOW, max_details=1)
            self.assertFalse(one["complete"])
            self.assertEqual(one["events"], [])
            two = ny.collect_chunk(source(ny.WONDER), fetch, now=NOW, max_details=1, checkpoint=one["checkpoint"])
        self.assertTrue(two["complete"])
        self.assertEqual(len(two["events"]), 2)
        self.assertTrue(all(row["description"] == full.strip() for row in two["events"]))
        self.assertEqual(one["checkpoint"]["cursor"], 1)
        self.assertFalse(any("format=" in call.args[0] for call in fetch.call_args_list))

    def test_blank_and_oversize_events_are_held_without_placeholder_or_truncation(self):
        cards = [square_card("/events/blank", "Blank", ""), square_card("/events/large", "Large", "x" * 12001), square_card("/events/valid", "Valid")]
        with patch.object(ny, "record", side_effect=record):
            result = ny.collect_chunk(source(ny.WONDER), Mock(return_value=listing(*cards)), now=NOW)
        self.assertEqual([r["title"] for r in result["events"]], ["Valid"])
        self.assertEqual({d["reason"] for d in result["checkpoint"]["diagnostics"]}, {
            "new_york_nightlife_description_missing", "new_york_nightlife_description_limit"})

    def test_explicit_offsite_street_is_not_replaced_with_venue_default_or_map_point(self):
        page = listing(square_card(location="22 Fictional Avenue Brooklyn, NY, 11221 United States"))
        with patch.object(ny, "record", side_effect=record):
            result = ny.collect_chunk(source(ny.WONDER), Mock(return_value=page), now=NOW)
        row = result["events"][0]
        self.assertEqual(row["venue_address"], "22 Fictional Avenue, Brooklyn, NY 11221")
        self.assertIsNone(row["lat"])
        self.assertIsNone(row["lng"])
        self.assertIsNone(ny.reviewed_venue_location(ny.WONDER, "Wonderville", row["venue_address"]))

    def test_unresolved_new_location_is_held(self):
        result = ny.collect_chunk(source(ny.WONDER), Mock(return_value=listing(square_card(location="A different venue in Queens"))), now=NOW)
        self.assertEqual(result["events"], [])
        self.assertEqual(result["checkpoint"]["diagnostics"][0]["reason"], "new_york_nightlife_venue_unresolved")

    def test_exact_numeric_street_point_survives_shared_legacy_address_recognizer(self):
        def shared_record(*args, **kwargs):
            row = record(*args, **kwargs)
            row.update(lat=None, lng=None, reason="missing_verified_venue_geo")
            return row
        with patch.object(ny, "record", side_effect=shared_record):
            row = ny._row(ny.FIFTH, dict(url=ny.SOURCES[ny.FIFTH][0] + "/tacos",
                title="Tacos", start="2026-11-17T17:00:00-05:00", end="2026-11-17T20:00:00-05:00"),
                "Complete food popup details.")
        self.assertEqual((row["lat"], row["lng"]), ny.POINTS[ny.FIFTH])
        self.assertIsNone(row["reason"])
        self.assertIsNone(ny.reviewed_venue_location(ny.FIFTH, "Unrelated venue", ny.VENUES[ny.FIFTH][1]))

    def test_month_list_discovers_full_details_and_checks_printed_weekday(self):
        page = ('<div class="events-collection"><ul><li><h1><a href="/fifth-hammer-calendar/tacos">Taco Night</a></h1>'
                '<div>Tuesday, November 17, 2026, 5:00 PM – 11:00 PM</div>'
                '<div><a href="http://maps.google.com?q=10-28 46th Ave Long Island City United States">map</a></div></li></ul></div>')
        queue = ny._manifest(ny.FIFTH, page, NOW)
        self.assertEqual(len(queue), 1)
        self.assertNotIn("body", queue[0])
        self.assertEqual(queue[0]["venue"][1], "10-28 46th Avenue, Long Island City, NY 11101")
        with self.assertRaisesRegex(ValueError, "schedule_conflict"):
            ny._manifest(ny.FIFTH, page.replace("Tuesday", "Thursday"), NOW)

    def test_shopify_dated_variants_preserve_full_body_and_skip_package_or_sold_out(self):
        full = "Painting instruction with all included materials. " * 70
        item = dict(url="https://twentysidedstore.com/products/mini-painting")
        with patch.object(ny, "record", side_effect=record):
            rows = ny._product_detail(item, product_page(body=full), NOW)
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["starts_at"] for row in rows}, {"2026-11-16T19:00:00-05:00", "2026-11-23T19:00:00-05:00"})
        self.assertTrue(all(row["description"] == full.strip() for row in rows))
        self.assertEqual(rows[0]["venue_address"], "280 Grand Street, Brooklyn, NY 11211")
        self.assertNotEqual(rows[0]["id"], rows[1]["id"])

    def test_shopify_undated_recurring_label_does_not_generate_guessed_occurrences(self):
        item = dict(url="https://twentysidedstore.com/products/mini-painting")
        payload = product_page(variants=[dict(id=1, title="Every Monday @ 7p-10p", available=True)])
        self.assertEqual(ny._product_detail(item, payload, NOW), [])
        with self.assertRaisesRegex(ValueError, "product_changed"):
            ny._product_detail(item, product_page(vendor="Book", type="Board Game"), NOW)
        with self.assertRaisesRegex(ValueError, "product_changed"):
            ny._product_detail(item, product_page(description={"text": "Not a native description string."}), NOW)

    def test_shopify_full_description_must_match_visible_product_body(self):
        payload = product_page().replace('<div class="product-description"><p>Complete class details.</p>', '<div class="product-description"><p>A different class.</p>')
        with self.assertRaisesRegex(ValueError, "detail_changed"):
            ny._product_detail(dict(url="https://twentysidedstore.com/products/mini-painting"), payload, NOW)

    def test_same_time_different_brewery_events_keep_distinct_identity_and_unknown_end(self):
        page = kills_page([
            dict(name="Release One", startDate="2026-11-30T12:00:00-05:00", description="Our first new release."),
            dict(name="Release Two", startDate="2026-11-30T12:00:00-05:00", description="Our second new release."),
        ])
        with patch.object(ny, "record", side_effect=record):
            result = ny.collect_chunk(source(ny.KILLS), Mock(return_value=page), now=NOW)
        self.assertEqual(len(result["events"]), 2)
        self.assertEqual(len({r["id"] for r in result["events"]}), 2)
        self.assertTrue(all(r["ends_at"] is None for r in result["events"]))
        self.assertEqual(result["events"][0]["lat"], 40.644642)

    def test_sake_uses_complete_class_detail_instead_of_short_jsonld_summary(self):
        url = "https://www.sakestudiescenter.com/classes/sake-and-cheese-pairing"
        full = "Cheeses, sake varieties, the tour and cancellation terms. " * 65
        item = dict(url=url, occurrences=[dict(url=url, title="Sake & Cheese", start="2026-11-15T15:00:00-05:00", end="2026-11-15T16:30:00-05:00")])
        page = f'<link rel="canonical" href="{url}.html"><div class="detail-body"><p>{full}</p></div><footer>34 34th Street, Brooklyn NY 11232</footer>'
        with patch.object(ny, "record", side_effect=record):
            rows = ny._sake_detail(item, page)
        self.assertEqual(rows[0]["description"], full.strip())
        self.assertEqual(rows[0]["venue_address"], "34 34th Street Industry City Building 6, Brooklyn, NY 11232")

    def test_changed_manifest_resets_partial_snapshot(self):
        first = listing(square_card("/events/first", "First", "Short", excerpt=True), square_card("/events/second", "Second", "Short", excerpt=True))
        pages = {ny.SOURCES[ny.WONDER][0]: first,
                 "https://www.wonderville.nyc/events/first": square_detail("https://www.wonderville.nyc/events/first", "First", "Full first."),
                 "https://www.wonderville.nyc/events/second": square_detail("https://www.wonderville.nyc/events/second", "Second", "Full second.")}
        fetch = Mock(side_effect=lambda url, accept: pages[url])
        with patch.object(ny, "record", side_effect=record):
            one = ny.collect_chunk(source(ny.WONDER), fetch, now=NOW, max_details=1)
            pages[ny.SOURCES[ny.WONDER][0]] = listing(square_card("/events/replacement", "Replacement", "Full replacement."))
            two = ny.collect_chunk(source(ny.WONDER), fetch, now=NOW, checkpoint=one["checkpoint"])
        self.assertEqual([row["title"] for row in two["events"]], ["Replacement"])

    def test_checkpoint_and_source_url_are_bound_to_registered_venue(self):
        with patch.object(ny, "record", side_effect=record):
            result = ny.collect_chunk(source(ny.WONDER), Mock(return_value=listing(square_card())), now=NOW)
        invalid = deepcopy(result["checkpoint"])
        invalid["queue"][0]["url"] = "https://example.com/events/other"
        with self.assertRaisesRegex(ValueError, "checkpoint_invalid"):
            ny.collect_chunk(source(ny.WONDER), Mock(), now=NOW, checkpoint=invalid)
        with self.assertRaisesRegex(ValueError, "unregistered"):
            ny.collect({**source(ny.WONDER), "feed_url": ny.SOURCES[ny.WONDER][0] + "?format=json"}, Mock(), now=NOW)
        self.assertFalse(ny.event_url(ny.WONDER, "https://www.wonderville.nyc/events/foo?format=json"))
        self.assertFalse(ny.event_url(ny.WONDER, "https://www.wonderville.nyc.evil.test/events/foo"))

    def test_checkpoint_rejects_changed_occurrence_time_address_geo_or_diagnostics(self):
        with patch.object(ny, "record", side_effect=record):
            result = ny.collect_chunk(source(ny.WONDER), Mock(return_value=listing(square_card())), now=NOW)
        for field, value in [("starts_at", "2026-11-19T19:00:00-05:00"),
                             ("venue_address", "22 Fictional Avenue, Brooklyn, NY 11221"),
                             ("lat", 42.0), ("description", "Changed cached prose.")]:
            with self.subTest(field=field):
                invalid = deepcopy(result["checkpoint"])
                invalid["events"][0][field] = value
                with self.assertRaisesRegex(ValueError, "checkpoint_invalid"):
                    ny.collect_chunk(source(ny.WONDER), Mock(), now=NOW, checkpoint=invalid)
        invalid = deepcopy(result["checkpoint"])
        invalid["events"] = []
        with self.assertRaisesRegex(ValueError, "checkpoint_invalid"):
            ny.collect_chunk(source(ny.WONDER), Mock(), now=NOW, checkpoint=invalid)


if __name__ == "__main__":
    unittest.main()
