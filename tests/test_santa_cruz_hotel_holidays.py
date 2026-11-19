"""Santa Cruz owner-authored hotel holiday calendars, no syndicated rows or guessed points."""
from datetime import datetime, timezone
import pytest

from roomquest import santa_cruz_hotel_holidays as h
from roomquest.publisher_evidence import family

NOW = datetime(2026, 11, 19, 21, tzinfo=timezone.utc)
CHAMINADE_BODY = (
    "<main><h1>Breakfast with Santa</h1>"
    "<p>Gather the family for a merry morning filled with holiday magic and delicious bites. "
    "Enjoy a festive holiday buffet, meet Santa and his friends, and capture the perfect "
    "holiday memory with a special photo with Santa.</p>"
    "<div>Breakfast with Santa Two Dates : Saturday, December 5 &amp; Sunday, December 13, 2026 "
    "Times : 9:00 am - 11:00 am Where : Sunset Dining Room at Chaminade Resort &amp; Spa</div>"
    "<div>Buffet Selections Scrambled Eggs, Bacon &amp; Sausage, Potatoes, Pancakes, Pastries, "
    "Fruit, Juice, Coffee &amp; Tea, Hot Cocoa Station Selections subject to change</div>"
    "</main><footer><p>One Chaminade Lane, Santa Cruz, CA 95065</p></footer>"
)
THANKS_BODY = (
    "<main><h1>Thanksgiving at Chaminade</h1>"
    "<p>Celebrate Thanksgiving with a festive meal overlooking Santa Cruz and the Monterey Bay.</p>"
    "<div>Thanksgiving Day Buffet Thursday, November 26, 2026 9:00 am - 5:00 pm</div>"
    "<div>Selections Breakfast Entrees: Scrambled Eggs, Bacon, Sausage, Pancakes, "
    "Omelet Bar with Carving Station, Raw Seafood Bar, Fresh Fruit and Salad Station, "
    "Dessert Bar, Herbed Roasted Turkey Breast and Apple Sage Stuffing "
    "Selections subject to change</div>"
    "</main><footer><p>One Chaminade Lane, Santa Cruz, CA 95065</p></footer>"
)
DREAM_BODY = (
    "<main><h1>Join us for the 8th Annual Breakfast with Santa!</h1>"
    "<div class='event-details'><div class='description'>"
    "<h3>Dream Inn Presents Breakfast with Santa</h3>"
    "<h2>Saturday December 12th, 2026</h2><h3>9:00am - 12:00pm</h3>"
    "<p>Program Starts 9:45am. Join us for the festivities: FULL OCEAN VIEWS "
    "BREAKFAST BUFFET FULL BAR (FOR THE PARENTS, NOT THE ELVES) COOKIE DECORATING "
    "ARTS &amp; CRAFTS FACE PAINTING VISIT AND SONGS WITH SANTA, AND SPECIAL "
    "GUEST MRS. CLAUS SURPRISE CHRISTMAS STORY READING! Happy Holidays!</p>"
    "</div></div></main><footer>175 W Cliff Dr, Santa Cruz, CA 95060</footer>"
)

def src(key):
    return dict(source_key=key, feed_url=h.SOURCES[key][0], kind="html",
                platform_adapter="html", timezone=h.ZONE)

def fetch(**updates):
    data={h.SANTA_URL:CHAMINADE_BODY,h.THANKSGIVING_URL:THANKS_BODY,h.DREAM_URL:DREAM_BODY}
    data.update(updates)
    return lambda url,accept: data[url]

def test_chaminade_three_independent_original_sessions():
    rows=h.collect(src(h.CHAMINADE),fetch(),now=NOW)
    assert len(rows)==3
    assert [r["starts_at"][:10] for r in rows]==["2026-11-26","2026-12-05","2026-12-13"]
    assert all("Chaminade Lane" in r["venue_address"] for r in rows)
    assert all(r["lat"] is None and r["lng"] is None for r in rows)
    assert rows[0]["ends_at"].startswith("2026-11-27T01:00")
    assert "Raw Seafood Bar" in rows[0]["description"]
    assert "meet Santa" in rows[1]["description"]
    assert all(family(h.CHAMINADE,r["event_url"]) for r in rows)

def test_dream_inn_has_real_hotel_street_and_program_time_not_start():
    rows=h.collect(src(h.DREAM_INN),fetch(),now=NOW)
    assert len(rows)==1
    row=rows[0]
    assert row["starts_at"].startswith("2026-12-12T17:00")
    assert row["ends_at"].startswith("2026-12-12T20:00")
    assert row["venue_address"]=="175 W Cliff Dr, Santa Cruz, CA 95060"
    assert row["lat"] is None and row["lng"] is None
    assert "COOKIE DECORATING" in row["description"]
    assert family(h.DREAM_INN,row["event_url"])=="santa_cruz_hotel:"+h.DREAM_INN

def test_source_and_event_identity_fail_closed():
    with pytest.raises(ValueError,match="hotel_source_identity_mismatch"):
        h.collect(src(h.DREAM_INN)|{"feed_url":h.DREAM_URL+"?format=json"},fetch(),now=NOW)
    assert not h.event_url(h.DREAM_INN,h.DREAM_URL+"?redirect=evil")
    assert not h.event_url(h.CHAMINADE,h.DREAM_URL)
    assert family(h.CHAMINADE,"https://evil.invalid/event") is None

def test_owner_schedule_and_address_drift_are_not_accepted():
    with pytest.raises(ValueError,match="hotel_santa_schedule_missing"):
        h.collect(src(h.CHAMINADE),fetch(**{h.SANTA_URL:CHAMINADE_BODY.replace("December 13","December 14")}),now=NOW)
    with pytest.raises(ValueError,match="hotel_thanksgiving_schedule_missing"):
        h.collect(src(h.CHAMINADE),fetch(**{h.THANKSGIVING_URL:THANKS_BODY.replace("November 26","November 27")}),now=NOW)
    with pytest.raises(ValueError,match="hotel_official_street_missing"):
        h.collect(src(h.DREAM_INN),fetch(**{h.DREAM_URL:DREAM_BODY.replace("175 W Cliff Dr","Santa Cruz")}),now=NOW)
    with pytest.raises(ValueError,match="hotel_dream_schedule_or_narrative_drift"):
        h.collect(src(h.DREAM_INN),fetch(**{h.DREAM_URL:DREAM_BODY.replace("December 12th","December 13th")}),now=NOW)

def test_no_invented_annually_recurring_sessions():
    assert h.collect(src(h.CHAMINADE),fetch(),now=datetime(2027,2,1,tzinfo=timezone.utc))==[]
    assert h.collect(src(h.DREAM_INN),fetch(),now=datetime(2027,2,1,tzinfo=timezone.utc))==[]
