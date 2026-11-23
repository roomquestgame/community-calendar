"""Published clock syntax against the already verified synthetic Drupal shape.

The evidence file retains the exact visible clock strings and their provenance.
No hidden publisher attributes, missing times or venue coordinates are inferred.
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from roomquest import preview_worker as worker, wildlife_trusts as wildlife
from roomquest.registration_formats import source_key

FIXTURES = Path(__file__).parent / 'fixtures' / 'national_feeds'
EXAMPLES = json.loads((FIXTURES / 'wildlife-published-clocks.json').read_text())['examples']
NOW = datetime(2026, 11, 22, 9, tzinfo=timezone.utc)
SOURCE = {'feed_url': wildlife.BCN, 'source_key': source_key(wildlife.BCN),
          'kind': 'html', 'platform_adapter': 'html', 'registered_native_content_version': 1}
DETAIL = wildlife.BCN + '/2026-11-23-nature-workshop'


@pytest.fixture(autouse=True)
def fixed_window(monkeypatch):
    monkeypatch.setattr(worker, '_future_datetime', lambda value: value.astimezone(timezone.utc)
                        if NOW <= value <= NOW + timedelta(days=60) else None)


def fixture(clock, start='2026-11-28T13:00:00+00:00', *, end=None):
    body = (FIXTURES / 'wildlife-detail.html').read_text()
    body = body.replace('10:00am - 1:00pm', clock).replace('2026-11-23T10:00:00Z', start)
    if end is not None:
        body = body.replace('</time>', f'</time><time itemprop="endDate" datetime="{end}"></time>', 1)
    day = start.split('T')[0]
    item = {'url': DETAIL, 'title': 'Nature workshop', 'start': day, 'end': day}
    return body, item


@pytest.mark.parametrize('example', EXAMPLES, ids=['hour-to-dot-minutes', 'dot-minutes-to-dot-minutes'])
def test_published_to_ranges_preserve_exact_minutes_and_native_fields(example):
    body, item = fixture(example['clock'], example['expected_start'])
    rows, reason = wildlife.parse_detail(body, item, source=SOURCE)
    assert reason == 'included'
    [row] = rows
    assert row['starts_at'] == example['expected_start']
    assert row['ends_at'] == example['expected_end']
    assert row['timezone'] == 'Europe/London'
    assert (row['lat'], row['lng']) == (52.251619, -0.247675)
    assert 'Booking is required.' in row['description']
    assert row['event_url'] == DETAIL
    wildlife.validate_native(row, SOURCE)


@pytest.mark.parametrize('clock', [
    '', 'TBC', 'Afternoon', '1 to 3.30pm', '1pm to 3.3pm', '1pm to 3.60pm',
    '13pm to 15pm', '1pm to 3pm or 4pm', '1pm tomorrow 3.30pm',
    '9.30am at the Stonebridge car park entrance',
])
def test_unknown_incomplete_and_ambiguous_clocks_still_hold(clock):
    body, item = fixture(clock)
    assert wildlife.parse_detail(body, item, source=SOURCE) == ([], 'wildlife_event_clock_unresolved')


def test_readable_time_still_must_match_the_published_datetime():
    body, item = fixture('1pm to 3.30pm', '2026-11-28T12:00:00+00:00')
    assert wildlife.parse_detail(body, item, source=SOURCE) == ([], 'wildlife_event_clock_unresolved')


def test_explicit_end_time_conflict_is_not_overwritten():
    body, item = fixture('1pm to 3.30pm', end='2026-11-28T15:00:00+00:00')
    assert wildlife.parse_detail(body, item, source=SOURCE) == ([], 'wildlife_detail_time_conflict')


def test_date_hint_conflict_and_date_ranges_still_hold():
    body, item = fixture('1pm to 3.30pm')
    item.update(start='2026-11-27', end='2026-11-27')
    assert wildlife.parse_detail(body, item, source=SOURCE) == ([], 'wildlife_detail_date_conflict')
    item.update(start='2026-11-28', end='2026-11-29')
    assert wildlife.parse_detail(body, item, source=SOURCE) == ([], 'wildlife_multiple_dates_unresolved')


def test_dot_minutes_do_not_strip_meridiem_punctuation_or_invent_an_end():
    body, item = fixture('1.30 p.m.', '2026-11-28T13:30:00+00:00')
    [row], reason = wildlife.parse_detail(body, item, source=SOURCE)
    assert reason == 'included'
    assert row['starts_at'] == '2026-11-28T13:30:00+00:00'
    assert row['ends_at'] is None
