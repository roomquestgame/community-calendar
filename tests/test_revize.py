from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from roomquest import preview_worker, revize

FIXTURE = Path(__file__).parent / 'fixtures/south_hill/town_20261106.json'
CAPTURED = json.loads(FIXTURE.read_text())
NOW = datetime(2026, 11, 6, 13, tzinfo=timezone.utc)
SOURCE = {'source_key': revize.SOURCE_KEY, 'feed_url': revize.FEED_URL,
          'kind': 'json', 'platform_adapter': 'revize', 'timezone': revize.TIMEZONE}


def freeze(monkeypatch, value):
    actual = datetime

    class Meta(type):
        def __instancecheck__(cls, item):
            return isinstance(item, actual)

    class Clock(actual, metaclass=Meta):
        @classmethod
        def now(cls, tz=None):
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    monkeypatch.setattr(preview_worker, 'datetime', Clock)
    monkeypatch.setattr(revize, 'datetime', Clock)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    freeze(monkeypatch, NOW)


def event(rid='72'):
    return deepcopy(next(item for item in CAPTURED if item['id'] == rid))


def parse(items):
    return revize.parse(json.dumps(items))


def test_actual_snapshot_has_public_occurrences_and_exact_named_venues(capsys):
    rows = revize.parse(FIXTURE.read_text())
    assert [row['id'] for row in rows] == [
        'revize:50__20261110T000000Z', 'revize:72__20261204T230000Z',
        'revize:50__20261215T000000Z',
    ]
    assert rows[0]['ends_at'] == '2026-11-10T02:00:00+00:00'
    assert rows[0]['venue_address'] == '111 E. Danville Street, South Hill, VA 23970'
    assert rows[1]['venue_address'] == '225 E. Danville St, South Hill, VA 23970'
    assert rows[0]['publisher_categories'] == ['Meeting']
    assert rows[1]['publisher_categories'] == ['Events']
    assert 'Citizens to Address Council' in rows[0]['description']
    assert all(row['event_url'] == row['details_evidence_url'] == revize.CALENDAR for row in rows)
    assert all(row['timezone'] == 'America/New_York' for row in rows)
    assert all(row['lat'] is None and row['lng'] is None for row in rows)
    assert all(row['image_extractor_version'] == 'publisher_event_candidates_v1' for row in rows)
    assert all('image_url' not in row and 'publisher_status' not in row for row in rows)
    log = capsys.readouterr().err
    assert 'unsupported_all_day_time' in log and 'revize:73' in log


def test_refresh_discovers_new_record_and_preserves_its_offsite_address():
    added = event()
    added.update(id='80', rid='80', title='New public program',
                 start='2026-11-20T18:00:00', end='2026-11-20T20:00:00', duration='02:00',
                 location='141 E South Main St, Littleton, NC 27850',
                 desc='Bring%20your%20questions.%0ARegistration%20required.')
    before = parse(CAPTURED)
    after = parse(CAPTURED + [added])
    new = next(row for row in after if row['id'].startswith('revize:80__'))
    assert len(after) == len(before) + 1
    assert new['venue_city'] == 'Littleton'
    assert new['venue_address'].endswith('Littleton, NC 27850')
    assert new['description'] == 'Bring your questions.\nRegistration required.'
    assert {r['id'] for r in before} <= {r['id'] for r in after}


def test_recurrence_exceptions_and_additions_survive_refresh():
    council = event('50')
    council['rrule'] += '\nEXDATE:20261109T190000\nRDATE:20261112T190000'
    rows = parse([council])
    assert [r['id'] for r in rows] == ['revize:50__20261113T000000Z', 'revize:50__20261215T000000Z']
    assert all(r['ends_at'].endswith('02:00:00+00:00') for r in rows)


def test_dst_transition_preserves_publisher_local_hour(monkeypatch):
    freeze(monkeypatch, datetime(2027, 2, 25, tzinfo=timezone.utc))
    council = event('50')
    council.update(start='2027-02-28T19:00:00', end='2027-02-28T21:00:00',
                   rrule='DTSTART:20270228T190000\nRRULE:FREQ=WEEKLY;COUNT=4;BYDAY=SU')
    rows = parse([council])
    assert [r['starts_at'] for r in rows] == [
        '2027-03-01T00:00:00+00:00', '2027-03-08T00:00:00+00:00',
        '2027-03-14T23:00:00+00:00', '2027-03-21T23:00:00+00:00',
    ]


