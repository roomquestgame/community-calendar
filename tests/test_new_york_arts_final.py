from copy import deepcopy
from datetime import datetime, timedelta, timezone
from html import escape
import json
import unittest
from unittest.mock import Mock, patch

from roomquest import new_york_arts_final as ny
from tests.test_new_york_arts import fake_record

NOW = datetime(2026, 11, 14, 23, tzinfo=timezone.utc)


def source(key):
    return dict(source_key=key, feed_url=ny.SOURCES[key][0], kind="html", platform_adapter="html", timezone=ny.ZONE)


def transit_event(index=1, **changes):
    item = dict(id=index, title=f"Transit family program {index}", status="publish", description="",
                timezone=ny.ZONE, start_date="2026-12-06 10:00:00", end_date="2026-12-06 11:00:00",
                utc_start_date="2026-12-06 15:00:00", utc_end_date="2026-12-06 16:00:00",
                url=f"https://www.nytransitmuseum.org/program/family-{index}/", categories=[dict(name="Family Programs")],
                modified_utc="2026-11-14 12:00:00")
    item.update(changes)
    return item


def transit_detail(item, body="Explore transport together.", location=None):
    event = {"@type": "Event", "name": item["title"], "url": item["url"],
             "eventStatus": "https://schema.org/EventScheduled", "startDate": "2026-12-06T10:00:00-05:00",
             "endDate": "2026-12-06T11:00:00-05:00", "location": location or {
                 "url": "https://www.nytransitmuseum.org/location/transit-museum/", "name": ny.TRANSIT_VENUE[0],
                 "geo": {"latitude": ny.TRANSIT_VENUE[3], "longitude": ny.TRANSIT_VENUE[4]}}}
    return (f'<script type="application/ld+json">{json.dumps({"@graph": [event]})}</script>'
            '<section id="tribe-events-pg-template"><div id="tribe-events-content"><div class="top-text-content">'
            f'<div class="text-content"><p>{escape(body)}</p></div><div class="text-content"><p>Full second column.</p></div>'
            '</div></div><section class="ip-collapse"><p>Final accessibility and ticket conditions.</p></section></section>')


def transit_fetch(count=3):
    events = [transit_event(i + 1) for i in range(count)]
    def fetch(url, accept):
        if url.startswith(ny.TRANSIT_API):
            return json.dumps(dict(events=events, total_pages=1))
        return transit_detail(next(e for e in events if e["url"] == url))
    return fetch, events


def fth_item(slug="program", title="Family program"):
    return dict(id=slug, title=title, url="https://www.flushingtownhall.org/show-details/" + slug, listing_date="Dec 5, 2026")


def fth_detail(title="Family program", body="DATE: December 5, 2026 TIME: 12 – 4 PM Join the full afternoon.", day="Dec 5, 2026", clock="12:00 PM"):
    return (f'<div id="content"><h1>{escape(title)}</h1><div id="tabsparent"><div id="about"><p>{escape(body)}</p></div>'
            f'<table><tbody><tr><td>{day}</td><td><span>{clock}</span></td></tr></tbody></table></div></div>')


def maker_context(identity="2000000000001", **changes):
    basic = dict(id=identity, url=f"https://www.eventbrite.com/e/fabrication-class-tickets-{identity}",
                 name="Fabrication class", summary="Learn fabrication.", organizer={"id": "18615337552"},
                 organizationId="61731221749", status="live", isListed=True, isProtected=False, isOnline=False,
                 startDate={"local": "2026-12-05T10:00:00", "utc": "2026-12-05T15:00:00Z", "timezone": ny.ZONE},
                 endDate={"local": "2026-12-05T14:00:00", "utc": "2026-12-05T19:00:00Z", "timezone": ny.ZONE},
                 venue={"name": "Makerspace NYC- Brooklyn Army Terminal", "address": {
                     "localizedMultiLineAddressDisplay": ["140 58th St", "Building B, Unit 1C", "Brooklyn, NY 11220"],
                     "latitude": "40.6455001", "longitude": "-74.0239072", "region": "NY", "city": "Brooklyn", "country": "US"}})
    basic.update(changes)
    return dict(basicInfo=basic, taxonomies={"category": "Hobbies", "subcategory": "DIY", "format": "Class"},
                structuredContent={"modules": [{"type": "text", "text": "<p>Complete workshop narrative.</p>"}], "widgets": {}}, gallery={"images": []})


