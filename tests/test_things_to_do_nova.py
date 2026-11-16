"""Small synthetic NOVA Drupal contracts; no copied publisher HTML/narratives."""

import unittest
from copy import deepcopy

from roomquest import things_to_do_nova as nova


PARK = {
    "park_slug": "potomac-overlook-regional-park",
    "park_name": "Potomac Overlook Regional Park",
    "city": "Arlington",
    "state": "VA",
    "location_text": "Potomac Overlook Regional Park, Arlington, VA",
    "location_source_url": "https://www.novaparks.com/parks/potomac-overlook-regional-park",
}
LISTING = PARK["location_source_url"] + "/things-to-do"
MEADOW = {
    "park_slug": "meadowlark-botanical-gardens", "park_name": "Meadowlark Botanical Gardens",
    "city": "Vienna", "state": "VA", "location_text": "Meadowlark Botanical Gardens, Vienna, VA",
    "location_source_url": "https://www.novaparks.com/parks/meadowlark-botanical-gardens",
}


def card(identity="101", title="Woodland Trail", body="", href=None, extra="",
         node_type="thing-to-do"):
    heading = f'<a href="{href}">{title}</a>' if href else title
    narrative = f'<div class="field--name-body">{body}</div>' if body else ""
    return (
        f'<article id="node-{identity}" data-history-node-id="{identity}" '
        f'class="node node--type-{node_type} node--view-mode-teaser">'
        f'<h3>{heading}</h3>{narrative}{extra}</article>'
    )


def listing(cards, extra="", context=None):
    context = context or PARK
    return (
        '<html><header><a href="https://cabins.example/">Book Now</a></header>'
        '<main id="main-content"><article class="node--type-page node--view-mode-full">'
        f'<h1>{context["park_name"]}</h1>'
        '<nav><h2>Tertiary Menu</h2><a href="/parks/foreign/things-to-do/play">Play</a></nav>'
        '<div class="listing activity"><div class="content-container"><div class="content">'
        f'{cards}</div></div></div></article>{extra}</main></html>'
    )


def detail(identity="101", title="Woodland Trail", body="", extra="", outside=""):
    return (
        '<html><header><a href="https://fareharbor.com/unrelated/">Book Now</a></header>'
        f'<main id="main-content"><article id="node-{identity}" data-history-node-id="{identity}" '
        'class="node node--type-thing-to-do node--view-mode-full">'
        f'<h1>{PARK["park_name"]}</h1><nav><h2>Tertiary Menu</h2></nav>'
        f'<div class="content-container t-align-center"><h2>{title}</h2></div>'
        f'<div class="field--name-body">{body}</div>{extra}</article>{outside}</main></html>'
    )


def parent_page(section="", extra=""):
    return (
        '<main id="main-content"><article class="node--type-park node--view-mode-full">'
        f'<h1>{MEADOW["park_name"]}</h1>'
        '<div class="paragraph--type--item paragraph--view-mode--accordion">'
        '<button class="field--name-field-title">Garden Fees</button>'
        '<div class="field--name-field-intro">Unrelated admission charges.</div></div>'
        '<div class="paragraph--type--item paragraph--view-mode--accordion">'
        '<button class="field--name-field-title">Visitor Center</button>'
        f'<div class="field--name-field-intro">{section}</div></div>{extra}</article></main>'
    )


