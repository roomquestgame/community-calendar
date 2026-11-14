from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html import escape
import json
import re
import unittest
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup

from roomquest import atlantic_city_local_venues as ac


NOW = datetime(2026, 11, 14, 23, 10, tzinfo=timezone.utc)


def source(key):
    return dict(source_key=key, feed_url=ac.SOURCES[key][0], kind="html", platform_adapter="html", timezone=ac.ZONE)


def record(title, start, end, venue, street, city, url, identity, category="", lat=None, lng=None, tz=None, **kwargs):
    return dict(id=identity, title=title, starts_at=start, ends_at=end, venue_name=venue,
                venue_address=street, venue_city=city, event_url=url, category=category,
                lat=lat, lng=lng, reason=None if lat is not None else "missing_verified_venue_geo")


def slack_event(number=1, title="Community workshop", description="The native short introduction.", **overrides):
    value = dict(id=f"00000000-0000-0000-0000-{number:012d}", instanceId=ac.SLACK_INSTANCE,
        title=title, slug="workshop-" + str(number), description=description, status=0,
        scheduling=dict(config=dict(startDate="2026-11-17T23:00:00Z", endDate="2026-11-18T01:00:00Z",
                                    timeZoneId=ac.ZONE, scheduleTbd=False, endDateHidden=False)),
        registration=dict(type=3, restrictedTo=0, ticketing=dict(soldOut=True)),
        location=dict(name="Slack Tide Brewing Company", fullAddress=dict(subdivision="NJ",
                       streetAddress=dict(number="1879", name="U.S. 9"))))
    value.update(overrides)
    return value


def slack_list(events, more=False):
    data = {"appsWarmupData": {ac.SLACK_APP: {ac.SLACK_WIDGET: {
        "events": {"events": events, "hasMore": more, "moreLoading": False}}}}}
    links = "".join(f'<a data-hook="title" href="https://www.slacktidebrewingco.com/event-details/{event["slug"]}">{escape(event["title"])}</a>' for event in events)
    return '<footer>1879 Route 9 Clermont, NJ 08210</footer>' + links + '<script id="wix-warmup-data" type="application/json">' + json.dumps(data) + '</script>'


def slack_detail(event, body="<p>All workshop instructions and materials.</p>", *, start=None, end="default", short=None):
    config = event["scheduling"]["config"]
    url = "https://www.slacktidebrewingco.com/event-details/" + event["slug"]
    description = event["description"] if short is None else short
    data = dict(**{"@type": "Event"}, name=event["title"], description=description,
                startDate=start or config["startDate"],
                endDate=config.get("endDate") if end == "default" else end,
                eventStatus="https://schema.org/EventScheduled",
                eventAttendanceMode="https://schema.org/OfflineEventAttendanceMode",
                location=dict(url=url, name="Slack Tide Brewing Company", address="1879 US-9, CAPE MAY CH, NJ 08210, USA"))
    header = f'<div data-hook="event-description">{escape(description)}</div>' if description else ""
    about = f'<section data-hook="about-section"><div data-id="content-viewer">{body}</div></section>' if body else ""
    native = deepcopy(event)
    native["longDescription"] = {"nodes": [{"type": "TEXT", "textData": {"text": BeautifulSoup(body, "html.parser").get_text(" ")}}]}
    warmup = {"appsWarmupData": {ac.SLACK_APP: {"EventsPageInitialState": {"event": {"event": native}}}}}
    return (f'<script type="application/ld+json">{json.dumps(data)}</script><script id="wix-warmup-data">{json.dumps(warmup)}</script><h1 data-hook="event-title">{escape(event["title"])}</h1>' + header + about)


def slack_pages(events):
    pages = {ac.SOURCES[ac.SLACK][0]: slack_list(events)}
    pages.update({"https://www.slacktidebrewingco.com/event-details/" + event["slug"]: slack_detail(event) for event in events})
    return pages


