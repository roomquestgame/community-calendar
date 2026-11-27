from copy import deepcopy
from datetime import datetime, timezone
import html
import unittest
from unittest.mock import Mock, patch

from roomquest import new_york_local_expansion as ny


NOW = datetime(2026, 11, 15, 1, 10, tzinfo=timezone.utc)


def source(key):
    return dict(source_key=key, feed_url=ny.SOURCES[key][0], kind="html", platform_adapter="html", timezone=ny.ZONE)


def record(title, start, end, venue, address, city, url, identity, **kwargs):
    return dict(id=identity, title=title, starts_at=start, ends_at=end, venue_name=venue,
                venue_address=address, venue_city=city, event_url=url,
                lat=kwargs.get("lat"), lng=kwargs.get("lng"))


def square_card(path="/events/music", title="Music", body="Full musician biography.", *, strong=False, excerpt=False, location=None):
    times = ('<time class="event-time-localized-start" datetime="2026-11-20">2:00 PM</time>'
             '<time class="event-time-localized-end" datetime="2026-11-20">8:00 PM</time>')
    address = ""
    if strong or location:
        street = location or "185 Van Dyke Street Brooklyn, NY, 11231 United States"
        address = f'<li class="eventlist-meta-address">Strong Rope Brewery <a href="http://maps.google.com?q={html.escape(street)}">(map)</a></li>'
    prose = (f'<div class="eventlist-excerpt">{body}</div>' if excerpt else
             f'<div class="eventlist-description"><div class="sqs-layout">{body}</div></div>')
    return f'<article class="eventlist-event--upcoming"><a class="eventlist-title-link" href="{path}">{title}</a>{times}{address}{prose}</article>'


def listing(*cards):
    return '<div class="eventlist">' + "".join(cards) + '</div><footer>627 5th Avenue, Brooklyn, NY 11215</footer>'


def strong_detail(path, title="Food Pop-Up", body="Full popup description, menu and availability until sold out.", street="185 Van Dyke Street"):
    return (f'<link rel="canonical" href="https://www.strongropebrewery.com{path}">'
            f'<h1 class="eventitem-title">{title}</h1>'
            '<time class="event-time-localized-start" datetime="2026-11-20">2:00 PM</time>'
            '<time class="event-time-localized-end" datetime="2026-11-20">8:00 PM</time>'
            '<li class="eventitem-meta-address"><span class="eventitem-meta-address-line--title">Strong Rope Brewery</span>'
            f'<span>{street}</span><span>Brooklyn, NY, 11231</span>'
            f'<a href="http://maps.google.com?q={street} Brooklyn, NY, 11231 United States">(map)</a></li>'
            f'<div class="eventitem-column-content"><div class="sqs-layout"><p>{body}</p></div></div>')


def fad_home():
    return ''.join(f'<a href="{url}">Holiday market</a>' for url in ny.FAD_SERIES)


def fad_page(url, body="Complete market details with accessibility and admission information."):
    spec = ny.FAD_SERIES[url]
    return (f'<link rel="canonical" href="{url}"><div class="sqs-layout" data-type="page">'
            f'<div class="sqs-html-content"><h1>{spec["heading"]}</h1></div>'
            f'<div class="sqs-html-content"><h2>{spec["schedule"]}</h2></div>'
            f'<div class="sqs-html-content"><h3>{spec["address"]}</h3></div>'
            f'<div class="sqs-html-content"><p>{body}</p><p>Pets are welcome!</p></div></div>'
            '<footer>Navigation and newsletter signup.</footer>')


