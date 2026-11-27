from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import Mock, patch

from roomquest import new_york_social_final as ny


NOW = datetime(2026, 11, 14, 23, 10, tzinfo=timezone.utc)


def source(key):
    return dict(source_key=key, feed_url=ny.SOURCES[key][0], kind="html", platform_adapter="html", timezone=ny.ZONE)


def normalized_record(title, start, end, venue, address, city, url, identity, *args, **kwargs):
    start, end = ny.timestamp(start, ny.ZONE), ny.timestamp(end, ny.ZONE)
    return dict(id=identity, title=title, starts_at=start.isoformat(), ends_at=end.isoformat() if end else None,
                venue_name=venue, venue_address=address, venue_city=city, event_url=url,
                lat=kwargs.get("lat"), lng=kwargs.get("lng"))


def osnyc_card(title="Game Tournament", body="Complete competition details.", venue="50 Bowery Street", slug="tournament"):
    return (f'<article class="eventlist-event--upcoming"><a class="eventlist-title-link" href="/events/{slug}">{title}</a>'
            '<time class="event-time-12hr-start" datetime="2026-11-18">7:00 PM</time>'
            '<time class="event-time-12hr-end" datetime="2026-11-18">11:00 PM</time>'
            '<time class="event-time-12hr-end" datetime="2026-11-18">23:00</time>'
            f'<li class="eventlist-meta-address">{venue} (map)</li>'
            f'<div class="eventlist-description"><div data-layout-label="Post Body"><p>{body}</p></div></div></article>')


def osnyc_page(*cards):
    return '<div class="eventlist">' + ''.join(cards) + '</div>'


def sip_page():
    return '''<h1>Weekly events!</h1><div data-testid="richTextElement">
      <p>Monday:</p><p>Park Slope Chess Club hosts every Monday at 6pm!</p>
      <p>It's free open play for anyone interested in chess.</p><p>Learn more on their Instagram:</p>
      <p><a href="https://www.instagram.com/parkslopechess/">Park Slope Chess Club</a></p>
      <p>MTG DRAFT @6:30!</p><p>Vote on the set in our Discord.</p>
      <p>Bi-weekly writing meetup:</p><p>Find details here.</p>
      <p>Tuesday:</p><p>Riftbound @7pm</p><p>Pack per match win.</p>
      <p>Bi-weekly boardgame meetup:</p><p>Check dates.</p>
      <p>Wednesday:</p><p>Commander night! @6:30pm</p><p>Every Wed at 6pm; raffle and games.</p>
      </div><div data-testid="richTextElement">
      <p>Thursday:</p><p>Flesh and Blood @7pm</p><p>Format depends on the week.</p>
      <p>Lorcana @6:30pm</p><p>Play Disney's card game.</p>
      <p>Friday:</p><p>Family Fridays!</p><p>Half-price admission after 4pm.</p>
      <p>Riftbound @7pm</p><p>Pack per match win.</p>
      <p>Saturday:</p><p>MTG Draft @10:15am</p><p>Draft the latest set and win packs.</p>
      <p>Bi-weekly Queer Commander night! @6:30pm</p><p>Every Wed at 6pm.</p></div>'''


def pauper_page():
    cards = []
    for day, venue, street, clock in (
        ("Monday", "Hex & Co. Upper West Side", "2911 Broadway, New York, NY 10025", "7:00 PM"),
        ("Tuesday", "Hex & Co. Union Square", "801 Broadway, New York, NY 10003", "7:00 PM"),
        ("Thursday", "Victory Point", "112 Brunswick St, Jersey City, NJ 07302", "7:00 PM"),
        ("Saturday", "Brooklyn Strategist", "148 Pierrepont St, Brooklyn, NY 11201", "2:00 PM"),
    ):
        cards.append(f'<div><h5>{day} at {venue}</h5><h6>Location: <a>{venue}</a></h6><p>Address: {street}</p><p>Time: {clock}</p></div>')
    return ('<main><h1>Pauper League Schedule</h1><section>' + ''.join(cards) + '</section><section>'
            '<h3>Season 7 Schedule</h3><p>Runs from <strong>October 5, 2026</strong> through <strong>February 21, 2027</strong>.</p>'
            '<p>No weeklies <strong>November 23 - December 6, 2026</strong> and <strong>December 21, 2026 - January 3, 2027</strong>.</p>'
            '<h3>Event Format</h3><p>Play with common cards. Earn league points.</p><p>Read the full official format rules.</p>'
            '<h3>How to Join</h3><p>Show up at the designated time and place. No advance registration.</p>'
            '<p>Need a deck? Union Square offers rental decks.</p></section></main>')


