from copy import deepcopy
from datetime import datetime, timedelta, timezone
import html
import json
import unittest
from unittest.mock import Mock, patch

from roomquest import new_york_social_remaining as ny


NOW = datetime(2026, 11, 14, 22, tzinfo=timezone.utc)


def source(key):
    return dict(source_key=key, feed_url=ny.SOURCES[key][0], kind="html", platform_adapter="html", timezone=ny.ZONE)


def normalized_record(title, start, end, venue, address, city, url, identity, **kwargs):
    return dict(id=identity, title=title, starts_at=start.isoformat(), ends_at=end.isoformat() if end else None,
                venue_name=venue, venue_address=address, venue_city=city, event_url=url,
                lat=kwargs.get("lat"), lng=kwargs.get("lng"))


def clocks():
    return ('<time class="event-time-12hr-start" datetime="2026-11-18">1:00 PM</time>'
            '<time class="event-time-12hr-end" datetime="2026-11-18">3:00 PM</time>'
            '<time class="event-time-12hr-end" datetime="2026-11-18">15:00</time>')


def square_listing(key, *, title="Class", slug="class", body="Complete native narrative.", excerpt=True):
    path = ny.SOURCES[key][0].split(".org")[-1] if key == ny.IRISH else "/upcoming-events"
    content = f'<div class="eventlist-excerpt">{body}</div>' if excerpt else f'<div class="eventlist-description"><div class="sqs-layout">{body}</div></div>'
    return (f'<div class="eventlist"><article class="eventlist-event--upcoming">'
            f'<a class="eventlist-title-link" href="{path}/{slug}">{title}</a>{clocks()}{content}</article></div>')


def square_detail(url, title, body=None, *, meta=None):
    content = "" if body is None else f'<div class="sqs-layout">{body}</div>'
    metadata = "" if meta is None else f'<meta name="description" content="{html.escape(meta)}"><meta property="og:description" content="{html.escape(meta)}">'
    return (f'<link rel="canonical" href="{url}">{metadata}<h1 class="eventitem-title">{title}</h1>'
            f'{clocks()}<div class="eventitem-column-content">{content}</div>'
            '<footer>New York Irish Center 1040 Jackson Avenue Long Island City NY 11101</footer>')


def industry_event(*, slug="class", title="Class", body="Complete publisher description.", start="2026-11-18 13:00:00", end="2026-11-18 15:00:00", identity=1):
    return dict(id=identity, url=f"https://industrycity.com/event/{slug}/", title=title, description=f"<p>{body}</p>",
                start_date=start, end_date=end, timezone="UTC+0", status="publish", all_day=False)


def industry_api(*events, **overrides):
    result = dict(events=list(events), total=len(events), total_pages=1)
    result.update(overrides)
    return json.dumps(result)


def industry_detail(event, *, street="68 34th St", venue="Fort Hamilton Distillery", schedule="Wed, November 18 | 1:00 pm - 3:00 pm", location=None, body=None):
    place = (f'<div class="location-line-wrapper"><strong>{venue}</strong><div class="location-line">{street} BLDG: 6</div></div>'
             if location is None else location)
    return (f'<link rel="canonical" href="{event["url"]}"><div class="business-left-side">'
            f'<h1 class="tribe-events-single-event-title">{event["title"]}</h1>'
            f'<h3 class="event-date-time">{schedule}</h3>'
            f'<div class="tribe-events-single-event-description">{body or event["description"]}</div>{place}</div>'
            '<footer>220 36th Street Suite 2-A, Brooklyn, NY 11232</footer>')


def wix_event(slug="community-workshop", body="Complete native program information.", **overrides):
    event = dict(id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", slug=slug, title="Community Workshop", status=0,
                 publishedDate="2026-11-01T10:00:00Z", description="Short introduction.", about="",
                 longDescription=dict(nodes=[dict(type="PARAGRAPH", nodes=[dict(type="TEXT", textData=dict(text=body))])]),
                 scheduling=dict(config=dict(scheduleTbd=False, startDate="2026-11-18T18:00:00Z", endDate="2026-11-18T20:00:00Z", timeZoneId=ny.ZONE, endDateHidden=False)),
                 location=dict(type=0, tbd=False, name="Brooklyn Community Pride Center", address="1561 Bedford Ave, Brooklyn, NY 11225, USA",
                               coordinates=dict(lat=40.6687009, lng=-73.9550745),
                               fullAddress=dict(country="US", subdivision="NY", city="Brooklyn", formattedAddress="1561 Bedford Ave, Brooklyn, NY 11225, USA",
                                                streetAddress=dict(number="1561", name="Bedford Avenue"), geocode=dict(latitude=40.6687009, longitude=-73.9550745))))
    event.update(overrides)
    return event


