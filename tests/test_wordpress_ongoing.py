"""Retain an observed TEC occurrence through its own explicit end.

These fixtures exercise parsing and the existing bounded REST request. They do
not assert that TEC's start_date filter returns events which started earlier.
"""
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest

from roomquest.collection_window import collection_scope
from roomquest.mapsee_adapter import parse_tribe
from roomquest.wordpress_adapter import collect


ANCHOR = datetime(2026, 11, 28, 12, tzinfo=timezone.utc)
WINDOW = {
    'collection_window': {
        'version': 1,
        'start': ANCHOR.isoformat(),
        'end': (ANCHOR + timedelta(days=60)).isoformat(),
    },
}
PHOTO = 'https://publisher.example/images/rink-season.jpg'


@pytest.fixture(autouse=True)
def bounded_window():
    with collection_scope(WINDOW):
        yield


def event(start, end):
    zone = ZoneInfo('America/New_York')
    item = {
        'id': 42,
        'status': 'publish',
        'title': 'Synthetic ice rink season',
        'url': 'https://publisher.example/event/rink-season/',
        'timezone': zone.key,
        'utc_start_date': start.isoformat(),
        'start_date': start.astimezone(zone).replace(tzinfo=None).isoformat(),
        'image': {'url': PHOTO},
        'venue': {
            'venue': 'Arts Center',
            'address': '213 South Main Street',
            'city': 'Graham',
            'state': 'NC',
        },
    }
    if end is not None:
        item['utc_end_date'] = end.isoformat()
        item['end_date'] = end.astimezone(zone).replace(tzinfo=None).isoformat()
    return item


@pytest.mark.parametrize('remaining', [timedelta(minutes=30), timedelta(days=15)])
@pytest.mark.parametrize('strict', [False, True])
def test_explicit_future_end_keeps_week_old_occurrence_and_image(remaining, strict):
    start, end = ANCHOR - timedelta(days=8), ANCHOR + remaining
    item = event(start, end)
    rows = parse_tribe({'events': [item]}, strict_public=strict)
    assert len(rows) == 1
    row = rows[0]
    assert row['id'] == '42'
    assert row['starts_at'] == start.isoformat()
    assert row['ends_at'] == end.isoformat()
    assert row['event_url'] == item['url']
    assert row['image_url'] == PHOTO
    assert row['timezone'] == 'America/New_York'


@pytest.mark.parametrize('end', [None, ANCHOR - timedelta(seconds=1), ANCHOR])
def test_absent_or_elapsed_end_does_not_revive_old_occurrence(end):
    assert parse_tribe({'events': [event(ANCHOR - timedelta(days=8), end)]}) == []


def test_equal_start_and_end_is_not_treated_as_verified_duration():
    start = ANCHOR - timedelta(hours=2)
    assert parse_tribe({'events': [event(start, start)]}) == []


def test_invalid_end_still_fails_instead_of_confirming_an_empty_calendar():
    start = ANCHOR - timedelta(days=8)
    with pytest.raises(ValueError, match='invalid_event_end'):
        parse_tribe({'events': [event(start, start - timedelta(minutes=1))]})


def test_local_publisher_times_retain_their_timezone_and_actual_instants():
    start, end = ANCHOR - timedelta(days=8), ANCHOR + timedelta(days=15)
    item = event(start, end)
    del item['utc_start_date'], item['utc_end_date']
    row = parse_tribe({'events': [item]})[0]
    assert datetime.fromisoformat(row['starts_at']) == start
    assert datetime.fromisoformat(row['ends_at']) == end
    assert row['timezone'] == 'America/New_York'


def test_future_window_excludes_outside_starts_and_retains_overlapping_season():
    later = ANCHOR + timedelta(days=30)
    window = {'collection_window': {
        'version': 1, 'start': later.isoformat(),
        'end': (later + timedelta(days=60)).isoformat(),
    }}
    items = [
        dict(event(later - timedelta(days=8), later + timedelta(days=2)), id=1),
        dict(event(later - timedelta(days=8), later), id=2),
        dict(event(later + timedelta(days=2), later + timedelta(days=3)), id=3),
        dict(event(later + timedelta(days=60), later + timedelta(days=61)), id=4),
    ]
    with collection_scope(window):
        rows = parse_tribe({'events': items})
    assert [row['id'] for row in rows] == ['1', '3']
    assert datetime.fromisoformat(rows[0]['starts_at']) == later - timedelta(days=8)


def test_existing_public_status_and_visibility_filters_still_apply():
    good = event(ANCHOR - timedelta(days=8), ANCHOR + timedelta(days=15))
    patches = [
        {'status': 'draft'}, {'status': 'trash'}, {'event_status': 'cancelled'},
        {'hide_from_listings': True}, {'is_virtual': True}, {'all_day': True},
    ]
    rows = parse_tribe({'events': [good] + [dict(good, **p) for p in patches]},
                      strict_public=True)
    assert [row['id'] for row in rows] == ['42']


def test_retention_does_not_expand_rest_window_or_add_requests():
    requested = []
    item = event(ANCHOR - timedelta(days=8), ANCHOR + timedelta(days=15))

    def fetch(url, accept):
        requested.append((urlsplit(url), accept))
        return json.dumps({'events': [item], 'total': 1, 'total_pages': 1})

    rows = collect({'feed_url': 'https://publisher.example/?organizer=12'}, fetch)
    assert [row['id'] for row in rows] == ['42']
    assert len(requested) == 1
    url, accept = requested[0]
    assert url.hostname == 'publisher.example'
    assert url.path == '/wp-json/tribe/events/v1/events'
    assert accept == 'application/json'
    assert parse_qs(url.query) == {
        'organizer': ['12'], 'per_page': ['100'], 'page': ['1'],
        'start_date': ['2026-11-28'], 'end_date': ['2027-01-27'],
    }
