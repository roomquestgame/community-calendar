"""Santa Cruz Art League: official HTML receipts, no guessing from recurring prose."""
from datetime import datetime, timezone
import pytest
from roomquest import santa_cruz_art_league as m
from roomquest.publisher_evidence import family

NOW = datetime(2026, 11, 19, 21, tzinfo=timezone.utc)
SOURCE = {"source_key":m.KEY,"feed_url":m.INDEX,"kind":"html",
          "platform_adapter":"html","timezone":m.ZONE}
BODY1 = "Join us in celebrating the creativity of our artistic community! The Santa Cruz Art League Members’ Exhibition is a showcase of art by current members, open to the public to enjoy."
BODY2 = "This year’s theme, Simple Pleasures, was selected through a vote by our community. Artists are invited to reflect on the small, meaningful moments that bring joy, whether found in food shared with friends, time in nature, beloved pets, creative rituals, or the everyday beauty that surrounds us."
CLOCK = "First Friday Reception: December 4, 5:00 pm - 7:30 pm"
YEAR = "On View: Wednesday, November 18 - Friday, December 18, 2026"
STREET = "526 Broadway Santa Cruz, CA 95060"


def fixture(index=None, detail=None):
    index = index if index is not None else (
        "<main><h3>Members’ Exhibition: Simple Pleasures</h3>"
        f"<p>{CLOCK}</p><p>{STREET}</p></main>")
    detail = detail if detail is not None else (
        "<main><h1>Simple Pleasures</h1>"
        f"<p>{YEAR}</p><p>{CLOCK}</p>"
        f"<p>{BODY1}</p><p>{BODY2}</p><p>{STREET}</p></main>")
    return lambda url, accept: {m.INDEX: index, m.DETAIL: detail}[url]


def test_verified_only_publisher_event_and_geocodio_street():
    rows=m.collect(SOURCE,fixture(),now=NOW)
    assert len(rows)==1
    row=rows[0]
    assert row["venue_address"]==m.STREET and row["lat"] is None and row["lng"] is None
    assert row["starts_at"].startswith("2026-12-05T01:00:00")
    assert row["ends_at"].startswith("2026-12-05T03:30:00")
    assert row["event_url"]==m.DETAIL
    assert BODY1 in row["description"] and BODY2 in row["description"]
    assert row.get("image_url") in (None,"")
    assert family(m.KEY,m.DETAIL)=="santa_cruz_art_league"
    assert family(m.KEY,"https://evil.test/event")==None


def test_fail_closed_on_publisher_disagreement():
    with pytest.raises(ValueError,match="art_league_event_clock_missing"):
        m.collect(SOURCE,fixture(detail="<main><h1>Simple Pleasures</h1><p>"+YEAR+"</p><p>December 5, 5pm - 7:30pm</p><p>"+STREET+"</p></main>"),now=NOW)
    with pytest.raises(ValueError,match="art_league_exhibition_year_missing"):
        m.collect(SOURCE,fixture(detail="<main><h1>Simple Pleasures</h1><p>"+CLOCK+"</p><p>"+BODY1+"</p><p>"+BODY2+"</p><p>"+STREET+"</p></main>"),now=NOW)


def test_no_invented_street_or_exhibition_narrative():
    with pytest.raises(ValueError,match="art_league_official_street_missing"):
        m.collect(SOURCE,fixture(index="<main><h3>Members’ Exhibition: Simple Pleasures</h3><p>"+CLOCK+"</p></main>"),now=NOW)
    with pytest.raises(ValueError,match="art_league_narrative_missing"):
        m.collect(SOURCE,fixture(detail="<main><h1>Simple Pleasures</h1><p>"+YEAR+"</p><p>"+CLOCK+"</p><p>Generic workshop.</p><p>"+STREET+"</p></main>"),now=NOW)


def test_bounded_url_contract_and_no_future_inferred_sessions():
    with pytest.raises(ValueError,match="art_league_source_identity_mismatch"):
        m.collect(SOURCE|{"feed_url":m.INDEX+"?format=json"},fixture(),now=NOW)
    assert not m.event_url(m.DETAIL+"?format=json")
    assert not m.event_url("https://www.scal.org/members-show-2026")
    assert m.collect(SOURCE,fixture(),now=datetime(2027,2,1,tzinfo=timezone.utc))==[]
