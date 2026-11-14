import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode

from icalendar import Calendar, Event

from roomquest import atlantic_city_markets_gaming as mg


NOW = datetime(2026, 11, 14, 22, tzinfo=timezone.utc)


def preview(title, start, end, venue, address, city, url, identity, *args, **kwargs):
    return {"id": identity, "title": title, "starts_at": start, "ends_at": end,
            "venue_name": venue, "venue_address": address, "venue_city": city,
            "event_url": url, "lat": kwargs.get("lat"), "lng": kwargs.get("lng"),
            "reason": None if kwargs.get("lat") is not None else "missing_verified_venue_geo"}


def tcg_html(body="Collect Pokemon and Magic cards.", date="Sunday December 20th, 2026"):
    return f'''<section><h1 data-aid="ABOUT_HEADLINE_RENDERED0">Next Show: {date}</h1>
    <div data-aid="ABOUT_DESCRIPTION_RENDERED0"><p>Showboat Resort Atlantic City NJ</p>
    <p>Early Bird 10AM-12PM $15</p><p>General Admission 12PM-5:00PM $10</p>
    <p>Kids 12 &amp; under free with paid Adult</p></div></section>
    <section><h2 data-aid="ABOUT_SECTION_TITLE_RENDERED">About Atlantic City TCG Show</h2>
    <div data-ux="ContentCard"><h4 data-aid="ABOUT_HEADLINE_RENDERED0">150 Vendor Tables</h4>
    <h4>Invisible adjacent sizing headline</h4>
    <div data-aid="ABOUT_DESCRIPTION_RENDERED0">{body}</div></div>
    <div data-ux="ContentCard"><h4 data-aid="ABOUT_HEADLINE_RENDERED1">Trading Card Tournaments</h4>
    <div data-aid="ABOUT_DESCRIPTION_RENDERED1">Next Tournament<br>Magic Tournament<br>TBD</div></div>
    </section><p data-aid="CONTACT_INFO_ADDRESS_REND">Showboat Resort Atlantic City, 801 Boardwalk, Atlantic City, NJ, USA</p>'''


def top_deck_html(calendar_id=mg.EHT_CALENDAR_ID, zone=mg.ZONE):
    src = base64.b64encode(calendar_id.encode()).decode().rstrip("=")
    query = urlencode({"title": "Top Deck Games - EHT Events", "ctz": zone, "src": src})
    return ('<h2>egg harbor township</h2><p>3003 English Creek Ave<br>Egg Harbor Township, NJ 08234</p>'
            f'<iframe src="https://calendar.google.com/calendar/embed?{query}"></iframe>')


def event(uid, start, *, body="Join our public game night. All players welcome.",
          location="3003 English Creek Ave, Egg Harbor Township, NJ 08234, USA", title="Public game night"):
    e = Event()
    e.add("UID", uid)
    e.add("SUMMARY", title)
    e.add("DTSTART", start)
    e.add("DTEND", start + timedelta(hours=2))
    e.add("DESCRIPTION", body)
    e.add("LOCATION", location)
    return e


def feed(*events):
    c = Calendar()
    c.add("VERSION", "2.0")
    c.add("X-WR-CALNAME", "04. EHT - Public")
    c.add("X-WR-TIMEZONE", mg.ZONE)
    for e in events:
        c.add_component(e)
    return c.to_ical().decode()


def reeds_page():
    essential = {"accessTokensUrl": mg.REEDS_VISITOR}
    model = {"site": {"metaSiteId": mg.REEDS_SITE}, "siteFeaturesConfigs": {
        "tpaCommons": {"widgetsClientSpecMapData": {
            "14fcce6e-b2fe-c9dc-1831-64f837bb83f6": {
                "appDefinitionId": mg.REEDS_APP, "widgetUrl": "https://calendar.boomte.ch/widget"}}}}}
    return (f'<link rel="canonical" href="{mg.SOURCES[mg.REEDS][0]}">'
            f'<script id="wix-essential-viewer-model" type="application/json">{json.dumps(essential)}</script>'
            f'<script id="wix-viewer-model" type="application/json">{json.dumps(model)}</script>'
            f'<div id="{mg.REEDS_COMPONENT}"><iframe></iframe></div>'
            '<p>5075 Spruce Ave<br>Egg Harbor Township, NJ 08234</p>')


