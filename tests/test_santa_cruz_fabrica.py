"""Strict first-party Fábrica source; December publisher conflict must not leak."""
from datetime import datetime, timezone
import pytest
from roomquest import santa_cruz_fabrica as f
from roomquest.publisher_evidence import family, image_url
from roomquest.preview_worker import PreviewError

NOW=datetime(2026,11,19,20,tzinfo=timezone.utc)
SOURCE={"source_key":f.KEY,"feed_url":f.URL,"kind":"html","platform_adapter":"html","timezone":f.ZONE}
PHOTO="https://thefabricaworkshop.org/wp-content/uploads/2026/09/img_9330.heic-1.jpg"
NARR="Bring something to mend and learn some new mending methods! You’re also welcome to join with any hand-stitching project (knitting, crochet, embroidery, etc.)."

def html_block(dates, *, street="703 Pacific Ave, Santa Cruz", body=NARR,photo=True):
    img=('<figure><img data-orig-file="'+PHOTO+'"/></figure>') if photo else ''
    return ('<article><div class="entry-content">'
            '<div class="wp-block-columns"><div><h2>“Mending Circle”</h2>'+img+'</div>'
            '<div><p>@ The Fábrica '+street+'</p><p>'+dates+'</p>'
            '<p>'+body+'</p></div></div></div></article>')

def fixtures(index=None, blog=None, contact=None):
    index=index if index is not None else html_block("Tuesdays! November 10 November 24 December 6 6pm – 8 pm",
                                                     body=NARR+" * No machines during this time.")
    blog=blog if blog is not None else html_block("Tuesdays! November 10 & 24, December 8, 2026 6pm – 8 pm")
    contact=contact if contact is not None else '<article><div class="entry-content">The Fábrica, 703 Pacific Avenue, Santa Cruz, California</div></article>'
    content={f.URL:index,f.BLOG:blog,f.CONTACT:contact}
    return lambda url, accept: content[url]

def run(fetch=None,source=None,now=NOW):
    return f.collect(source or SOURCE, fetch or fixtures(),now=now)

def test_only_intersection_of_original_schedules_no_invented_tuesday_repeats():
    rows=run()
    assert len(rows)==1
    row=rows[0]
    assert row["starts_at"].startswith("2026-11-25T02:00:00")
    assert row["ends_at"].startswith("2026-11-25T04:00:00")
    assert row["venue_address"]==f.STREET
    assert row["event_url"]==f.BLOG
    assert row["lat"] is None and row["lng"] is None
    assert "No machines" in row["description"]
    assert row["image_url"]==PHOTO
    assert row["publisher_categories"]==["Mending","Textile Art","Community Workshop"]
    assert family(f.KEY,f.BLOG)=="santa_cruz_fabrica"
    assert image_url(PHOTO,"santa_cruz_fabrica")==PHOTO
    assert "December 6" not in row["description"]

def test_december_conflict_held_even_if_it_is_a_future_day():
    assert all(not row["starts_at"].startswith("2026-12-") for row in run())

def test_consistent_future_december_occurrence_if_both_owner_pages_corrected():
    corrected=fixtures(index=html_block("Tuesdays! November 24 December 8 6pm – 8 pm"),
                       blog=html_block("Tuesdays! November 24 December 8, 2026 6pm – 8 pm"))
    assert len(run(corrected))==2

def test_no_event_if_primary_address_or_contact_drift():
    with pytest.raises(ValueError,match="fabrica_event_incomplete"):
        run(fixtures(index=html_block("Tuesdays! November 24 6pm – 8 pm",street="Santa Cruz")))
    with pytest.raises(ValueError,match="fabrica_official_address_drift"):
        run(fixtures(contact="<article><div class='entry-content'>Santa Cruz</div></article>"))

def test_no_event_if_unpublished_narrative_or_year_or_clock():
    with pytest.raises(ValueError,match="fabrica_event_incomplete"):
        run(fixtures(index=html_block("Tuesdays! November 24 6pm – 8 pm",body="")))
    with pytest.raises(ValueError,match="fabrica_publisher_year_missing"):
        run(fixtures(blog=html_block("Tuesdays! November 24 6pm – 8 pm")))
    with pytest.raises(ValueError,match="fabrica_event_incomplete"):
        run(fixtures(index=html_block("Tuesdays! November 24 7pm – 8 pm")))

def test_no_identity_or_photo_host_trust():
    with pytest.raises(ValueError,match="fabrica_source_identity_mismatch"):
        run(source=SOURCE|{"feed_url":"https://other.test/events"})
    assert not f.event_url("https://other.test/2026/10/27/spooky-season-happenings-at-the-fabrica-and-the-hub/")
    assert not f.event_url(f.BLOG+"?next=1")
    assert f.photo_url("https://evil.test"+PHOTO[29:]) is None
    assert f.photo_url("https://thefabricaworkshop.org/wp-content/uploads/2026/09/logo.jpg") is None

def test_empty_once_dates_expire():
    assert run(now=datetime(2027,2,1,tzinfo=timezone.utc))==[]

