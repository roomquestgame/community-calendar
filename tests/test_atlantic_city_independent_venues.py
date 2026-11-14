from datetime import datetime, timedelta, timezone
from html import escape
import json
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from roomquest import atlantic_city_independent_venues as ac


NOW = datetime(2026, 11, 14, 21, 30, tzinfo=timezone.utc)
VENTNOR_BODY = ("Join us for our second annual Holiday Market at Ventnor Social! Come sip, shop and support "
                "your local Businesses. 🥂🛍️We’ll have fun for the whole family with 1/2 price arcade games, "
                "drink specials, crafts and lots of holiday shopping!")


def source(key):
    return dict(source_key=key, feed_url=ac.SOURCES[key][0], kind="html", platform_adapter="html", timezone=ac.ZONE)


def record(title, start, end, venue, address, city, url, identity, category="", lat=None, lng=None, tz=None, **kwargs):
    return dict(id=str(identity), title=title, starts_at=start, ends_at=end, venue_name=venue,
                venue_address=address, venue_city=city, event_url=url, category=category,
                lat=lat, lng=lng, reason="missing_verified_venue_geo" if lat is None else None)


def times(day="2026-12-02", start="6:00 PM", end="8:00 PM"):
    return (f'<time class="event-time-localized-start" datetime="{day}">{start}</time>'
            f'<time class="event-time-localized-end" datetime="{day}">{end}</time>')


def square_card(key=ac.CARDINAL, title="Wine evening", path="wine-evening", text="Short listing excerpt.", **kwargs):
    base = "/events-at-cardinal/" if key == ac.CARDINAL else "/events/"
    location = '<li class="eventlist-meta-address">Ventnor Social (map)</li>' if key == ac.VENTNOR else ""
    return (f'<article class="eventlist-event eventlist-event--upcoming"><a class="eventlist-title-link" '
            f'href="{base}{path}">{title}</a>{times(**kwargs)}{location}'
            f'<div class="eventlist-excerpt">{escape(text)}</div></article>')


def square_detail(key=ac.CARDINAL, title="Wine evening", path="wine-evening", body="Complete event narrative.", **kwargs):
    url = ac.SOURCES[key][0] + "/" + path
    location = ("" if key == ac.CARDINAL else
                '<meta property="og:street-address" content="6417 Ventnor Avenue">'
                '<meta property="og:locality" content="Ventnor City">'
                '<meta property="og:region" content="New Jersey">'
                '<meta property="og:postal-code" content="08406">'
                f'<meta property="og:description" content="{escape(VENTNOR_BODY)}">')
    return (f'<link rel="canonical" href="{url}">{location}<h1 class="eventitem-title">{title}</h1>'
            f'{times(**kwargs)}<div class="eventitem-column-content"><div class="sqs-layout">{body}</div></div>'
            '<footer>201 S. New York Ave, Atlantic City, NJ 08401</footer>')


def tribe_event(identity=42, body="<p>Every complete event detail.</p>", **overrides):
    value = dict(id=identity, title="A wine tasting", status="publish", timezone="UTC+0",
                 start_date="2026-11-21 18:00:00", end_date="2026-11-21 20:00:00",
                 utc_start_date="2026-11-21 18:00:00", utc_end_date="2026-11-21 20:00:00",
                 url=f"https://renaultwinery.com/event/tasting-{identity}/", description=body,
                 categories=[dict(name="Wine Tasting")],
                 venue=dict(venue="Renault Winery &amp; Resort", address="72 North Bremen Avenue",
                            city="Egg Harbor City, NJ 08215", state="NJ", zip="08215"))
    value.update(overrides)
    return value


def tribe_payload(items, pages=1, total=None):
    return json.dumps(dict(events=items, total_pages=pages, total=len(items) if total is None else total))