@pytest.mark.parametrize('start,end,current,reason', [
    ('2027-03-14T02:30:00', '2027-03-14T04:30:00', datetime(2027, 3, 1, tzinfo=timezone.utc), 'timezone_nonexistent'),
    ('2026-11-01T01:30:00', '2026-11-01T03:30:00', datetime(2026, 10, 20, tzinfo=timezone.utc), 'timezone_ambiguous'),
])
def test_ambiguous_or_nonexistent_local_time_is_held(monkeypatch, capsys, start, end, current, reason):
    freeze(monkeypatch, current)
    item = event()
    item.update(start=start, end=end, duration='02:00')
    with pytest.raises(ValueError, match='revize_event_evidence_unavailable'):
        parse([item])
    assert reason in capsys.readouterr().err


def test_ongoing_event_is_retained_until_its_actual_end(monkeypatch):
    freeze(monkeypatch, datetime(2026, 12, 5, 1, 45, tzinfo=timezone.utc))
    rows = parse([event()])
    assert len(rows) == 1 and rows[0]['ends_at'] == '2026-12-05T02:00:00+00:00'
    freeze(monkeypatch, datetime(2026, 12, 5, 2, tzinfo=timezone.utc))
    assert parse([event()]) == []


@pytest.mark.parametrize('location', ['', 'Town Hall', 'Unknown Pavilion', 'Online via Zoom'])
def test_unknown_venue_has_no_publisher_office_fallback(location, capsys):
    item = event()
    item['location'] = location
    rows = parse([event('50'), item])
    assert all(r['id'].startswith('revize:50__') for r in rows)
    assert 'event_held' in capsys.readouterr().err


def test_duration_conflict_and_all_day_are_held_not_invented(capsys):
    bad = event()
    bad['duration'] = '04:00'
    rows = parse([event('50'), bad, event('73')])
    assert len(rows) == 2
    log = capsys.readouterr().err
    assert 'publisher_schedule_conflict' in log and 'unsupported_all_day_time' in log


@pytest.mark.parametrize('title', ['Town Hall Closed: holiday', 'Private event', 'Members-only dinner', 'Town Hall Closing Early'])
def test_nonpublic_and_closure_records_are_excluded(title):
    item = event()
    item['title'] = title
    assert parse([item]) == []


@pytest.mark.parametrize('status,expected', [('CANCELLED', 'cancelled'), ('canceled', 'cancelled'), ('postponed', 'postponed')])
def test_explicit_status_preserves_exact_occurrence_identity_on_refresh(status, expected):
    before = parse([event('50')])
    changed = event('50')
    changed['status'] = status
    after = parse([changed])
    assert [r['id'] for r in after] == [r['id'] for r in before]
    assert [r['starts_at'] for r in after] == [r['starts_at'] for r in before]
    assert all(r['publisher_status'] == expected for r in after)
    assert all(r['details_evidence_url'] == revize.CALENDAR for r in after)
    assert all('publisher_status' not in r for r in before)


def test_missing_or_text_only_cancellation_does_not_create_status(capsys):
    changed = event()
    changed['title'] = 'Cancelled: ' + changed['title']
    rows = parse([event('50'), changed])
    assert all('publisher_status' not in r for r in rows)
    assert 'cancellation_requires_exact_status' in capsys.readouterr().err
    assert parse([]) == []


@pytest.mark.parametrize('status', ['cancelled', 'postponed'])
def test_explicit_status_survives_removed_venue_and_end(status):
    before = parse([event()])[0]
    changed = event()
    changed.update(status=status, location='')
    changed.pop('end')
    changed.pop('duration')
    after = parse([changed])[0]
    assert after['id'] == before['id'] and after['starts_at'] == before['starts_at']
    assert after['publisher_status'] == status and after['ends_at'] is None
    assert after['venue_address'] == after['venue_city'] == after['venue_name'] == ''
    assert after['lat'] is None and after['lng'] is None
    assert after['location_provenance'] == 'publisher_status_without_venue'


def test_ongoing_cancellation_has_exact_past_start_without_a_guessed_end(monkeypatch):
    freeze(monkeypatch, datetime(2026, 12, 5, 1, 45, tzinfo=timezone.utc))
    changed = event()
    changed.update(status='cancelled', location='')
    changed.pop('end')
    changed.pop('duration')
    row = parse([changed])[0]
    assert row['starts_at'] == '2026-12-04T23:00:00+00:00'
    assert row['id'] == 'revize:72__20261204T230000Z' and row['ends_at'] is None