def trivia_event(body="Let's Go Trivia Nights at Bronx Alehouse! Tuesdays at 7pm. Bronx, NY 10463", **overrides):
    event = dict(id=10017646, status="publish", title="Bronx Alehouse", description=f"<p>{body}</p>", excerpt="Short intro...",
                 timezone=ny.ZONE, utc_start_date="2026-11-18 00:00:00", utc_end_date="2026-11-18 02:00:00",
                 start_date="2026-11-17 19:00:00", end_date="2026-11-17 21:00:00", all_day=False,
                 url="https://letsgotrivia.com/find-a-trivia/bronx-alehouse/2026-11-17/",
                 venue=dict(id=230356, venue="Bronx Alehouse", address="216 W 238th St", city="Bronx", state="NY", zip="NY"))
    event.update(overrides)
    return event


def trivia_api(*events, **overrides):
    data = dict(events=list(events), total=len(events), total_pages=1)
    data.update(overrides)
    return json.dumps(data)


def amelia_event(identity=1, body="Complete artist biography, program and attendance details.", **overrides):
    event = dict(id=identity, name=f"Band {identity}", status="approved", show=True, description=f"<p>{body}</p>",
                 locationId=4, customLocation=None, timeZone=None, bookable=False,
                 latitude=40.748441, longitude=-73.987853,
                 periods=[dict(id=identity + 1000, eventId=identity, periodStart="2026-11-18 20:00:00", periodEnd="2026-11-18 23:00:00")],
                 gallery=[dict(position=1, pictureFullPath="http://radegasthall.com/wp-content/uploads/2026/11/band.png")])
    event.update(overrides)
    return event


def amelia_api(events, count=None):
    return json.dumps(dict(data=dict(events=events, count=len(events) if count is None else count, countTotal=145)))


