"""Fail-closed tests for first-party Bluffton Chamber business education feed."""
import unittest
from datetime import datetime, timezone
from roomquest import lowcountry_bluffton_chamber as s

TITLE = "Get to Know Your Chamber - Membership Benefits Overview - December 2026"
DETAIL = "https://blufftonchamberofcommerce.org/events/details/get-to-know-your-chamber-membership-benefits-overview-december-2026-21153"
NOW = datetime(2026, 11, 19, 22, 15, tzinfo=timezone.utc)
PROSE = ("Welcome to an exclusive opportunity to unlock the full potential of your "
         "Chamber membership! Whether you are a new (or FUTURE) member eager to explore "
         "offerings or considering joining the Chamber, learn about networking, "
         "workshops, and community business opportunities from local professionals.")

def source():
    return dict(source_key=s.KEY, feed_url=s.FEED, kind="html",
                platform_adapter="html", timezone=s.ZONE)

def pages(*, location=None, clock=None, prose=None, title=TITLE, index_title=None):
    location = location or "The Cove (located in Buckwalter Place) 97 Progressive Street Bluffton, SC 29910"
    clock = clock or "Thursday Dec 3, 2026 8:30 AM - 10:00 AM EST"
    prose = prose or PROSE
    listing = ('<html><head><title>Greater Bluffton Chamber of Commerce - Events Calendar</title></head>'
               '<div class="gz-events-listing"><a href="' + DETAIL + '">' +
               (index_title or title) + '</a></div></html>')
    detail = ('<html><div class="gz-event-details"><h1>' + title + '</h1>'
              '<div class="gz-details-links"><div class="col-sm-5">Date and Time ' +
              clock + ' Location ' + location +
              ' Fees/Admission Complimentary Website Chamber</div></div>'
              '<div class="gz-event-description"><p>' + prose +
              '</p></div></div></html>')
    return {s.FEED: listing, DETAIL: detail}

class ChamberTests(unittest.TestCase):
    def collect(self, **kwargs):
        bodies = pages(**kwargs)
        return s.collect(source(), lambda url, accept: bodies[url], now=NOW)

    def test_valid_event_exact_address_and_local_time(self):
        rows = self.collect()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["category"], "learn")
        self.assertEqual(row["venue_address"], "97 Progressive Street, Bluffton, SC 29910")
        self.assertEqual(row["starts_at"], datetime(2026, 12, 3, 13, 30, tzinfo=timezone.utc).isoformat())
        self.assertEqual(row["ends_at"], datetime(2026, 12, 3, 15, tzinfo=timezone.utc).isoformat())
        self.assertGreater(len(row["description"]), 80)
        self.assertEqual(row["lat"], s.VENUES["the cove"]["lat"])
        self.assertNotIn("image_url", row)

    def test_source_url_and_syndication_guards(self):
        self.assertFalse(s.source_valid({**source(), "feed_url": "https://evil.test/events/catgid/6"}))
        self.assertFalse(s.event_url(DETAIL + "?from=unknown"))
        self.assertFalse(s.event_url(DETAIL.replace("blufftonchamberofcommerce.org", "other.example")))
        self.assertRaisesRegex(ValueError, "no_original_candidates", s.collect, source(),
                               lambda u, a: pages(index_title="Southern Barrel Tuesday Game Night")[u],
                               now=NOW)

    def test_reject_location_drift_and_time_mismatch(self):
        self.assertRaisesRegex(ValueError, "no_verified_occurrences", self.collect,
                               location="The Cove 99 Progressive Street Bluffton, SC 29910")
        self.assertRaisesRegex(ValueError, "no_verified_occurrences", self.collect,
                               clock="Thursday Dec 3, 2026 8:30 AM - 10:00 AM EDT")
        self.assertRaisesRegex(ValueError, "no_verified_occurrences", self.collect,
                               clock="Friday Dec 3, 2026 8:30 AM - 10:00 AM EST")

    def test_reject_member_only_and_no_public_description(self):
        self.assertRaisesRegex(ValueError, "no_verified_occurrences", self.collect,
                               prose="Members only. "+PROSE)
        self.assertRaisesRegex(ValueError, "no_verified_occurrences", self.collect,
                               prose="A brief announcement with no details about public admission or membership status at all.")

if __name__ == "__main__":
    unittest.main()
