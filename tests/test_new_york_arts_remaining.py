from copy import deepcopy
from datetime import datetime, timezone
from html import escape
import json
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from roomquest import new_york_arts_remaining as ny
from tests.test_new_york_arts import fake_record

NOW = datetime(2026, 11, 14, 22, tzinfo=timezone.utc)


def source(key):
    return dict(source_key=key, feed_url=ny.SOURCES[key][0], kind="html", platform_adapter="html", timezone=ny.ZONE)


def cp_event(identity=7, **changes):
    item = dict(id=identity, title="Community Resource Fair", status="publish", description="Meet community groups and learn about local services.",
                start_date="2026-12-04 11:00:00", end_date="2026-12-04 14:00:00",
                utc_start_date="2026-12-04 16:00:00", utc_end_date="2026-12-04 19:00:00", timezone=ny.ZONE,
                url="https://www.commonpoint.org/event/resource-fair", categories=[dict(id=4, name="Event")],
                venue=dict(venue="Sam Field Center", address="58-20 Little Neck Parkway", city="Little Neck", state="New York", zip="11362"))
    item.update(changes)
    return item


def cp_payload(*items, total_pages=1):
    return json.dumps(dict(events=items, total_pages=total_pages))


def nyu_event(identity=7, **changes):
    item = dict(id=identity, title="Public performance", url=f"https://events.nyu.edu/event/{identity}-public-performance",
                date_iso="2026-11-18T19:30:00-05:00", date_utc="2026-11-19 00:30:00", date2_iso=None,
                date2_utc=None, timezone=ny.ZONE, status=1, event_types=["Arts", " Open to the Public"],
                description="A full performance narrative with an em dash — and a final condition.", summary="Opening introduction.", cost="Free",
                location_id=471, location="Skirball Center for the Performing Arts", location_title="Skirball Center for the Performing Arts",
                location_latitude=40.729795, location_longitude=-73.997749)
    item.update(changes)
    return item


def nyu_payload(*items, page=1, total_pages=1, total_results=None, fields=None):
    return json.dumps(dict(meta=dict(type="events", page=page, total_pages=total_pages, per_page=100,
                                    total_results=len(items) if total_results is None else total_results,
                                    response_fields=ny.NYU_FIELDS.split(",") if fields is None else fields), data=items), ensure_ascii=False)


def gl_place(street="886 Fulton St"):
    return ('<div class="event-details__location--location"><p class="address">'
            '<span class="address-line1">Hops Hill at Fulton</span>'
            f'<span class="address-line2">{street}</span><span class="locality">Brooklyn</span>'
            '<span class="administrative-area">NY</span><span class="postal-code">11238</span></p></div>')


def gl_card(index):
    return (f'<article class="event-list" id="event-{index}"><h3 class="event-list__title">'
            f'<a href="/event/2026-11-18/book-group-{index}">Book group {index}</a></h3>'
            + gl_place() + '</article>')


def gl_listing(count=2):
    return ('<form data-drupal-selector="views-exposed-form-indiecommerce-event-list-page-events"></form>'
            + ''.join(gl_card(i + 1) for i in range(count)))


def gl_detail(index=1, text="Read and discuss a book together.", street="886 Fulton St"):
    value = dict(**{"@type": "Event"}, name=f"Book group {index}",
                 url=f"https://greenlightbookstore.com/event/2026-11-18/book-group-{index}",
                 startDate="2026-11-18T19:00:00-05:00", endDate="2026-11-18T20:00:00-05:00",
                 eventStatus="https://schema.org/EventScheduled",
                 location={"address": {"streetAddress": "Hops Hill at Fulton886 Fulton St"}})
    return (f'<script type="application/ld+json">{json.dumps(value)}</script>'
            f'<h1 class="event-details__info--title">Book group {index}</h1>' + gl_place(street)
            + f'<div class="event-details__info--body"><p>{escape(text)}</p></div>'
            '<div class="event-details__books-related-books">Retail product descriptions must not enter the event narrative.</div>')


def gl_fetch(url, accept):
    if "/event/" in url:
        return gl_detail(int(url.rsplit("-", 1)[1]))
    return gl_listing() if url.endswith("2026/11") else gl_listing(0)


