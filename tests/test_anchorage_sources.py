"""Anchorage primary calendars: exact feeds, full narratives and verified venues."""
from datetime import datetime, timezone
import json

import pytest

from roomquest import anchorage_sources as ak
from roomquest import preview_worker

NOW = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
LIBRARY_EVENT = """BEGIN:VEVENT
UID:20870
DTSTART:20261202T193000Z
DTEND:20261202T200000Z
SUMMARY:Parachute Storytime at Muldoon
DESCRIPTION:<p>Stories &amp; movement for toddlers at the library.</p>
LOCATION:1251 Muldoon Rd.\\, Suite 158\\, Muldoon Town Center\\, Anchorage\\, AK\\, 99504\\, US
URL:https://anchorage.librarycalendar.com/event/parachute-storytime
CATEGORIES:Storytime
STATUS:CONFIRMED
END:VEVENT
"""
def source(key):
    url, kind, adapter = ak.SOURCES[key]
    return dict(source_key=key, feed_url=url, kind=kind, platform_adapter=adapter, timezone=ak.ZONE)

def calendar(*events):
    return "BEGIN:VCALENDAR\nVERSION:2.0\n" + "\n".join(events) + "\nEND:VCALENDAR\n"

def library_fetch(body):
    def fetch(url, accept):
        assert (url, accept) == (ak.SOURCES[ak.LIBRARY][0], 'text/calendar')
        return body
    return fetch

def garden_event(**changes):
    start = int(datetime(2026, 12, 2, 20, tzinfo=timezone.utc).timestamp() * 1000)
    base = dict(id='6a7e4cc1f64a261bda468074', workflowState=1,
                title='Storytime in the Garden', startDate=start,
                endDate=start + 3_600_000, body='<p>Enjoy stories &amp; a walk among the plants.</p>',
                categories=[], fullUrl='/upcoming-events-workshops/storytime-in-the-gardendec2nd',
                location=dict(mapLat=40.7207559, mapLng=-74.0007613, addressTitle='', addressLine1=''),
                assetUrl='https://images.squarespace-cdn.com/content/v1/616714e4784be422bb89da49/1773790689653-M15EIZWYO8T6XNSMDN0K/Storytime+Graphic+2026+V2.png')
    base.update(changes)
    return base

def garden_fetch(*events):
    data = json.dumps({'website': {'timeZone': ak.ZONE}, 'upcoming': list(events), 'pagination': {'nextPage': False}})
    def fetch(url, accept):
        assert url == ak.SOURCES[ak.GARDEN][0] + '?format=json' and accept == 'application/json'
        return data
    return fetch

@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(preview_worker, '_future_datetime', lambda value: value.astimezone(timezone.utc))

def test_library_ics_preserves_body_and_exact_branch_address():
    rows = ak.collect(source(ak.LIBRARY), library_fetch(calendar(LIBRARY_EVENT)), now=NOW)
    assert len(rows) == 1
    row = rows[0]
    assert row['venue_name'] == 'Muldoon Library'
    assert row['venue_address'] == '1251 Muldoon Road Suite 158, Anchorage, AK 99504'
    assert row['timezone'] == 'America/Anchorage'
    assert row['category'] == 'learn'
    assert row['description'] == 'Stories & movement for toddlers at the library.'
    assert row['lat'] is None and row['lng'] is None

def test_library_does_not_guess_offsite_venue_or_description():
    bad_venue = LIBRARY_EVENT.replace('1251 Muldoon Rd.\\, Suite 158', '9999 Imagined Road')
    blank = LIBRARY_EVENT.replace('<p>Stories &amp; movement for toddlers at the library.</p>', ' ')
    too_long = LIBRARY_EVENT.replace('<p>Stories &amp; movement for toddlers at the library.</p>', 'A' * 12001)
    assert ak.collect(source(ak.LIBRARY), library_fetch(calendar(bad_venue)), now=NOW) == []
    assert ak.collect(source(ak.LIBRARY), library_fetch(calendar(blank)), now=NOW) == []
    assert ak.collect(source(ak.LIBRARY), library_fetch(calendar(too_long)), now=NOW) == []

def test_library_cancellation_and_unknown_activity_are_held():
    cancelled = LIBRARY_EVENT.replace('STATUS:CONFIRMED', 'STATUS:CANCELLED')
    unknown = LIBRARY_EVENT.replace('Parachute Storytime at Muldoon', 'Unspecified Program').replace('CATEGORIES:Storytime', 'CATEGORIES:General')
    assert ak.collect(source(ak.LIBRARY), library_fetch(calendar(cancelled)), now=NOW) == []
    assert ak.collect(source(ak.LIBRARY), library_fetch(calendar(unknown)), now=NOW) == []

def test_garden_ignores_default_nyc_pin_and_keeps_full_size_image():
    rows = ak.collect(source(ak.GARDEN), garden_fetch(garden_event()), now=NOW)
    assert len(rows) == 1
    row = rows[0]
    assert row['venue_address'] == '4601 Campbell Airstrip Road, Anchorage, AK 99507'
    assert row['lat'] is None and row['lng'] is None
    assert row['category'] == 'learn'
    assert row['description'] == 'Enjoy stories & a walk among the plants.'
    assert row['image_url'].endswith('Storytime+Graphic+2026+V2.png')
    assert row['image_evidence_url'] == row['event_url']

def test_garden_offsite_blank_or_oversized_narratives_are_held():
    assert ak.collect(source(ak.GARDEN), garden_fetch(garden_event(location={'addressLine1':'123 Unknown St, Fairbanks, AK'})), now=NOW) == []
    assert ak.collect(source(ak.GARDEN), garden_fetch(garden_event(body='')), now=NOW) == []
    assert ak.collect(source(ak.GARDEN), garden_fetch(garden_event(body='A' * 12001)), now=NOW) == []

def test_reject_unknown_feed_timezone_identity_and_thumbnail():
    for changed in ({'timezone':'America/New_York'}, {'feed_url':'https://example.com/foo'},
                    {'source_key':'new_anchorage_aggregate'}):
        with pytest.raises(ValueError, match='unregistered_anchorage_source'):
            ak.collect(dict(source(ak.LIBRARY), **changed), library_fetch(calendar(LIBRARY_EVENT)), now=NOW)
    assert not ak.event_url(ak.GARDEN,'https://example.com/upcoming-events-workshops/storytime')
    assert ak.photo_url(ak.GARDEN, 'https://images.squarespace-cdn.com/content/v1/a/b/venue-logo.png') is None
    assert ak.photo_url(ak.GARDEN, 'https://images.squarespace-cdn.com/content/v1/a/b/portrait.jpg?format=150w') is None

def test_worker_preview_routes_through_bounded_existing_fetch(monkeypatch):
    def fake_fetch(url, accept, **kwargs):
        assert kwargs['respect_robots'] is True
        assert kwargs['allowed_hosts'] == ('anchorage.librarycalendar.com',)
        return calendar(LIBRARY_EVENT)
    monkeypatch.setattr(preview_worker, 'fetch_publisher', fake_fetch)
    result = preview_worker.preview_source(source(ak.LIBRARY))
    assert result['p_future_count'] == len(result['p_events']) == 1
    assert result['p_events'][0]['category'] == 'learn'
    assert 'p_parser_capability' not in result  # Backend V3 is not enabled for ICS/Squarespace.