def tom_unit(kind="tom_inline", title="Dance party", body="The full native dinner and music narrative.", headings=None):
    return dict(id="tomasello:section-1", url=ac.SOURCES[ac.TOMASELLO][0], type=kind,
                title=title, body=body, headings=headings or [title, "Friday November 27, 2026 at 7pm"],
                all_text=body, hold=None)


def lizzie_unit(month=11, year=2026):
    return dict(id=f"lizzie:month:{year}:{month}", url="https://www.lizzierosemusic.com/november",
                title="November", type="lizzie_month", month=month, year=year, hold=None)


def lizzie_card(title="The Artist", body=None, link="https://www.lizzierosemusic.com/product-page/the-artist-nov-19-2026", *, button=False, movie=False):
    body = body or "Complete artist biography.\nThurs. November 19th, 2026\nDoors Open- 7:00 pm\nShowtime- 7:30 pm"
    action = '<button>Buy Tickets</button>' if button else f'<a href="{link}">{"RSVP" if movie else "Buy Tickets"}</a>'
    return (f'<div class="wixui-repeater__item" id="native-card"><div class="wixui-rich-text">{escape(title)}</div>'
            f'<div class="wixui-rich-text"><p>{escape(body)}</p></div><a href="http://www.wix.com"></a>{action}</div>')


def lizzie_month(card, heading="November 2026"):
    return BeautifulSoup(f'<main><h2>{heading}</h2>{card}</main>', "html.parser")


def ticket(title="The Artist- Thurs. Nov 19th, 2026", availability=""):
    return {"title": title, "availability": availability}


