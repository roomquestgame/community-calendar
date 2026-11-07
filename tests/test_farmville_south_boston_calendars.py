from datetime import datetime, timezone
import json

import pytest

from roomquest import preview_worker, prizery, virginia_wix_events, visit_farmville


class DateTimeType(type):
    def __instancecheck__(cls, value):
        return isinstance(value, datetime)


class FixedClock(datetime, metaclass=DateTimeType):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 7, 12, tzinfo=timezone.utc).astimezone(tz)


def source(key, url):
    return {'source_key': key, 'feed_url': url, 'kind': 'html',
            'platform_adapter': 'html', 'timezone': 'America/New_York'}


def test_wix_partial_listing_fails_before_details():
    key = 'north_street_press_club_va'
    url = virginia_wix_events.SOURCES[key][0]
    calls = []

    def fetch(location, mime):
        calls.append(location)
        return ('<a data-hook="title" href="/event-details/open-mic">Open Mic</a>'
                '<button data-hook="load-more-button">Load More</button>')

    with pytest.raises(ValueError, match='pagination_requires_review'):
        virginia_wix_events.collect(source(key, url), fetch)
    assert calls == [url]


def test_prizery_keeps_timed_show_and_holds_theatre_run(monkeypatch):
    monkeypatch.setattr(preview_worker, 'datetime', FixedClock)
    url = 'https://prizery.org/jukebox-saturday-night/'
    image = 'https://prizery.org/site/wp-content/uploads/2026/11/Jukebox.jpg'
    summary = 'Thursday, December 17 at 7:30 pm, Tickets $35'
    listing = (
        f'<article class="category-events"><h3 class="elementor-post__title">'
        f'<a href="{url}">Jukebox Saturday Night</a></h3>'
        f'<div class="elementor-post__excerpt">{summary}</div></article>'
        '<article class="category-events"><h3 class="elementor-post__title">'
        '<a href="https://prizery.org/a-theatre-run/">Theatre Run</a></h3>'
        '<div class="elementor-post__excerpt">November 13-22, 2026</div></article>')
    detail = (
        f'<link rel="canonical" href="{url}">'
        '<meta property="article:published_time" content="2026-11-02T18:04:03+00:00">'
        f'<meta property="og:image" content="{image}"><h1>Jukebox Saturday Night</h1><p>{summary}</p>')
    calls = []

    def fetch(location, mime):
        calls.append(location)
        return listing if location == prizery.SOURCE_URL else detail

    rows = prizery.collect(source(prizery.SOURCE_KEY, prizery.SOURCE_URL), fetch)
    assert calls == [prizery.SOURCE_URL, url]
    assert len(rows) == 1
    assert rows[0]['starts_at'] == '2026-12-18T00:30:00+00:00'
    assert rows[0]['venue_address'] == '700 Bruce Street, South Boston, VA 24592'
    assert rows[0]['image_evidence_url'] == url
    assert rows[0]['image_url'] == image
    detail = detail.replace('7:30 pm', '8:30 pm')
    with pytest.raises(ValueError, match='prizery_event_detail_mismatch'):
        prizery.collect(source(prizery.SOURCE_KEY, prizery.SOURCE_URL), fetch)


def test_wix_detail_preserves_venue_and_own_artwork(monkeypatch):
    monkeypatch.setattr(preview_worker, 'datetime', FixedClock)
    key = 'berry_hill_resort_va'
    url = 'https://www.berryhillresort.com/event-details/holiday-garland-workshop'
    image = 'https://static.wixstatic.com/media/56bd96_b9a5fab88e6c45b6901fe10f881d7aaf~mv2.png'
    item = {
        '@context': 'https://schema.org', '@type': 'Event', 'name': 'Holiday Garland Workshop',
        'startDate': '2026-11-18T17:30:00-05:00', 'endDate': '2026-11-18T19:00:00-05:00',
        'eventStatus': 'https://schema.org/EventScheduled',
        'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
        'location': {'@type': 'Place', 'url': url, 'name': 'Berry Hill Resort',
                     'address': '3105 River Rd, South Boston, VA 24592'},
        'image': {'@type': 'ImageObject', 'url': image},
    }
    result = virginia_wix_events.event_detail(
        '<script type="application/ld+json">' + json.dumps(item) + '</script>',
        key, url, item['name'])
    assert result['starts_at'] == '2026-11-18T22:30:00+00:00'
    assert result['venue_address'] == '3105 River Rd, South Boston, VA 24592'
    assert result['lat'] is None
    assert result['image_url'] == image
    assert result['image_evidence_url'] == url


def test_farmville_market_keeps_distinct_occurrences_and_checks_detail_time(monkeypatch):
    monkeypatch.setattr(preview_worker, 'datetime', FixedClock)
    monkeypatch.setattr(visit_farmville, 'datetime', FixedClock)
    url = 'https://visitfarmville.com/events/farmville-farmers-market/'
    days = ('November 14, 2026', 'November 21, 2026')
    rows = ''.join(f'<tr><td>{day}<br>9:00 am - 1:00 pm</td>'
                   f'<td><a href="{url}">Farmville Farmer’s Market</a></td><td></td></tr>' for day in days)
    listing = f'<div class="em-events-list"><table>{rows}</table></div>'
    detail = (
        '<div class="entry-content"><div class="em-event-single">'
        '<div><div class="em-location-map-container"><div class="em-map-balloon-content">'
        '213 North Street - Farmville, VA<br><a href="/locations/market/">Events</a></div></div></div>'
        '<p><strong>Date/Time</strong> Date(s) - April 4, 2026 - November 28, 2026 9:00 am - 1:00 pm</p>'
        '<p><strong>Location</strong> <a href="/locations/market/">Farmer’s Market</a></p>'
        '<p>Fresh local produce and baked goods.</p></div></div>')
    config = source(visit_farmville.SOURCE_KEY, visit_farmville.SOURCE_URL)
    requested = []

    def fetch(location, mime):
        requested.append(location)
        return listing if location == config['feed_url'] else detail

    results = visit_farmville.collect(config, fetch)
    assert requested == [config['feed_url'], url]
    assert [row['starts_at'] for row in results] == ['2026-11-14T14:00:00+00:00', '2026-11-21T14:00:00+00:00']
    assert {row['venue_address'] for row in results} == {'213 North Street, Farmville, VA'}
    detail = detail.replace('1:00 pm', '2:00 pm')
    with pytest.raises(ValueError, match='farmville_listing_detail_schedule_conflict'):
        visit_farmville.collect(config, fetch)