class NewYorkLocalExpansionTests(unittest.TestCase):
    def test_original_facts_ignore_provider_label_and_reviewed_points(self):
        body = "Complete musician biography and public program."
        page = listing(square_card(body=body))
        renamed = {**source(ny.FREDDYS), "publisher_name": "Renamed provider label"}
        with patch.object(ny, "record", side_effect=record):
            first = ny.collect_chunk(source(ny.FREDDYS), Mock(return_value=page), now=NOW)["events"][0]
            again = ny.collect_chunk(renamed, Mock(return_value=page), now=NOW)["events"][0]
        facts = first["collector_event_content_v1"]["facts"]
        self.assertEqual(again["collector_event_content_v1"], first["collector_event_content_v1"])
        self.assertEqual(facts["venue_name"], ny.VENUES[ny.FREDDYS][0])
        self.assertEqual(facts["venue_address"], ny.VENUES[ny.FREDDYS][1])
        self.assertNotIn("source_latitude", facts)
        self.assertNotIn("source_longitude", facts)
        self.assertEqual((first["lat"], first["lng"]), ny.POINTS[ny.FREDDYS])

    def test_publisher_narrative_change_changes_fingerprint_input_not_identity(self):
        with patch.object(ny, "record", side_effect=record):
            first = ny.collect_chunk(source(ny.FREDDYS), Mock(return_value=listing(square_card(body="Original details."))), now=NOW)["events"][0]
            changed = ny.collect_chunk(source(ny.FREDDYS), Mock(return_value=listing(square_card(body="Changed publisher details."))), now=NOW)["events"][0]
        self.assertEqual(changed["id"], first["id"])
        self.assertNotEqual(changed["collector_event_content_v1"], first["collector_event_content_v1"])

    def test_full_body_survives_shared_two_thousand_character_default(self):
        body = "Musician biography, access details and full performance program. " * 60 + "Final publisher paragraph."
        fetch = Mock(return_value=listing(square_card(body=body)))
        with patch.object(ny, "record", side_effect=record):
            result = ny.collect_chunk(source(ny.FREDDYS), fetch, now=NOW)
        self.assertTrue(result["complete"])
        self.assertEqual(result["events"][0]["description"], body)
        self.assertGreater(len(body), 2000)
        self.assertEqual((result["events"][0]["lat"], result["events"][0]["lng"]), ny.POINTS[ny.FREDDYS])
        fetch.assert_called_once_with(ny.SOURCES[ny.FREDDYS][0], "text/html")

    def test_blank_link_only_and_oversized_publisher_bodies_stay_held(self):
        page = listing(square_card("/events/blank", body=""),
                       square_card("/events/links", body="https://instagram.com/band linktr.ee/band"),
                       square_card("/events/large", body="x" * 12001),
                       square_card("/events/ok", body="Complete concert program."),
                       square_card("/events/closed", title="Closed for private party"))
        with patch.object(ny, "record", side_effect=record):
            result = ny.collect_chunk(source(ny.FREDDYS), Mock(return_value=page), now=NOW)
        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(len(result["checkpoint"]["diagnostics"]), 3)
        self.assertEqual(result["checkpoint"]["manifest_count"], 4)
        self.assertEqual({d["reason"] for d in result["checkpoint"]["diagnostics"]},
                         {"new_york_local_description_missing", "new_york_local_description_limit"})

    def test_excerpts_require_full_details_and_resume_exposes_only_complete_snapshot(self):
        paths = ["/events-calendar/first", "/events-calendar/second"]
        pages = {ny.SOURCES[ny.STRONG][0]: listing(*(square_card(p, "Food Pop-Up", "Short excerpt.", strong=True, excerpt=True) for p in paths))}
        pages.update({"https://www.strongropebrewery.com" + p: strong_detail(p) for p in paths})
        fetch = Mock(side_effect=lambda url, accept: pages[url])
        with patch.object(ny, "record", side_effect=record):
            first = ny.collect_chunk(source(ny.STRONG), fetch, now=NOW, max_details=1)
            self.assertFalse(first["complete"])
            self.assertEqual(first["events"], [])
            second = ny.collect_chunk(source(ny.STRONG), fetch, now=NOW, max_details=1, checkpoint=first["checkpoint"])
        self.assertTrue(second["complete"])
        self.assertEqual(len(second["events"]), 2)
        self.assertTrue(all("availability until sold out" in row["description"] for row in second["events"]))
        self.assertFalse(any("format=" in call.args[0] for call in fetch.call_args_list))
        ny._validate_checkpoint(second["checkpoint"], ny.STRONG, NOW)

    def test_new_offsite_street_is_held_without_borrowing_reviewed_point(self):
        page = listing(square_card("/events-calendar/offsite", strong=True, location="999 Other Avenue Brooklyn, NY, 11231 United States"))
        result = ny.collect_chunk(source(ny.STRONG), Mock(return_value=page), now=NOW)
        self.assertEqual(result["events"], [])
        self.assertEqual(result["checkpoint"]["diagnostics"][0]["reason"], "new_york_local_venue_unresolved")
        self.assertIsNone(ny.reviewed_venue_location(ny.STRONG, "Different Venue", ny.VENUES[ny.STRONG][1]))

    def test_fad_expands_only_twenty_seven_reviewed_2026_sessions(self):
        pages = {ny.SOURCES[ny.FAD][0]: fad_home(), **{url: fad_page(url) for url in ny.FAD_SERIES}}
        with patch.object(ny, "record", side_effect=record):
            first = ny.collect_chunk(source(ny.FAD), lambda url, accept: pages[url], now=NOW, max_details=1)
            self.assertEqual(first["events"], [])
            result = ny.collect_chunk(source(ny.FAD), lambda url, accept: pages[url], now=NOW, checkpoint=first["checkpoint"])
        self.assertEqual(len(result["events"]), 27)
        self.assertEqual(len({row["id"] for row in result["events"]}), 27)
        self.assertTrue(all(row["starts_at"].endswith("11:00:00-05:00") and row["ends_at"].endswith("18:00:00-05:00") for row in result["events"]))
        self.assertTrue(all(row["description"].endswith("Pets are welcome!") and "newsletter" not in row["description"] for row in result["events"]))
        self.assertEqual(ny._manifest(ny.FAD, fad_home(), datetime(2027, 11, 15, tzinfo=timezone.utc)), [])
        ny._validate_checkpoint(result["checkpoint"], ny.FAD, NOW)

    def test_fad_changed_dates_or_street_fail_closed(self):
        queue = ny._manifest(ny.FAD, fad_home(), NOW)
        item = queue[0]
        payload = fad_page(item["url"])
        for altered in (payload.replace("11am", "10am"), payload.replace("190 Court", "191 Court") if "190 Court" in payload else payload.replace("55 Water", "57 Water")):
            with self.assertRaisesRegex(ValueError, "schedule_conflict"):
                ny._detail(ny.FAD, item, altered)

    def test_checkpoint_cannot_inject_records_locations_or_source_urls(self):
        with patch.object(ny, "record", side_effect=record):
            state = ny.collect_chunk(source(ny.FREDDYS), Mock(return_value=listing(square_card())), now=NOW)["checkpoint"]
        for field, value in (("lat", 0), ("description", ""), ("event_url", "https://evil.invalid/event"), ("title", "Another event")):
            tampered = deepcopy(state)
            tampered["events"][0][field] = value
            with self.assertRaisesRegex(ValueError, "checkpoint_invalid"):
                ny._validate_checkpoint(tampered, ny.FREDDYS, NOW)
        altered_source = source(ny.FREDDYS)
        altered_source["feed_url"] += "?format=ical"
        fetch = Mock()
        with self.assertRaisesRegex(ValueError, "unregistered"):
            ny.collect_chunk(altered_source, fetch, now=NOW)
        fetch.assert_not_called()

    def test_calendar_edit_restarts_checkpoint_and_drops_previous_snapshot(self):
        paths = ["/events-calendar/first", "/events-calendar/second"]
        page = listing(*(square_card(p, "Food Pop-Up", "Short.", strong=True, excerpt=True) for p in paths))
        pages = {ny.SOURCES[ny.STRONG][0]: page, **{"https://www.strongropebrewery.com" + p: strong_detail(p) for p in paths}}
        with patch.object(ny, "record", side_effect=record):
            first = ny.collect_chunk(source(ny.STRONG), lambda url, accept: pages[url], now=NOW, max_details=1)
            pages[ny.SOURCES[ny.STRONG][0]] = listing(square_card(paths[1], "Food Pop-Up", "Short.", strong=True, excerpt=True))
            restarted = ny.collect_chunk(source(ny.STRONG), lambda url, accept: pages[url], now=NOW, checkpoint=first["checkpoint"])
        self.assertEqual(restarted["checkpoint"]["manifest_count"], 1)
        self.assertEqual([row["event_url"] for row in restarted["events"]], ["https://www.strongropebrewery.com" + paths[1]])

    def test_checkpoint_rejects_tampered_facts_and_replays_legacy_prefix(self):
        paths = ["/events-calendar/first", "/events-calendar/second"]
        pages = {ny.SOURCES[ny.STRONG][0]: listing(*(square_card(p, "Food Pop-Up", "Short.", strong=True, excerpt=True) for p in paths))}
        pages.update({"https://www.strongropebrewery.com" + p: strong_detail(p) for p in paths})
        with patch.object(ny, "record", side_effect=record):
            first = ny.collect_chunk(source(ny.STRONG), lambda url, accept: pages[url], now=NOW, max_details=1)
            tampered = deepcopy(first["checkpoint"])
            tampered["events"][0]["collector_event_content_v1"]["facts"]["description"] = "Tampered facts."
            with self.assertRaisesRegex(ValueError, "checkpoint_invalid"):
                ny._validate_checkpoint(tampered, ny.STRONG, NOW)
            legacy = deepcopy(first["checkpoint"])
            legacy["events"][0].pop("collector_event_content_v1")
            complete = ny.collect_chunk(source(ny.STRONG), lambda url, accept: pages[url], now=NOW,
                                        max_details=1, checkpoint=legacy)
        self.assertTrue(complete["complete"])
        self.assertTrue(all("collector_event_content_v1" not in row for row in complete["events"]))


if __name__ == "__main__":
    unittest.main()
