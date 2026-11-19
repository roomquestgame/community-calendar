"""Santa Cruz Turkey Trot + MeloMelo calendar publisher proof isolation."""
from datetime import datetime, timezone
import json
import pytest
from roomquest import santa_cruz_turkey_trot as race, santa_cruz_melo as melo
from roomquest.publisher_evidence import family

NOW = datetime(2026, 11, 19, 2, tzinfo=timezone.utc)


def source(module):
    return dict(source_key=module.KEY, feed_url=module.URL,
                kind="html", platform_adapter="html", timezone=module.ZONE)


RACE_EVENT = {
    "@type": "SportsEvent", "name": "Santa Cruz Turkey Trot",
    "startDate": "2026-11-21T07:45:00-08:00",
    "endDate": "2026-11-21T10:00:59-08:00",
    "description": ("Join the Turkey Trot on the Santa Cruz coast. "
                    "Enjoy an out-and-back race near Natural Bridges State Park, "
                    "with the 10K, 5K and kids 1K, finisher socks for the 10K and 5K, "
                    "and awards for top finishers. Participants can pick up their race bibs."),
    "location": {"address": {
        "streetAddress": "2300 Delaware Ave", "addressLocality": "Santa Cruz",
        "addressRegion": "CA", "postalCode": "95060", "addressCountry": "US"
    }},
}


def race_html(event=None):
    return ('<html><body><main>Santa Cruz Turkey Trot</main><script type="application/ld+json">'
            + json.dumps(event or RACE_EVENT) + '</script>' + (" " * 700) + '</body></html>')


def test_turkey_first_party_event_window_and_address():
    rows = race.collect(source(race), lambda u, a: race_html(), now=NOW)
    assert len(rows) == 1
    assert rows[0]["starts_at"] == "2026-11-21T15:45:00+00:00"
    assert rows[0]["ends_at"] == "2026-11-21T18:00:59+00:00"
    assert rows[0]["venue_address"] == race.STREET
    assert rows[0]["lat"] is None and rows[0]["lng"] is None
    assert len(rows[0]["description"]) >= 150
    assert family(race.KEY, race.URL) == "santa_cruz_turkey_trot"
    assert family(race.KEY, race.URL+"?redirect=bad") is None


def test_turkey_missing_street_drifts_and_outdated_absent():
    with pytest.raises(ValueError, match="street_changed"):
        race.collect(source(race), lambda u, a: race_html(RACE_EVENT | {
            "location": {"address": RACE_EVENT["location"]["address"] | {"streetAddress": "Some other street"}}
        }), now=NOW)
    with pytest.raises(ValueError, match="date_drift"):
        race.collect(source(race), lambda u, a: race_html(RACE_EVENT | {
            "startDate": "2026-11-22T07:45:00-08:00"
        }), now=NOW)
    assert race.collect(source(race), lambda u, a: race_html(), now=datetime(2027,1,2,tzinfo=timezone.utc)) == []


def _item(title, start="2026-11-23T19:00:00-08:00",
          end="2026-11-23T22:30:00-08:00", venue="Open Mic Night",
          prose="Open Mic Night. Sign-ups at 7:00 PM. Starts at 8:00 PM every Monday. Join us to hear local musicians and build community!"):
    return f"""<li class="simcal-event simcal-events-calendar-922">
    <span class="simcal-event-title">{title}</span>
    <div class="simcal-event-details"><p>
    <span class="simcal-event-start-time" content="{start}">7:00 pm</span>
    <span class="simcal-event-end-time" content="{end}">10:30 pm</span></p>
    <meta itemprop="address" content="{venue}"/>
    <div class="simcal-event-description"><p>{prose}</p></div></div></li>"""


def melo_html(*entries):
    return ('<html><body><h1>SANTA CRUZ</h1><section>1101 Pacific Ave '
            'Santa Cruz, CA 95060</section><ul>' + ''.join(entries)
            + '</ul></body></html>' + (" " * 900))


def test_melo_named_venue_to_official_street_and_real_occurrences():
    raw = melo_html(_item("Open Mic Night"), _item("Open Mic Night"),
                    _item("Tidal Tuesday $6 High Tides"),
                    _item("Charity Poker Tournament", start="2026-11-21T20:00:00-08:00",
                          end="2026-11-22T00:00:00-08:00",
                          venue="MeloMelo Kava Bar, 1101 Pacific Ave Suite D, Santa Cruz, CA",
                          prose="3 tables, winner from each table wins a prize. All proceeds donated to a local charity in Santa Cruz."))
    rows = melo.collect(source(melo), lambda u, a: raw, now=NOW)
    assert len(rows) == 2
    assert len(set(r["id"] for r in rows)) == 2
    assert all(r["venue_address"] == melo.ADDRESS and r["lat"] is None and r["lng"] is None for r in rows)
    assert all(r["event_url"] == melo.URL and r["description"] for r in rows)
    assert family(melo.KEY, melo.URL) == "santa_cruz_melo"
    assert family(melo.KEY, "https://evil.example/santacruz/") is None


def test_melo_no_unknown_street_fabrication_or_timezone_drift():
    raw = melo_html(_item("Open Mic Night", venue="999 Unknown Rd, Another City CA"))
    assert melo.collect(source(melo), lambda u, a: raw, now=NOW) == []
    raw = melo_html(_item("Open Mic Night", start="2026-11-23T19:00:00-05:00"))
    with pytest.raises(ValueError, match="timezone_drift"):
        melo.collect(source(melo), lambda u, a: raw, now=NOW)
    raw = melo_html(_item("Open Mic Night")).replace("1101 Pacific Ave", "500 Fake Road")
    with pytest.raises(ValueError, match="official_street_unverified"):
        melo.collect(source(melo), lambda u, a: raw, now=NOW)


def test_melo_bad_source_and_truncated_event_text():
    with pytest.raises(ValueError, match="unregistered"):
        melo.collect(source(melo) | {"feed_url": "https://attacker.test"}, lambda u,a: melo_html(), now=NOW)
    assert melo.collect(source(melo), lambda u,a: melo_html(_item("Open Mic Night", prose="Hi")), now=NOW) == []