class LocalVenuesTests(unittest.TestCase):
    def test_slack_full_native_body_and_literal_symbols_are_preserved(self):
        event = slack_event()
        unit = ac._slack_manifest(BeautifulSoup(slack_list([event]), "html.parser"), NOW)[0]
        full = "Detailed instructions. " * 260 + "R&D: 5 < 10. Final accessibility paragraph."
        with patch.object(ac, "record", side_effect=record):
            rows = ac._slack_detail(unit, slack_detail(event, "<p>" + escape(full) + "</p>"), NOW)
        self.assertEqual(rows[0]["description"], event["description"] + "\n\n" + full)
        self.assertGreater(len(rows[0]["description"]), 5000)
        self.assertEqual(rows[0]["venue_address"], "1879 US Highway 9, Clermont, NJ 08210")
        self.assertEqual(rows[0]["category"], "")

    def test_short_description_is_used_only_from_the_actual_complete_detail(self):
        event = slack_event(description="Three trivia rounds. Gift cards for the winning teams.")
        unit = ac._slack_manifest(BeautifulSoup(slack_list([event]), "html.parser"), NOW)[0]
        with patch.object(ac, "record", side_effect=record):
            row = ac._slack_detail(unit, slack_detail(event, body=""), NOW)[0]
        self.assertEqual(row["description"], event["description"])
        with self.assertRaisesRegex(ValueError, "detail_identity"):
            ac._slack_detail(unit, slack_detail(event, body="", short="A different listing excerpt."), NOW)

    def test_blank_and_over_limit_prose_never_emits_a_clipped_row(self):
        event = slack_event(description="")
        unit = ac._slack_manifest(BeautifulSoup(slack_list([event]), "html.parser"), NOW)[0]
        with self.assertRaisesRegex(ValueError, "description_missing"):
            ac._slack_detail(unit, slack_detail(event, body=""), NOW)
        with self.assertRaisesRegex(ValueError, "description_limit"):
            ac._slack_detail(unit, slack_detail(event, body="<p>" + "x" * 12001 + "</p>"), NOW)
        self.assertEqual(ac._full("x" * 12000), "x" * 12000)

    def test_slack_event_date_conflict_and_detail_identity_are_rejected(self):
        event = slack_event()
        unit = ac._slack_manifest(BeautifulSoup(slack_list([event]), "html.parser"), NOW)[0]
        with self.assertRaisesRegex(ac.Hold, "description_date_conflict"):
            ac._slack_detail(unit, slack_detail(event, body="<p>Join us on November 6th.</p>"), NOW)
        with self.assertRaisesRegex(ac.Hold, "schedule_conflict"):
            ac._slack_detail(unit, slack_detail(event, start="2026-11-18T23:00:00Z"), NOW)
        with self.assertRaisesRegex(ValueError, "detail_identity"):
            ac._slack_detail(unit, slack_detail(event).replace('data-hook="event-title"', 'data-hook="wrong-title"'), NOW)

    def test_slack_recurring_label_does_not_invent_future_occurrences_or_end(self):
        event = slack_event(title="Name That Tune - Second Wednesday of Every Month")
        event["scheduling"]["config"].update(endDateHidden=True)
        unit = ac._slack_manifest(BeautifulSoup(slack_list([event]), "html.parser"), NOW)[0]
        with patch.object(ac, "record", side_effect=record):
            rows = ac._slack_detail(unit, slack_detail(event, end=None), NOW)
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["ends_at"])

    def test_wix_unused_ticket_soldout_does_not_override_external_registration(self):
        event = slack_event()
        units = ac._slack_manifest(BeautifulSoup(slack_list([event]), "html.parser"), NOW)
        self.assertIsNone(units[0]["hold"])
        with self.assertRaisesRegex(ValueError, "manifest_incomplete"):
            ac._slack_manifest(BeautifulSoup(slack_list([event], more=True), "html.parser"), NOW)

    def test_complete_only_checkpoint_and_database_wire_contract(self):
        events = [slack_event(n, title=f"Workshop {n}") for n in range(1, 4)]
        pages = slack_pages(events)
        fetch = Mock(side_effect=lambda url, accept: pages[url])
        state = None
        with patch.object(ac, "record", side_effect=record):
            for index in range(3):
                result = ac.collect_chunk(source(ac.SLACK), fetch, checkpoint=state, now=NOW, max_details=1)
                state = result["checkpoint"]
                self.assertEqual(state["cursor"], index + 1)
                if index < 2:
                    self.assertFalse(result["complete"])
                    self.assertEqual(result["events"], [])
        self.assertTrue(result["complete"])
        self.assertEqual(len(result["events"]), 3)
        # These predicates come from rq_curator_gateway.write_fetch_checkpoint,
        # which consumes the returned payload directly without a worker wrapper.
        self.assertIs(type(state["version"]), int)
        self.assertEqual(state["version"], 1)
        self.assertRegex(state["manifest_hash"], r"^[a-f0-9]{64}$")
        self.assertLessEqual(state["manifest_count"], 200)
        self.assertLessEqual(len(state["events"]), 201)
        self.assertLessEqual(len(state["diagnostics"]), 400)
        self.assertEqual(state["window_start"], "2026-11-14")
        self.assertRegex(state["started_at"], r"T\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)$")
        self.assertEqual(state["events"], [row for group in state["results"] for row in group["events"]])
        self.assertEqual(state["diagnostics"], [d for group in state["results"] for d in group["diagnostics"]])
        self.assertLess(len(json.dumps(state).encode()), 900000)

    def test_checkpoint_rejects_flat_alias_tampering_and_bool_version(self):
        pages = slack_pages([slack_event(n, title=f"Workshop {n}") for n in (1, 2)])
        with patch.object(ac, "record", side_effect=record):
            state = ac.collect_chunk(source(ac.SLACK), lambda u, a: pages[u], now=NOW, max_details=1)["checkpoint"]
        mutations = [dict(version=True), dict(events=[]), dict(window_start="2026-11-15"), dict(started_at="2026-11-14T23:10:00+01:00")]
        for fields in mutations:
            damaged = deepcopy(state)
            damaged.update(fields)
            with self.subTest(fields=fields), self.assertRaisesRegex(ValueError, "checkpoint_invalid"):
                ac._checkpoint(damaged, ac.SLACK, NOW)

    def test_changed_manifest_restarts_without_mixing_snapshots(self):
        first, second = slack_event(1, title="First"), slack_event(2, title="Second")
        pages = slack_pages([first, second])
        with patch.object(ac, "record", side_effect=record):
            state = ac.collect_chunk(source(ac.SLACK), lambda u, a: pages[u], now=NOW, max_details=1)["checkpoint"]
            first["description"] = "New publisher description."
            pages = slack_pages([first, second])
            result = ac.collect_chunk(source(ac.SLACK), lambda u, a: pages[u], checkpoint=state, now=NOW, max_details=1)
        self.assertEqual(result["checkpoint"]["cursor"], 1)
        self.assertEqual(len(result["checkpoint"]["events"]), 1)
        self.assertIn("New publisher description.", result["checkpoint"]["events"][0]["description"])
        self.assertNotEqual(state["manifest_hash"], result["checkpoint"]["manifest_hash"])

    def test_noncheckpoint_call_and_unregistered_source_fail(self):
        pages = slack_pages([slack_event(n, title=f"Workshop {n}") for n in range(1, 4)])
        with patch.object(ac, "record", side_effect=record), self.assertRaisesRegex(ValueError, "publisher_checkpoint_required"):
            ac.collect(source(ac.SLACK), lambda u, a: pages[u], now=NOW)
        wrong = source(ac.SLACK)
        wrong["feed_url"] += "/"
        fetch = Mock()
        with self.assertRaisesRegex(ValueError, "unregistered"):
            ac.collect_chunk(wrong, fetch, now=NOW)
        fetch.assert_not_called()

    def test_source_venue_street_point_contract_is_literal(self):
        for key, (venue, street, _) in ac.VENUES.items():
            self.assertIsNotNone(ac.reviewed_venue_location(key, venue, street))
            self.assertIsNone(ac.reviewed_venue_location(key, venue + " Annex", street))
            self.assertIsNone(ac.reviewed_venue_location(key, venue, street.replace(" NJ ", " PA ")))
        key = ac.TOMASELLO
        changed = dict(ac.VENUES)
        changed[key] = (changed[key][0], "100 Different Street, Hammonton, NJ 08037", "Hammonton")
        with patch.object(ac, "VENUES", changed):
            self.assertIsNone(ac.reviewed_venue_location(key, *ac.VENUES[key][:2]))

    def test_actual_end_retains_event_with_less_than_one_hour_left(self):
        start = NOW - timedelta(hours=2)
        end = NOW + timedelta(minutes=20)
        with patch.object(ac, "record", side_effect=record) as writer:
            row = ac._row(ac.TOMASELLO, "Workshop", start, end, ac.SOURCES[ac.TOMASELLO][0], "ongoing", "Complete body.", NOW)
        self.assertIsNotNone(row)
        self.assertTrue(writer.call_args.kwargs["retain_until_end"])
        self.assertFalse(ac._within(start, end, end))
        self.assertFalse(ac._within(NOW + timedelta(days=60), None, NOW))

    def test_tomasello_inline_schedule_and_two_explicit_participation_options(self):
        body = "Join us November 27 from 7 - 11 PM. Complete dance-party instructions."
        with patch.object(ac, "record", side_effect=record):
            dance = ac._tom_inline(tom_unit(body=body), NOW)[0]
            yoga = ac._tom_inline(tom_unit(title="YOGA, PILATES, MIMOSA BRUNCH & SHOPPING", headings=["YOGA, PILATES, MIMOSA BRUNCH & SHOPPING"],
                body="Saturday, November 21, 2026\nAt 9:15 AM, enjoy Flow & Unwind, a 45-minute yoga class. At 10:30 AM, join Faith Jobson for Mat Pilates. Mimosa brunch follows your final class."), NOW)
        self.assertEqual(ac.timestamp(dance["ends_at"]).hour, 23)
        self.assertEqual(len(yoga), 2)
        self.assertEqual([ac.timestamp(row["starts_at"]).hour for row in yoga], [9, 10])
        self.assertTrue(all(row["ends_at"] is None for row in yoga))
        self.assertEqual(yoga[0]["description"], yoga[1]["description"])

    def test_tomasello_linked_shop_keeps_full_vendor_lists(self):
        unit = tom_unit("tom_shop", body="Saturday, November 14 & 21, 2026\nShort introduction.")
        unit["url"] = "https://tomasellowinery.com/sip---shop"
        html = '<div class="dmNewParagraph"><h2>Pop Up Sip &amp; Shop</h2><h4>Saturday, NOVEMBER 14 &amp; 21 12:00pm to 5:00pm</h4><p>Entire detailed narrative.</p><p>November 21st vendors: Artist A, Artist B.</p><p>Children are welcome. Final reservation instructions.</p></div>'
        with patch.object(ac, "record", side_effect=record):
            rows = [row for row in ac._tom_shop(unit, BeautifulSoup(html, "html.parser"), NOW) if row]
        self.assertEqual(len(rows), 1)
        self.assertIn("Final reservation instructions.", rows[0]["description"])
        self.assertIn("Artist B.", rows[0]["description"])
        self.assertNotIn("Short introduction", rows[0]["description"])
        with self.assertRaisesRegex(ac.Hold, "schedule_conflict"):
            ac._tom_shop(unit, BeautifulSoup(html.replace("14 &amp; 21", "14 &amp; 22"), "html.parser"), NOW)

    def test_opera_soldout_is_local_to_its_own_occurrence(self):
        unit = tom_unit("tom_opera", body="The complete opera-series introduction.")
        unit["url"] = "https://tomasellowinery.com/opera-gala"
        html = '<main>' + ''.join(f'<section><div class="dmNewParagraph" id="opera-{day}"><h4>holiday opera gala</h4><h4>december {day}, 2026 | 2:00pm</h4><p>Full dinner menu for this date.</p></div><a>{label}</a></section>' for day, label in [(6, "SOLD OUT"), (12, "TICKETS")]) + '</main>'
        with patch.object(ac, "record", side_effect=record):
            rows, diagnostics = ac._tom_opera(unit, BeautifulSoup(html, "html.parser"), NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(ac.timestamp(rows[0]["starts_at"]).day, 12)
        self.assertIsNone(rows[0]["ends_at"])
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0]["reason"], "local_venue_nonpublic_or_sold_out")

    def test_undated_music_edition_cannot_roll_forward_or_silently_change(self):
        unit = tom_unit("tom_music")
        unit["url"] = "https://tomasellowinery.com/sips---sounds-hammonton"
        html = '<main><section><div><h2>hammonton incrediblu music series</h2></div><p>Full series introduction.</p></section><div class="dmNewParagraph"><h4>Artist A</h4><p>Sunday, November 15</p><p>2 - 5 pm</p><h4>Artist B</h4><p>Saturday, November 21</p><p>2 - 5 pm</p></div></main>'
        soup = BeautifulSoup(html, "html.parser")
        digest = sha256(ac._body(soup.select_one(".dmNewParagraph")).encode()).hexdigest()
        with patch.object(ac, "REVIEWED_MUSIC_DIGEST", digest), patch.object(ac, "record", side_effect=record):
            rows = ac._tom_music(unit, soup, NOW)
            expired = ac._tom_music(unit, soup, NOW + timedelta(days=365))
            with self.assertRaisesRegex(ac.Hold, "edition_requires_review"):
                ac._tom_music(unit, BeautifulSoup(html.replace("Artist B", "Changed Artist"), "html.parser"), NOW)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row is None for row in expired))

    def test_lizzie_full_bio_doors_showtime_and_unknown_end(self):
        full = "Full native artist biography. " * 170 + "R&D 5 < 10.\nThurs. November 19th, 2026\nDoors Open- 7:00 pm\nShowtime- 7:30 pm"
        url = "https://www.lizzierosemusic.com/product-page/the-artist-nov-19-2026"
        with patch.object(ac, "record", side_effect=record):
            rows, diagnostics = ac._lizzie_month(lizzie_unit(), lizzie_month(lizzie_card(body=full)), NOW, {url: ticket()})
        self.assertEqual(diagnostics, [])
        self.assertEqual(rows[0]["description"], full)
        self.assertEqual(ac.timestamp(rows[0]["starts_at"]).strftime("%H:%M"), "19:30")
        self.assertIsNone(rows[0]["ends_at"])

    def test_lizzie_year_weekday_and_catalog_conflicts_are_held(self):
        url = "https://www.lizzierosemusic.com/product-page/the-artist-nov-19-2026"
        bodies = ["Full bio.\nThurs. November 19th, 2025\nShowtime- 7:30 pm", "Full bio.\nFriday November 19th, 2026\nShowtime- 7:30 pm"]
        reasons = ["local_venue_calendar_date_conflict", "local_venue_weekday_conflict"]
        for body, reason in zip(bodies, reasons):
            rows, diagnostics = ac._lizzie_month(lizzie_unit(), lizzie_month(lizzie_card(body=body)), NOW, {url: ticket()})
            self.assertEqual(rows, [])
            self.assertEqual(diagnostics[0]["reason"], reason)
        rows, diagnostics = ac._lizzie_month(lizzie_unit(), lizzie_month(lizzie_card()), NOW, {url: ticket(availability="Sold out")})
        self.assertEqual(rows, [])
        self.assertIn("sold_out", diagnostics[0]["reason"])

    def test_lizzie_unlinked_button_requires_exact_native_artist_and_date(self):
        url = "https://www.lizzierosemusic.com/product-page/the-artist-nov-19-2026"
        with patch.object(ac, "record", side_effect=record):
            rows, diagnostics = ac._lizzie_month(lizzie_unit(), lizzie_month(lizzie_card(button=True)), NOW,
                                                 {url: ticket(availability="Tickets at Door if Available")})
        self.assertEqual(diagnostics, [])
        self.assertEqual(rows[0]["event_url"], url)
        self.assertTrue(rows[0]["description"].endswith("Tickets at Door if Available"))
        rows, diagnostics = ac._lizzie_month(lizzie_unit(), lizzie_month(lizzie_card(button=True)), NOW,
                                             {url: ticket(title="The Artist- Fri. Nov 20th, 2026")})
        self.assertEqual(rows, [])
        self.assertEqual(diagnostics[0]["reason"], "local_venue_event_identity")

    def test_lizzie_native_film_prose_links_the_calendar_actually_ingested(self):
        card = lizzie_card(title="Local Film", movie=True, link="https://www.moviesonmainstreet.com/event-details/local-film")
        with patch.object(ac, "record", side_effect=record):
            rows, diagnostics = ac._lizzie_month(lizzie_unit(), lizzie_month(card), NOW, {})
        self.assertEqual(diagnostics, [])
        self.assertEqual(rows[0]["event_url"], lizzie_unit()["url"])

    def test_native_catalog_pagination_is_bounded_and_only_linked_pages_fetch(self):
        url = "https://www.lizzierosemusic.com/product-page/the-artist-nov-19-2026"
        html = f'<li data-hook="product-list-grid-item"><a data-hook="product-item-product-details-link" href="{url}"><span data-hook="product-item-name">The Artist- Thurs. Nov 19th, 2026</span></a></li><a data-hook="product-list-pagination-link-seo-link" href="{ac.LIZZIE_TICKETS}?page=2"></a>'
        tickets, pages = ac._lizzie_tickets(BeautifulSoup(html, "html.parser"))
        self.assertEqual(pages, [2])
        state = {"results": [{"unit_id": "lizzie:tickets:1", "tickets": tickets, "ticket_pages": pages}]}
        unit = dict(type="lizzie_tickets", page=2, hold=None)
        self.assertTrue(ac._needs_fetch(unit, state))
        unit["page"] = 3
        self.assertFalse(ac._needs_fetch(unit, state))
        with self.assertRaisesRegex(ValueError, "manifest_incomplete"):
            ac._lizzie_tickets(BeautifulSoup(html.replace("?page=2", "?page=11"), "html.parser"))

    def test_native_full_body_preserves_tail_beyond_rendered_read_more_boundary(self):
        event = slack_event()
        unit = ac._slack_manifest(BeautifulSoup(slack_list([event]), "html.parser"), NOW)[0]
        payload = slack_detail(event, body="<p>First paragraph. Final essential instructions.</p>")
        payload = payload.replace('<p>First paragraph. Final essential instructions.</p>', '<p>First paragraph.</p>')
        with patch.object(ac, "record", side_effect=record):
            rows = ac._slack_detail(unit, payload, NOW)
        self.assertEqual(rows[0]["description"], event["description"] + "\n\nFirst paragraph. Final essential instructions.")
        with self.assertRaisesRegex(ac.Hold, "description_incomplete"):
            ac._slack_detail(unit, payload.replace('<p>First paragraph.</p>', '<p>A contradictory rendered body.</p>'), NOW)

    def test_later_catalog_link_to_an_unfetched_page_blocks_completion(self):
        state = {"results": [
            {"unit_id": "lizzie:tickets:1", "tickets": {"one": ticket()}, "ticket_pages": [10]},
            {"unit_id": "lizzie:tickets:10", "tickets": {"ten": ticket()}, "ticket_pages": [9]},
        ]}
        with self.assertRaisesRegex(ValueError, "manifest_incomplete"):
            ac._catalog(state, require_complete=True)

    def test_checkpoint_saved_rows_require_title_timezone_and_public_attendance(self):
        pages = slack_pages([slack_event(n, title=f"Workshop {n}") for n in (1, 2)])
        with patch.object(ac, "record", side_effect=record):
            state = ac.collect_chunk(source(ac.SLACK), lambda u, a: pages[u], now=NOW, max_details=1)["checkpoint"]
        for field, value in [("title", ""), ("timezone", "UTC"), ("attendance_mode", "online")]:
            damaged = deepcopy(state)
            damaged["events"][0][field] = value
            damaged["results"][0]["events"][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "checkpoint_invalid"):
                ac._checkpoint(damaged, ac.SLACK, NOW)

    def test_publisher_pacing_preserves_completed_work_without_partial_staging(self):
        from roomquest.preview_worker import PreviewError
        events = [slack_event(n, title=f"Workshop {n}") for n in (1, 2)]
        pages = slack_pages(events)
        blocked_url = "https://www.slacktidebrewingco.com/event-details/workshop-2"
        def fetch(url, accept):
            if url == blocked_url:
                raise PreviewError("publisher_pacing_deferred")
            return pages[url]
        with patch.object(ac, "record", side_effect=record):
            result = ac.collect_chunk(source(ac.SLACK), fetch, now=NOW)
        self.assertFalse(result["complete"])
        self.assertEqual(result["events"], [])
        self.assertEqual(result["checkpoint"]["cursor"], 1)
        self.assertEqual(len(result["checkpoint"]["events"]), 1)

    def test_event_identity_rejects_foreign_hosts_queries_and_fragments(self):
        for key in ac.SOURCES:
            self.assertFalse(ac.event_url(key, "https://evil.example/event-details/foo"))
        url = "https://www.slacktidebrewingco.com/event-details/trivia"
        self.assertTrue(ac.event_url(ac.SLACK, url))
        self.assertFalse(ac.event_url(ac.SLACK, url + "?preview=1"))
        self.assertFalse(ac.event_url(ac.SLACK, url + "#other"))


if __name__ == "__main__":
    unittest.main()