class NovaThingsToDoParserTests(unittest.TestCase):
    def test_sparse_activities_sharing_listing_remain_distinct(self):
        rows = nova.parse_page(listing(card("101") + card("102", "Visitor Center")), LISTING, PARK)
        self.assertEqual([r["external_id"] for r in rows], ["novaparks:node:101", "novaparks:node:102"])
        self.assertEqual([r["source_url"] for r in rows], [LISTING + "#node-101", LISTING + "#node-102"])
        for row in rows:
            self.assertEqual(row["extracted_from_url"], LISTING)
            self.assertEqual(row["location_text"], PARK["location_text"])
            for field in ("description", "image_url", "source_categories", "availability_text", "price_text", "booking_url"):
                self.assertIsNone(row[field], field)
            self.assertNotIn("starts_at", row)
            self.assertNotIn("kid_friendly", row)
            self.assertNotIn("is_free", row)

    def test_detail_and_listing_share_drupal_identity_and_keep_fetch_provenance(self):
        url = LISTING + "/woodland-trail"
        teaser = nova.parse_page(listing(card(href=url)), LISTING, PARK)[0]
        full = nova.parse_page(detail(title="Updated Trail Name", body="A trail description."), url, PARK)[0]
        self.assertEqual(teaser["external_id"], full["external_id"])
        self.assertEqual(teaser["source_url"], url)
        self.assertEqual(teaser["extracted_from_url"], LISTING)
        self.assertEqual(full["extracted_from_url"], url)
        self.assertEqual(full["title"], "Updated Trail Name")

    def test_listing_fragment_selects_only_its_activity(self):
        rows = nova.parse_page(listing(card("101") + card("102", "Visitor Center")), LISTING + "#node-102", PARK)
        self.assertEqual([r["external_id"] for r in rows], ["novaparks:node:102"])
        self.assertEqual(rows[0]["extracted_from_url"], LISTING)

    def test_donations_and_boilerplate_are_excluded_but_private_and_seasonal_options_remain(self):
        cards = (card("101", "Adopt An Animal", href=LISTING + "/adopt-an-animal")
                 + card("102", "Birthday Parties")
                 + card("103", "Seasonal Lights")
                 + card("104", "Pool", node_type="waterpark")
                 + card("105", "The Atrium", node_type="wedding-venue"))
        outside = card("999", "Global Ropes Course") + '<article class="node--type-notification">W&amp;OD closure</article>'
        rows = nova.parse_page(listing(cards, extra=outside), LISTING, PARK)
        self.assertEqual([r["title"] for r in rows], ["Birthday Parties", "Seasonal Lights", "Pool", "The Atrium"])
        self.assertNotIn(LISTING + "/adopt-an-animal", nova.discover_links(listing(cards), LISTING, PARK))

    def test_cross_park_or_other_site_sections_use_supporting_listing(self):
        urls = ["https://www.novaparks.com/camps-programs/a-camp",
                "https://www.novaparks.com/parks/climb-upton",
                "https://www.novaparks.com/weddings-catering/a-venue"]
        markup = listing("".join(card(str(101 + i), f"Activity {i}", href=url) for i, url in enumerate(urls)))
        rows = nova.parse_page(markup, LISTING, PARK)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["source_url"].startswith(LISTING + "#node-") for row in rows))
        self.assertEqual(nova.discover_links(markup, LISTING, PARK), [])

    def test_lazy_photo_and_source_categories_are_preserved_without_inferences(self):
        extra = ('<div class="field--name-field-image"><img src="data:image/gif;base64,AAA" '
                 'data-src="/sites/default/files/photos/example%20photo.jpg?itok=abc"></div>'
                 '<div class="field--name-field-categories"><div class="field__item">Family/Play</div>'
                 '<div class="field__item">Outdoor Programs</div></div>')
        row = nova.parse_page(listing(card(extra=extra)), LISTING, PARK)[0]
        self.assertEqual(row["image_url"], "https://www.novaparks.com/sites/default/files/photos/example%20photo.jpg?itok=abc")
        self.assertEqual(row["source_categories"], ["Family/Play", "Outdoor Programs"])
        self.assertNotIn("kid_friendly", row)

    def test_only_activity_hours_fees_and_confirmed_booking_links_are_extracted(self):
        extra = ('<div class="content-container"><h2 class="field--name-field-additional-content-heading">Hours of Operation</h2>'
                 '<div class="field--name-field-additional-content"><p>Summer weekends, 11AM–4PM.</p></div></div>'
                 '<div class="field--name-field-fees"><h2>Fees</h2><div>$9 per group.</div></div>'
                 '<a href="https://anc.apm.activecommunities.com/novaparks/reservation?onlineSiteId=0">Book Now</a>')
        outside = '<h2>Opening Hours</h2><p>Park gates: daily at dawn.</p>'
        url = LISTING + "/a-program"
        row = nova.parse_page(detail(body="A program description.", extra=extra, outside=outside), url, PARK)[0]
        self.assertEqual(row["availability_text"], "Summer weekends, 11AM–4PM.")
        self.assertEqual(row["price_text"], "Fees $9 per group.")
        self.assertEqual(row["booking_url"], "https://anc.apm.activecommunities.com/novaparks/reservation?onlineSiteId=0")
        sparse = nova.parse_page(detail(outside=outside), url, PARK)[0]
        self.assertIsNone(sparse["availability_text"])
        self.assertIsNone(sparse["booking_url"])

    def test_discovery_is_scoped_deduplicated_and_rejects_unsafe_links(self):
        good = LISTING + "/nature-center"
        bad = ["javascript:alert(1)", "http://www.novaparks.com/parks/potomac-overlook-regional-park/things-to-do/a",
               "https://www.novaparks.com.evil.example/parks/potomac-overlook-regional-park/things-to-do/a",
               "https://www.novaparks.com@evil.example/parks/potomac-overlook-regional-park/things-to-do/a",
               "https://www.novaparks.com:444/parks/potomac-overlook-regional-park/things-to-do/a",
               LISTING + "/%2e%2e/admin", LISTING + "/../admin", LISTING + "/a?redirect=evil",
               LISTING + "#node-101", "https://www.novaparks.com/parks/upton-hill-regional-park/things-to-do/mini-golf",
               "/events/a-show", "/sites/default/files/map.pdf", "mailto:person@example.com"]
        links = [good, good, *bad]
        extra = "".join(f'<a href="{url}">Read More</a>' for url in links)
        markup = listing(card(extra=extra), extra=f'<a href="{LISTING}/outside-the-activity">Other</a>')
        self.assertEqual(nova.discover_links(markup, LISTING, PARK), [good])

    def test_source_identity_context_and_changed_page_shape_fail_explicitly(self):
        for url in ("https://evil.example/a", LISTING + "/%2e%2e/admin", LISTING + "?page=1",
                    "https://www.novaparks.com/parks/upton-hill-regional-park/things-to-do"):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "source_url_out_of_scope"):
                nova.parse_page(listing(card()), url, PARK)
        with self.assertRaisesRegex(ValueError, "page_shape_changed"):
            nova.parse_page("<html><h1>Access denied</h1></html>", LISTING, PARK)
        with self.assertRaisesRegex(ValueError, "listing_shape_changed"):
            nova.parse_page(f'<main id="main-content"><h1>{PARK["park_name"]}</h1></main>', LISTING, PARK)
        bad = deepcopy(PARK); bad["city"] = ""
        with self.assertRaisesRegex(ValueError, "park_context_invalid"):
            nova.parse_page(listing(card()), LISTING, bad)
        bad = deepcopy(PARK); bad["location_source_url"] = "https://evil.example/"
        with self.assertRaisesRegex(ValueError, "location_source_invalid"):
            nova.parse_page(listing(card()), LISTING, bad)

    def test_empty_or_redesigned_pilot_catalog_is_held_for_review(self):
        changed = card().replace("node--type-thing-to-do", "redesigned-activity-card")
        for content in ("", changed, card("102") + changed):
            with self.subTest(content=content), self.assertRaisesRegex(ValueError, "listing_shape_changed"):
                nova.parse_page(listing(content), LISTING, PARK)
            with self.assertRaisesRegex(ValueError, "listing_shape_changed"):
                nova.discover_links(listing(content), LISTING, PARK)

    def test_missing_required_title_cannot_be_reported_as_healthy_partial_data(self):
        for content in (card(title=""), card("102") + card(title="")):
            with self.subTest(content=content), self.assertRaisesRegex(ValueError, "activity_title_missing"):
                nova.parse_page(listing(content), LISTING, PARK)
            with self.assertRaisesRegex(ValueError, "activity_title_missing"):
                nova.discover_links(listing(content), LISTING, PARK)

    def test_hours_stop_before_wrapped_peer_section_or_alert_article(self):
        unrelated = (
            '<section><h2>Park Alerts</h2><p>A different trail is closed.</p></section>',
            '<article class="node--type-notification"><p>A different trail is closed.</p></article>',
        )
        for after in unrelated:
            with self.subTest(after=after):
                extra = ('<div class="content-container"><h2>Hours of Operation</h2>'
                         '<div><p>Weekends, 11AM–4PM.</p></div>' + after + '</div>')
                row = nova.parse_page(detail(extra=extra), LISTING + "/a-program", PARK)[0]
                self.assertEqual(row["availability_text"], "Weekends, 11AM–4PM.")

    def test_discovery_link_limit_is_explicit_and_matches_worker_limit(self):
        self.assertEqual(nova.MAX_LINKS, 40)
        extra = "".join(f'<a href="{LISTING}/activity-{i}">More</a>' for i in range(41))
        with self.assertRaisesRegex(ValueError, "link_limit"):
            nova.discover_links(listing(card(extra=extra)), LISTING, PARK)

    def test_suspicious_optional_links_do_not_discard_valid_activity(self):
        for url in ("data:image/svg+xml,evil", "https://127.0.0.1/private", "https://www.novaparks.com.evil.example/x"):
            with self.subTest(url=url):
                extra = (f'<div class="field--name-field-image"><img src="{url}"></div>'
                         f'<a href="{url}">Book Now</a>')
                row = nova.parse_page(listing(card(extra=extra)), LISTING, PARK)[0]
                self.assertIsNone(row["image_url"])
                self.assertIsNone(row["booking_url"])

    def test_invalid_id_and_resource_limits_do_not_report_successful_empty(self):
        invalid = listing(card()).replace('data-history-node-id="101"', 'data-history-node-id="202"')
        with self.assertRaisesRegex(ValueError, "node_identity_invalid"):
            nova.parse_page(invalid, LISTING, PARK)
        with self.assertRaisesRegex(ValueError, "candidate_limit"):
            nova.parse_page(listing("".join(card(str(i + 1)) for i in range(nova.MAX_CANDIDATES + 1))), LISTING, PARK)
        with self.assertRaisesRegex(ValueError, "html_limit"):
            nova.parse_page("x" * (nova.MAX_HTML_BYTES + 1), LISTING, PARK)

    def test_known_location_can_be_city_level_without_inventing_address_or_coordinates(self):
        context = deepcopy(PARK); context.pop("location_text")
        row = nova.parse_page(listing(card()), LISTING, context)[0]
        self.assertEqual(row["location_text"], "Potomac Overlook Regional Park, Arlington, VA")
        self.assertNotIn("lat", row)
        self.assertNotIn("lng", row)

    def test_detail_narrative_includes_additional_content_without_fees_or_foreign_articles(self):
        extra = ('<div class="field--name-field-additional-content"><p>A hand-built pavilion displays cultural art.</p>'
                 '<a class="button" href="/rental-form">Request a reservation</a>'
                 '<p><a href="/files/garden-rental.pdf">Garden Rental Form</a></p></div>'
                 '<div class="field--name-field-fees">An unrelated rental price.</div>'
                 '<article class="node--type-promo"><div class="field--name-field-additional-content">'
                 'A different ropes course.</div></article>')
        row = nova.parse_page(detail(body="The garden introduction.", extra=extra), LISTING + "/garden", PARK)[0]
        self.assertEqual(row["description"], "The garden introduction.\nA hand-built pavilion displays cultural art.")

    def test_hours_additional_content_does_not_enter_activity_description(self):
        extra = ('<div><h2 class="field--name-field-additional-content-heading">Hours of Operation</h2>'
                 '<div class="field--name-field-additional-content">Weekends, noon to dusk.</div></div>')
        row = nova.parse_page(detail(body="Activity narrative.", extra=extra), LISTING + "/program", PARK)[0]
        self.assertEqual(row["description"], "Activity narrative.")
        self.assertEqual(row["availability_text"], "Weekends, noon to dusk.")

    def test_rendered_program_offerings_exclude_booking_fees_grants_and_promotions(self):
        extra = ('<div class="paragraph--type--single-column-copy"><div class="field--name-field-copy">'
                 '<p>Contact staff to book a school visit.</p>'
                 '<div class="accordion-heading"><button>PROGRAM OFFERINGS</button></div>'
                 '<div class="accordion-content"><p>Hands-on science programs include guided nature hikes.</p>'
                 '<article class="node--type-promo">A different music festival.</article></div>'
                 '<div class="accordion-heading"><button>KNOW BEFORE YOU BOOK</button></div>'
                 '<div class="accordion-content">Group booking policy.</div>'
                 '<div class="accordion-heading"><button>FEES</button></div>'
                 '<div class="accordion-content">Conditional school pricing.</div></div></div>'
                 '<div class="paragraph--type--single-column-copy"><h2>Outdoor Kids Grants</h2>'
                 '<div class="field--name-field-copy">Funding for other park programs.</div></div>')
        row = nova.parse_page(detail(title="Field Trips", extra=extra), LISTING + "/field-trips", PARK)[0]
        self.assertEqual(row["description"], "Hands-on science programs include guided nature hikes.")

    def test_program_source_heading_boundary_retains_only_the_named_section(self):
        extra = ('<div class="paragraph--type--single-column-copy"><div class="field--name-field-copy">'
                 '<h3>Program Offerings</h3><p>Explore habitats.</p><ul><li>Guided investigation hike.</li></ul>'
                 '<h3>Fees</h3><p>Do not inherit this pricing.</p></div></div>')
        row = nova.parse_page(detail(extra=extra), LISTING + "/field-trips", PARK)[0]
        self.assertEqual(row["description"], "Explore habitats. Guided investigation hike.")

    def test_expanded_narrative_remains_bounded_and_optional(self):
        extra = '<div class="field--name-field-additional-content">' + 'x' * (nova.MAX_TEXT_CHARS + 50) + '</div>'
        row = nova.parse_page(detail(extra=extra), LISTING + "/program", PARK)[0]
        self.assertEqual(len(row["description"]), nova.MAX_TEXT_CHARS)
        self.assertIsNone(nova.parse_page(detail(), LISTING + "/program", PARK)[0]["description"])

    def test_reviewed_parent_section_enriches_only_the_existing_visitor_center(self):
        markup = parent_page('<p>The lobby hosts rotating art displays.</p>'
                             '<a href="/parks/meadowlark-botanical-gardens/things-to-do/unreviewed">Other attraction</a>')
        rows = nova.parse_page(markup, MEADOW["location_source_url"], MEADOW)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["external_id"], "novaparks:node:293")
        self.assertEqual(row["title"], "Visitor Center")
        self.assertEqual(row["source_url"], MEADOW["location_source_url"] + "/things-to-do#node-293")
        self.assertEqual(row["extracted_from_url"], MEADOW["location_source_url"])
        self.assertNotIn("admission", row["description"])
        for key in ("image_url", "source_categories", "availability_text", "price_text", "booking_url"):
            self.assertIsNone(row[key], key)
        self.assertEqual(nova.discover_links(markup, MEADOW["location_source_url"], MEADOW), [])

    def test_parent_section_is_exact_unambiguous_and_not_a_generic_parent_crawler(self):
        duplicate = ('<div class="paragraph--type--item paragraph--view-mode--accordion">'
                     '<button class="field--name-field-title">Visitor Center</button>'
                     '<div class="field--name-field-intro">Another entry.</div></div>')
        for markup in (parent_page(), parent_page('A lobby art show.', duplicate),
                       parent_page('A lobby art show.').replace('>Visitor Center<', '>Visitor Center Rentals<')):
            with self.subTest(markup=markup), self.assertRaisesRegex(ValueError, 'parent_section_changed'):
                nova.parse_page(markup, MEADOW["location_source_url"], MEADOW)
        with self.assertRaisesRegex(ValueError, 'source_url_out_of_scope'):
            nova.parse_page(parent_page('A lobby art show.'), PARK["location_source_url"], PARK)
        with self.assertRaisesRegex(ValueError, 'source_url_out_of_scope'):
            nova.parse_page(parent_page('A lobby art show.'), MEADOW["location_source_url"], PARK)


if __name__ == "__main__":
    unittest.main()
