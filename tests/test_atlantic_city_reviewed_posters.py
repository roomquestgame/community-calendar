from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
import json
import unittest
from unittest.mock import Mock, patch

from roomquest import atlantic_city_reviewed_posters as ac


NOW = datetime(2026, 11, 14, 22, 16, 2, tzinfo=timezone.utc)


def source(key):
    return dict(source_key=key, feed_url=ac.SOURCES[key][0], kind="html", platform_adapter="html", timezone=ac.ZONE)


def raw_record(title, start, end, venue, address, city, url, identity, category="", **kwargs):
    return dict(id=identity, title=title, starts_at=start, ends_at=end, venue_name=venue,
                venue_address=address, venue_city=city, event_url=url, category=category,
                lat=kwargs.get("lat"), lng=kwargs.get("lng"))


def reviewed_test_assets():
    # Deterministic stand-ins exercise the same byte-hash boundary. Live
    # publisher asset hashes and exact transcripts are verified separately in
    # the committed replay evidence, without vendoring third-party images.
    posters = deepcopy(ac.POSTERS)
    assets = {}
    for name, item in posters.items():
        data = b"\xff\xd8\xff" + name.encode() + b"\xff\xd9"
        item["sha256"] = sha256(data).hexdigest()
        assets[item["url"]] = data
    return posters, assets


def vagabond_html():
    blocks = "".join('<div class="sqs-block" id="' + item["block"] + '"><img data-src="'
                     + escape(item["url"], quote=True) + '"></div>'
                     for item in ac.POSTERS.values() if item["source"] == ac.VAGABOND)
    return ('<link rel="canonical" href="' + ac.SOURCES[ac.VAGABOND][0] + '">'
            '<section data-section-id="' + ac.VAGABOND_SECTION + '">' + blocks + '</section>'
            '<div class="sqs-html-content"><h3>EHT VAGABOND</h3>'
            '<p>3016 Ocean Heights Ave<br>Egg Harbor Township, NJ 08234</p></div>')


def charity_fixture():
    url = "https://img1.wsimg.com/blobby/go/" + ac.CHARITY_SITE + "/gpub/147f856b6ed8691c/script.js"
    image = ac.POSTERS["christmas-mart-2026"]["url"]
    gallery = dict(id=ac.CHARITY_WIDGET, widgetId=ac.CHARITY_WIDGET, title=ac.CHARITY_TITLE + " ",
                   env="production", renderMode="PUBLISH",
                   galleryImages=[dict(image=dict(image=image))],
                   images=[dict(imageData=dict(src=image))])
    html = ('<link rel="canonical" href="https://charityleague-ac.com/">'
            '<div data-ux="Widget" id="' + ac.CHARITY_WIDGET + '">'
            '<h2 data-aid="GALLERY_SECTION_TITLE_RENDERED">' + ac.CHARITY_TITLE + '</h2></div>'
            '<script src="' + url + '"></script>')
    script = ("window.gallery=JSON.parse(" + json.dumps(json.dumps(gallery)) + ");"
              "window.bootstrap=JSON.parse(" + json.dumps(json.dumps({"widgetId": ac.CHARITY_WIDGET})) + ");")
    return html, url, script, gallery