class NewYorkSocialFinalTests(unittest.TestCase):
    def test_osnyc_preserves_complete_long_post_body_with_one_request(self):
        body = "Registration, participation, accessibility and competition rules. " * 70 + "Final complete paragraph."
        fetch = Mock(return_value=osnyc_page(osnyc_card(body=body)))
        with patch.object(ny, "record", side_effect=normalized_record):
            rows = ny.collect(source(ny.OSNYC), fetch, now=NOW)
        self.assertEqual(rows[0]["description"], body)
        self.assertGreater(len(rows[0]["description"]), 2000)
        self.assertEqual(rows[0]["venue_address"], "50 Bowery, New York, NY 10013")
        facts = rows[0]["collector_event_content_v1"]["facts"]
        self.assertEqual(facts["venue_name"], "50 Bowery Street")
        self.assertNotIn("venue_address", facts)
        self.assertEqual(rows[0]["starts_at"], "2026-11-18T19:00:00-05:00")
        fetch.assert_called_once_with(ny.SOURCES[ny.OSNYC][0], "text/html")

    def test_osnyc_explicit_closure_and_sold_out_entry_are_held(self):
        payload = osnyc_page(osnyc_card(title="OS NYC Closed", slug="closed"),
                             osnyc_card(body="TICKETS ARE SOLD OUT!!", slug="sold-out"))
        rows, held = ny.inspect_payload(ny.OSNYC, payload, now=NOW)
        self.assertEqual(rows, [])
        self.assertEqual([x["reason"] for x in held], ["publisher_nonpublic", "publisher_nonpublic"])

    def test_outer_provider_label_is_not_content_but_event_narrative_is(self):
        with patch.object(ny, "record", side_effect=normalized_record):
            first = ny.collect(source(ny.OSNYC), Mock(return_value=osnyc_page(osnyc_card())), now=NOW)[0]
            changed = ny.collect(source(ny.OSNYC), Mock(return_value=osnyc_page(
                osnyc_card(body="Changed publisher event narrative."))), now=NOW)[0]
        before = json.dumps(first["collector_event_content_v1"]["facts"], sort_keys=True)
        first["provider_label"] = "Renamed source label"
        self.assertEqual(before, json.dumps(first["collector_event_content_v1"]["facts"], sort_keys=True))
        self.assertNotEqual(before, json.dumps(changed["collector_event_content_v1"]["facts"], sort_keys=True))

    def test_osnyc_offsite_program_cannot_inherit_bowery_pin(self):
        rows, held = ny.inspect_payload(ny.OSNYC, osnyc_page(osnyc_card(venue="Other venue, 81 East 7th Street")), now=NOW)
        self.assertEqual(rows, [])
        self.assertEqual(held[0]["reason"], "publisher_venue_changed")

    def test_osnyc_excerpt_cannot_be_certified_as_full_body(self):
        page = osnyc_page(osnyc_card()).replace('data-layout-label="Post Body"', 'class="eventlist-excerpt"')
        with self.assertRaisesRegex(ValueError, "description_missing"):
            ny.inspect_payload(ny.OSNYC, page, now=NOW)

    def test_osnyc_offsite_map_query_cannot_keep_default_street_label(self):
        page = osnyc_page(osnyc_card()).replace('50 Bowery Street (map)',
            '50 Bowery Street <a href="https://maps.google.com?q=81+East+7th+Street,+New+York,+NY+10003">(map)</a>')
        rows, held = ny.inspect_payload(ny.OSNYC, page, now=NOW)
        self.assertEqual(rows, [])
        self.assertEqual(held[0]["reason"], "publisher_venue_changed")

    def test_wild_east_uses_dated_program_clock_and_complete_native_line(self):
        line = "Thurs, Nov 19th: Landline Comedy from 8 - 9:30pm. Free"
        page = ('<h2>TAPROOM EVENTS</h2><div class="sqs-html-content"><h3>NOVEMBER 2026</h3>'
                f'<p>{line}</p><p>Thurs, Nov 19th: Lectures on Tap from 6:30-8pm. (Closed to the public)</p>'
                '<p>Sun, Nov 29th: Ubiquity Music Festival.</p></div>')
        with patch.object(ny, "record", side_effect=normalized_record):
            rows, held = ny.inspect_payload(ny.WILD, page, now=NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["description"], line)
        self.assertEqual(rows[0]["title"], "Landline Comedy")
        self.assertEqual(rows[0]["starts_at"], "2026-11-19T20:00:00-05:00")
        self.assertEqual(rows[0]["ends_at"], "2026-11-19T21:30:00-05:00")
        self.assertEqual({x["reason"] for x in held}, {"publisher_nonpublic", "publisher_clock_missing"})

    def test_wild_east_conflicting_weekday_is_not_silently_corrected(self):
        page = '<h2>TAPROOM EVENTS</h2><div class="sqs-html-content"><h3>NOVEMBER 2026</h3><p>Fri, Nov 19th: Comedy from 8-10pm. Free</p></div>'
        rows, held = ny.inspect_payload(ny.WILD, page, now=NOW)
        self.assertEqual(rows, [])
        self.assertEqual(held[0]["reason"], "publisher_schedule_conflict")

    def test_sip_reviewed_28_day_window_keeps_seven_programs_and_all_prose(self):
        with patch.object(ny, "record", side_effect=normalized_record):
            rows, held = ny.inspect_payload(ny.SIP, sip_page(), now=NOW)
        self.assertEqual(len(rows), 28)
        self.assertEqual(len(held), 5)
        chess = [row for row in rows if row["title"] == "Park Slope Chess Club"]
        self.assertEqual(len(chess), 4)
        self.assertTrue(chess[0]["description"].endswith("Park Slope Chess Club"))
        self.assertIn("Learn more on their Instagram", chess[0]["description"])
        monday = [row for row in rows if row["title"] == "MTG DRAFT"]
        self.assertEqual(len(monday), 4)
        self.assertTrue(all("T18:30:00-05:00" in row["starts_at"] for row in monday))
        self.assertTrue(all(NOW <= ny.timestamp(row["starts_at"]) < NOW + timedelta(days=28) for row in rows))
        self.assertTrue(all(row["schedule_provenance"] == "reviewed_publisher_weekly_schedule" for row in rows))
        self.assertTrue(all(row["ends_at"] is None for row in rows))

    def test_revalidated_weekly_schedule_rolls_only_28_days_and_respects_native_season_end(self):
        later = NOW + timedelta(days=40)
        with patch.object(ny, "record", side_effect=normalized_record):
            rows, _ = ny.inspect_payload(ny.SIP, sip_page(), now=later)
            expired, _ = ny.inspect_payload(ny.PAUPER, pauper_page(), now=datetime(2027, 2, 22, tzinfo=timezone.utc))
        self.assertEqual(len(rows), 28)
        self.assertTrue(all(later <= ny.timestamp(r["starts_at"]) < later + timedelta(days=28) for r in rows))
        self.assertTrue(all(r["schedule_reviewed_at"] == later.isoformat() for r in rows))
        self.assertEqual(expired, [])

    def test_recurring_event_identity_is_stable_across_refreshes(self):
        with patch.object(ny, "record", side_effect=normalized_record):
            first, _ = ny.inspect_payload(ny.SIP, sip_page(), now=NOW)
            again, _ = ny.inspect_payload(ny.SIP, sip_page(), now=NOW + timedelta(hours=1))
        self.assertEqual([r["id"] for r in first], [r["id"] for r in again])

    def test_pauper_preserves_native_holiday_breaks_and_exact_branch_addresses(self):
        with patch.object(ny, "record", side_effect=normalized_record):
            rows, held = ny.inspect_payload(ny.PAUPER, pauper_page(), now=NOW)
        self.assertEqual(len(rows), 6)
        self.assertEqual(held[0]["reason"], "outside_new_york_city")
        self.assertEqual({row["starts_at"][:10] for row in rows}, {"2026-11-16", "2026-11-17", "2026-11-21", "2026-12-07", "2026-12-08", "2026-12-12"})
        self.assertEqual({row["venue_address"] for row in rows}, {v[0] for v in ny.PAUPER_VENUES.values()})
        self.assertTrue(all("rental decks" not in r["description"] for r in rows if r["venue_name"] != "Hex & Co. Union Square"))

    def test_pauper_changed_season_requires_review(self):
        with self.assertRaisesRegex(ValueError, "schedule_conflict"):
            ny.inspect_payload(ny.PAUPER, pauper_page().replace("February 21, 2027", "March 7, 2027"), now=NOW)

    def test_pauper_changed_venue_is_held_without_old_address_fallback(self):
        with patch.object(ny, "record", side_effect=normalized_record):
            rows, held = ny.inspect_payload(ny.PAUPER, pauper_page().replace("148 Pierrepont St", "151 Court St"), now=NOW)
        self.assertEqual(len(rows), 4)
        self.assertIn("publisher_venue_changed", {h["reason"] for h in held})

    def test_trivia_reuses_tec_utc_parser_with_full_description_and_correct_zip(self):
        body = "Complete competition and participation information. " * 70 + "Bronx, NY 10463"
        fetch = Mock(return_value=trivia_api(trivia_event(body)))
        with patch.object(ny, "record", side_effect=normalized_record), patch("roomquest.mapsee_adapter.record", side_effect=normalized_record):
            rows = ny.collect(source(ny.BRONX), fetch, now=NOW)
        self.assertEqual(rows[0]["description"], body)
        self.assertEqual(rows[0]["venue_address"], "216 West 238th Street, Bronx, NY 10463")
        self.assertEqual(rows[0]["starts_at"], "2026-11-18T00:00:00+00:00")
        self.assertIn("venue=230356", fetch.call_args.args[0])
        self.assertNotIn("Short intro", rows[0]["description"])

    def test_trivia_incomplete_page_cannot_be_certified(self):
        with self.assertRaisesRegex(ValueError, "manifest_limit"):
            ny.inspect_payload(ny.BRONX, trivia_api(trivia_event(), total=2), now=NOW)

    def test_trivia_moved_or_unknown_venue_cannot_inherit_bronx_point(self):
        event = trivia_event()
        event["venue"]["address"] = "300 Other Street"
        rows, held = ny.inspect_payload(ny.BRONX, trivia_api(event), now=NOW)
        self.assertEqual(rows, [])
        self.assertEqual(held[0]["reason"], "publisher_venue_changed")

    def test_description_boundary_rejects_blank_and_oversize_without_truncation(self):
        for body, error in (("", "description_missing"), ("x" * 12001, "description_limit")):
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                ny._body(body)
        self.assertEqual(ny._body("x" * 12000), "x" * 12000)

    def test_source_profile_url_and_reviewed_points_are_exact(self):
        changed = source(ny.SIP)
        changed["feed_url"] += "?format=json"
        fetch = Mock()
        with self.assertRaisesRegex(ValueError, "unregistered"):
            ny.collect(changed, fetch, now=NOW)
        fetch.assert_not_called()
        self.assertFalse(ny.event_url(ny.OSNYC, "https://www.os-nyc.com.evil.test/events/example"))
        self.assertFalse(ny.event_url(ny.OSNYC, "https://www.os-nyc.com/events/../account"))
        self.assertIsNone(ny.reviewed_venue_location(ny.OSNYC, "Other Venue", ny.VENUES[ny.OSNYC][1]))

    def test_expired_budget_never_starts_a_publisher_request(self):
        fetch = Mock()
        with self.assertRaisesRegex(ValueError, "collection_deadline"):
            ny.collect(source(ny.WILD), fetch, deadline_at=0, now=NOW)
        fetch.assert_not_called()

    def test_radegast_one_request_per_chunk_never_publishes_a_partial_page(self):
        fetch1 = Mock(return_value=amelia_api([amelia_event(i) for i in range(1, 13)], count=13))
        fetch2 = Mock(return_value=amelia_api([amelia_event(13)], count=13))
        with patch.object(ny, "record", side_effect=normalized_record):
            first = ny.collect_chunk(source(ny.RADEGAST), fetch1, now=NOW)
            final = ny.collect_chunk(source(ny.RADEGAST), fetch2, checkpoint=first["checkpoint"], now=NOW + timedelta(seconds=61))
        self.assertFalse(first["complete"])
        self.assertEqual(first["events"], [])
        self.assertEqual(first["checkpoint"]["cursor"], 12)
        self.assertTrue(final["complete"])
        self.assertEqual(len(final["events"]), 13)
        self.assertEqual(final["checkpoint"]["started_at"], first["checkpoint"]["started_at"])
        self.assertEqual(final["checkpoint"]["manifest_count"], 13)
        fetch1.assert_called_once_with(ny.RADEGAST_API + "1", "application/json")
        fetch2.assert_called_once_with(ny.RADEGAST_API + "2", "application/json")
        ny._radegast_checkpoint(final["checkpoint"], NOW + timedelta(seconds=61))

    def test_radegast_count_change_restarts_an_empty_generation_for_next_paced_turn(self):
        with patch.object(ny, "record", side_effect=normalized_record):
            first = ny.collect_chunk(source(ny.RADEGAST), Mock(return_value=amelia_api([amelia_event(i) for i in range(1, 13)], count=13)), now=NOW)
            changed = ny.collect_chunk(source(ny.RADEGAST), Mock(return_value=amelia_api([amelia_event(13), amelia_event(14)], count=14)),
                                       checkpoint=first["checkpoint"], now=NOW + timedelta(seconds=61))
        self.assertFalse(changed["complete"])
        self.assertEqual(changed["events"], [])
        self.assertEqual(changed["checkpoint"]["cursor"], 0)
        self.assertEqual(changed["checkpoint"]["next_page"], 1)
        self.assertNotEqual(first["checkpoint"]["manifest_hash"], changed["checkpoint"]["manifest_hash"])
        ny._radegast_checkpoint(changed["checkpoint"], NOW + timedelta(seconds=61))

    def test_radegast_full_bodies_ignore_generic_native_coordinate_placeholder(self):
        body = "Complete artist biography and performance information. " * 60 + "Last paragraph."
        with patch.object(ny, "record", side_effect=normalized_record):
            result = ny.collect_chunk(source(ny.RADEGAST), Mock(return_value=amelia_api([amelia_event(body=body, locationId=3)])), now=NOW)
        row = result["events"][0]
        self.assertEqual(row["description"], body)
        self.assertEqual(row["venue_address"], "186 Berry Street, Brooklyn, NY 11249")
        self.assertEqual((row["lat"], row["lng"]), ny.RADEGAST_POINT)
        self.assertNotEqual(row["lat"], 40.748441)
        self.assertEqual(row["starts_at"], "2026-11-18T20:00:00-05:00")
        self.assertEqual(row["image_url"], "https://radegasthall.com/wp-content/uploads/2026/11/band.png")
        facts = row["collector_event_content_v1"]["facts"]
        self.assertEqual(facts["provider_venue_id"], "3")
        self.assertNotIn("venue_address", facts)
        self.assertNotIn("source_latitude", facts)

    def test_radegast_room_label_is_not_an_event_description(self):
        for body in ("Bar Stage", "", "undefined", "a" * 12001):
            with self.subTest(body=body[:20]):
                result = ny.collect_chunk(source(ny.RADEGAST), Mock(return_value=amelia_api([amelia_event(body=body)])), now=NOW)
                self.assertTrue(result["complete"])
                self.assertEqual(result["events"], [])
                self.assertIn(result["checkpoint"]["diagnostics"][0]["reason"],
                              {"new_york_social_final_description_missing", "new_york_social_final_description_limit"})

    def test_radegast_invalid_period_and_unknown_room_are_explicit_holds(self):
        backwards = amelia_event(1)
        backwards["periods"][0]["periodEnd"] = "2026-11-18 00:00:00"
        missing_end = amelia_event(2)
        missing_end["periods"][0]["periodEnd"] = None
        unknown = amelia_event(3, locationId=999)
        offsite = amelia_event(4, customLocation="Another event space")
        result = ny.collect_chunk(source(ny.RADEGAST), Mock(return_value=amelia_api([backwards, missing_end, unknown, offsite])), now=NOW)
        self.assertTrue(result["complete"])
        self.assertEqual(result["events"], [])
        self.assertEqual([h["reason"] for h in result["checkpoint"]["diagnostics"]],
                         ["publisher_schedule_conflict", "publisher_schedule_conflict", "publisher_venue_changed", "publisher_venue_changed"])

    def test_radegast_checkpoint_tampering_is_rejected_before_fetch(self):
        with patch.object(ny, "record", side_effect=normalized_record):
            first = ny.collect_chunk(source(ny.RADEGAST), Mock(return_value=amelia_api([amelia_event(i) for i in range(1, 13)], count=13)), now=NOW)
        cases = []
        cursor = deepcopy(first["checkpoint"]); cursor["cursor"] = 11; cases.append(cursor)
        description = deepcopy(first["checkpoint"]); description["events"][0]["description"] = ""; cases.append(description)
        content = deepcopy(first["checkpoint"]); content["events"][0]["collector_event_content_v1"]["facts"]["description"] = "tampered"; cases.append(content)
        geo = deepcopy(first["checkpoint"]); geo["events"][0]["lat"] = 40.748441; cases.append(geo)
        window = deepcopy(first["checkpoint"]); window["window_start"] = "2026-11-15"; cases.append(window)
        for state in cases:
            fetch = Mock()
            with self.assertRaisesRegex(ValueError, "checkpoint_invalid"):
                ny.collect_chunk(source(ny.RADEGAST), fetch, checkpoint=state, now=NOW)
            fetch.assert_not_called()

    def test_radegast_legacy_checkpoint_prefix_finishes_without_invented_originals(self):
        with patch.object(ny, "record", side_effect=normalized_record):
            first = ny.collect_chunk(source(ny.RADEGAST), Mock(return_value=amelia_api([amelia_event(i) for i in range(1, 13)], count=13)), now=NOW)
            legacy = deepcopy(first["checkpoint"])
            for row in legacy["events"]:
                row.pop("collector_event_content_v1")
            final = ny.collect_chunk(source(ny.RADEGAST), Mock(return_value=amelia_api([amelia_event(13)], count=13)),
                                     checkpoint=legacy, now=NOW + timedelta(seconds=61))
        self.assertTrue(final["complete"])
        self.assertTrue(all("collector_event_content_v1" not in row for row in final["events"]))

    def test_radegast_missing_page_records_cannot_claim_complete(self):
        with patch.object(ny, "record", side_effect=normalized_record):
            first = ny.collect_chunk(source(ny.RADEGAST), Mock(return_value=amelia_api([amelia_event(i) for i in range(1, 13)], count=13)), now=NOW)
        with self.assertRaisesRegex(ValueError, "manifest_changed"):
            ny.collect_chunk(source(ny.RADEGAST), Mock(return_value=amelia_api([], count=13)), checkpoint=first["checkpoint"], now=NOW + timedelta(seconds=61))

    def test_radegast_all_or_nothing_collect_requires_durable_checkpoint(self):
        with patch.object(ny, "record", side_effect=normalized_record), self.assertRaisesRegex(ValueError, "checkpoint_required"):
            ny.collect(source(ny.RADEGAST), Mock(return_value=amelia_api([amelia_event(i) for i in range(1, 13)], count=13)), now=NOW)

    def test_radegast_deep_link_is_limited_to_native_public_event_popup(self):
        self.assertTrue(ny.event_url(ny.RADEGAST, "https://radegasthall.com/?ameliaEventPopup=75"))
        self.assertFalse(ny.event_url(ny.RADEGAST, "https://radegasthall.com/?ameliaEventPopup=75&next=https://evil.test"))
        self.assertFalse(ny.event_url(ny.RADEGAST, ny.RADEGAST_API + "1"))