def wix_detail(event):
    url = "https://www.lgbtbrooklyn.org/event-details/" + event["slug"]
    data = dict(appsWarmupData={ny.WIX_APP: dict(EventsPageInitialState=dict(event=dict(event=event)))})
    return f'<link rel="canonical" href="{url}"><script id="wix-warmup-data" type="application/json">{json.dumps(data)}</script>'


def wix_calendar(*slugs):
    data = dict(appsWarmupData={ny.WIX_APP: dict(widget=dict(events=dict(events=[dict(slug=s) for s in slugs], hasMore=True)))})
    return f'<script id="wix-warmup-data" type="application/json">{json.dumps(data)}</script>'


def sitemap(*slugs):
    return '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(
        f'<url><loc>https://www.lgbtbrooklyn.org/event-details/{s}/form</loc><lastmod>2026-09-01</lastmod></url>' for s in slugs) + '</urlset>'


class NewYorkSocialRemainingTests(unittest.TestCase):
    def test_irish_full_detail_replaces_excerpt_and_keeps_all_long_text(self):
        full = "Full course materials, accessibility and participation information. " * 50 + "Final paragraph."
        url = ny.SOURCES[ny.IRISH][0] + "/class"
        pages = {ny.SOURCES[ny.IRISH][0]: square_listing(ny.IRISH, body="Short intro..."), url: square_detail(url, "Class", full)}
        with patch.object(ny, "record", side_effect=normalized_record):
            result = ny.collect_chunk(source(ny.IRISH), lambda u, a: pages[u], now=NOW)
        row = result["events"][0]
        self.assertTrue(result["complete"])
        self.assertEqual(row["description"], full)
        self.assertGreater(len(row["description"]), 2000)
        self.assertEqual(row["venue_address"], "10-40 Jackson Avenue, Long Island City, NY 11101")
        self.assertEqual((row["lat"], row["lng"]), ny.POINTS[ny.IRISH])

    def test_empty_irish_detail_requires_identical_complete_native_metadata(self):
        url = ny.SOURCES[ny.IRISH][0] + "/class"
        text = "This is the complete published class description."
        item = ny._square_manifest(ny.IRISH, square_listing(ny.IRISH, body=text), NOW)[0]
        with patch.object(ny, "record", side_effect=normalized_record):
            row = ny._irish_detail(item, square_detail(url, "Class", meta=text))[0]
        self.assertEqual(row["description"], text)
        with self.assertRaisesRegex(ValueError, "description_missing"):
            ny._irish_detail(item, square_detail(url, "Class", meta="Truncated..."))

    def test_irish_outing_is_held_without_headquarters_location(self):
        title = "Theater Outing"
        url = ny.SOURCES[ny.IRISH][0] + "/class"
        pages = {ny.SOURCES[ny.IRISH][0]: square_listing(ny.IRISH, title=title), url: square_detail(url, title, "Meet us for an outing.")}
        result = ny.collect_chunk(source(ny.IRISH), lambda u, a: pages[u], now=NOW)
        self.assertEqual(result["events"], [])
        self.assertEqual(result["checkpoint"]["diagnostics"][0]["reason"], "new_york_social_location_unresolved")
        other = square_detail(url, "Class", "Public class at a different venue.") + '<li class="eventitem-meta-address">Other venue <a href="https://maps.google.com?q=410+West+42nd+Street+New+York,+NY+10036">(map)</a></li>'
        item = ny._square_manifest(ny.IRISH, square_listing(ny.IRISH), NOW)[0]
        with self.assertRaisesRegex(ValueError, "location_unresolved"):
            ny._irish_detail(item, other)

    def test_repair_native_full_card_needs_its_actual_current_venue(self):
        fetch = Mock(return_value=square_listing(ny.REPAIR, body="Repair Cafe Brooklyn at Another World\n629 Nostrand Ave", excerpt=False))
        with patch.object(ny, "record", side_effect=normalized_record):
            result = ny.collect_chunk(source(ny.REPAIR), fetch, now=NOW)
        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(result["events"][0]["venue_address"], "629 Nostrand Avenue, Brooklyn, NY 11216")
        fetch.assert_called_once_with(ny.SOURCES[ny.REPAIR][0], "text/html")
        changed = ny.collect_chunk(source(ny.REPAIR), Mock(return_value=square_listing(ny.REPAIR, body="Repair Cafe at a new venue", excerpt=False)), now=NOW)
        self.assertEqual(changed["events"], [])
        self.assertEqual(changed["checkpoint"]["diagnostics"][0]["reason"], "new_york_social_location_unresolved")

    def test_repair_excerpt_hydrates_detail_and_cannot_use_irish_center_default(self):
        url = ny.SOURCES[ny.REPAIR][0] + "/class"
        full = "Repair Cafe Brooklyn at Another World, 629 Nostrand Avenue. Bring your broken object and learn how to repair it."
        pages = {ny.SOURCES[ny.REPAIR][0]: square_listing(ny.REPAIR, body=""), url: square_detail(url, "Class", full)}
        with patch.object(ny, "record", side_effect=normalized_record):
            result = ny.collect_chunk(source(ny.REPAIR), lambda u, a: pages[u], now=NOW)
        self.assertEqual(result["events"][0]["description"], full)
        self.assertEqual(result["events"][0]["venue_address"], ny.VENUES[ny.REPAIR][1])
        self.assertNotEqual(result["events"][0]["venue_address"], ny.VENUES[ny.IRISH][1])

    def test_industry_complete_api_prose_and_native_local_time_survive_wrong_utc_label(self):
        body = "Complete workshop details. " * 120 + "Last sentence."
        event = industry_event(body="\u200b" + body)
        fetch = Mock(side_effect=[industry_api(event), industry_detail(event, body=f"<p>{body}</p>")])
        with patch.object(ny, "record", side_effect=normalized_record):
            result = ny.collect_chunk(source(ny.INDUSTRY), fetch, now=NOW)
        row = result["events"][0]
        self.assertEqual(row["description"], body)
        self.assertEqual(row["starts_at"], "2026-11-18T13:00:00-05:00")
        self.assertEqual(row["venue_address"], "68 34th Street Building 6, Brooklyn, NY 11232")
        self.assertIn("/wp-json/tribe/events/v1/events?", fetch.call_args_list[0].args[0])

    def test_industry_event_location_supports_named_venues_and_floors(self):
        cases = {
            "<p>The Box Factory<br>51 34th Street<br>Brooklyn, NY 11232</p>": ("The Box Factory", "51 34th Street, Brooklyn, NY 11232"),
            "<p>Industry City 33 35th Street, 2nd Floor Brooklyn NY 11232</p>": ("Industry City", "33 35th Street 2nd Floor, Brooklyn, NY 11232"),
            "<p>brooklynONE Tom Kane Theater<br>Building 5, 51 35th Street<br>Brooklyn, NY 11232</p>": ("brooklynONE Tom Kane Theater", "51 35th Street Building 5, Brooklyn, NY 11232"),
        }
        for location, expected in cases.items():
            with self.subTest(location=location):
                soup = ny.BeautifulSoup(industry_detail(industry_event(), location=location), "html.parser")
                self.assertEqual(ny._industry_location(soup)[:2], expected)
        soup = ny.BeautifulSoup(industry_detail(industry_event(), location="<p>Location to be announced</p>"), "html.parser")
        with self.assertRaisesRegex(ValueError, "location_unresolved"):
            ny._industry_location(soup)

    def test_industry_explicit_next_year_schedule_is_checked(self):
        event = industry_event(start="2027-01-02 16:30:00", end="2027-01-02 19:30:00")
        item = ny._industry_manifest(Mock(return_value=industry_api(event)), NOW)[0]
        with patch.object(ny, "record", side_effect=normalized_record):
            rows = ny._industry_detail(item, industry_detail(event, schedule="January 2, 2027 | 4:30 pm - 7:30 pm"))
        self.assertEqual(len(rows), 1)
        with self.assertRaisesRegex(ValueError, "schedule_conflict"):
            ny._industry_detail(item, industry_detail(event, schedule="January 2, 2028 | 4:30 pm - 7:30 pm"))

    def test_industry_duplicate_sake_classes_and_stale_recurrence_are_held(self):
        sake = industry_event(slug="guided-brewery-tour-and-sake-tasting/2026-11-18")
        stale = industry_event(slug="spirited-away-psychic-paranormal-night/2026-12-08", body="Tuesday, November 10th, 7-11pm", start="2026-12-08 19:00:00", end="2026-12-08 23:00:00", identity=2)
        fetch = Mock(return_value=industry_api(sake, stale))
        result = ny.collect_chunk(source(ny.INDUSTRY), fetch, now=NOW)
        self.assertTrue(result["complete"])
        self.assertEqual(result["events"], [])
        self.assertEqual({x["reason"] for x in result["checkpoint"]["diagnostics"]}, {"existing_direct_sake_source", "publisher_schedule_conflict"})
        self.assertEqual(fetch.call_count, 1)

    def test_industry_manifest_cannot_claim_completeness_for_missing_page_records(self):
        with self.assertRaisesRegex(ValueError, "calendar_changed"):
            ny._industry_manifest(Mock(return_value=industry_api(industry_event(), total=2)), NOW)
        with self.assertRaisesRegex(ValueError, "calendar_changed"):
            ny._industry_manifest(Mock(return_value=industry_api(industry_event(), industry_event())), NOW)

    def test_wix_public_sitemap_handles_duplicate_suffix_and_never_fetches_forms(self):
        active = "workshop-2026-11-18-13-00-1"
        old = "workshop-2026-02-18-13-00-1"
        queue = ny._wix_manifest(wix_calendar(active), sitemap(active, old, "undated-publisher-event"), NOW)
        self.assertEqual({x["url"].rsplit("/", 1)[-1] for x in queue}, {active, "undated-publisher-event"})
        self.assertTrue(all(not x["url"].endswith("/form") for x in queue))
        with self.assertRaisesRegex(ValueError, "calendar_changed"):
            ny._wix_manifest(wix_calendar("missing-new-event"), sitemap(active), NOW)

    def test_wix_manifest_500_override_is_source_specific_and_enforced(self):
        slugs = [f"event-{n}" for n in range(500)]
        self.assertEqual(len(ny._wix_manifest(wix_calendar(slugs[0]), sitemap(*slugs), NOW)), 500)
        with self.assertRaisesRegex(ValueError, "manifest_limit"):
            ny._wix_manifest(wix_calendar(slugs[0]), sitemap(*slugs, "event-500"), NOW)
        self.assertEqual(ny.CHECKPOINT_MANIFEST_LIMITS, {ny.PRIDE: 500})
        self.assertEqual(ny.CHECKPOINT_EVENT_LIMITS, {ny.PRIDE: 500})

    def test_wix_full_rich_text_is_preserved_and_offsite_street_is_not_replaced(self):
        full = "All public participation requirements and accessibility details. " * 50 + "Final native paragraph."
        event = wix_event(body=full)
        event["location"].update(name="Offsite Community Hall", address="220 36th St, Brooklyn, NY 11232, USA", coordinates=dict(lat=40.656, lng=-74.007))
        event["location"]["fullAddress"].update(formattedAddress=event["location"]["address"], streetAddress=dict(number="220", name="36th Street"), geocode=dict(latitude=40.656, longitude=-74.007))
        with patch.object(ny, "record", side_effect=normalized_record):
            row = ny._wix_detail(dict(url="https://www.lgbtbrooklyn.org/event-details/" + event["slug"]), wix_detail(event), NOW)[0]
        self.assertEqual(row["description"], full)
        self.assertEqual(row["venue_address"], "220 36th St, Brooklyn, NY 11232")
        self.assertEqual((row["lat"], row["lng"]), (40.656, -74.007))
        self.assertEqual(row["location_provenance"], "publisher_event_geo")

    def test_wix_expired_online_unavailable_and_empty_events_are_explicitly_held(self):
        event = wix_event()
        url = "https://www.lgbtbrooklyn.org/event-details/" + event["slug"]
        for reason, change in [
            ("publisher_event_not_active", lambda e: e.update(status=3)),
            ("not_in_person_or_unpublished", lambda e: e["location"].update(type=1)),
            ("no_available_appointments", lambda e: e.update(title="Counseling | 0 Appointments Left")),
            ("new_york_social_description_missing", lambda e: e.update(longDescription={}, description="", about="")),
            ("new_york_social_description_limit", lambda e: e.update(longDescription=dict(nodes=[dict(type="TEXT", textData=dict(text="x" * 12001))]))),
        ]:
            candidate = deepcopy(event); change(candidate)
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                ny._wix_detail(dict(url=url), wix_detail(candidate), NOW)
        event["scheduling"]["config"].update(startDate="2026-01-18T18:00:00Z", endDate="2026-01-18T20:00:00Z")
        self.assertEqual(ny._wix_detail(dict(url=url), wix_detail(event), NOW), [])

    def test_wix_empty_rich_editor_paragraph_does_not_mask_the_full_short_narrative(self):
        event = wix_event()
        event["longDescription"] = dict(nodes=[dict(type="PARAGRAPH", nodes=[])])
        event["description"] = "A weekly public meeting with full participation information published in this sentence."
        with patch.object(ny, "record", side_effect=normalized_record):
            row = ny._wix_detail(dict(url="https://www.lgbtbrooklyn.org/event-details/" + event["slug"]), wix_detail(event), NOW)[0]
        self.assertEqual(row["description"], event["description"])

    def test_wix_disagreeing_native_street_and_coordinates_are_not_guessed(self):
        event = wix_event()
        event["location"]["fullAddress"]["streetAddress"]["number"] = "220"
        with self.assertRaisesRegex(ValueError, "location_unresolved"):
            ny._wix_location(event)
        event = wix_event()
        event["location"]["coordinates"]["lat"] += 0.01
        with self.assertRaisesRegex(ValueError, "location_unresolved"):
            ny._wix_location(event)

    def test_wix_checkpoint_publishes_only_complete_hydration_and_rejects_forged_identity(self):
        one, two = wix_event("event-one"), wix_event("event-two")
        pages = {ny.SOURCES[ny.PRIDE][0]: wix_calendar("event-one", "event-two"), ny.WIX_SITEMAP: sitemap("event-one", "event-two")}
        pages.update({"https://www.lgbtbrooklyn.org/event-details/" + e["slug"]: wix_detail(e) for e in [one, two]})
        fetch = Mock(side_effect=lambda u, a: pages[u])
        with patch.object(ny, "record", side_effect=normalized_record):
            first = ny.collect_chunk(source(ny.PRIDE), fetch, now=NOW, max_details=1)
            self.assertFalse(first["complete"])
            self.assertEqual(first["events"], [])
            final = ny.collect_chunk(source(ny.PRIDE), fetch, now=NOW + timedelta(seconds=30), checkpoint=first["checkpoint"], max_details=1)
        self.assertTrue(final["complete"])
        self.assertEqual(len(final["events"]), 2)
        self.assertEqual(final["checkpoint"]["started_at"], first["checkpoint"]["started_at"])
        self.assertEqual(final["checkpoint"]["window_start"], "2026-11-14")
        self.assertFalse(any(call.args[0].endswith("/form") for call in fetch.call_args_list))
        forged = deepcopy(first["checkpoint"]); forged["events"][0]["id"] = "nyc-social:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "checkpoint_invalid"):
            ny.collect_chunk(source(ny.PRIDE), fetch, now=NOW, checkpoint=forged)

    def test_wix_higher_chunk_ceiling_still_yields_before_the_worker_deadline(self):
        slugs = [f"event-{n}" for n in range(20)]
        pages = {ny.SOURCES[ny.PRIDE][0]: wix_calendar(slugs[0]), ny.WIX_SITEMAP: sitemap(*slugs)}
        pages.update({"https://www.lgbtbrooklyn.org/event-details/" + slug: wix_detail(wix_event(slug)) for slug in slugs})
        elapsed, calls = [0], []
        def fetch(url, accept):
            calls.append(url)
            elapsed[0] += 4
            return pages[url]
        with patch.object(ny, "record", side_effect=normalized_record), patch.object(ny, "monotonic", side_effect=lambda: elapsed[0]):
            result = ny.collect_chunk(source(ny.PRIDE), fetch, now=NOW, deadline_at=36)
        self.assertFalse(result["complete"])
        self.assertEqual(result["events"], [])
        self.assertEqual(result["checkpoint"]["cursor"], 4)
        self.assertEqual(len(calls), 6)
        self.assertLess(elapsed[0], 36)

    def test_source_binding_deadline_and_url_guards_apply_before_fetch(self):
        fetch = Mock()
        bad = source(ny.PRIDE); bad["feed_url"] += "?format=json"
        with self.assertRaisesRegex(ValueError, "unregistered"):
            ny.collect_chunk(bad, fetch, now=NOW)
        with self.assertRaisesRegex(ValueError, "collection_deadline"):
            ny.collect_chunk(source(ny.PRIDE), fetch, now=NOW, deadline_at=0)
        fetch.assert_not_called()
        for url in ["https://evil.example/event-details/x", "https://www.lgbtbrooklyn.org/event-details/x?private=true", "https://www.lgbtbrooklyn.org/event-details/x%2f.."]:
            self.assertFalse(ny.event_url(ny.PRIDE, url))
        repair_image = "https://images.squarespace-cdn.com/content/v1/68978b464835ee5a17b7ded8/1788180033671-E9X33KVZ8EQU9K9RWJWA/EJL+260131+2098.jpg"
        self.assertEqual(ny.photo_url(ny.REPAIR, repair_image), repair_image)
        self.assertIsNone(ny.photo_url(ny.IRISH, repair_image))


if __name__ == "__main__":
    unittest.main()