def test_recurring_cancellation_still_requires_provable_occurrences():
    changed = event('50')
    changed.update(status='cancelled', location='')
    changed.pop('end')
    changed.pop('duration')
    with pytest.raises(ValueError, match='revize_event_evidence_unavailable'):
        parse([changed])


def test_narrative_is_decoded_sanitized_and_bounded_without_placeholder_image():
    item = event()
    item['desc'] = '%3Cp%3ELearn%20%26amp%3B%20build.%3C%2Fp%3E%3Cscript%3Ebad()%3C%2Fscript%3E%3Cp%3E' + 'x' * 3000 + '%3C%2Fp%3E'
    row = parse([item])[0]
    assert row['description'].startswith('Learn & build.\n')
    assert len(row['description']) == 2000 and 'bad()' not in row['description']
    assert 'image_url' not in row and row['publisher_details'] == {}


@pytest.mark.parametrize('payload', ['<html>Unavailable</html>', '{', '{}', '[null]'])
def test_broken_payload_is_failure_not_healthy_zero(payload):
    with pytest.raises(ValueError, match='unsupported_revize_payload'):
        revize.parse(payload)


def test_conflicting_duplicate_identity_is_not_silently_selected():
    changed = event()
    changed['location'] = 'Different place'
    with pytest.raises(ValueError, match='conflicting_event_identity'):
        parse([event(), changed])
    assert len(parse([event(), event()])) == 1


@pytest.mark.parametrize('rule,reason', [
    ('DTSTART:20250908T190000\nRRULE:FREQ=MINUTELY', 'unsupported_dense_recurrence'),
    ('DTSTART:20250908T190000\nRRULE:FREQ=MONTHLY\nEXDATE:bad', 'recurrence_invalid'),
    ('DTSTART:20250909T190000\nRRULE:FREQ=MONTHLY', 'publisher_schedule_conflict'),
    ('DTSTART:20250908T190000\nRRULE:FREQ=MONTHLY;INTERVAL=0', 'recurrence_invalid'),
    ('DTSTART:20250908T190000\nRRULE:FREQ=MONTHLY;COUNT=0', 'recurrence_invalid'),
])
def test_unsupported_or_invalid_recurrence_fails_complete_snapshot(rule, reason):
    item = event('50')
    item['rrule'] = rule
    with pytest.raises(ValueError, match=reason):
        parse([event(), item])


def test_impossible_recurrence_combination_is_bounded_by_the_collection_window():
    item = event('50')
    item['rrule'] = 'DTSTART:20250908T190000\nRRULE:FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30'
    assert parse([item]) == []


def test_array_recurrence_and_scan_bounds_fail_closed(monkeypatch):
    with pytest.raises(ValueError, match='source_record_limit'):
        parse([event()] * 501)
    with pytest.raises(ValueError, match='recurrence_record_limit'):
        parse([event('50')] * 51)
    monkeypatch.setattr(revize, 'MAX_RECURRENCE_STEPS', 2)
    with pytest.raises(ValueError, match='recurrence_expansion_limit'):
        parse([event('50')])


@pytest.mark.parametrize('field,value', [('source_key', 'other'), ('feed_url', revize.FEED_URL + '&extra=1'),
                                        ('kind', 'html'), ('platform_adapter', 'html'), ('timezone', 'UTC')])
def test_source_identity_is_checked_before_fetch(field, value):
    source = {**SOURCE, field: value}
    calls = []
    with pytest.raises(ValueError, match='unregistered_revize_source'):
        revize.collect(source, lambda *args: calls.append(args))
    assert calls == []


def test_injected_transport_fetches_only_reviewed_endpoint_and_propagates_failures():
    calls = []
    rows = revize.collect(SOURCE, lambda *args: calls.append(args) or FIXTURE.read_text())
    assert len(rows) == 3 and calls == [(revize.FEED_URL, 'application/json')]
    def unavailable(*args):
        raise TimeoutError('publisher unavailable')
    with pytest.raises(TimeoutError):
        revize.collect(SOURCE, unavailable)


def test_deadline_is_checked_after_fetch_before_success(monkeypatch):
    ticks = iter([0, 0, 26])
    monkeypatch.setattr(revize, 'monotonic', lambda: next(ticks))
    with pytest.raises(ValueError, match='collection_deadline'):
        revize.collect(SOURCE, lambda *args: '[]')
