"""Publisher zero-length times stay start-only through real ICS/TEC intake.

Fixture clocks keep the reviewed publisher dates intact. Transport and RPCs are
mocked; these tests do not approve sources or release manual publication Holds.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from roomquest import ics_adapter, preview_worker, wordpress_adapter
from roomquest.mapsee_adapter import parse_tribe
from roomquest.registration_formats import probe, source_key
from scripts import combine_ics


FIXTURES = Path(__file__).parent / 'fixtures' / 'uk_zero_end'
PHCL_URL = 'https://www.phcl.org/events.ics'
RHTS_URL = 'https://www.rhts.co.uk/wp-json/tribe/events/v1/events'
NOW = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fixed_clock_and_no_network(monkeypatch):
    class ClockMeta(type):
        def __instancecheck__(cls, value):
            return isinstance(value, datetime)

    class Clock(datetime, metaclass=ClockMeta):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz is not None else NOW.replace(tzinfo=None)

    class Day(date):
        @classmethod
        def today(cls):
            return NOW.date()

    for module in (preview_worker, ics_adapter, wordpress_adapter):
        monkeypatch.setattr(module, 'datetime', Clock)
    monkeypatch.setattr(combine_ics, 'date', Day)

    def forbidden(*_args, **_kwargs):
        raise AssertionError('zero-duration fixture test attempted live transport')

    monkeypatch.setattr('socket.getaddrinfo', forbidden)
    monkeypatch.setattr('urllib.request.urlopen', forbidden)
    monkeypatch.setattr('requests.sessions.Session.request', forbidden)


def preview(start, end, **kwargs):
    return preview_worker._preview('Community event', start, end, 'Actual venue',
                                   None, None, 'https://example.org/event',
                                   'unchanged-id', **kwargs)


def source(url, adapter):
    return {'source_key': source_key(url), 'feed_url': url,
            'kind': 'ical' if adapter == 'ical' else 'json',
            'platform_adapter': adapter, 'timezone': 'Europe/London'}


def ics_event(*, start='20261128T110000Z', end='20261128T110000Z', extra=''):
    return ('BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n'
            'UID:zero-end-fixture\r\nSUMMARY:Community event\r\n'
            f'DTSTART:{start}\r\n' + (f'DTEND:{end}\r\n' if end else '') + extra +
            'LOCATION:Actual venue\r\nURL:https://example.org/event\r\n'
            'END:VEVENT\r\nEND:VCALENDAR\r\n')


def test_real_phcl_probe_and_collection_preserve_three_start_only_occurrences():
    raw = (FIXTURES / 'phcl-20261123.ics').read_text()
    assert probe(PHCL_URL, raw, 'ical')
    with patch.object(preview_worker, 'fetch_publisher', return_value=raw) as fetch:
        result = preview_worker.preview_source(source(PHCL_URL, 'ical'))
    rows = {row['id']: row for row in result['p_events']}
    assert result['p_error'] is None and result['p_future_count'] == 4
    assert rows.keys() == {'8625@phcl.org', '8911@phcl.org', '8912@phcl.org', '8913@phcl.org'}
    for uid, day in (('8911@phcl.org', '2026-11-28'), ('8912@phcl.org', '2026-12-05'),
                     ('8913@phcl.org', '2026-12-12')):
        row = rows[uid]
        assert row['starts_at'] == day + 'T11:00:00+00:00'
        assert row['ends_at'] is None
        assert row['timezone'] == 'Europe/London'
        assert row['event_url'].startswith('https://www.phcl.org/events/')
        assert row['venue_name'].startswith('Primrose Hill Community Library')
        assert row['description']
    assert rows['8625@phcl.org']['ends_at'] == '2026-11-23T11:30:00+00:00'
    fetch.assert_called_once()
    assert fetch.call_args.kwargs['respect_robots'] is True


def test_real_rhts_probe_and_collection_keep_valid_durations_and_native_identity():
    raw = (FIXTURES / 'rhts-20261122.json').read_text()
    original = json.loads(raw)
    assert probe(RHTS_URL, raw, 'wordpress')
    claim = {**source(RHTS_URL, 'wordpress'), 'registered_native_content_version': 1}
    with patch.object(preview_worker, 'fetch_publisher', return_value=raw) as fetch:
        result = preview_worker.preview_source(claim)
    rows = {row['id']: row for row in result['p_events']}
    assert result['p_error'] is None and result['p_future_count'] == 5
    assert rows['5668']['ends_at'] is None
    assert rows['5668']['starts_at'] == '2026-12-19T11:00:00+00:00'
    for event in original['events']:
        row = rows[str(event['id'])]
        assert row['event_url'] == event['url']
        assert row['timezone'] == 'Europe/London'
        assert row['venue_name'] == event['venue']['venue']
        assert row['lat'] is None and row['lng'] is None
        assert row['reason'] == 'missing_verified_venue_geo'
        if event['id'] != 5668:
            assert row['ends_at'] == event['utc_end_date'].replace(' ', 'T') + '+00:00'
    # The multi-day Santa aggregate remains unchanged for its separate manual
    # schedule review. This parser normalization does not split it into sessions.
    assert rows['5012']['ends_at'] == '2026-12-06T16:00:00+00:00'
    fetch.assert_called_once()
    assert fetch.call_args.kwargs['respect_robots'] is True


@pytest.mark.parametrize('offset', [timezone.utc, timezone(timedelta(hours=1))])
def test_equal_instants_normalize_without_changing_identity_or_start(offset):
    start = NOW + timedelta(days=2)
    row = preview(start, start.astimezone(offset))
    assert row['ends_at'] is None
    assert row['starts_at'] == start.isoformat()
    assert row['id'] == 'unchanged-id'


def test_same_wall_clock_across_dst_fold_preserves_real_duration():
    zone = ZoneInfo('Europe/London')
    start = datetime(2026, 10, 25, 1, 30, tzinfo=zone, fold=0)
    end = start.replace(fold=1)
    # The actual DST occurrence predates the fixture clock; isolate only the
    # lookahead gate, leaving the time normalization and output conversion real.
    with patch.object(preview_worker, '_future_datetime', return_value=start.astimezone(timezone.utc)):
        row = preview(start, end)
    assert row['starts_at'] == '2026-10-25T00:30:00+00:00'
    assert row['ends_at'] == '2026-10-25T01:30:00+00:00'


@pytest.mark.parametrize('duration', [None, timedelta(minutes=30), timedelta(days=1, hours=5),
                                      timedelta(minutes=-1)])
def test_other_end_values_keep_their_existing_representation(duration):
    start = NOW + timedelta(days=2)
    end = start + duration if duration is not None else None
    row = preview(start, end)
    assert row['ends_at'] == (end.isoformat() if end else None)


@pytest.mark.parametrize('age,visible', [(2, True), (3, False), (4, False)])
def test_existing_retain_until_end_policy_uses_unknown_end_window(age, visible):
    start = NOW - timedelta(hours=age)
    row = preview(start, start, allow_ongoing=True, retain_until_end=True)
    assert (row is not None) is visible
    if visible:
        assert row['ends_at'] is None  # The fallback window is never a stated finish.


def test_generic_ongoing_admission_policy_is_not_broadened():
    start = NOW - timedelta(hours=1)
    assert preview(start, start, allow_ongoing=True) is None


def test_equal_naive_values_do_not_gain_a_timezone_or_an_event():
    start = (NOW + timedelta(days=2)).replace(tzinfo=None)
    assert preview(start, start) is None


def test_ics_cancellation_is_still_withheld():
    assert ics_adapter.parse(ics_event(extra='STATUS:CANCELLED\r\n'), {'url': PHCL_URL}) == []


def test_ics_date_only_values_are_still_unsupported():
    raw = ics_event().replace('DTSTART:20261128T110000Z', 'DTSTART;VALUE=DATE:20261128')
    raw = raw.replace('DTEND:20261128T110000Z', 'DTEND;VALUE=DATE:20261128')
    with pytest.raises(ValueError, match='unsupported_all_day_time'):
        ics_adapter.parse(raw, {'url': PHCL_URL})


def test_ics_recurrence_identity_and_exception_dates_are_preserved():
    raw = ics_event(extra='RRULE:FREQ=WEEKLY;COUNT=3\r\nEXDATE:20261205T110000Z\r\n')
    rows = ics_adapter.parse(raw, {'url': PHCL_URL})
    assert [row['id'] for row in rows] == ['zero-end-fixture__20261128', 'zero-end-fixture__20261212']
    assert all(row['ends_at'] is None for row in rows)


@pytest.mark.parametrize('change', [{'all_day': True}, {'event_status': 'cancelled'},
                                   {'status': 'trash'}, {'hide_from_listings': True}])
def test_tec_restrictions_are_preserved(change):
    payload = json.loads((FIXTURES / 'rhts-20261122.json').read_text())
    event = deepcopy(next(row for row in payload['events'] if row['id'] == 5668))
    event.update(change)
    assert parse_tribe({'events': [event]}, strict_public=True) == []


def test_tec_end_before_start_remains_an_error():
    payload = json.loads((FIXTURES / 'rhts-20261122.json').read_text())
    event = deepcopy(next(row for row in payload['events'] if row['id'] == 5668))
    event['end_date'] = event['utc_end_date'] = '2026-12-19 10:59:00'
    with pytest.raises(ValueError, match='invalid_event_end'):
        parse_tribe({'events': [event]}, strict_public=True)


def test_worker_sends_null_end_without_a_review_or_publication_override():
    claim = source(PHCL_URL, 'ical')
    with patch.object(preview_worker, 'fetch_publisher', return_value=ics_event()), \
            patch.object(preview_worker, 'supabase_rpc', return_value=1) as rpc:
        result = preview_worker._process_claimed_source(claim)
    assert result == {'complete': 1, 'failed': 0, 'staged': 1}
    staged = rpc.call_args_list[0].args
    assert staged[0] == 'community_collector_record_staged_events'
    row = staged[1]['p_events'][0]
    assert row['ends_at'] is None and row['reason'] == 'missing_verified_venue_geo'
    assert not {'decision', 'review_decision', 'approved', 'end_time_verified'} & row.keys()
