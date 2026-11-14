"""Atlantic City parser facts survive the real category worker boundaries."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from roomquest import atlantic_city_community as community
from roomquest import atlantic_city_venues as venues
from roomquest import category_worker as category
from roomquest import preview_worker as worker
from roomquest import visit_atlantic_city as visit
from roomquest.publisher_pacing import observe_crawl_delay
from tests.test_visit_atlantic_city import NOW, SOURCE, detail, sitemap, url


CLAIM = "community_collector_claim_category"
READ = "community_collector_read_fetch_checkpoint"
WRITE = "community_collector_write_fetch_checkpoint"
STAGE = "community_collector_record_staged_events"
RECORD = "community_collector_record_preview_v2"
PUBLISH = "community_collector_publish_category"
FINISH = "community_collector_finish_category"


class Harness:
    def __init__(self, testcase, source, *, pages=None):
        self.testcase = testcase
        self.source = {**source, "source_id": 6001, "action": "collect"}
        self.pages = pages or {}
        self.clock = 100.0
        self.calls, self.fetched, self.staged = [], [], []
        self.checkpoint, self.revision = None, 0
        self.fail_stage = False
        self.reject_write = False
        self.pacing = 1
        self.expects_checkpoint = self.source.get("fetch_checkpoint_version") == 1
        for target, name, replacement in (
            (category, "monotonic", lambda: self.clock),
            (worker, "monotonic", lambda: self.clock),
            (visit, "monotonic", lambda: self.clock),
            (community, "monotonic", lambda: self.clock),
            (category, "sleep", self.sleep),
            (category, "supabase_rpc", self.rpc),
            (worker, "supabase_rpc", self.rpc),
            (worker, "fetch_publisher", self.fetch),
            (worker, "_future_datetime", lambda value: value.astimezone(timezone.utc)),
        ):
            active = patch.object(target, name, replacement)
            active.start()
            testcase.addCleanup(active.stop)
        original = visit.collect_chunk
        active = patch.object(visit, "collect_chunk", side_effect=lambda *args, **kwargs:
                              original(*args, **{**kwargs, "now": NOW}))
        active.start()
        testcase.addCleanup(active.stop)
        original_noyes = community.collect_chunk
        active = patch.object(community, "collect_chunk", side_effect=lambda *args, **kwargs:
                              original_noyes(*args, **{**kwargs, "now": NOW}))
        active.start()
        testcase.addCleanup(active.stop)

    def sleep(self, seconds):
        self.clock += seconds

    def fetch(self, target, accept, **kwargs):
        self.testcase.assertTrue(kwargs["respect_robots"])
        self.testcase.assertLess(self.clock, kwargs["deadline_at"])
        self.testcase.assertIn(target.split("/")[2], kwargs["allowed_hosts"])
        observe_crawl_delay(self.pacing)
        self.clock += 0.1
        self.fetched.append(target)
        result = self.pages[target]
        if isinstance(result, Exception):
            raise result
        return result

    def rpc(self, operation, payload, **kwargs):
        self.calls.append((operation, deepcopy(payload)))
        if operation == CLAIM:
            return deepcopy(self.source)
        if operation in (READ, WRITE):
            self.testcase.assertEqual(payload["p_category"], "html")
            self.testcase.assertEqual(payload["p_ticket"], "fixture-ticket")
            self.testcase.assertEqual(payload["p_source_key"], self.source["source_key"])
        if operation == READ:
            return {"checkpoint": deepcopy(self.checkpoint), "revision": self.revision}
        if operation == WRITE:
            self.testcase.assertEqual(payload["p_expected_revision"], self.revision)
            self.testcase.assertEqual(payload["p_publisher_crawl_delay_seconds"], self.pacing)
            self.testcase.assertFalse(payload["p_publisher_wait_unbounded"])
            if self.reject_write:
                return {"checkpoint_saved": False, "revision": self.revision}
            self.checkpoint = deepcopy(payload["p_checkpoint"])
            self.revision += 1
            return {"checkpoint_saved": True, "revision": self.revision}
        if operation == STAGE:
            if self.expects_checkpoint:
                self.testcase.assertEqual(self.checkpoint["cursor"], self.checkpoint["manifest_count"])
            if self.fail_stage:
                self.fail_stage = False
                raise worker.PreviewError("database_unavailable")
            self.staged.extend(deepcopy(payload["p_events"]))
            return len(payload["p_events"])
        if operation == RECORD:
            self.testcase.assertNotIn("p_parser_capability", payload)
            if payload["p_error"] is None and self.expects_checkpoint:
                self.testcase.assertEqual(self.checkpoint["cursor"], self.checkpoint["manifest_count"])
                # The corresponding database completion trigger owns deletion.
                self.checkpoint, self.revision = None, 0
            return None
        if operation == PUBLISH:
            self.testcase.assertIsNone(self.checkpoint)
            self.testcase.assertTrue(any(op == RECORD and row["p_error"] is None
                                         for op, row in self.calls))
            return {"outcome": "completed"}
        if operation == FINISH:
            return True
        raise AssertionError(operation)

    def run(self):
        return category.collect_category(self.source["kind"], "fixture-ticket")


class AtlanticCityWorkerTests(unittest.TestCase):
    def noyes(self, count=8):
        feed, kind, adapter = community.SOURCES[community.NOYES]
        source = {"source_key": community.NOYES, "feed_url": feed, "kind": kind,
                  "platform_adapter": adapter, "timezone": community.ZONE,
                  "fetch_checkpoint_version": 1}
        urls = [feed + f"/2026/workshop-{n}" for n in range(count)]
        prose = "Complete workshop description and participation instructions. " * 60 + "The final published condition."
        pages = {}
        listing = []
        for n, target in enumerate(urls):
            begins = datetime(2026, 11, 25, 23, tzinfo=timezone.utc) + timedelta(days=n)
            ends = begins + timedelta(hours=2)
            title = f"Community Art Workshop {n}"
            query = urlencode({"action": "TEMPLATE", "text": title,
                               "dates": begins.strftime("%Y%m%dT%H%M%SZ") + "/" + ends.strftime("%Y%m%dT%H%M%SZ"),
                               "location": "2200 Fairmount Ave, Atlantic City, NJ, 08401, United States"})
            later = f'<a class="eventitem-pager-newer" href="{urls[n+1]}">Later Event:</a>' if n + 1 < count else ""
            pages[target] = f'''<article class="eventitem"><h1 class="eventitem-title">{title}</h1>
              <a href="https://www.google.com/calendar/event?{query}">Google Calendar</a>
              <li class="eventitem-meta-address">Noyes Arts Garage 2200 Fairmount Ave Atlantic City, NJ, 08401</li>
              <div class="eventitem-column-content"><div class="sqs-layout"><p>{prose}</p></div></div></article>{later}'''
            if begins.month == 11:
                listing.append(f'<li><h1><a href="{target}">{title}</a></h1>{begins.strftime("%B %d, %Y")}</li>')
        pages[feed] = "<noscript><ul>" + "".join(listing) + "</ul></noscript>"
        return Harness(self, source, pages=pages), urls, prose

    def tourism(self, count=8, capability=1):
        prose = "Complete publisher paragraph. " * 100 + "The final full sentence."
        pages = {visit.SITEMAP: sitemap([url(n) for n in range(1, count + 1)])}
        pages.update({url(n): detail(n, prose=prose) for n in range(1, count + 1)})
        state = Harness(self, {**SOURCE, "fetch_checkpoint_version": capability}, pages=pages)
        return state, prose

    def test_visit_category_routes_to_checkpoint_and_only_stages_complete_manifest(self):
        state, prose = self.tourism()
        first = state.run()
        self.assertTrue(first["fetch_pending"])
        self.assertEqual(first["staged"], 0)
        self.assertEqual(state.checkpoint["cursor"], 6)
        self.assertEqual([op for op, _ in state.calls], [CLAIM, READ, WRITE, FINISH])
        self.assertEqual(state.calls[-1][1]["p_outcome"], "fetch_pending")
        second = state.run()
        self.assertEqual((second["complete"], second["failed"], second["staged"]), (1, 0, 8))
        self.assertTrue(all(row["description"] == prose for row in state.staged))
        self.assertTrue(all(row["venue_address"] == "1000 Boardwalk, Atlantic City, NJ 08401"
                            for row in state.staged))
        self.assertEqual([op for op, _ in state.calls].count(RECORD), 1)
        self.assertEqual([op for op, _ in state.calls].count(PUBLISH), 1)
        self.assertEqual(len({(row["id"], row["starts_at"]) for row in state.staged}), 8)
        self.assertTrue(all(state.fetched.count(url(n)) == 1 for n in range(1, 9)))

    def test_complete_visit_checkpoint_survives_staging_failure_without_detail_refetch(self):
        state, _ = self.tourism(2)
        state.fail_stage = True
        first = state.run()
        self.assertEqual(first["failed"], 1)
        self.assertEqual(state.checkpoint["cursor"], 2)
        self.assertNotIn(PUBLISH, [op for op, _ in state.calls])
        second = state.run()
        self.assertEqual(second["staged"], 2)
        self.assertEqual(second["complete"], 1)
        self.assertEqual(state.fetched.count(url()), 1)
        self.assertEqual(state.fetched.count(url(2)), 1)

    def test_visit_unacknowledged_checkpoint_never_reaches_staging_or_publication(self):
        state, _ = self.tourism(2)
        state.reject_write = True
        result = state.run()
        self.assertEqual(result["failed"], 1)
        self.assertNotIn(STAGE, [op for op, _ in state.calls])
        self.assertNotIn(PUBLISH, [op for op, _ in state.calls])

    def test_legacy_visit_without_advertised_checkpoint_cannot_publish_partial_calendar(self):
        state, _ = self.tourism(capability=None)
        result = state.run()
        self.assertEqual(result["failed"], 1)
        self.assertFalse(any(op in (READ, WRITE, STAGE, PUBLISH) for op, _ in state.calls))
        recorded = next(row for op, row in state.calls if op == RECORD)
        self.assertEqual(recorded["p_error"], "visit_atlantic_checkpoint_required")

    def test_registered_html_venues_preserve_full_prose_and_address_through_v2(self):
        source = {"source_key": venues.ANCHOR, "feed_url": venues.SOURCES[venues.ANCHOR][0],
                  "kind": "html", "platform_adapter": "html", "timezone": venues.ZONE}
        prose = "Full details about this local performance. " * 80 + "The last admission condition."
        payload = f'''<div class="collection-list"><div class="w-dyn-item">
          <a id="event-location" href="/shows/community-concert"></a>
          <div id="event-start">November 18, 2026 8:00 PM</div>
          <div id="event-title">Community Concert</div>
          <div id="event-desc"><p>{prose}</p></div></div></div>'''
        state = Harness(self, source, pages={source["feed_url"]: payload})
        original = venues.collect
        with patch.object(venues, "collect", side_effect=lambda *args, **kwargs:
                          original(*args, **kwargs, now=NOW)):
            result = state.run()
        self.assertEqual((result["complete"], result["failed"], result["staged"]), (1, 0, 1))
        self.assertEqual(state.staged[0]["description"], prose)
        self.assertEqual(state.staged[0]["venue_address"], venues.VENUES[venues.ANCHOR][1])
        self.assertEqual(state.staged[0]["category"], "")
        self.assertNotIn("publisher_categories", state.staged[0])
        self.assertNotIn(READ, [op for op, _ in state.calls])

    def test_county_ical_uses_same_description_preserving_route(self):
        feed, kind, adapter = community.SOURCES[community.COUNTY]
        source = {"source_key": community.COUNTY, "feed_url": feed, "kind": kind,
                  "platform_adapter": adapter, "timezone": community.ZONE}
        row = {"id": "official-library-program", "title": "Local book group",
               "starts_at": "2026-11-20T18:00:00+00:00", "ends_at": "2026-11-20T19:00:00+00:00",
               "event_url": "https://atlanticcounty.librarycalendar.com/event/local-book-group-1",
               "venue_name": "Absecon Branch Library", "lat": None, "lng": None,
               "venue_address": "305 New Jersey Avenue, Absecon, NJ 08201", "venue_city": "Absecon",
               "description": "A complete library narrative. " * 100 + "Final paragraph.", "category": ""}
        state = Harness(self, source, pages={feed: "official calendar"})

        def collect(selected, fetch, *, deadline_at):
            self.assertEqual(selected["source_key"], community.COUNTY)
            fetch(feed, "text/calendar")
            return [deepcopy(row)]

        with patch.object(community, "collect", side_effect=collect):
            result = state.run()
        self.assertEqual((result["complete"], result["failed"], result["staged"]), (1, 0, 1))
        self.assertEqual(state.staged, [row])
        self.assertEqual([op for op, _ in state.calls], [CLAIM, STAGE, RECORD, PUBLISH, FINISH])

    def test_noyes_pending_chunk_does_not_stage_and_complete_forward_chain_uses_v2(self):
        state, urls, prose = self.noyes()
        first = state.run()
        self.assertTrue(first["fetch_pending"])
        self.assertEqual((first["complete"], first["failed"], first["staged"]), (0, 0, 0))
        self.assertEqual([op for op, _ in state.calls], [CLAIM, READ, WRITE, FINISH])
        self.assertEqual(state.checkpoint["cursor"], 6)
        self.assertEqual(state.checkpoint["manifest_count"], 7)
        second = state.run()
        self.assertEqual((second["complete"], second["failed"], second["staged"]), (1, 0, 8))
        self.assertTrue(all(row["description"] == prose for row in state.staged))
        self.assertTrue(all(row["venue_address"] == "2200 Fairmount Ave, Atlantic City, NJ 08401"
                            for row in state.staged))
        self.assertEqual(len({row["event_url"] for row in state.staged}), 8)
        self.assertTrue(any(row["starts_at"].startswith("2026-12-") for row in state.staged))
        self.assertTrue(all(state.fetched.count(target) == 1 for target in urls))
        self.assertEqual([op for op, _ in state.calls].count(RECORD), 1)
        self.assertEqual([op for op, _ in state.calls].count(PUBLISH), 1)

    def test_noyes_complete_checkpoint_retries_staging_without_refetching_details(self):
        state, urls, prose = self.noyes(2)
        state.fail_stage = True
        first = state.run()
        self.assertEqual(first["failed"], 1)
        self.assertEqual(state.checkpoint["cursor"], state.checkpoint["manifest_count"])
        self.assertNotIn(PUBLISH, [op for op, _ in state.calls])
        result = state.run()
        self.assertEqual((result["complete"], result["failed"], result["staged"]), (1, 0, 2))
        self.assertTrue(all(row["description"] == prose for row in state.staged))
        self.assertTrue(all(state.fetched.count(target) == 1 for target in urls))

    def test_city_calendar_uses_its_host_and_only_stages_complete_checkpoint_via_v2(self):
        feed, kind, adapter = community.SOURCES[community.CITY]
        source = {"source_key": community.CITY, "feed_url": feed, "kind": kind,
                  "platform_adapter": adapter, "timezone": community.ZONE,
                  "fetch_checkpoint_version": 1}
        prose = "Full community program, participation and access instructions. " * 60 + "The final condition."
        manifest, pages = [], {}
        for n in range(1, 8):
            begins = datetime(2026, 11, 20, 18) + timedelta(days=n)
            ends = begins + timedelta(hours=2)
            title = f"Community Program {n}"
            manifest.append({"id": n, "title": title, "className": "Event", "allDay": False,
                             "start": begins.isoformat(), "end": ends.isoformat()})
            pages[f"https://www.acnj.gov/api/data/GetEvent?id={n}"] = json.dumps({
                "Event_ID": n, "Event_Title": title, "Event_IsCanceled": False, "Event_IsAllDay": False,
                "Event_StartDateTime": begins.isoformat(), "Event_EndDateTime": ends.isoformat(),
                "Event_Description": f"<p>{prose}</p>",
                "Event_Location": "Atlantic City Hall, 1301 Bacharach Boulevard, Atlantic City, NJ 08401"})
        listing = "https://www.acnj.gov/api/data/GetCalendarData?" + urlencode({
            "start": NOW.date().isoformat(), "end": (NOW.date() + timedelta(days=61)).isoformat()})
        pages[listing] = json.dumps(manifest)
        state = Harness(self, source, pages=pages)
        first = state.run()
        self.assertTrue(first["fetch_pending"])
        self.assertEqual([op for op, _ in state.calls], [CLAIM, READ, WRITE, FINISH])
        self.assertEqual(state.checkpoint["cursor"], 6)
        result = state.run()
        self.assertEqual((result["complete"], result["failed"], result["staged"]), (1, 0, 7))
        self.assertTrue(all(row["description"] == prose for row in state.staged))
        self.assertTrue(all(row["venue_address"] == "1301 Bacharach Boulevard, Atlantic City, NJ 08401"
                            for row in state.staged))
        self.assertEqual([op for op, _ in state.calls].count(RECORD), 1)
        self.assertEqual([op for op, _ in state.calls].count(PUBLISH), 1)
        self.assertTrue(all(state.fetched.count(f"https://www.acnj.gov/api/data/GetEvent?id={n}") == 1
                            for n in range(1, 8)))

    def test_greatday_all_details_finish_before_full_prose_reaches_v2_staging(self):
        from roomquest import greatday_atlantic_city as gd
        from tests.test_greatday_atlantic_city import card, detail, listing, SOURCE
        prose = 'November 21, 2026 from 11 a.m. to 1 p.m. ' + 'Complete participation details. ' * 100 + 'Final admission condition.'
        pages = {gd.URL: listing(''.join(card(f'program-{n}', f'Program {n}') for n in range(7)))}
        pages.update({gd.URL + f'/program-{n}': detail(f'Program {n}', prose) for n in range(7)})
        state = Harness(self, {**SOURCE, 'fetch_checkpoint_version': 1}, pages=pages)
        original = gd.collect_chunk
        with patch.object(gd, 'monotonic', lambda: state.clock), patch.object(gd, 'collect_chunk',
                side_effect=lambda *args, **kwargs: original(*args, **kwargs, now=NOW)):
            first = state.run()
            self.assertTrue(first['fetch_pending'])
            self.assertFalse(state.staged)
            result = state.run()
        self.assertEqual((result['complete'], result['failed'], result['staged']), (1, 0, 7))
        self.assertTrue(all(row['description'] == prose for row in state.staged))
        self.assertTrue(all(row['venue_address'] == '108 N Pennsylvania Avenue, Atlantic City, NJ 08401'
                            for row in state.staged))
        self.assertEqual([op for op, _ in state.calls].count(RECORD), 1)
        self.assertEqual([op for op, _ in state.calls].count(PUBLISH), 1)

    def test_greatday_legacy_path_cannot_publish_a_partial_manifest(self):
        from tests.test_greatday_atlantic_city import SOURCE
        state = Harness(self, SOURCE)
        result = state.run()
        self.assertEqual(result['failed'], 1)
        self.assertFalse(state.fetched)
        self.assertNotIn(STAGE, [op for op, _ in state.calls])
        recorded = next(payload for operation, payload in state.calls if operation == RECORD)
        self.assertEqual(recorded['p_error'], 'publisher_checkpoint_required')

    def test_stockton_department_full_html_body_survives_shared_worker(self):
        from roomquest import atlantic_city_stockton as stockton
        from tests.test_atlantic_city_stockton import department_card
        feed, kind, adapter = stockton.SOURCES[stockton.HRC]
        prose = 'Free and open to the public. ' + 'Complete lecture and participation information. ' * 100 + 'Final condition.'
        source = dict(source_key=stockton.HRC, feed_url=feed, kind=kind,
                      platform_adapter=adapter, timezone=stockton.ZONE)
        state = Harness(self, source, pages={feed: department_card(body='<p>' + prose + '</p>')})
        with patch.object(stockton, 'monotonic', lambda: state.clock):
            result = state.run()
        self.assertEqual((result['complete'], result['failed'], result['staged']), (1, 0, 1))
        self.assertEqual(state.staged[0]['description'], prose)
        self.assertEqual(state.staged[0]['venue_address'], stockton.MAIN_STREET)

    def test_pdf_binary_fetch_and_full_description_survive_shared_worker(self):
        from roomquest import atlantic_city_pdf_programs as pdf
        from tests.test_atlantic_city_pdf_programs import pdf_bytes
        prose = 'Full Moon Climb, ' + 'Complete public program and admission details. ' * 100 + 'Final condition.'
        payload = pdf_bytes('2026 Calendar of Events PROCEEDS BENEFIT ABSECON LIGHTHOUSE\n'
                            'Friday, December 4 Luminary Light Festival, 5pm to 7pm\n' + prose)
        source = dict(source_key=pdf.LIGHTHOUSE, feed_url=pdf.LIGHTHOUSE_DOCUMENT,
                      kind='html', platform_adapter='html', timezone=pdf.ZONE)
        state = Harness(self, source, pages={pdf.LIGHTHOUSE_DOCUMENT: payload})
        with patch.object(pdf, 'monotonic', lambda: state.clock):
            result = state.run()
        self.assertEqual((result['complete'], result['failed'], result['staged']), (1, 0, 1))
        self.assertEqual(state.staged[0]['description'], prose)
        self.assertEqual(state.staged[0]['venue_address'], '31 South Rhode Island Avenue, Atlantic City, NJ 08401')


if __name__ == "__main__":
    unittest.main()