def reeds_visitor(**claims):
    scope = {"instanceId": mg.REEDS_INSTANCE, "appDefId": mg.REEDS_APP, **claims}
    instance = "a" * 40 + "." + base64.urlsafe_b64encode(json.dumps(scope).encode()).decode().rstrip("=")
    return json.dumps({"metaSiteId": mg.REEDS_SITE, "apps": {mg.REEDS_APP: {"instance": instance}}})


def reeds_event(identity=1, **changes):
    return {"id": identity, "comp_id": mg.REEDS_COMPONENT, "instance": mg.REEDS_INSTANCE,
            "kind": "1", "title": "Farm workshop", "start": "2026-11-21T11:00",
            "end": "2026-11-21T14:00", "time_zone": mg.ZONE, "all_day": 0,
            "desc": "<p>Join the complete public workshop. Bring your own materials.</p>",
            "repeat": {"type": "", "advanced": "", "end": "720", "interval": "1",
                       "exclude": [], "additionalDates": []},
            "venue": {"locationType": "physical", "name": "Reed's Farm",
                      "address": "5075 Spruce Ave, Egg Harbor Township, NJ 08234, USA",
                      "lat": 39.3842615, "lng": -74.5865073}, **changes}


def reeds_calendar(*events, **changes):
    return json.dumps({"id": mg.REEDS_CALENDAR_ID, "comp_id": mg.REEDS_COMPONENT,
                       "instance": mg.REEDS_INSTANCE, "url": mg.SOURCES[mg.REEDS][0],
                       "published": 1, "time_zone": mg.ZONE, "events": list(events),
                       "synced_events": [], "tokens": [], **changes})