def greenbelt_basic(identity="2004822817014", **overrides):
    basic = dict(id=identity, name="Storytime: Lenape and Corn", status="live",
                 url=f"https://www.eventbrite.com/e/storytime-lenape-and-corn-tickets-{identity}",
                 organizationId=ny.GREENBELT_ORGANIZATION, organizer=dict(id=ny.GREENBELT_ORGANIZER),
                 isOnline=False, isProtected=False, isListed=True, isParentEvent=False,
                 hideStartDate=False, hideEndDate=False,
                 summary="Join the Greenbelt Nature Center for a pre-Thanksgiving story and craft.",
                 startDate=dict(local="2026-11-20T11:00:00", utc="2026-11-20T16:00:00Z", timezone=ny.ZONE),
                 endDate=dict(local="2026-11-20T13:00:00", utc="2026-11-20T18:00:00Z", timezone=ny.ZONE),
                 venue=dict(name="Greenbelt Nature Center", address=dict(
                     localizedMultiLineAddressDisplay=["700 Rockland Ave.", "Staten Island, NY 10314"],
                     country="US", region="NY", city="Staten Island")))
    basic.update(overrides)
    return basic


def greenbelt_listing(*basics, **overrides):
    events = [dict(id=b["id"], name=b["name"], url=b["url"], primary_organizer_id=ny.GREENBELT_ORGANIZER,
                   start_date=b["startDate"]["local"].split("T")[0], start_time=b["startDate"]["local"].split("T")[1],
                   end_time=b["startDate"]["local"].split("T")[1], timezone=ny.ZONE) for b in basics]
    page = dict(organizer=dict(id=ny.GREENBELT_ORGANIZER, profilePageUrl=ny.SOURCES[ny.GREENBELT][0]),
                upcomingEvents=events, upcomingEventsTotal=len(events), hasMoreUpcoming=False, upcomingEventsFailed=False)
    page.update(overrides)
    return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(dict(props=dict(pageProps=page))) + '</script>'


