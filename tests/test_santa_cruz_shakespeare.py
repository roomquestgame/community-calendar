"""Original Santa Cruz Shakespeare dates, venue, student exclusions and drift gates."""
from datetime import datetime, timezone
import pytest
from roomquest import santa_cruz_shakespeare as m
from roomquest.publisher_evidence import family

NOW = datetime(2026, 11, 19, 9, tzinfo=timezone.utc)
SOURCE = {"source_key":m.KEY,"feed_url":m.URL,"kind":"html","platform_adapter":"html","timezone":m.ZONE}
TICKET = "https://santacruzshakespeare.my.salesforce-sites.com/ticket/#/instances/"

def page(*, venue="846 Front St, Santa Cruz, CA 95060", runtime="95 minutes with no intermission",
         n="A Christmas Carol returns as a holiday tradition for the whole family! Audiences can expect a theatrical and music-filled adaptation of this classic play in the heart of Santa Cruz.",
         extra=""):
    return (f'<main><div class="elementor-widget-text-editor">'
            f'<p>A Christmas Carol by Charles Dickens. Adapted by Charles Pasternak. Directed by Alicia Gibson. Music Direction by Luke Shepherd.</p>'
            f'<p>{n} Please note that this production is staged at the Veterans Memorial Building in Downtown Santa Cruz, located at {venue}.</p>'
            '<p><strong>PERFORMANCES:</strong></p><ul>'
            f'<li><a href="{TICKET}a0Fcx00000FrjeHEAR">Thursday, December 3, 2026 at 2:00 PM</a> – preview</li>'
            '<li><a href="https://santacruzshakespeare.org/education/educators/student-matinees/">Tuesday, December 8 at 9:00 AM</a> – Student Matinee</li>'
            f'<li><a href="{TICKET}a0Fcx00000FrBfqEAF">Friday, December 4, 2026 at 7:00 PM</a> – opening</li>'
            + extra +
            f'</ul><p>RUN TIME:</p><p>{runtime}</p></div></main>')

def collector(html=None, now=NOW, source=SOURCE):
    return m.collect(source, lambda url, accept: (html or page()), now=now)

def test_real_publisher_venue_street_runtimes_and_identity():
    rows=collector()
    assert len(rows)==2
    assert [x["starts_at"] for x in rows]==["2026-12-03T22:00:00+00:00","2026-12-05T03:00:00+00:00"]
    assert [x["ends_at"] for x in rows]==["2026-12-03T23:35:00+00:00","2026-12-05T04:35:00+00:00"]
    assert all(x["venue_address"]==m.STREET and x["lat"] is None and x["lng"] is None for x in rows)
    assert all(x["event_url"]==m.URL and x["publisher_ticket_url"].startswith(TICKET) for x in rows)
    assert all(len(x["description"])>=220 and x.get("image_url") in (None,"") for x in rows)
    assert len({x["id"] for x in rows})==2
    assert all(x["publisher_details"] == {} for x in rows)
    assert family(m.KEY,m.URL)=="santa_cruz_shakespeare"
    assert family(m.KEY,"https://other.net") is None

def test_fail_closed_on_absent_street_narrative_runtime():
    with pytest.raises(ValueError, match="shakespeare_venue_runtime_narrative_missing"):
        collector(page(venue="somewhere in Santa Cruz"))
    with pytest.raises(ValueError, match="shakespeare_venue_runtime_narrative_missing"):
        collector(page(runtime="90 minutes"))
    with pytest.raises(ValueError, match="shakespeare_venue_runtime_narrative_missing"):
        collector(page(n="Just a show"))

def test_fail_closed_on_fake_date_wrong_host_or_duplicate_instance():
    extra=f'<li><a href="{TICKET}a0Fcx00000FrZzzEAR">Sunday, December 7, 2026 at 7:00 PM</a></li>'
    with pytest.raises(ValueError,match="shakespeare_weekday_disagreement"):
        collector(page(extra=extra))
    with pytest.raises(ValueError,match="shakespeare_duplicate_instance"):
        collector(page(extra=f'<li><a href="{TICKET}a0Fcx00000FrjeHEAR">Saturday, December 5, 2026 at 7:00 PM</a></li>'))
    with pytest.raises(ValueError,match="shakespeare_date_or_ticket_drift"):
        collector(page(extra='<li><a href="https://evil.test/2026">Saturday, December 5, 2026 at 7:00 PM</a></li>'))

def test_source_identity_and_expiration():
    with pytest.raises(ValueError,match="shakespeare_source_identity_mismatch"):
        collector(source=SOURCE|{"feed_url":m.URL+"?x=1"})
    assert collector(now=datetime(2027,3,1,tzinfo=timezone.utc))==[]
    assert not m.event_url(m.URL+"?x=1")

