"""Evidence matching, future-safe intake and bounded venue lookup regressions."""
from datetime import datetime, timedelta, timezone
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from roomquest import venue_resolver as v
from roomquest.preview_worker import parse_ics_preview, parse_jsonld_preview

CLAIM = {"venue_key": "fixture", "lease_id": "fixture-lease",
         "venue_name": "Witherspoon Student Center, African American Cultural Center (218)",
         "event_title": "You Are Here Exhibition", "event_url": "https://calendar.ncsu.edu/event/exhibit",
         "publisher_name": "NC State African American Cultural Center",
         "publisher_url": "https://calendar.ncsu.edu/"}
PLACE = {"@type": "Place", "name": "Witherspoon Student Center", "address": {
    "@type": "PostalAddress", "streetAddress": "2810 Cates Ave", "addressLocality": "Raleigh",
    "addressRegion": "NC", "postalCode": "27606", "addressCountry": "US"}}


def page(data):
    return '<script type="application/ld+json">' + json.dumps(data) + '</script>'


class EvidenceTests(unittest.TestCase):
    def test_room_suffix_matches_real_parent_building(self):
        self.assertTrue(v.venue_matches(CLAIM["venue_name"], PLACE["name"]))
        result = v.extract_candidates(page(PLACE), CLAIM["event_url"], CLAIM)
        self.assertEqual(len(result), 1)
        self.assertIn("2810 Cates Ave, Raleigh, NC", result[0]["address"])

    def test_generic_room_and_wrong_venue_do_not_match(self):
        self.assertFalse(v.venue_matches("Meeting Room", "Student Center"))
        self.assertFalse(v.venue_matches("West Caldwell Library", "Glen Ridge Library"))
        unrelated = {**PLACE, "name": "Talley Student Union"}
        self.assertEqual(v.extract_candidates(page(unrelated), CLAIM["event_url"], CLAIM), [])

    def test_exact_event_location_can_supply_actual_away_address(self):
        actual = {"name": "Away Gallery", "address": {"streetAddress": "400 W Church St",
                  "addressLocality": "Orlando", "addressRegion": "FL", "addressCountry": "US"}}
        event = {"@type": "VisualArtsEvent", "name": CLAIM["event_title"], "location": actual}
        result = v.extract_candidates(page(event), CLAIM["event_url"], CLAIM)
        self.assertIn("Orlando, FL", result[0]["address"])
        self.assertNotIn("Raleigh", result[0]["address"])

    def test_unrelated_event_metadata_is_not_evidence(self):
        event = {"@type": "Event", "name": "Unrelated event", "location": PLACE}
        self.assertEqual(v.extract_candidates(page(event), CLAIM["event_url"], CLAIM), [])

    def test_contact_page_is_bound_to_venue_identity(self):
        claim = {**CLAIM, "venue_name": "Glen Ridge Public Library"}
        text = '<h1>Glen Ridge Public Library</h1><address>240 Ridgewood Avenue<br>Glen Ridge, NJ 07028</address>'
        result = v.extract_candidates(text, "https://www.glenridgelibrary.org/contact-us.html", claim)
        self.assertEqual(len(result), 1)
        self.assertIn("240 Ridgewood Avenue", result[0]["address"])
        self.assertEqual(v.extract_candidates(text.replace('Glen Ridge Public Library', 'Other Organization'),
                                             CLAIM["event_url"], claim), [])

    def test_multiple_distinct_addresses_require_review(self):
        other = {**PLACE, "address": {**PLACE["address"], "streetAddress": "100 Other Street"}}
        result = v.resolve(CLAIM, fetcher=lambda _: page([PLACE, other]), clock=lambda: 0, deadline=20)
        self.assertIsNone(result)

    def test_complete_us_address_required(self):
        for address in [{}, {"streetAddress": "2810 Cates Ave"},
                        {**PLACE["address"], "addressCountry": "Canada"},
                        {**PLACE["address"], "streetAddress": "PO Box 123"}]:
            self.assertIsNone(v.structured_address(address))

    def test_follow_only_publisher_local_venue_links(self):
        html = ('<a href="/witherspoon_student_center">Witherspoon Student Center</a>'
                '<a href="https://evil.example/venue">Witherspoon Student Center</a>'
                '<a href="https://127.0.0.1/venue">Witherspoon Student Center</a>')
        self.assertEqual(v.next_links(html, CLAIM["event_url"], CLAIM),
                         ["https://calendar.ncsu.edu/witherspoon_student_center"])

    def test_event_then_venue_page_and_fetch_bound(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return ('<a href="/witherspoon">Witherspoon Student Center</a>'
                    if len(calls) == 1 else page(PLACE))
        self.assertIsNotNone(v.resolve(CLAIM, fetcher=fetch, clock=lambda: 0, deadline=20))
        self.assertEqual(len(calls), 2)

    def test_public_url_checks_before_network(self):
        for url in ['https://127.0.0.1/a','https://user:password@example.org/a',
                    'http://example.org/a','https://example.org:444/a']:
            with patch.object(v.requests, 'Session') as session:
                with self.assertRaises(ValueError):
                    v.fetch_page(url)
                session.return_value.__enter__.return_value.get.assert_not_called()

    def test_json_graph_and_wrong_event_footer(self):
        graph = {"@graph": [{"@type": "Organization", "name": "Unrelated Publisher", "address": PLACE["address"]}, PLACE]}
        self.assertEqual(len(v.extract_candidates(page(graph), CLAIM["event_url"], CLAIM)), 1)
        footer = '<h1>An unrelated event</h1><footer>2810 Cates Ave, Raleigh, NC 27606</footer>'
        self.assertEqual(v.extract_candidates(footer, CLAIM["event_url"], CLAIM), [])


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
    def database(self, action, payload):
        self.calls.append((action, payload))
        return [CLAIM] if action == 'claim' else {"recorded": True}

    def test_disabled_or_nonproduction_never_claims(self):
        with patch.dict(os.environ, {"VERCEL_ENV": "preview", "FORWARD_GEOCODER_ENABLED": "true"}):
            self.assertEqual(v.run_batch(database=self.database)["claimed"], 0)
        self.assertEqual(self.calls, [])

    def test_claimed_identity_and_evidence_are_submitted_once(self):
        resolver = MagicMock(return_value={"address": "2810 Cates Ave, Raleigh, NC", "evidence_url": CLAIM['event_url'],
                                           "evidence_name": PLACE['name'], "method": 'venue_jsonld'})
        with patch.dict(os.environ, {"VERCEL_ENV": "production", "FORWARD_GEOCODER_ENABLED": "true"}):
            result = v.run_batch(database=self.database, resolver=resolver)
        self.assertEqual(result['resolved'], 1)
        self.assertEqual([x[0] for x in self.calls], ['claim','submit'])
        self.assertEqual(self.calls[-1][1]['lease_id'], CLAIM['lease_id'])

    def test_uncertain_result_is_reviewed_without_geocoder_request(self):
        with patch.dict(os.environ, {"VERCEL_ENV": "production", "FORWARD_GEOCODER_ENABLED": "true"}):
            result = v.run_batch(database=self.database, resolver=lambda *a,**k: None)
        self.assertEqual(result['review'], 1)
        self.assertEqual(self.calls[-1][1]['reason'], 'needs_review')


class IntakeTests(unittest.TestCase):
    def test_ics_category_objects_decode_to_publisher_labels(self):
        when = (datetime.now(timezone.utc)+timedelta(days=2)).strftime('%Y%m%dT%H%M%SZ')
        ics = ('BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:label-fixture\r\n'
               'SUMMARY:Community program\r\nDTSTART:'+when+'\r\nCATEGORIES:Arts,Exhibition\r\n'
               'CATEGORIES:Music\r\nLOCATION:Gallery\r\nURL:https://example.org/event\r\n'
               'END:VEVENT\r\nEND:VCALENDAR\r\n')
        rows = parse_ics_preview(ics)
        self.assertEqual(rows[0]['category'], 'Arts, Exhibition, Music')
        self.assertNotIn('object at', rows[0]['category'])

    def test_jsonld_preserves_complete_address_components(self):
        date = (datetime.now(timezone.utc)+timedelta(days=2)).isoformat()
        event = {"@type": "Event", "name": "Exhibition", "startDate": date,
                 "url": CLAIM['event_url'], "location": PLACE}
        rows = parse_jsonld_preview(page(event))
        self.assertIn('Raleigh, NC, 27606', rows[0]['venue_address'])


if __name__ == '__main__':
    unittest.main()