def greenbelt_detail(basic=None, modules=None, widgets=None):
    if basic is None:
        basic = greenbelt_basic()
    if modules is None:
        modules = [dict(type="text", text="<p>Learn about corn, hear a story and create a craft. Supplies are limited.</p>")]
    context = dict(basicInfo=basic, structuredContent=dict(modules=modules, widgets=widgets or {}),
                   taxonomies=dict(category="Family & Education", format="Class"), gallery=dict(images=[]))
    return ('<script id="__NEXT_DATA__" type="application/json">' + json.dumps(dict(props=dict(pageProps=dict(context=context))))
            + '</script><script type="application/ld+json">{"@type":"Event","description":"Short teaser..."}</script>')


class GreenbeltFinalTests(unittest.TestCase):
    def test_complete_native_body_and_real_detail_end_wait_for_manifest_recheck(self):
        basic = greenbelt_basic()
        listing = greenbelt_listing(basic)
        long_body = "Program and accessibility information. " * 90 + "Final native paragraph."
        modules = [dict(type="text", text="<p>" + long_body + "</p>"), dict(type="text", text="<p>Supplies are limited.</p>")]
        fetch = Mock(side_effect=[listing, greenbelt_detail(basic, modules), listing])
        with patch.object(ny, "record", side_effect=normalized_record):
            manifest = ny.collect_chunk(source(ny.GREENBELT), fetch, now=NOW)
            hydrated = ny.collect_chunk(source(ny.GREENBELT), fetch, checkpoint=manifest["checkpoint"], now=NOW)
            final = ny.collect_chunk(source(ny.GREENBELT), fetch, checkpoint=hydrated["checkpoint"], now=NOW)
        self.assertEqual(manifest["events"], [])
        self.assertEqual(hydrated["events"], [])
        self.assertFalse(hydrated["complete"])
        self.assertTrue(final["complete"])
        self.assertIsInstance(final["checkpoint"], dict)
        row = final["events"][0]
        self.assertIn(long_body, row["description"])
        self.assertTrue(row["description"].endswith("Supplies are limited."))
        self.assertNotIn("Short teaser", row["description"])
        self.assertEqual(row["ends_at"], "2026-11-20T13:00:00-05:00")
        self.assertEqual(row["venue_address"], "700 Rockland Avenue, Staten Island, NY 10314")
        self.assertEqual(row["venue_name"], "Greenbelt Nature Center (in Blood Root Valley)")
        self.assertEqual(final["checkpoint"]["started_at"], manifest["checkpoint"]["started_at"])
        self.assertEqual(fetch.call_count, 3)

    def test_complete_overview_only_is_supported_but_blanks_and_ellipsis_are_held(self):
        basic = greenbelt_basic(summary="Learn to navigate through the Greenbelt as people did long before GPS, with a compass and a map!")
        item = ny._greenbelt_manifest(greenbelt_listing(basic))[0]
        with patch.object(ny, "record", side_effect=normalized_record):
            row, held = ny._greenbelt_detail(item, greenbelt_detail(basic, []), NOW)
        self.assertIsNone(held)
        self.assertEqual(row["description"], basic["summary"])
        self.assertEqual(row["native_text_module_count"], 0)
        for text in ("", "TBD", "Learn to navigate...", basic["name"]):
            changed = dict(basic, summary=text)
            row, held = ny._greenbelt_detail(item, greenbelt_detail(changed, []), NOW)
            self.assertIsNone(row)
            self.assertEqual(held, "new_york_social_final_description_missing")

    def test_oversize_description_is_held_without_clipping(self):
        basic = greenbelt_basic()
        item = ny._greenbelt_manifest(greenbelt_listing(basic))[0]
        row, reason = ny._greenbelt_detail(item, greenbelt_detail(basic, [dict(type="text", text="x" * 12001)]), NOW)
        self.assertIsNone(row)
        self.assertEqual(reason, "new_york_social_final_description_limit")

    def test_incomplete_or_wrong_organizer_manifest_cannot_start(self):
        basic = greenbelt_basic()
        for page in (greenbelt_listing(basic, hasMoreUpcoming=True), greenbelt_listing(basic, upcomingEventsTotal=2),
                     greenbelt_listing(basic, upcomingEventsFailed=True),
                     greenbelt_listing(basic, organizer=dict(id="other", profilePageUrl=ny.SOURCES[ny.GREENBELT][0]))):
            with self.assertRaisesRegex(ValueError, "manifest_limit"):
                ny.collect_chunk(source(ny.GREENBELT), Mock(return_value=page), now=NOW)

    def test_wrong_detail_owner_or_url_cannot_be_published(self):
        basic = greenbelt_basic()
        item = ny._greenbelt_manifest(greenbelt_listing(basic))[0]
        for changed in (dict(basic, organizer=dict(id="other")), dict(basic, organizationId="other"),
                        dict(basic, url="https://www.eventbrite.com/e/unrelated-tickets-2004822817015")):
            with self.assertRaisesRegex(ValueError, "identity"):
                ny._greenbelt_detail(item, greenbelt_detail(changed), NOW)

    def test_unknown_venue_and_local_utc_conflicts_are_held(self):
        basic = greenbelt_basic()
        item = ny._greenbelt_manifest(greenbelt_listing(basic))[0]
        offsite = deepcopy(basic)
        offsite["venue"]["address"]["localizedMultiLineAddressDisplay"][0] = "701 Rockland Ave"
        self.assertEqual(ny._greenbelt_detail(item, greenbelt_detail(offsite), NOW)[1], "publisher_venue_changed")
        wrong_clock = deepcopy(basic)
        wrong_clock["startDate"]["utc"] = "2026-11-20T15:00:00Z"
        self.assertEqual(ny._greenbelt_detail(item, greenbelt_detail(wrong_clock), NOW)[1], "publisher_schedule_conflict")
        self.assertEqual(ny._greenbelt_detail(item, greenbelt_detail(basic, widgets=dict(faqs=["Extra instructions"])), NOW)[1],
                         "new_york_social_final_description_shape_changed")

    def test_bounded_details_resume_without_releasing_partial_rows(self):
        basics = [greenbelt_basic(str(2004822817014 + i)) for i in range(3)]
        listing = greenbelt_listing(*basics)
        manifest = ny.collect_chunk(source(ny.GREENBELT), Mock(return_value=listing), now=NOW)
        details = Mock(side_effect=[greenbelt_detail(b) for b in basics])
        with patch.object(ny, "record", side_effect=normalized_record):
            first = ny.collect_chunk(source(ny.GREENBELT), details, checkpoint=manifest["checkpoint"], now=NOW)
            second = ny.collect_chunk(source(ny.GREENBELT), details, checkpoint=first["checkpoint"], now=NOW)
        self.assertEqual(first["checkpoint"]["cursor"], 2)
        self.assertEqual(second["checkpoint"]["cursor"], 3)
        self.assertEqual(first["events"], [])
        self.assertEqual(second["events"], [])
        self.assertEqual(details.call_count, 3)

    def test_changed_final_manifest_fails_before_release(self):
        basic = greenbelt_basic()
        listing = greenbelt_listing(basic)
        with patch.object(ny, "record", side_effect=normalized_record):
            first = ny.collect_chunk(source(ny.GREENBELT), Mock(return_value=listing), now=NOW)
            second = ny.collect_chunk(source(ny.GREENBELT), Mock(return_value=greenbelt_detail(basic)), checkpoint=first["checkpoint"], now=NOW)
        with self.assertRaisesRegex(ValueError, "manifest_changed"):
            ny.collect_chunk(source(ny.GREENBELT), Mock(return_value=greenbelt_listing()), checkpoint=second["checkpoint"], now=NOW)

    def test_checkpoint_tampering_is_rejected_before_fetch(self):
        basic = greenbelt_basic()
        with patch.object(ny, "record", side_effect=normalized_record):
            first = ny.collect_chunk(source(ny.GREENBELT), Mock(return_value=greenbelt_listing(basic)), now=NOW)
            second = ny.collect_chunk(source(ny.GREENBELT), Mock(return_value=greenbelt_detail(basic)), checkpoint=first["checkpoint"], now=NOW)
        states = []
        state = deepcopy(second["checkpoint"]); state["events"][0]["lat"] = 40.75; states.append(state)
        state = deepcopy(second["checkpoint"]); state["events"][0]["description"] = ""; states.append(state)
        state = deepcopy(second["checkpoint"]); state["events"][0]["publisher_organizer_id"] = "other"; states.append(state)
        state = deepcopy(second["checkpoint"]); state["diagnostics"] = []; states.append(state)
        state = deepcopy(second["checkpoint"]); state["window_start"] = "2026-11-15"; states.append(state)
        state = deepcopy(second["checkpoint"]); state["queue"][0]["url"] = "https://evil.test/e/event"; states.append(state)
        for state in states:
            fetch = Mock()
            with self.assertRaisesRegex(ValueError, "checkpoint_invalid"):
                ny.collect_chunk(source(ny.GREENBELT), fetch, checkpoint=state, now=NOW)
            fetch.assert_not_called()

    def test_failed_detail_fetch_preserves_input_checkpoint_and_deadline_is_checked(self):
        first = ny.collect_chunk(source(ny.GREENBELT), Mock(return_value=greenbelt_listing(greenbelt_basic())), now=NOW)
        before = deepcopy(first["checkpoint"])
        with self.assertRaisesRegex(RuntimeError, "temporary transport"):
            ny.collect_chunk(source(ny.GREENBELT), Mock(side_effect=RuntimeError("temporary transport")), checkpoint=before, now=NOW)
        self.assertEqual(before, first["checkpoint"])
        fetch = Mock()
        with patch.object(ny, "monotonic", return_value=100), self.assertRaisesRegex(ValueError, "collection_deadline"):
            ny.collect_chunk(source(ny.GREENBELT), fetch, checkpoint=before, now=NOW, deadline_at=110)
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