class ReviewedPosterTests(unittest.TestCase):
    def test_all_current_programs_preserve_complete_text_and_exact_destinations(self):
        posters, pages = reviewed_test_assets()
        pages[ac.SOURCES[ac.VAGABOND][0]] = vagabond_html()
        html, script_url, script, _ = charity_fixture()
        pages.update({ac.SOURCES[ac.CHARITY][0]: html, script_url: script})
        fetch = Mock(side_effect=lambda url, accept: pages[url])
        with patch.object(ac, "POSTERS", posters), patch.object(ac, "record", side_effect=raw_record):
            vagabond = ac.collect(source(ac.VAGABOND), fetch, now=NOW)
            charity = ac.collect(source(ac.CHARITY), fetch, now=NOW)
        self.assertEqual((len(vagabond), len(charity)), (18, 1))
        self.assertEqual(sum(row["ends_at"] is None for row in vagabond), 17)
        self.assertEqual({row["description"] for row in vagabond},
                         {item["description"] for item in ac.POSTERS.values() if item["source"] == ac.VAGABOND})
        santa = next(row for row in vagabond if row["title"] == "Breakfast with Santa")
        self.assertEqual(santa["starts_at"], "2026-12-05T09:30:00-05:00")
        self.assertEqual(santa["ends_at"], "2026-12-05T12:00:00-05:00")
        self.assertIn("Space is limited call or email to book today.", santa["description"])
        self.assertTrue(santa["description"].endswith("$5 Bloody Marys $5 Mimosas"))
        self.assertEqual(charity[0]["description"], ac.POSTERS["christmas-mart-2026"]["description"])
        self.assertEqual(sha256(charity[0]["description"].encode()).hexdigest(),
                         "8ffe82ba2775ebef3d713c9fb49694563fc9373ccd3c2b9fb7b4737f71c1e2ce")
        self.assertEqual(charity[0]["starts_at"], "2026-11-20T10:00:00-05:00")
        self.assertEqual(charity[0]["ends_at"], "2026-11-20T19:00:00-05:00")
        self.assertEqual((santa["lat"], santa["lng"]), (39.360186000003, -74.615697000001))
        self.assertEqual((charity[0]["lat"], charity[0]["lng"]), (39.352284000003, -74.561652000001))
        for row in vagabond + charity:
            self.assertRegex(row["venue_address"], r", NJ 0\d{4}$")
            self.assertEqual(row["category"], "")
        self.assertEqual(sum(call.args[1] == "image/jpeg" for call in fetch.call_args_list), 4)

    def test_changed_image_bytes_fail_before_any_partial_snapshot_returns(self):
        posters, pages = reviewed_test_assets()
        pages[ac.SOURCES[ac.VAGABOND][0]] = vagabond_html()
        pages[posters["dj-bingo-tuesdays"]["url"]] += b"new edition"
        with patch.object(ac, "POSTERS", posters), patch.object(ac, "record") as record:
            with self.assertRaisesRegex(ValueError, "edition_changed"):
                ac.collect(source(ac.VAGABOND), lambda url, accept: pages[url], now=NOW)
        record.assert_not_called()

    def test_changed_poster_url_does_not_reuse_reviewed_text(self):
        posters, pages = reviewed_test_assets()
        pages[ac.SOURCES[ac.VAGABOND][0]] = vagabond_html().replace("santa+breakfast+2026.jpg", "santa+breakfast+2027.jpg")
        with patch.object(ac, "POSTERS", posters):
            with self.assertRaisesRegex(ValueError, "manifest_changed"):
                ac.collect(source(ac.VAGABOND), lambda url, accept: pages[url], now=NOW)

    def test_new_image_in_program_section_requires_review(self):
        posters, pages = reviewed_test_assets()
        pages[ac.SOURCES[ac.VAGABOND][0]] = vagabond_html().replace("</section>", '<img src="https://example.org/new-program.jpg"></section>')
        with patch.object(ac, "POSTERS", posters):
            with self.assertRaisesRegex(ValueError, "manifest_changed"):
                ac.collect(source(ac.VAGABOND), lambda url, accept: pages[url], now=NOW)

    def test_weekly_schedule_has_fixed_freshness_boundary(self):
        posters, pages = reviewed_test_assets()
        pages[ac.SOURCES[ac.VAGABOND][0]] = vagabond_html()
        with patch.object(ac, "POSTERS", posters), patch.object(ac, "record", side_effect=raw_record):
            rows = ac.collect(source(ac.VAGABOND), lambda url, accept: pages[url],
                              now=datetime(2027, 1, 1, tzinfo=timezone.utc))
            self.assertEqual(len(rows), 3)  # Jan 5, Jan 6, Jan 12; never Jan 13.
            self.assertTrue(all(datetime.fromisoformat(row["starts_at"]).date() <= ac.WEEKLY_REVIEWED_THROUGH for row in rows))
            with self.assertRaisesRegex(ValueError, "freshness_expired"):
                ac.collect(source(ac.VAGABOND), lambda url, accept: pages[url],
                           now=datetime(2027, 1, 13, 12, tzinfo=timezone.utc))

    def test_known_end_retains_last_minutes_without_inventing_unknown_end(self):
        item = ac.POSTERS["christmas-mart-2026"]
        ongoing = datetime(2026, 11, 20, 23, 45, tzinfo=timezone.utc)
        occurrences = list(ac._occurrences(item, ongoing))
        self.assertEqual(len(occurrences), 1)
        self.assertEqual(occurrences[0][2].isoformat(), "2026-11-20T19:00:00-05:00")
        self.assertEqual(list(ac._occurrences(item, datetime(2026, 11, 21, tzinfo=timezone.utc))), [])
        past_start = datetime(2026, 11, 18, 23, 30, tzinfo=timezone.utc)
        bingo = list(ac._occurrences(ac.POSTERS["dj-bingo-tuesdays"], past_start))
        self.assertTrue(all(start > past_start and end is None for _, start, end in bingo))

    def test_source_identity_and_canonical_url_prevent_cross_publisher_reuse(self):
        altered = source(ac.VAGABOND)
        altered["feed_url"] = "https://www.vagabondkitchenandtap.com/home-ac"
        fetch = Mock()
        with self.assertRaisesRegex(ValueError, "source_identity"):
            ac.collect(altered, fetch, now=NOW)
        fetch.assert_not_called()
        self.assertFalse(ac.event_url(ac.VAGABOND, ac.SOURCES[ac.VAGABOND][0] + "?format=json"))
        with self.assertRaisesRegex(ValueError, "page_identity"):
            ac._page(vagabond_html().replace("/home-eht", "/home-ac"), ac.VAGABOND)

    def test_changed_branch_address_never_gets_the_eht_point(self):
        self.assertIsNone(ac.reviewed_venue_location(ac.VAGABOND, "Vagabond AC", "672 N Trenton Ave, Atlantic City, NJ 08401"))
        self.assertIsNone(ac.reviewed_venue_location(ac.VAGABOND, ac.VENUES[ac.VAGABOND][0], "3018 Ocean Heights Ave, Egg Harbor Township, NJ 08234"))
        self.assertIsNone(ac.reviewed_venue_location(ac.VAGABOND, "Different restaurant", ac.VENUES[ac.VAGABOND][1]))
        with patch.dict(ac.VENUES, {ac.VAGABOND: ("Changed name", "Changed address", "Egg Harbor Township")}):
            self.assertIsNone(ac.reviewed_venue_location(ac.VAGABOND, *ac.VENUES[ac.VAGABOND][:2]))
        posters, pages = reviewed_test_assets()
        pages[ac.SOURCES[ac.VAGABOND][0]] = vagabond_html().replace("3016 Ocean Heights Ave", "672 N Trenton Ave")
        with patch.object(ac, "POSTERS", posters):
            with self.assertRaisesRegex(ValueError, "venue_changed"):
                ac.collect(source(ac.VAGABOND), lambda url, accept: pages[url], now=NOW)

    def test_charity_gallery_identity_and_complete_image_manifest_are_required(self):
        posters, assets = reviewed_test_assets()
        html, script_url, script, gallery = charity_fixture()
        for mutate in (lambda g: g.update(widgetId="wrong"),
                       lambda g: g["galleryImages"].append(deepcopy(g["galleryImages"][0])),
                       lambda g: g["images"][0]["imageData"].update(src="https://example.org/other.jpeg")):
            changed = deepcopy(gallery); mutate(changed)
            pages = {**assets, ac.SOURCES[ac.CHARITY][0]: html,
                     script_url: "JSON.parse(" + json.dumps(json.dumps(changed)) + ")"}
            with patch.object(ac, "POSTERS", posters), self.assertRaisesRegex(ValueError, "gallery_changed|edition_changed"):
                ac.collect(source(ac.CHARITY), lambda url, accept: pages[url], now=NOW)

    def test_charity_does_not_execute_javascript_or_fetch_unadvertised_script(self):
        html, script_url, _, _ = charity_fixture()
        calls = []
        def fetch(url, accept):
            calls.append(url)
            return html if url == ac.SOURCES[ac.CHARITY][0] else 'JSON.parse((function(){throw "execute"})())'
        with self.assertRaisesRegex(ValueError, "gallery_incomplete"):
            ac.collect(source(ac.CHARITY), fetch, now=NOW)
        self.assertEqual(calls, [ac.SOURCES[ac.CHARITY][0], script_url])
        self.assertFalse(ac._script_url(script_url.replace(ac.CHARITY_SITE, "other-site")))
        self.assertFalse(ac._script_url(script_url + "?format=json"))

    def test_blank_oversized_text_and_nonjpeg_responses_are_rejected(self):
        for value, error in (("", "description_missing"), ("x" * 12001, "description_limit")):
            with self.assertRaisesRegex(ValueError, error):
                ac._description(value)
        exact = "All complete program instructions. " * 150 + "Final registration restriction."
        self.assertEqual(ac._description(exact), exact)
        for value in ("not bytes", b"<html>challenge</html>", b"\xff\xd8\xff" + b"x" * ac.MAX_IMAGE):
            with self.assertRaisesRegex(ValueError, "invalid_image"):
                ac._verify_image(ac.POSTERS["christmas-mart-2026"], lambda u, a: value, None)

    def test_deadline_stops_before_fetch(self):
        fetch = Mock()
        with patch.object(ac, "monotonic", return_value=10):
            with self.assertRaisesRegex(ValueError, "collection_deadline"):
                ac.collect(source(ac.VAGABOND), fetch, deadline_at=11, now=NOW)
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
