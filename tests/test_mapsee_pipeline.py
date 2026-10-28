"""Mapsee intake/security/occurrence tests with synthetic publisher responses."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from roomquest import preview_worker as worker
from roomquest.mapsee_adapter import (parse_ics, parse_jsonld, parse_localist,
    parse_open_data, parse_squarespace, parse_tribe, profiles, collect, timestamp)
from scripts.mapsee_catalog import build, canonical_url, country_evidence, priority


class MapseeTests(unittest.TestCase):
    def setUp(self):
        self.start=datetime.now(timezone.utc)+timedelta(days=2)
        self.iso=self.start.isoformat()

    def ics(self,extra="",start=None):
        start=start or self.start.strftime("%Y%m%dT%H%M%SZ")
        return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:fixture\r\n"
            f"SUMMARY:Factual Concert\r\nDTSTART:{start}\r\nLOCATION:Actual Hall\\, 123 Main St\\, Raleigh\\, NC\r\n"
            "URL:https://publisher.example.org/event/1\r\nDESCRIPTION:Do not copy this\r\n"
            "ATTACH:https://publisher.example.org/image.jpg\r\nCATEGORIES:Music,Community\r\n"+extra+
            "END:VEVENT\r\nEND:VCALENDAR\r\n")

    def test_source_count_and_positive_us_evidence(self):
        data=profiles()
        self.assertEqual(len(data),2632)
        self.assertTrue(all(s["country"]=="US" for s in data.values()))
        self.assertNotIn("US",country_evidence({"name":"Paris Club","geocode_suffix":", Paris","url":"https://example.fr/calendar.ics"})[:1])
        self.assertEqual(country_evidence({"geocode_suffix":", Raleigh, North Carolina"})[0],"US")
        self.assertEqual(country_evidence({"venue":{"country":"GB"},"name":"Durham"})[0],"GB")
        self.assertEqual(canonical_url("https://www.EXAMPLE.org/feed/?b=2&a=1&utm_source=test"),"https://example.org/feed?a=1&b=2")
        self.assertNotEqual(canonical_url("https://example.org/feed?calendar=1"),canonical_url("https://example.org/feed?calendar=2"))
        self.assertEqual(priority({"name":"Richmond District Neighborhood Center", "_metro":"San Francisco, United States", "venue":{"region":"CA"}}),3)
        self.assertEqual(priority({"name":"Chesterfield County Parks, VA", "geocode_suffix":", Chesterfield, Virginia"}),2)

    def test_ics_facts_only_and_real_recurring_occurrences(self):
        rows=parse_ics(self.ics("RRULE:FREQ=DAILY;COUNT=3\r\n"),{"url":"https://publisher.example.org/feed.ics"})
        self.assertEqual(len(rows),3)
        self.assertEqual(len({x["starts_at"] for x in rows}),3)
        self.assertTrue(all(r["event_url"]=="https://publisher.example.org/event/1" for r in rows))
        self.assertTrue(all(r["lat"] is None and "description" not in r and "image_url" not in r for r in rows))
        self.assertIn("Music",rows[0]["category"])

    def test_empty_parse_recurrence_and_timezone_are_distinct(self):
        self.assertEqual(parse_ics("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR",{}),[])
        with self.assertRaisesRegex(ValueError,"invalid_calendar_payload"):
            parse_ics("<html>Access denied</html>",{})
        with self.assertRaisesRegex(ValueError,"timezone_unresolved"):
            parse_ics(self.ics(start=self.start.strftime("%Y%m%dT%H%M%S")),{})
        with self.assertRaisesRegex(ValueError,"recurrence_invalid"):
            parse_ics(self.ics("RRULE:FREQ=NOT_A_FREQUENCY\r\n"),{})
        with self.assertRaisesRegex(ValueError,"timezone_ambiguous"):
            timestamp("2026-11-01T01:30:00","America/New_York")
        with self.assertRaisesRegex(ValueError,"timezone_nonexistent"):
            timestamp("2027-03-14T02:30:00","America/New_York")
        with self.assertRaisesRegex(ValueError,"unsupported_jsonld_event_shape"):
            parse_jsonld('<script type="application/ld+json">{"@type":"Organization","name":"Publisher"}</script>')

    def test_ongoing_event_keeps_its_actual_start_and_verified_end(self):
        from roomquest.mapsee_adapter import record
        start=datetime.now(timezone.utc)-timedelta(hours=2)
        end=datetime.now(timezone.utc)+timedelta(hours=2)
        r=record("Ongoing concert",start.isoformat(),end.isoformat(),"Actual Hall","123 Main St, Raleigh, NC","Raleigh","https://publisher.example.org/ongoing","1")
        self.assertEqual(r["starts_at"],start.isoformat())
        self.assertEqual(r["ends_at"],end.isoformat())

    def test_localist_every_explicit_occurrence_and_only_event_coordinates(self):
        d={"events":[{"event":{"id":123,"title":"Actual Walk","description":"Do not copy",
            "location_name":"Actual Park","address":"123 Main St, Raleigh, NC", "localist_url":"https://publisher.example.org/walk",
            "geo":{"latitude":"35.78","longitude":"-78.64"},"event_instances":[
                {"event_instance":{"start":self.iso}}, {"event_instance":{"start":(self.start+timedelta(days=1)).isoformat()}}]}}]}
        rows=parse_localist(d)
        self.assertEqual(len(rows),2);self.assertEqual(rows[0]["lat"],35.78)
        self.assertNotIn("description",rows[0])
        d["events"][0]["event"]["geo"]={}
        self.assertIsNone(parse_localist(d)[0]["lat"])

    def test_jsonld_complete_postal_address_and_no_catalog_defaults(self):
        d={"@context":"https://schema.org","@type":"MusicEvent","name":"Actual Concert","startDate":self.iso,
           "url":"https://publisher.example.org/concert","description":"Do not copy","image":"image.jpg",
           "location":{"@type":"Place","name":"Actual Hall","address":{"streetAddress":"123 Main Street","addressLocality":"Raleigh","addressRegion":"NC","postalCode":"27601"}}}
        rows=parse_jsonld('<script type="application/ld+json">'+json.dumps(d)+'</script>')
        self.assertEqual(rows[0]["venue_address"],"123 Main Street, Raleigh, NC, 27601")
        self.assertIsNone(rows[0]["lat"]);self.assertNotIn("description",rows[0])
        self.assertNotIn("image_url",rows[0])

    def test_wordpress_utc_and_squarespace_and_open_data(self):
        d={"events":[{"id":4,"title":"Actual Workshop","utc_start_date":self.start.strftime("%Y-%m-%d %H:%M:%S"),
           "url":"https://publisher.example.org/workshop","venue":{"venue":"Actual Hall","address":"123 Main St","city":"Raleigh","state":"NC","zip":"27601"}}]}
        rows=parse_tribe(d);self.assertIn("Raleigh, NC",rows[0]["venue_address"])
        d={"upcoming":[{"id":"4","title":"Actual Cleanup","startDate":int(self.start.timestamp()*1000),
          "fullUrl":"/events/cleanup","location":{"addressTitle":"Actual Park","addressLine1":"123 Main St","addressLine2":"Raleigh, NC"}}]}
        rows=parse_squarespace(d,"https://publisher.example.org/events")
        self.assertEqual(rows[0]["event_url"],"https://publisher.example.org/events/cleanup")
        rows=parse_open_data([{"name":"Actual Cleanup","start":self.iso,"street":"123 Main St, Raleigh, NC","link":"https://publisher.example.org/cleanup"}],
            {"map":{"title":"name","start":"start","address":"street","url":"link"}})
        self.assertEqual(len(rows),1);self.assertIsNone(rows[0]["lat"])

    def test_unregistered_or_changed_urls_fail_before_fetch(self):
        p=next(iter(profiles().values()))
        with patch("roomquest.preview_worker.fetch_publisher") as fetch:
            with self.assertRaisesRegex(worker.PreviewError,"unregistered_mapsee_source"):
                worker.preview_source({"source_key":p["source_key"],"feed_url":"https://other.example.org/"})
            fetch.assert_not_called()

    def test_expired_scheduled_deadline_does_not_start_another_fetch(self):
        p=next(iter(profiles().values()))
        with patch("roomquest.preview_worker.fetch_publisher") as fetch:
            with self.assertRaisesRegex(worker.PreviewError,"collection_deadline"):
                worker.preview_source({"source_key":p["source_key"],"feed_url":p["url"]},deadline_at=worker.monotonic()-1)
            fetch.assert_not_called()

    def test_honest_agent_and_robots_are_required_only_for_new_catalog(self):
        response=MagicMock(status_code=200,headers={},encoding="utf-8")
        response.iter_content.return_value=[b"BEGIN:VCALENDAR"]
        with patch("roomquest.preview_worker.validate_public_dns"),patch(
                "roomquest.preview_worker.robots_allowed",return_value=False),patch("roomquest.preview_worker.requests.Session") as factory:
            with self.assertRaisesRegex(worker.PreviewError,"robots_denied"):
                worker.fetch_publisher("https://publisher.example.org/feed.ics","text/calendar",respect_robots=True)
            factory.return_value.__enter__.return_value.get.assert_not_called()
        with patch("roomquest.preview_worker.validate_public_dns"),patch(
                "roomquest.preview_worker.robots_allowed",return_value=True),patch("roomquest.preview_worker.requests.Session") as factory:
            factory.return_value.__enter__.return_value.get.return_value=response
            worker.fetch_publisher("https://publisher.example.org/feed.ics","text/calendar",respect_robots=True)
            self.assertIn("RoomQuest",factory.return_value.__enter__.return_value.get.call_args.kwargs["headers"]["User-Agent"])
            self.assertNotIn("Mozilla",factory.return_value.__enter__.return_value.get.call_args.kwargs["headers"]["User-Agent"])

    def test_paginated_sources_cannot_silently_pass_as_empty(self):
        p={"type":"localist","config":{},"url":"https://publisher.example.org"}
        with self.assertRaisesRegex(ValueError,"pagination_limit"):
            collect({"feed_url":p["url"]},p,lambda *_:json.dumps({"events":[],"page":{"total":10}}))

    def test_large_sources_use_existing_hundred_record_rpc_in_batches(self):
        rows=[{"id":str(i)} for i in range(219)]
        result={"p_source_key":"municipal_mapsee_fixture","p_samples":[],"p_events":rows,"p_future_count":219,"p_venue_count":0,"p_error":None}
        with patch.object(worker,"preview_source",return_value=result),patch.object(worker,"supabase_rpc",side_effect=[100,100,19,None]) as rpc:
            output=worker._process_claimed_source({"source_key":"municipal_mapsee_fixture"})
            self.assertEqual(output["staged"],219)
            self.assertEqual([len(call.args[1]["p_events"]) for call in rpc.call_args_list[:3]],[100,100,19])

    def test_publisher_cooldown_does_not_end_a_mapsee_slot_early(self):
        source={"source_key":"municipal_mapsee_fixture"}
        with patch.object(worker,"supabase_rpc",side_effect=[[source],[],[source]]),patch.object(
                worker,"_process_claimed_source",return_value={"complete":1,"failed":0,"staged":1}),patch.object(
                worker,"sleep") as pause:
            result=worker.collect_bulk_previews(max_sources=2)
        self.assertEqual(result["claimed"],2)
        pause.assert_called_once_with(1.1)


if __name__=="__main__":unittest.main()