class AtlanticMarketsGamingTest(unittest.TestCase):
    @patch.object(mg, "record", side_effect=preview)
    def test_tcg_publishes_one_show_and_preserves_both_admission_phases(self, _):
        rows = mg._tcg(tcg_html(), NOW)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["starts_at"], "2026-12-20T10:00:00-05:00")
        self.assertEqual(row["ends_at"], "2026-12-20T17:00:00-05:00")
        self.assertIn("General Admission 12PM-5:00PM $10", row["description"])
        self.assertIn("Kids 12 & under free with paid Adult", row["description"])
        self.assertTrue(row["description"].endswith("Magic Tournament\nTBD"))
        self.assertNotIn("Invisible adjacent", row["description"])
        self.assertEqual(row["venue_address"], mg.VENUES[mg.TCG][1])
        self.assertEqual((row["lat"], row["lng"]), (39.361572000003, -74.418345000001))
        self.assertIsNone(row["reason"])

    @patch.object(mg, "record", side_effect=preview)
    def test_tcg_full_long_prose_and_escaped_literals_survive(self, _):
        text = "Read &lt;bring your binder&gt;. " + "A complete vendor condition. " * 100 + "Final booth instruction."
        body = "<p>" + text + "</p>"
        row = mg._tcg(tcg_html(body), NOW)[0]
        self.assertGreater(len(row["description"]), 2000)
        self.assertIn("Read <bring your binder>.", row["description"])
        self.assertIn("Final booth instruction.", row["description"])

    def test_tcg_missing_or_oversized_description_is_rejected(self):
        for body, error in [("<p> </p>", "description_missing"), ("x" * 12001, "description_limit")]:
            with self.subTest(body_length=len(body)), self.assertRaisesRegex(ValueError, error):
                mg._tcg(tcg_html(body), NOW)

    def test_tcg_wrong_weekday_ambiguous_year_or_disconnected_clocks_fail(self):
        for payload in [tcg_html(date="Monday December 20th, 2026"),
                        tcg_html(date="Sunday December 20th"),
                        tcg_html().replace("General Admission 12PM", "General Admission 1PM")]:
            with self.assertRaisesRegex(ValueError, "schedule_changed"):
                mg._tcg(payload, NOW)

    def test_tcg_venue_change_does_not_inherit_showboat(self):
        with self.assertRaisesRegex(ValueError, "venue_changed"):
            mg._tcg(tcg_html().replace("801 Boardwalk", "999 Boardwalk"), NOW)

    @patch.object(mg, "record", side_effect=preview)
    def test_tcg_past_and_beyond_window_are_not_projected(self, _):
        self.assertEqual(mg._tcg(tcg_html(), NOW + timedelta(days=61)), [])
        self.assertEqual(mg._tcg(tcg_html(), NOW - timedelta(days=61)), [])

    def test_top_deck_chooses_exact_eht_calendar(self):
        html = top_deck_html() + '<iframe src="https://calendar.google.com/calendar/embed?title=Cherry+Hill&amp;src=other"></iframe>'
        self.assertEqual(mg._top_deck_calendar(html), mg.EHT_ICS)
        with self.assertRaisesRegex(ValueError, "calendar_changed"):
            mg._top_deck_calendar(top_deck_html("wrong@group.calendar.google.com"))
        with self.assertRaisesRegex(ValueError, "calendar_changed"):
            mg._top_deck_calendar(top_deck_html(zone="America/Chicago"))
        with self.assertRaisesRegex(ValueError, "venue_changed"):
            mg._top_deck_calendar(top_deck_html().replace("3003 English Creek Ave", "1400 Haddonfield Road"))

    def test_wrong_calendar_payload_and_raw_component_limit_rejected(self):
        with self.assertRaisesRegex(ValueError, "calendar_changed"):
            mg._validated_calendar(feed().replace("04. EHT - Public", "Cherry Hill"))
        future = datetime.now(timezone.utc) + timedelta(days=2)
        with self.assertRaisesRegex(ValueError, "source_record_limit"):
            mg._validated_calendar(feed(*(event(str(i), future) for i in range(1001))))

    def test_blank_location_association_and_explicit_offsite_address(self):
        self.assertEqual(mg._top_deck_location("")[0], mg.VENUES[mg.TOP_DECK])
        self.assertEqual(mg._top_deck_location("Top Deck Games, 3003 English Creek Ave, Egg Harbor Township, NJ 08234, USA")[0], mg.VENUES[mg.TOP_DECK])
        offsite = mg._top_deck_location("Community Hall, 123 Main Street, Hammonton, NJ 08037, USA")
        self.assertEqual(offsite[0], ("Community Hall", "123 Main Street, Hammonton, NJ 08037", "Hammonton"))
        row = dict(venue_name=offsite[0][0], venue_address=offsite[0][1], lat=None, lng=None)
        self.assertIsNone(mg._point(row, mg.TOP_DECK)["lat"])
        self.assertIsNone(mg._top_deck_location("Some unspecified remote venue"))
        self.assertIsNone(mg._top_deck_location("123 Main Street, Hammonton, NJ"))
        self.assertIsNone(mg._top_deck_location("Community Hall, 123 Main Street, Hammonton, NJ"))
        self.assertEqual(mg._top_deck_location("3003 English Creek Ave, Egg Harbor Township, NJ")[0], mg.VENUES[mg.TOP_DECK])

    def test_reviewed_points_require_exact_source_venue_street(self):
        venue, address, _ = mg.VENUES[mg.TOP_DECK]
        row = dict(venue_name=venue, venue_address=address)
        self.assertEqual(mg._point(row, mg.TOP_DECK)["lat"], 39.433320000003)
        for key, name, street in [(mg.TCG, venue, address), (mg.TOP_DECK, "Other venue", address),
                                  (mg.TOP_DECK, venue, address.replace("3003", "3005"))]:
            self.assertNotIn("lat", mg._point(dict(venue_name=name, venue_address=street), key))

    def test_ics_real_expansion_retains_overrides_exclusions_and_long_plain_text(self):
        now = datetime.now(timezone.utc)
        start = (now + timedelta(days=2)).replace(hour=20, minute=0, second=0, microsecond=0)
        prose = "Read <bring ID>.\n" + "Full public tournament conditions. " * 90 + "Final prize condition."
        markup = ("<p>Read &lt;bring ID&gt;.</p><span data-layout=\"" + "x" * 12000
                  + "\"></span><p>" + "Full public tournament conditions. " * 90 + "Final prize condition.</p>")
        master = event("real-series", start, body=markup, location="")
        master.add("RRULE", {"FREQ": "WEEKLY", "COUNT": 4})
        master.add("EXDATE", start + timedelta(days=7))
        override = event("real-series", start + timedelta(days=15), body="A complete moved occurrence with &lt;special rules&gt;.",
                         location="123 Main Street, Hammonton, NJ 08037")
        override.add("RECURRENCE-ID", start + timedelta(days=14))
        canceled = event("real-series", start + timedelta(days=21))
        canceled.add("RECURRENCE-ID", start + timedelta(days=21))
        canceled.add("STATUS", "CANCELLED")
        rows = mg._top_deck(feed(master, override, canceled), now)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["description"], prose)
        self.assertGreater(len(rows[0]["description"]), 2000)
        self.assertEqual(rows[0]["venue_address"], mg.VENUES[mg.TOP_DECK][1])
        self.assertEqual(rows[1]["description"], "A complete moved occurrence with <special rules>.")
        self.assertEqual(rows[1]["venue_address"], "123 Main Street, Hammonton, NJ 08037")
        self.assertIsNone(rows[1].get("lat"))

    def test_ics_cancelled_master_and_private_title_are_not_published(self):
        now = datetime.now(timezone.utc)
        e = event("cancelled", now + timedelta(days=1))
        e.add("STATUS", "CANCELLED")
        e.add("RRULE", {"FREQ": "WEEKLY", "COUNT": 3})
        private = event("private", now + timedelta(days=2), title="Private party")
        self.assertEqual(mg._top_deck(feed(e, private), now), [])

    def test_ics_future_blank_and_over_limit_prose_are_rejected(self):
        now = datetime.now(timezone.utc)
        for body, error in [("", "description_missing"), ("x" * 12001, "description_limit")]:
            with self.subTest(length=len(body)), self.assertRaisesRegex(ValueError, error):
                mg._top_deck(feed(event("bad-prose", now + timedelta(days=2), body=body)), now)

    def test_expired_group_pruning_keeps_moved_override_and_rdate(self):
        now = datetime.now(timezone.utc)
        past = (now - timedelta(days=90)).replace(microsecond=0)
        moved = event("moved", past)
        moved.add("RRULE", {"FREQ": "WEEKLY", "UNTIL": past + timedelta(days=10)})
        override = event("moved", now + timedelta(days=3), body="The moved event has its full new instructions.")
        override.add("RECURRENCE-ID", past + timedelta(days=7))
        with_rdate = event("rdate", past)
        with_rdate.add("RRULE", {"FREQ": "WEEKLY", "UNTIL": past + timedelta(days=10)})
        with_rdate.add("RDATE", now + timedelta(days=4))
        expired = event("expired", past)
        expired.add("RRULE", {"FREQ": "WEEKLY", "UNTIL": past + timedelta(days=10)})
        parsed = mg._validated_calendar(feed(moved, override, with_rdate, expired))
        kept = mg._prune_expired_until_groups(parsed, now).walk("VEVENT")
        self.assertEqual({str(e["UID"]) for e in kept}, {"moved", "rdate"})
        rows = mg._top_deck(feed(moved, override, with_rdate, expired), now)
        self.assertEqual(len(rows), 2)
        self.assertIn("The moved event has its full new instructions.", [r["description"] for r in rows])

    def test_expired_malformed_rule_is_validated_before_pruning(self):
        now = datetime.now(timezone.utc)
        past = now - timedelta(days=90)
        e = event("dense-old", past)
        e.add("RRULE", {"FREQ": "SECONDLY", "UNTIL": past + timedelta(days=1)})
        with self.assertRaisesRegex(ValueError, "unsupported_dense_recurrence"):
            mg._top_deck(feed(e), now)

    @patch.object(mg, "record", side_effect=preview)
    def test_collect_source_fence_and_network_deadline(self, _):
        source = {"source_key": mg.TCG, "feed_url": mg.SOURCES[mg.TCG][0],
                  "kind": "html", "platform_adapter": "html", "timezone": mg.ZONE}

        def worker_fetch(url, accept):
            self.assertEqual((url, accept), (mg.SOURCES[mg.TCG][0], "text/html"))
            return tcg_html()

        fetch = Mock(side_effect=worker_fetch)
        self.assertEqual(len(mg.collect(source, fetch, now=NOW)), 1)
        self.assertEqual([call.args for call in fetch.call_args_list],
                         [(mg.SOURCES[mg.TCG][0], "text/html")])
        with self.assertRaisesRegex(ValueError, "unregistered_atlantic_markets_gaming_source"):
            mg.collect({**source, "feed_url": "https://other.example/"}, Mock())
        unfetched = Mock()
        with self.assertRaisesRegex(ValueError, "collection_deadline"):
            mg.collect(source, unfetched, deadline_at=0)
        unfetched.assert_not_called()
        self.assertTrue(mg.event_url(mg.TCG, mg.SOURCES[mg.TCG][0]))
        self.assertFalse(mg.event_url(mg.TCG, "https://atlanticcitytcgshow.com.evil.example/"))

    def test_robots_held_top_deck_cannot_dispatch_or_fetch(self):
        self.assertEqual(set(mg.SOURCES), {mg.TCG, mg.REEDS})
        self.assertNotIn(mg.TOP_DECK, mg.ALLOWED_HOSTS)
        source = {"source_key": mg.TOP_DECK, "feed_url": mg.HELD_SOURCES[mg.TOP_DECK][0],
                  "kind": "html", "platform_adapter": "html", "timezone": mg.ZONE}
        fetch = Mock()
        with self.assertRaisesRegex(ValueError, "unregistered_atlantic_markets_gaming_source"):
            mg.collect(source, fetch)
        fetch.assert_not_called()
        self.assertFalse(mg.event_url(mg.TOP_DECK, source["feed_url"]))

    @patch.object(mg, "record", side_effect=preview)
    def test_reeds_normal_public_page_guest_calendar_flow_uses_worker_interface(self, _):
        source = {"source_key": mg.REEDS, "feed_url": mg.SOURCES[mg.REEDS][0],
                  "kind": "html", "platform_adapter": "html", "timezone": mg.ZONE}
        visitor = reeds_visitor()
        api_url = mg._reeds_api_url(visitor)
        payloads = {source["feed_url"]: reeds_page(), mg.REEDS_VISITOR: visitor,
                    api_url: reeds_calendar(reeds_event())}

        def worker_fetch(url, accept):
            self.assertEqual(accept, "text/html" if url == source["feed_url"] else "application/json")
            return payloads[url]

        fetch = Mock(side_effect=worker_fetch)
        rows = mg.collect(source, fetch, now=NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual([call.args[0] for call in fetch.call_args_list],
                         [source["feed_url"], mg.REEDS_VISITOR, api_url])
        self.assertEqual(rows[0]["event_url"], source["feed_url"])
        self.assertNotIn("instance=", json.dumps(rows))
        self.assertEqual((rows[0]["lat"], rows[0]["lng"]), (39.3842615, -74.5865073))

    def test_reeds_public_widget_scope_rejects_identity_changes_and_account_claims(self):
        self.assertEqual(mg._reeds_context(reeds_page()), mg.REEDS_VISITOR)
        for page in [reeds_page().replace(mg.REEDS_APP, "other-app"),
                     reeds_page().replace(mg.REEDS_SITE, "other-site"),
                     reeds_page().replace(mg.REEDS_VISITOR, "https://other.example/access"),
                     reeds_page().replace("5075 Spruce Ave", "123 Spruce Ave")]:
            with self.assertRaisesRegex(ValueError, "calendar_changed|venue_changed"):
                mg._reeds_context(page)
        for visitor in [reeds_visitor(instanceId="other"), reeds_visitor(appDefId="other"),
                        reeds_visitor(siteMemberId="member"), reeds_visitor(permissions="OWNER")]:
            with self.assertRaisesRegex(ValueError, "public_widget_changed"):
                mg._reeds_api_url(visitor)
        for changes in [{"id": 9}, {"instance": "other"}, {"published": 0},
                        {"time_zone": "America/Chicago"}, {"synced_events": [{}]}]:
            with self.assertRaisesRegex(ValueError, "calendar_changed"):
                mg._reeds(reeds_calendar(**changes), NOW)

    @patch.object(mg, "record", side_effect=preview)
    def test_reeds_full_native_description_preserves_long_prose_and_escaped_literals(self, _):
        full = "Read <bring ID>.\n" + "All published workshop instructions. " * 100 + "Final cancellation condition."
        markup = ('<p>Read &lt;bring ID&gt;.</p><span data-layout="' + "x" * 12000 + '"></span><p>'
                  + "All published workshop instructions. " * 100 + "Final cancellation condition.</p>")
        row = mg._reeds(reeds_calendar(reeds_event(desc=markup)), NOW)[0]
        self.assertEqual(row["description"], full)
        self.assertGreater(len(row["description"]), 2000)
        self.assertEqual(row["venue_address"], mg.VENUES[mg.REEDS][1])
        with self.assertLogs(mg.log, level="WARNING") as captured:
            self.assertEqual(mg._reeds(reeds_calendar(reeds_event(desc="<p> </p>")), NOW), [])
        self.assertIn("description_unavailable", captured.output[0])
        with self.assertRaisesRegex(ValueError, "description_limit"):
            mg._reeds(reeds_calendar(reeds_event(desc="x" * 12001)), NOW)

    def test_reeds_weekly_iso_day_numeric_count_and_exclusions_match_widget(self):
        item = reeds_event(start="2026-11-15T11:00", end="2026-11-15T14:00",
                           repeat={"type": "Week", "advanced": ["6"], "end": "2", "interval": "1",
                                   "exclude": ["2026-11-28"], "additionalDates": []})
        dates = mg._boom_occurrences(item)
        self.assertEqual([start.date().isoformat() for start, _ in dates], ["2026-11-21", "2026-12-05"])
        self.assertTrue(all(start.isoweekday() == 6 and end - start == timedelta(hours=3) for start, end in dates))
        item["repeat"]["end"] = "2026-12-05"
        self.assertEqual(len(mg._boom_occurrences(item)), 1)

    def test_reeds_recurring_additions_and_unreviewed_kinds_fail_closed(self):
        addition = {"start": "2026-12-01T12:00", "end": "2026-12-01T13:00", "allDay": False}
        item = reeds_event(repeat={"type": "Week", "advanced": ["6"], "end": "2", "interval": "1",
                                   "exclude": [], "additionalDates": [addition]})
        with self.assertRaisesRegex(ValueError, "recurrence_changed"):
            mg._boom_occurrences(item)
        item["repeat"]["type"] = ""
        self.assertEqual(len(mg._boom_occurrences(item)), 2)
        for kind in ("2", "7", "unknown", None):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "calendar_changed"):
                mg._reeds(reeds_calendar(reeds_event(kind=kind)), NOW)

    @patch.object(mg, "record", side_effect=preview)
    def test_reeds_closure_suppresses_same_venue_but_preserves_explicit_offsite_event(self, _):
        closure = reeds_event(2, title="CLOSED FOR HOLIDAY", start="2026-11-21T09:00", end="2026-11-21T15:00")
        offsite = reeds_event(3, venue={"locationType": "physical", "name": "Community Hall",
                                     "address": "123 Main Street, Hammonton, NJ 08037", "lat": 39.3842615, "lng": -74.5865073})
        rows = mg._reeds(reeds_calendar(reeds_event(), closure, offsite), NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["venue_address"], "123 Main Street, Hammonton, NJ 08037")
        self.assertEqual(rows[0]["venue_name"], "Community Hall")
        self.assertIsNone(rows[0]["lat"])
        with self.assertRaisesRegex(ValueError, "schedule_changed"):
            mg._reeds(reeds_calendar({**closure, "all_day": 1}), NOW)

    def test_reeds_venue_requires_full_street_and_point_must_match_farm(self):
        item = reeds_event()
        self.assertEqual(mg._reeds_location(item)[3:], (39.3842615, -74.5865073))
        wrong = deepcopy(item)
        wrong["venue"].update(lat=40.7128, lng=-74.0060)
        self.assertEqual(mg._reeds_location(wrong)[3:], (None, None))
        for address in ["123 Main Street, Hammonton, NJ", "5075 Spruce Ave, Egg Harbor Township, NJ", "Egg Harbor Township"]:
            wrong["venue"]["address"] = address
            self.assertIsNone(mg._reeds_location(wrong))

    @patch.object(mg, "record", side_effect=preview)
    def test_reeds_preorder_and_provably_expired_cards_are_not_invented_events(self, _):
        preorder = reeds_event(2, title="Pie Preorders", start="2026-11-01T00:00", end="2026-11-20T00:00")
        expired = reeds_event(3, start="2025-11-01T11:00", end="2025-11-01T14:00", time_zone=None)
        self.assertEqual(len(mg._reeds(reeds_calendar(preorder, expired, reeds_event()), NOW)), 1)
        with self.assertRaisesRegex(ValueError, "schedule_changed"):
            mg._reeds(reeds_calendar(reeds_event(time_zone=None)), NOW)


if __name__ == "__main__":
    unittest.main()
