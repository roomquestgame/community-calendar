from datetime import datetime, timezone
from html import escape
import json
import pytest

from roomquest import santa_cruz_landing as s

NOW = datetime(2026, 11, 19, 20, tzinfo=timezone.utc)
SRC = {"source_key": s.KEY, "feed_url": s.URL,
       "kind": "html", "platform_adapter": "html", "timezone": s.ZONE}
LINK = "https://thelandingsv.org/events/fred-eaglesmith-by-snazzy-productions/"
NARRATIVE = ("Fred Eaglesmith performs original songs in Scotts Valley. "
             "The concert brings a touring songwriter and band to The Landing, "
             "with a live audience and a full evening of music. "
             "Tickets are offered through the publisher's original event page.")

def fixture(*, link=LINK, name="Fred Eaglesmith by Snazzy Productions",
            day="21 November 2026", start="7:00 pm", end="9:00 pm",
            address="251B Kings Village Rd, Scotts Valley", desc=NARRATIVE,
            status="https://schema.org/EventScheduled",
            schema_day="2026-11-21", private=False):
    title = "Private Event" if private else name
    event = {"@type":"Event", "url":link, "name":title,
             "eventStatus":status,
             "startDate":schema_day+"T12:00:00-07:00",
             "endDate":schema_day+"T14:00:00-07:00",
             "location":{"@type":"Place","name":"The Landing","address":address},
             "description":desc}
    return ('<script type="application/ld+json">'+json.dumps(event)+'</script>'
       + '<div class="mec-event-footer-carousel-type3">'
       + '<div class="mec-event-datetime-info-wrap">'
       + '<span class="mec-start-date-label">'+day+'</span>'
       + '<span class="mec-start-time">'+start+'</span>'
       + (('<span class="mec-end-time">'+end+'</span>') if end else '')
       + '</div><h4 class="mec-event-carousel-title"><a href="'+link+'">'+escape(title)+'</a></h4>'
       + '<div class="mec-event-location">'+address+'</div>'
       + '</div>')

def collect(html):
    return s.collect(SRC,lambda url,accept:html,now=NOW)

def test_original_description_visible_pacific_clock_street_without_fake_geocode():
    rows=collect(fixture())
    assert len(rows)==1
    r=rows[0]
    assert r["starts_at"]=="2026-11-22T03:00:00+00:00"
    assert r["ends_at"]=="2026-11-22T05:00:00+00:00"
    assert "songwriter" in r["description"] and r["lat"] is None and r["lng"] is None
    assert r["venue_address"]==s.STREET and r["event_url"]==LINK
    assert r["details_evidence_url"]==LINK

def test_original_wrong_schema_hour_cannot_override_display_clock():
    rows=collect(fixture(start="8:00 pm",end="10:00 pm"))
    assert rows[0]["starts_at"]=="2026-11-22T04:00:00+00:00"

@pytest.mark.parametrize("kw",[
    {"end":""},{"start":"unknown"},{"address":"123 Remote Venue, Watsonville"},
    {"private":True},{"schema_day":"2026-11-22"},
    {"status":"https://schema.org/EventCancelled"},{"desc":"Short teaser"},
    {"link":"https://evil.example/events/fred-eaglesmith-by-snazzy-productions/"},
])
def test_incomplete_ambiguous_offsite_private_or_wrong_owner_not_admitted(kw):
    assert collect(fixture(**kw))==[]

def test_source_tuple_bound_and_urls_strict():
    with pytest.raises(ValueError,match="unregistered_landing_source"):
        s.collect(SRC|{"feed_url":"https://fake.example/"},lambda url,accept:fixture(),now=NOW)
    assert not s.event_url("http://thelandingsv.org/events/a/")
    assert not s.event_url("https://thelandingsv.org/events/a/?x=1")

def test_no_unbounded_or_empty_carousel():
    with pytest.raises(ValueError,match="landing_missing_or_oversize_carousel"):
        collect("<p>No future events</p>")
    with pytest.raises(ValueError,match="landing_missing_or_oversize_carousel"):
        collect(fixture()*(s.MAX_RECORDS+1))

def test_stable_ids_and_duplicates():
    html=fixture()+fixture()
    r=collect(html)
    assert len(r)==1 and r[0]["id"]

def test_bounded_only_events_with_valid_ends():
    html=fixture()+fixture(name="Unverified holiday concert", link="https://thelandingsv.org/events/holiday-concert/", end="")
    r=collect(html)
    assert len(r)==1