class IndependentVenuesTests(unittest.TestCase):
    def test_native_square_body_preserved_instead_of_listing_excerpt(self):
        full = "Complete workshop information. " * 170 + "R&D: 5 < 10. Final dietary instructions."
        url = ac.SOURCES[ac.CARDINAL][0]
        pages = {url: '<div class="eventlist">' + square_card() + '</div>',
                 url + "/wine-evening": square_detail(body="<p>" + escape(full) + "</p>")}
        fetch = Mock(side_effect=lambda url, accept: pages[url])
        with patch.object(ac, "record", side_effect=record):
            rows = ac.collect(source(ac.CARDINAL), fetch, now=NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["description"], full)
        self.assertGreater(len(rows[0]["description"]), 4000)
        self.assertEqual(rows[0]["venue_address"], ac.VENUES[ac.CARDINAL][1])
        self.assertEqual((rows[0]["lat"], rows[0]["lng"]), (39.358251000003, -74.426868000001))
        self.assertEqual(rows[0]["category"], "")
        self.assertEqual(fetch.call_count, 2)

    def test_empty_native_square_body_requires_reviewed_complete_paragraph(self):
        url = ac.SOURCES[ac.VENTNOR][0]
        card = square_card(ac.VENTNOR, path="holiday-market-1", text=VENTNOR_BODY)
        detail = square_detail(ac.VENTNOR, path="holiday-market-1", body="")
        pages = {url: '<div class="eventlist">' + card + '</div>', url + "/holiday-market-1": detail}
        with patch.object(ac, "record", side_effect=record):
            rows = ac.collect(source(ac.VENTNOR), lambda u, a: pages[u], now=NOW)
        self.assertEqual(rows[0]["description"], VENTNOR_BODY)
        self.assertEqual(rows[0]["venue_address"], "6417 Ventnor Avenue, Ventnor City, NJ 08406")
        self.assertEqual(rows[0]["lat"], 39.338136000003)
        pages[url] = pages[url].replace("lots of holiday shopping!", "lots of holiday shopping and more!")
        with self.assertRaisesRegex(ValueError, "full_description_unavailable"):
            ac.collect(source(ac.VENTNOR), lambda u, a: pages[u], now=NOW)

    def test_new_native_ventnor_body_wins_over_previously_reviewed_excerpt(self):
        url = ac.SOURCES[ac.VENTNOR][0]
        pages = {url: '<div class="eventlist">' + square_card(ac.VENTNOR, path="holiday-market-1", text=VENTNOR_BODY) + '</div>',
                 url + "/holiday-market-1": square_detail(ac.VENTNOR, path="holiday-market-1", body="<p>A newly published complete body with more event details.</p>")}
        with patch.object(ac, "record", side_effect=record):
            rows = ac.collect(source(ac.VENTNOR), lambda u, a: pages[u], now=NOW)
        self.assertEqual(rows[0]["description"], "A newly published complete body with more event details.")

    def test_square_blank_oversized_and_conflicting_schedule_fail_without_clipping(self):
        url = ac.SOURCES[ac.CARDINAL][0]
        listing = '<div class="eventlist">' + square_card() + '</div>'
        for detail, error in [(square_detail(body=""), "full_description_unavailable"),
                              (square_detail(body="<p>" + "x" * 12001 + "</p>"), "description_limit"),
                              (square_detail(start="7:00 PM"), "schedule_conflict")]:
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                ac.collect(source(ac.CARDINAL), lambda u, a: listing if u == url else detail, now=NOW)

    def test_closures_private_and_sold_out_do_not_request_details(self):
        cards = "".join(square_card(title=t) for t in ["Closed for holiday", "Private event", "Cooking Class SOLD OUT"])
        fetch = Mock(return_value='<div class="eventlist">' + cards + '</div>')
        self.assertEqual(ac.collect(source(ac.CARDINAL), fetch, now=NOW), [])
        self.assertEqual(fetch.call_count, 1)

    def test_offsite_or_changed_square_venue_cannot_inherit_destination(self):
        from bs4 import BeautifulSoup
        card = BeautifulSoup(square_card(), "html.parser").article
        detail = square_detail().replace("201 S. New York Ave", "999 Relocated Street")
        with self.assertRaisesRegex(ValueError, "location_changed"):
            ac._square_detail(ac.CARDINAL, card, detail)

    def test_full_tribe_narrative_and_reviewed_local_wall_clock(self):
        body = "Complete wine workshop instructions. " * 140 + "Final paragraph: R&D 5 < 10."
        event = tribe_event(body="<p>" + escape(body) + "</p>")
        with patch("roomquest.mapsee_adapter.record", side_effect=record):
            rows = ac.collect(source(ac.RENAULT), Mock(return_value=tribe_payload([event])), now=NOW)
        self.assertEqual(rows[0]["description"], body)
        self.assertEqual(rows[0]["starts_at"], "2026-11-21T23:00:00+00:00")
        self.assertEqual(rows[0]["ends_at"], "2026-11-22T01:00:00+00:00")
        self.assertEqual(rows[0]["venue_address"], "72 North Bremen Avenue, Egg Harbor City, NJ 08215")
        self.assertEqual(rows[0]["category"], "Wine Tasting")
        self.assertEqual(rows[0]["lat"], 39.546288000003)

    def test_tribe_end_equal_start_is_unknown_end(self):
        event = tribe_event(end_date="2026-11-21 18:00:00", utc_end_date="2026-11-21 18:00:00")
        with patch("roomquest.mapsee_adapter.record", side_effect=record):
            rows = ac.collect(source(ac.RENAULT), Mock(return_value=tribe_payload([event])), now=NOW)
        self.assertIsNone(rows[0]["ends_at"])

    def test_tribe_mismatched_utc_and_local_clock_is_rejected(self):
        event = tribe_event(utc_start_date="2026-11-21 23:00:00")
        with self.assertRaisesRegex(ValueError, "schedule_conflict"):
            ac.collect(source(ac.RENAULT), Mock(return_value=tribe_payload([event])), now=NOW)
        event["timezone"] = "America/New_York"
        event["utc_end_date"] = "2026-11-22 01:00:00"
        with patch("roomquest.mapsee_adapter.record", side_effect=record):
            rows = ac.collect(source(ac.RENAULT), Mock(return_value=tribe_payload([event])), now=NOW)
        self.assertEqual(rows[0]["starts_at"], "2026-11-21T23:00:00+00:00")

    def test_known_implausible_music_clock_is_held_without_guessing_pm(self):
        event = tribe_event(identity=16527, start_date="2026-12-05 01:00:00", utc_start_date="2026-12-05 01:00:00",
                            end_date="2026-12-05 16:00:00", utc_end_date="2026-12-05 16:00:00")
        with self.assertLogs(ac.log, level="WARNING") as logs:
            self.assertEqual(ac.collect(source(ac.RENAULT), Mock(return_value=tribe_payload([event])), now=NOW), [])
        self.assertIn("15_hour_music_schedule", logs.output[0])

    def test_tribe_blank_oversized_descriptions_and_wrong_host_are_rejected(self):
        for event, error in [(tribe_event(body=""), "description_missing"),
                             (tribe_event(body="x" * 12001), "description_limit"),
                             (tribe_event(body={"text": "not native content"}), "invalid_wordpress_description"),
                             (tribe_event(url="https://other.example/event/fake/"), "event_identity")]:
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                ac.collect(source(ac.RENAULT), Mock(return_value=tribe_payload([event])), now=NOW)

    def test_country_club_footer_address_and_nonpublic_calendar_entries(self):
        event = tribe_event(url="https://accountryclub.com/event/thanksgiving-dinner-buffet-3/", venue=[])
        closed = tribe_event(identity=43, title="Taproom is Closed", body="", venue=[])
        with patch("roomquest.mapsee_adapter.record", side_effect=record):
            rows = ac.collect(source(ac.COUNTRY_CLUB), Mock(return_value=tribe_payload([event, closed])), now=NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["venue_address"], "1 Leo Fraser Drive, Northfield, NJ 08225")
        self.assertIn("(approximate map location)", rows[0]["venue_name"])
        self.assertEqual(rows[0]["location_provenance"], "reviewed_osm_clubhouse_polygon_centroid")

    def test_tribe_unknown_or_relocated_venue_does_not_inherit_street(self):
        event = tribe_event()
        event["venue"]["address"] = "999 Relocated Street"
        with self.assertLogs(ac.log, level="WARNING"):
            self.assertEqual(ac.collect(source(ac.RENAULT), Mock(return_value=tribe_payload([event])), now=NOW), [])

    def test_pagination_must_complete_and_duplicate_pages_are_rejected(self):
        first, second = tribe_event(), tribe_event(identity=43)
        fetch = Mock(side_effect=[tribe_payload([first], pages=2, total=2), tribe_payload([second], pages=2, total=2)])
        with patch("roomquest.mapsee_adapter.record", side_effect=record):
            rows = ac.collect(source(ac.RENAULT), fetch, now=NOW)
        self.assertEqual(len(rows), 2)
        self.assertIn("page=2", fetch.call_args_list[1].args[0])
        with self.assertRaisesRegex(ValueError, "incomplete_snapshot"):
            ac.collect(source(ac.RENAULT), Mock(return_value=tribe_payload([first], total=2)), now=NOW)
        with self.assertRaisesRegex(ValueError, "duplicate_occurrence"):
            ac.collect(source(ac.RENAULT), Mock(return_value=tribe_payload([first], pages=2, total=2)), now=NOW)
        fetch = Mock(side_effect=[tribe_payload([first], pages=2, total=2), tribe_payload([second], pages=2, total=3)])
        with self.assertRaisesRegex(ValueError, "snapshot_changed"):
            ac.collect(source(ac.RENAULT), fetch, now=NOW)

    def test_exact_point_identity_and_source_registration(self):
        for key in ac.SOURCES:
            venue, street, _ = ac.VENUES[key]
            self.assertIsNotNone(ac.reviewed_venue_location(key, venue, street))
            self.assertIsNone(ac.reviewed_venue_location(key, venue, "999 Different Street"))
            self.assertIsNone(ac.reviewed_venue_location(key, "Different venue", street))
            with patch.dict(ac.VENUES, {key: (venue, "999 Different Street", "Atlantic City")}):
                self.assertIsNone(ac.reviewed_venue_location(key, *ac.VENUES[key][:2]))
            with patch.dict(ac.VENUES, {key: ("Different venue", street, "Atlantic City")}):
                self.assertIsNone(ac.reviewed_venue_location(key, *ac.VENUES[key][:2]))
        self.assertIsNone(ac.reviewed_venue_location("unknown", *ac.VENUES[ac.CARDINAL][:2]))
        changed = source(ac.CARDINAL)
        changed["feed_url"] = "https://example.org/"
        fetch = Mock()
        with self.assertRaisesRegex(ValueError, "unregistered"):
            ac.collect(changed, fetch, now=NOW)
        fetch.assert_not_called()

    def test_window_and_event_url_constraints(self):
        self.assertFalse(ac.event_url(ac.CARDINAL, "https://www.cardinal-ac.com/events-at-cardinal/wine?format=json"))
        self.assertFalse(ac.event_url(ac.VENTNOR, "https://www.cardinal-ac.com/events-at-cardinal/wine"))
        self.assertTrue(ac.event_url(ac.RENAULT, "https://renaultwinery.com/event/stories-with-santa-5/2026-12-03/"))
        event = tribe_event(start_date="2027-03-21 18:00:00", utc_start_date="2027-03-21 18:00:00",
                            end_date="2027-03-21 20:00:00", utc_end_date="2027-03-21 20:00:00")
        self.assertEqual(ac.collect(source(ac.RENAULT), Mock(return_value=tribe_payload([event])), now=NOW), [])

    def test_native_query_uses_venue_day_across_utc_midnight(self):
        fetch = Mock(return_value=tribe_payload([]))
        ac.collect(source(ac.RENAULT), fetch,
                   now=datetime(2026, 11, 15, 2, tzinfo=timezone.utc))
        self.assertIn("start_date=2026-11-14", fetch.call_args.args[0])

    def test_actual_shared_parser_ongoing_row_remains_until_published_end(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        start = (now - timedelta(minutes=30)).astimezone(ZoneInfo(ac.ZONE)).strftime("%Y-%m-%d %H:%M:%S")
        end = (now + timedelta(minutes=30)).astimezone(ZoneInfo(ac.ZONE)).strftime("%Y-%m-%d %H:%M:%S")
        event = tribe_event(start_date=start, utc_start_date=start, end_date=end, utc_end_date=end)
        with patch.object(ac, "record", wraps=ac.record) as normalized:
            rows = ac.collect(source(ac.RENAULT), Mock(return_value=tribe_payload([event])), now=now)
        self.assertEqual(len(rows), 1)
        self.assertEqual(ac.timestamp(rows[0]["ends_at"]), now + timedelta(minutes=30))
        self.assertEqual(rows[0]["description"], "Every complete event detail.")
        self.assertEqual(rows[0]["venue_address"], ac.VENUES[ac.RENAULT][1])
        self.assertTrue(normalized.call_args.kwargs["retain_until_end"])


if __name__ == "__main__":
    unittest.main()
