"""Source-identity, original publisher event evidence and ICS cross-checks."""
from datetime import datetime, timezone
import pytest
from roomquest import rcnv_santa_cruz as m

NOW = datetime(2026, 11, 19, 22, tzinfo=timezone.utc)
TITLE = "Korea Is Not a War Base: Dispatches from the 2026 Jaju Solidarity Brigade"
URL = ("https://rcnv.org/events/"
       "korea-is-not-a-war-base-dispatches-from-the-2026-jaju-solidarity-brigade/")
SRC = {"source_key": m.KEY, "feed_url": m.INDEX,
       "kind": "html", "platform_adapter": "html", "timezone": m.ZONE}
INDEX = f'<div class="em-events-grid"><div class="em-item"><h3 class="em-item-title"><a href="{URL}">{TITLE}</a></h3></div></div>'
DETAIL = f"""
<h1 class="entry-title">{TITLE}</h1>
<div class="em-event-date">Nov 22, 2026</div>
<div class="em-event-time">3:00 pm - 5:00 pm</div>
<div class="em-item-meta-line em-event-location"><a>Resource Center for Nonviolence</a><br/>
612 Ocean St., Santa Cruz, CA, 95060</div>
<a class="em-a2c-download" href="{URL}ical/">Download ICS</a>
<div class="em-event-categories"><ul><li>Antiracism</li><li>Resisting Militarism</li></ul></div>
<section class="em-event-content"><p>Join organizers for a reportback
on their travels, the movement against occupation, and public solidarity.
The speakers will share the work of regional organizers and invite community
questions. This original publisher narrative is intentionally long enough
to require full event details rather than a title or a teaser summary.
Everyone is welcome to discuss the history and the local response.</p></section>
"""
ICS = f"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:559@rcnv.org
DTSTART;TZID=America/Los_Angeles:20261122T150000
DTEND;TZID=America/Los_Angeles:20261122T170000
URL:{URL}
SUMMARY:{TITLE}
X-APPLE-STRUCTURED-LOCATION;VALUE=URI:geo:0,0
END:VEVENT
END:VCALENDAR
"""

def feed(url, accept):
    if url == m.INDEX:
        assert accept == "text/html"
        return INDEX
    if url == URL:
        assert accept == "text/html"
        return DETAIL
    if url == URL + "ical/":
        assert accept == "text/calendar"
        return ICS
    raise AssertionError(f"unexpected original source URL {url}")

def test_original_publisher_event_full_story_and_timezone():
    rows = m.collect(SRC, feed, now=NOW)
    assert len(rows) == 1
    e = rows[0]
    assert e["starts_at"] == "2026-11-22T23:00:00+00:00"
    assert e["ends_at"] == "2026-11-23T01:00:00+00:00"
    assert e["venue_name"] == m.VENUE
    assert e["venue_address"] == m.STREET
    assert e["lat"] is None and e["lng"] is None
    assert "Everyone is welcome" in e["description"]
    assert e["id"] == "rcnv-559-rcnv-org-20261122"
    assert e["publisher_categories"] == ["Antiracism", "Resisting Militarism"]
    assert not e.get("image_candidate_url")

def test_source_identity_guard():
    with pytest.raises(ValueError, match="rcnv_wrong_source_identity"):
        m.collect({**SRC, "feed_url": "https://other.com"}, feed, now=NOW)

@pytest.mark.parametrize("changed", [
    INDEX.replace("https://rcnv.org", "https://attacker.example"),
    INDEX.replace("/events/korea", "/events/../korea"),
])
def test_offsite_or_malformed_calendar_links_rejected(changed):
    def bad(u, accept):
        return changed if u == m.INDEX else feed(u, accept)
    with pytest.raises(ValueError, match="rcnv_index_cross_host_or_invalid_link"):
        m.collect(SRC, bad, now=NOW)

@pytest.mark.parametrize("changed,reason", [
    (ICS.replace("T170000", "T180000"), "rcnv_page_ics_schedule_mismatch"),
    (ICS.replace("America/Los_Angeles", "America/New_York"), "rcnv_ics_start_missing"),
    (ICS.replace("UID:559@rcnv.org", "UID:"), "rcnv_ics_uid_missing"),
    (ICS.replace("https://rcnv.org", "https://outside.example"), "rcnv_ics_url_mismatch"),
])
def test_incorrect_calendar_times_or_identity_not_published(changed, reason):
    def bad(u, a):
        return changed if u.endswith("ical/") else feed(u, a)
    with pytest.raises(ValueError, match=reason):
        m.collect(SRC, bad, now=NOW)

def test_full_narrative_is_required():
    def bad(u, a):
        return DETAIL.replace("Join organizers", "Welcome")[:200] if u == URL else feed(u, a)
    with pytest.raises(ValueError, match="rcnv_event_schema_changed|rcnv_full_narrative_missing"):
        m.collect(SRC, bad, now=NOW)

def test_offsite_event_venue_cannot_use_publisher_headquarters():
    def bad(u, a):
        return DETAIL.replace("612 Ocean St., Santa Cruz, CA, 95060",
                              "Unknown private location") if u == URL else feed(u, a)
    with pytest.raises(ValueError, match="rcnv_event_venue_unverified"):
        m.collect(SRC, bad, now=NOW)

def test_expired_event_is_not_republished():
    future = datetime(2026, 12, 5, 12, tzinfo=timezone.utc)
    assert m.collect(SRC, feed, now=future) == []