def maker_detail(context):
    return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps({"props": {"pageProps": {"context": context}}}) + '</script>'


def maker_item(context):
    return {k: context["basicInfo"][k] for k in ("id", "url")}


def ics_event(identity=1, title="Play at BCM", desc="Full family play narrative.", day="20261205", start="100000", end="170000"):
    return (f"BEGIN:VEVENT\nUID:{identity}@brooklynkids.org\nSUMMARY:{title}\nDESCRIPTION:{desc}\n"
            f"DTSTART;TZID=America/New_York:{day}T{start}\nDTEND;TZID=America/New_York:{day}T{end}\n"
            f"URL:https://www.brooklynkids.org/events/program-{identity}/\nEND:VEVENT\n")


def ics(*events):
    return "BEGIN:VCALENDAR\nVERSION:2.0\n" + "".join(events) + "END:VCALENDAR\n"


def fake_preview(title, start, end, venue, lat, lng, url, identity, category="", **kwargs):
    return dict(title=title, starts_at=start.isoformat(), ends_at=end.isoformat() if end else None, id=identity)


def bpl_listing():
    return ('<div class="event-item"><div class="event-content">'
            '<a href="/calendar/roundtable-central-library-20261205-0700pm"><h4 class="card-title">Roundtable</h4></a>'
            '<div class="location">Central Library, Dweck Center</div>'
            '<p class="tags"><a>BPL Presents</a><a>author talks</a></p>Short excerpt…</div></div>')


def bpl_detail(body="Full author program and biographies."):
    return ('<link rel="canonical" href="https://www.bklynlibrary.org/calendar/roundtable-central-library-20261205-0700pm">'
            '<main><h1>Roundtable</h1><div class="meta"><div class="location">Central Library, Dweck Center</div></div>'
            '<p class="tags"><a>adults</a><a>BPL Presents</a><a>author talks</a></p>'
            '<div class="layout--twocol-section"><div class="layout__region--first"><p>' + escape(body) + '</p></div></div>'
            '<a href="/locations/central">Central Library</a><div itemprop="address">'
            '<div class="thoroughfare">10 Grand Army Plaza</div><span class="locality">Brooklyn</span>'
            '<span class="state">NY</span><span class="postal-code">11238</span></div>'
            '<div class="addeventatc"><span class="start">12/05/2026 07:00 pm</span><span class="end">12/05/2026 09:00 pm</span>'
            '<span class="timezone">America/New_York</span><span class="title">Roundtable</span>'
            '<span class="description">TRUNCATED CALENDAR EXCERPT…</span></div></main>')