class RemainingArtsTests(unittest.TestCase):
    def setUp(self):
        self.patches = [patch("roomquest.mapsee_adapter.record", side_effect=fake_record), patch.object(ny, "record", side_effect=fake_record)]
        for item in self.patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in self.patches])

    def test_commonpoint_uses_public_event_category_not_class_page_cap(self):
        fetch = Mock(return_value=cp_payload(cp_event()))
        row = ny.collect(source(ny.COMMONPOINT), fetch, now=NOW)[0]
        params = parse_qs(urlsplit(fetch.call_args.args[0]).query)
        self.assertEqual(params["categories"], ["4"])
        self.assertEqual(params["per_page"], ["50"])
        self.assertEqual(row["venue_address"], "58-20 Little Neck Parkway, Little Neck, NY 11362")
        with self.assertRaisesRegex(ValueError, "scope_changed"):
            ny.collect(source(ny.COMMONPOINT), Mock(return_value=cp_payload(cp_event(categories=[dict(id=6, name="Class")]))), now=NOW)

    def test_commonpoint_full_description_and_pagination_guard(self):
        text = "Community program full explanation. " * 90 + "Final condition."
        row = ny.collect(source(ny.COMMONPOINT), Mock(return_value=cp_payload(cp_event(description='<p>'+text+'</p>'))), now=NOW)[0]
        self.assertEqual(row["description"], text)
        self.assertGreater(len(row["description"]), 2000)
        with self.assertRaisesRegex(ValueError, "pagination_limit"):
            ny.collect(source(ny.COMMONPOINT), Mock(return_value=cp_payload(cp_event(), total_pages=38)), now=NOW)

    def test_commonpoint_bronx_point_requires_exact_native_identity_and_street(self):
        venue = dict(id=69030, venue="Commonpoint Bronx", address="1665 Hoe Ave",
                     city="The Bronx", state="NY", zip="10460")
        row = ny.collect(source(ny.COMMONPOINT), Mock(return_value=cp_payload(cp_event(venue=venue))), now=NOW)[0]
        self.assertEqual((row['lat'],row['lng']),(40.835703,-73.887896))
        self.assertEqual(row['location_provenance'],'reviewed_nyc_pad_exact_address')
        self.assertIsNone(row['reason'])
        for changed in ({**venue,'id':69031},{**venue,'venue':'Another Center'},
                        {**venue,'address':'1667 Hoe Ave'}):
            with self.subTest(venue=changed):
                row = ny.collect(source(ny.COMMONPOINT), Mock(return_value=cp_payload(cp_event(venue=changed))), now=NOW)[0]
                self.assertIsNone(row.get('lat'))

    def test_commonpoint_holds_conflicting_native_festival_hour(self):
        e = cp_event(145501, title="Hanukkah Festival", description="Join on Sunday from 1-3pm!",
                     start_date="2026-12-06 01:00:00", end_date="2026-12-06 15:00:00",
                     utc_start_date="2026-12-06 06:00:00", utc_end_date="2026-12-06 20:00:00")
        with self.assertLogs(ny.log, level="WARNING"):
            self.assertEqual(ny.collect(source(ny.COMMONPOINT), Mock(return_value=cp_payload(e)), now=NOW), [])

    def test_nyu_json_repairs_folded_utf8_without_decoder_relaxation(self):
        # The publisher's ICS splits this UTF-8 sequence across a legal byte
        # fold. JSON is fetched instead; no lossy decode is added anywhere.
        with self.assertRaises(UnicodeDecodeError):
            b"\xe2\r\n \x80\x94".decode("utf-8")
        text = "Full event narrative — " * 130 + "Final publisher condition."
        fetch = Mock(return_value=nyu_payload(nyu_event(description=text)))
        row = ny.collect(source(ny.NYU), fetch, now=NOW)[0]
        self.assertIn("/live/json/events/", fetch.call_args.args[0])
        self.assertIn("/response_fields/description,summary,location", fetch.call_args.args[0])
        self.assertIn(text, row["description"])
        self.assertEqual((row["lat"], row["lng"]), (40.729795, -73.997749))
        self.assertEqual(row["venue_address"], "566 LaGuardia Place, New York, NY 10012")

    def test_nyu_summary_cannot_replace_missing_full_body_or_oversize(self):
        data = nyu_payload(nyu_event(1, description=None, summary="Promotional excerpt"), nyu_event(2, description="x" * 12001))
        with self.assertLogs(ny.log, level="WARNING"):
            self.assertEqual(ny.collect(source(ny.NYU), Mock(return_value=data), now=NOW), [])

    def test_nyu_scope_excludes_remote_foreign_internal_and_nonpublic(self):
        data = nyu_payload(nyu_event(1, is_online=1), nyu_event(2, timezone="Europe/Amsterdam"),
                           nyu_event(3, title="Faculty Champion Drop-In Hours"),
                           nyu_event(4, event_types=["Students"]), nyu_event(5))
        self.assertEqual([r["id"] for r in ny.collect(source(ny.NYU), Mock(return_value=data), now=NOW)], ["5"])

    def test_nyu_external_links_and_unreviewed_venues_hold_individually(self):
        data = nyu_payload(nyu_event(1, url="https://example.org/event"),
                           nyu_event(2, location_id=999, location_title="NYU Washington DC"),
                           nyu_event(3, location_latitude=38.9, location_longitude=-77.0), nyu_event(4))
        with self.assertLogs(ny.log, level="WARNING"):
            self.assertEqual([r["id"] for r in ny.collect(source(ny.NYU), Mock(return_value=data), now=NOW)], ["4"])

    def test_nyu_requires_requested_full_fields_and_consistent_pagination(self):
        with self.assertRaisesRegex(ValueError, "pagination_limit"):
            ny.collect(source(ny.NYU), Mock(return_value=nyu_payload(nyu_event(), fields=[])), now=NOW)
        fetch = Mock(side_effect=[nyu_payload(nyu_event(1), total_pages=2, total_results=101),
                                  nyu_payload(nyu_event(2), page=2, total_pages=2, total_results=102)])
        with self.assertRaisesRegex(ValueError, "manifest_changed"):
            ny.collect(source(ny.NYU), fetch, now=NOW)

    def test_nyu_conflicting_timestamp_rejected(self):
        with self.assertRaisesRegex(ValueError, "schedule_changed"):
            ny.collect(source(ny.NYU), Mock(return_value=nyu_payload(nyu_event(date_utc="2026-11-19 01:30:00"))), now=NOW)

    def test_bronx_uses_full_native_body_epochs_and_exact_address(self):
        url = "https://bronxmuseum.org/event/winter-market/"
        listing = f'<article class="event-card"><a class="event-link" href="{url}"></a><h2 class="event-title">Winter market</h2><div class="event-date">Dec 4, 2026 6pm - 9pm</div></article>'
        full = "Meet artisans and participate in family art-making. " * 55
        detail = (f'<link rel="canonical" href="{url}"><div data-add-to-calendar data-title="Winter market" data-address="1040 Grand Concourse The Bronx, NY 10456" data-start="1796425200" data-end="1796436000"></div><div class="show-content"><p>{full}</p></div>')
        row = ny.collect(source(ny.BRONX), Mock(side_effect=[listing, detail]), now=NOW)[0]
        self.assertEqual(row["description"], full.strip())
        self.assertEqual(row["starts_at"], "2026-12-04T23:00:00+00:00")
        self.assertEqual(row["venue_address"], "1040 Grand Concourse, Bronx, NY 10456")

    def test_greenlight_uses_html_address_components_not_glued_jsonld(self):
        manifest = ny._greenlight_manifest(gl_fetch, float("inf"), NOW)
        full = "Read and discuss the entire work together. " * 80 + "Final registration requirement."
        row = ny._greenlight_detail(manifest[0], gl_detail(text=full), NOW)
        self.assertEqual(row["description"], full)
        self.assertEqual(row["venue_address"], "886 Fulton St, Brooklyn, NY 11238")
        self.assertNotIn("Retail product", row["description"])
        with self.assertRaisesRegex(ValueError, "venue_changed"):
            ny._greenlight_detail(manifest[0], gl_detail(street="999 Different Street"), NOW)

    def test_greenlight_checkpoint_only_emits_complete_snapshot_and_reuses_it(self):
        first = ny.collect_chunk(source(ny.GREENLIGHT), gl_fetch, now=NOW, max_details=1)
        self.assertFalse(first["complete"])
        self.assertEqual(first["events"], [])
        result = ny.collect_chunk(source(ny.GREENLIGHT), gl_fetch, checkpoint=first["checkpoint"], now=NOW, max_details=1)
        self.assertTrue(result["complete"])
        self.assertEqual(len(result["events"]), 2)
        no_http = Mock(side_effect=AssertionError("complete retry fetched HTTP"))
        replay = ny.collect_chunk(source(ny.GREENLIGHT), no_http, checkpoint=result["checkpoint"], now=NOW)
        self.assertEqual(replay["events"], result["events"])

    def test_greenlight_checkpoint_rejects_changed_street_geo_and_identity(self):
        state = ny.collect_chunk(source(ny.GREENLIGHT), gl_fetch, now=NOW)["checkpoint"]
        for field, value in (("venue_address", "999 Different Street, Brooklyn, NY 11238"), ("lat", 40.7),
                             ("id", "9999"), ("description", ""), ("image_url", "https://example.org/photo.jpg")):
            altered = deepcopy(state)
            altered["events"][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "checkpoint_invalid"):
                ny.collect_chunk(source(ny.GREENLIGHT), gl_fetch, checkpoint=altered, now=NOW)

    def test_source_identity_and_checkpoint_contract_are_exact(self):
        changed = source(ny.NYU)
        changed["feed_url"] += "?arbitrary=1"
        fetch = Mock()
        with self.assertRaisesRegex(ValueError, "unregistered"):
            ny.collect(changed, fetch, now=NOW)
        fetch.assert_not_called()
        with self.assertRaisesRegex(ValueError, "publisher_checkpoint_required"):
            ny.collect(source(ny.GREENLIGHT), fetch, now=NOW)


if __name__ == "__main__":
    unittest.main()