class FinalArtsTests(unittest.TestCase):
    def setUp(self):
        self.patcher = patch.object(ny, "record", side_effect=fake_record)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_exact_profiles_and_event_identity(self):
        for key in ny.SOURCES:
            altered = source(key)
            altered["timezone"] = "UTC"
            with self.assertRaisesRegex(ValueError, "unregistered_nyc_arts_final"):
                ny.collect(altered, Mock())
        self.assertFalse(ny.event_url(ny.MAKER, "https://www.eventbrite.com.evil.test/e/a-tickets-2000000000001"))
        self.assertFalse(ny.event_url(ny.TRANSIT, "https://www.nytransitmuseum.org/program/family/?x=1"))

    def test_transit_complete_columns_and_policies_replace_blank_api(self):
        item = transit_event()
        manifest = ny._transit_manifest(Mock(return_value=json.dumps({"events": [item], "total_pages": 1})), 1e99, NOW)[0]
        body = "Full native program description. " * 90 + "Last native sentence."
        row = ny._transit_detail(manifest, transit_detail(item, body), NOW)[0]
        self.assertIn(body, row["description"])
        self.assertIn("Full second column.", row["description"])
        self.assertTrue(row["description"].endswith("Final accessibility and ticket conditions."))
        self.assertGreater(len(row["description"]), 2000)
        self.assertEqual(row["venue_address"], "99 Schermerhorn Street, Brooklyn, NY 11201")

    def test_transit_excludes_members_virtual_and_rejects_timezone_conflict(self):
        e = transit_event()
        events = [e, transit_event(2, categories=[dict(name="Members-Only")]), transit_event(3, is_virtual=True)]
        queue = ny._transit_manifest(Mock(return_value=json.dumps({"events": events, "total_pages": 1})), 1e99, NOW)
        self.assertEqual([r["id"] for r in queue], ["1"])
        with self.assertRaisesRegex(ValueError, "schedule_changed"):
            ny._transit_manifest(Mock(return_value=json.dumps({"events": [transit_event(timezone="UTC")], "total_pages": 1})), 1e99, NOW)

    def test_transit_offsite_never_inherits_museum(self):
        e = transit_event()
        item = ny._transit_manifest(Mock(return_value=json.dumps({"events": [e], "total_pages": 1})), 1e99, NOW)[0]
        with self.assertRaisesRegex(ValueError, "meeting_place_not_public"):
            ny._transit_detail(item, transit_detail(e, location={"name": "Off-Site"}), NOW)

    def test_transit_station_resolution_is_visibly_approximate(self):
        e = transit_event(url="https://www.nytransitmuseum.org/program/grandcentral-12-11/")
        item = ny._transit_manifest(Mock(return_value=json.dumps({"events": [e], "total_pages": 1})), 1e99, NOW)[0]
        row = ny._transit_detail(item, transit_detail(e, "Explore Grand Central and Grand Central Madison. Follow ticket instructions.", {"name": "Off-Site"}), NOW)[0]
        self.assertIn("approximate meeting point", row["venue_name"])
        self.assertIn("Follow ticket instructions.", row["description"])
        self.assertEqual(row["venue_address"], "89 East 42nd Street, New York, NY 10017")

    def test_missing_or_oversized_body_is_never_silently_truncated(self):
        with self.assertRaisesRegex(ValueError, "description_missing"):
            ny._body("<p> </p>")
        with self.assertRaisesRegex(ValueError, "description_limit"):
            ny._body("z" * 12001)
        self.assertEqual(ny._body("z" * 12000), "z" * 12000)

    def test_checkpoint_is_bounded_and_never_emits_partial_rows(self):
        fetch, _ = transit_fetch(3)
        first = ny.collect_chunk(source(ny.TRANSIT), fetch, now=NOW, max_details=1)
        self.assertFalse(first["complete"])
        self.assertEqual(first["events"], [])
        self.assertEqual(first["checkpoint"]["cursor"], 1)
        second = ny.collect_chunk(source(ny.TRANSIT), fetch, checkpoint=first["checkpoint"], now=NOW)
        self.assertTrue(second["complete"])
        self.assertEqual(len(second["events"]), 3)
        no_network = Mock(side_effect=AssertionError("completed retry must be replayable"))
        replay = ny.collect_chunk(source(ny.TRANSIT), no_network, checkpoint=second["checkpoint"], now=NOW)
        self.assertEqual(replay["events"], second["events"])

    def test_changed_final_manifest_resets_previously_hydrated_rows(self):
        fetch, events = transit_fetch(3)
        first = ny.collect_chunk(source(ny.TRANSIT), fetch, now=NOW, max_details=1)
        events[0]["modified_utc"] = "2026-11-14 22:30:00"
        second = ny.collect_chunk(source(ny.TRANSIT), fetch, checkpoint=first["checkpoint"], now=NOW, max_details=2)
        self.assertEqual(second["checkpoint"]["cursor"], 0)
        self.assertFalse(second["complete"])
        self.assertEqual(second["events"], [])
        self.assertNotEqual(first["checkpoint"]["manifest_hash"], second["checkpoint"]["manifest_hash"])

    def test_slow_initial_manifest_persists_zero_cursor_then_resumes_without_listing(self):
        implementation, _ = transit_fetch(3)
        fetch = Mock(side_effect=implementation)
        with patch.object(ny, "monotonic", return_value=100):
            first = ny.collect_chunk(source(ny.TRANSIT), fetch, now=NOW, deadline_at=110)
        self.assertEqual(first["checkpoint"]["cursor"], 0)
        self.assertFalse(first["complete"])
        self.assertEqual(fetch.call_count, 1)
        fetch.reset_mock()
        second = ny.collect_chunk(source(ny.TRANSIT), fetch, checkpoint=first["checkpoint"], now=NOW, max_details=1)
        self.assertEqual(second["checkpoint"]["cursor"], 1)
        self.assertEqual(fetch.call_count, 1)
        self.assertNotIn("wp-json", fetch.call_args.args[0])

    def test_cold_ten_second_pacing_progresses_then_verifies_before_publish(self):
        implementation, _ = transit_fetch(3)
        state = None
        phases = []
        for _ in range(3):
            elapsed = [0]
            calls = []
            def paced_fetch(url, accept):
                # Cold robots + ten-second wait + response; subsequent GETs
                # are separated by another ten-second publisher wait.
                elapsed[0] += 13 if not calls else 12
                calls.append(url)
                self.assertLessEqual(elapsed[0], 36)
                return implementation(url, accept)
            with patch.object(ny, "monotonic", side_effect=lambda: elapsed[0]):
                result = ny.collect_chunk(source(ny.TRANSIT), paced_fetch, checkpoint=state,
                                          now=NOW, deadline_at=36)
            state = result["checkpoint"]
            phases.append((state["cursor"], result["complete"]))
        self.assertEqual(phases, [(1, False), (3, False), (3, True)])
        self.assertEqual(len(result["events"]), 3)

    def test_checkpoint_tampered_street_source_counts_and_clock_are_rejected(self):
        fetch, _ = transit_fetch(3)
        state = ny.collect_chunk(source(ny.TRANSIT), fetch, now=NOW, max_details=1)["checkpoint"]
        variants = []
        for mutate in [lambda s: s["events"][0].update(venue_address="1 Fake Street, New York, NY 10001"),
                       lambda s: s.update(source_key=ny.MAKER), lambda s: s.update(cursor=2),
                       lambda s: s.update(started_at="2026-11-14T18:00:00-05:00"),
                       lambda s: s["events"][0].update(starts_at="2026-12-07T10:00:00-05:00")]:
            value = deepcopy(state); mutate(value); variants.append(value)
        for value in variants:
            with self.assertRaisesRegex(ValueError, "checkpoint_invalid"):
                ny.collect_chunk(source(ny.TRANSIT), fetch, checkpoint=value, now=NOW)

    def test_checkpoint_expiry_and_input_timezone_normalize_to_utc(self):
        fetch, _ = transit_fetch(3)
        first = ny.collect_chunk(source(ny.TRANSIT), fetch, now=NOW.astimezone(ny.ZoneInfo(ny.ZONE)), max_details=1)
        self.assertTrue(first["checkpoint"]["started_at"].endswith("+00:00"))
        expired = ny.collect_chunk(source(ny.TRANSIT), fetch, checkpoint=first["checkpoint"], now=NOW + timedelta(hours=5), max_details=1)
        self.assertEqual(expired["checkpoint"]["started_at"], (NOW + timedelta(hours=5)).isoformat())

    def test_bcm_full_ics_body_member_filter_and_numbered_address(self):
        body = "Complete family program. " * 100 + "Final admission details."
        payload = ics(ics_event(desc=body), ics_event(2, title="Member Monday", desc="Members-only hours."))
        with patch("roomquest.preview_worker._preview", side_effect=fake_preview):
            rows = ny.collect(source(ny.BCM), Mock(return_value=payload), now=NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["description"], body)
        self.assertEqual(rows[0]["venue_address"], "145 Brooklyn Avenue, Brooklyn, NY 11213")
        self.assertEqual((rows[0]["lat"], rows[0]["lng"]), ny.BCM_VENUE[3:])

    def test_bcm_native_feed_cap_cannot_hide_thirty_day_coverage(self):
        payload = ics(*(ics_event(i + 1, day="20261120") for i in range(50)))
        with self.assertRaisesRegex(ValueError, "horizon_incomplete"):
            ny.collect(source(ny.BCM), Mock(return_value=payload), now=NOW)
        payload = ics(ics_event(day="20270110"))
        with patch("roomquest.preview_worker._preview", side_effect=fake_preview):
            self.assertEqual(ny.collect(source(ny.BCM), Mock(return_value=payload), now=NOW), [])

    def test_fth_reuses_actual_show_table_and_full_about_not_mobile_duplicate(self):
        body = "DATE: December 5, 2026 TIME: 12 – 4 PM " + "Complete program. " * 140
        detail = fth_detail(body=body) + '<div id="collapse-about">Duplicated mobile narrative.</div>'
        row = ny._flushing_detail(fth_item(), detail, NOW)[0]
        self.assertEqual(row["starts_at"], "2026-12-05T12:00:00-05:00")
        self.assertEqual(row["ends_at"], "2026-12-05T16:00:00-05:00")
        self.assertNotIn("Duplicated mobile", row["description"])
        self.assertGreater(len(row["description"]), 2000)

    def test_fth_offsite_venue_and_grantee_guard(self):
        slug = "max-pollak-the-rumbatap-jam"
        row = ny._flushing_detail(fth_item(slug), fth_detail(body="Community Arts Grantee Location: Terraza 7 40-19 Gleane St, Elmhurst, NY 11373. Dance with us."), NOW)[0]
        self.assertEqual(row["venue_address"], "40-19 Gleane Street, Elmhurst, NY 11373")
        with self.assertRaisesRegex(ValueError, "venue_unreviewed"):
            ny._flushing_detail(fth_item(), fth_detail(body="Community Arts Grantee Location: Another venue"), NOW)

    def test_fth_exhibition_hours_are_explicit_finite_occurrences(self):
        body = ("Lorimoto Gallery 1623 Hancock St, Queens, NY 11385. Exhibition November 2 through November 15, 2026 "
                "open Tuesday through Sunday, 12:00 to 6:00 PM. Panel Saturday, November 14th at 6:30 PM.")
        rows = ny._flushing_detail(fth_item("stones-throw", "Stone's Throw"), fth_detail("Stone's Throw", body), NOW)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["starts_at"] for r in rows}, {"2026-11-14T18:30:00-05:00", "2026-11-15T12:00:00-05:00"})
        self.assertEqual({r["venue_address"] for r in rows}, {"1623 Hancock Street, Queens, NY 11385"})

    def test_maker_public_owned_event_retains_every_text_module_and_native_point(self):
        context = maker_context()
        context["structuredContent"]["modules"] += [{"type": "text", "text": "<p>" + "Safety details. " * 160 + "Final materials condition.</p>"}]
        row = ny._maker_detail(maker_item(context), maker_detail(context), NOW)[0]
        self.assertIn("Complete workshop narrative.", row["description"])
        self.assertTrue(row["description"].endswith("Final materials condition."))
        self.assertGreater(len(row["description"]), 2000)
        self.assertEqual(row["venue_address"], "140 58th Street Building B Unit 1C, Brooklyn, NY 11220")
        context["basicInfo"]["organizer"]["id"] = "another-organizer"
        with self.assertRaisesRegex(ValueError, "identity_changed"):
            ny._maker_detail(maker_item(context), maker_detail(context), NOW)

    def test_maker_series_uses_prose_sessions_not_multi_month_continuous_event(self):
        context = maker_context(isParentEvent=True,
            startDate={"local": "2026-11-12T17:30:00", "utc": "2026-11-12T22:30:00Z", "timezone": ny.ZONE},
            endDate={"local": "2026-12-08T19:30:00", "utc": "2026-12-09T00:30:00Z", "timezone": ny.ZONE})
        context["structuredContent"]["modules"][0]["text"] = "<p>Thursday, November 12th - 5:30 - 7:30pm</p><p>Tuesday, December 8th - 5:30 - 7:30pm</p><p>Complete safety narrative.</p>"
        rows = ny._maker_detail(maker_item(context), maker_detail(context), NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["starts_at"], "2026-12-08T17:30:00-05:00")
        self.assertEqual(rows[0]["ends_at"], "2026-12-08T19:30:00-05:00")

    def test_maker_short_summary_cannot_substitute_full_body_and_new_widgets_hold(self):
        context = maker_context()
        context["structuredContent"]["modules"] = []
        with self.assertRaisesRegex(ValueError, "description_missing"):
            ny._maker_detail(maker_item(context), maker_detail(context), NOW)
        context = maker_context()
        context["structuredContent"]["widgets"] = {"faqs": [{"question": "What to bring?", "answer": "Materials."}]}
        with self.assertRaisesRegex(ValueError, "description_shape_changed"):
            ny._maker_detail(maker_item(context), maker_detail(context), NOW)

    def test_bpl_uses_full_native_body_not_truncated_calendar_description(self):
        item = ny._bpl_manifest(Mock(return_value=bpl_listing()), 1e99, NOW)[0]
        body = "Complete author biography and program. " * 140 + "Final publisher condition."
        row = ny._bpl_detail(item, bpl_detail(body), NOW)[0]
        self.assertEqual(row["description"], body)
        self.assertNotIn("TRUNCATED", row["description"])
        self.assertEqual(row["venue_name"], "Central Library, Dweck Center")
        self.assertEqual(row["venue_address"], "10 Grand Army Plaza, Brooklyn, NY 11238")
        self.assertEqual(row["starts_at"], "2026-12-05T19:00:00-05:00")
        self.assertEqual(row["publisher_categories"], ["adults", "BPL Presents", "author talks"])

    def test_bpl_scope_pagination_and_branch_address_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "bpl_scope_changed"):
            ny._bpl_manifest(Mock(return_value=bpl_listing().replace("BPL Presents", "Other series")), 1e99, NOW)
        with self.assertRaisesRegex(ValueError, "pagination_limit"):
            ny._bpl_manifest(Mock(return_value=bpl_listing() + '<nav class="pager"><a href="?page=1">Next</a></nav>'), 1e99, NOW)
        item = ny._bpl_manifest(Mock(return_value=bpl_listing()), 1e99, NOW)[0]
        with self.assertRaisesRegex(ValueError, "venue_changed"):
            ny._bpl_detail(item, bpl_detail().replace("11238", "10001"), NOW)
        with self.assertRaisesRegex(ValueError, "schedule_changed"):
            ny._bpl_detail(item, bpl_detail().replace("07:00 pm", "08:00 pm"), NOW)

    def test_bpl_encoded_publisher_slug_allowed_but_encoded_traversal_rejected(self):
        self.assertTrue(ny.event_url(ny.BPL, "https://www.bklynlibrary.org/calendar/classical-jo%C3%A3o-central-20261115-0400pm"))
        self.assertFalse(ny.event_url(ny.BPL, "https://www.bklynlibrary.org/calendar/%2E%2E%2Fprivate-20261115-0400pm"))
        self.assertIsNotNone(ny.photo_url(ny.BPL, "https://static.bklynlibrary.org/prod/public/images/events/calendar/poster.jpg"))


if __name__ == "__main__":
    unittest.main()
