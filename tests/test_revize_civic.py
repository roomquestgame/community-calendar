from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

from roomquest import revize

FIXTURE = Path(__file__).parent / 'fixtures/south_hill/town_20261106.json'
CAPTURED = json.loads(FIXTURE.read_text())
NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)


def event(rid):
    return deepcopy(next(item for item in CAPTURED if item['id'] == rid))


def test_opt_in_all_day_office_closure_has_date_precision_and_no_venue():
    rows = revize.parse([event('64')], now=NOW, include_civic=True)
    assert len(rows) == 1
    row = rows[0]
    assert row['starts_on'] == '2026-11-11' and row['ends_on'] == '2026-11-12'
    assert row['civic']['time_precision'] == 'date'
    assert row['civic']['kind'] == 'service' and row['civic_notice'] is True
    assert row['civic']['valid_until'] == row['ends_at']
    assert row['venue_name'] == '' and row['lat'] is None and row['lng'] is None


def test_legacy_consumer_keeps_original_exclusion():
    assert revize.parse([event('64')], now=NOW) == []
    source = {'source_key': revize.SOURCE_KEY, 'feed_url': revize.FEED_URL,
              'kind': 'json', 'platform_adapter': 'revize', 'timezone': revize.TIMEZONE}
    fetch = lambda *args: json.dumps([event('64')])
    assert revize.collect(source, fetch, now=NOW) == []
    assert len(revize.collect({**source, 'civic_contract_version': 1,
                              'civic_jurisdiction_id': 'us-va-south-hill'}, fetch, now=NOW)) == 1


def test_noon_conflict_is_held_and_not_turned_into_fabricated_closure(capsys):
    rows = revize.parse([event('64'), event('65')], now=NOW, include_civic=True)
    assert len(rows) == 1 and rows[0]['id'] == 'revize:notice:64'
    assert 'publisher_schedule_conflict' in capsys.readouterr().err


def test_timed_office_closure_preserves_published_times_without_fake_map_point():
    row, = revize.parse([event('66')], now=NOW, include_civic=True)
    assert row['starts_at'] == '2026-12-24T05:00:00+00:00'
    assert row['ends_at'] == '2026-12-26T04:55:00+00:00'
    assert row['civic']['time_precision'] == 'timed' and row['civic_notice'] is True
    assert row['venue_name'] == '' and row['venue_address'] == ''


def test_calendar_remains_mixed_and_all_day_activity_does_not_become_service(capsys):
    rows = revize.parse(CAPTURED, now=NOW, include_civic=True)
    council = [row for row in rows if row['id'].startswith('revize:50__')]
    assert council and all(row['civic']['kind'] == 'meeting' for row in council)
    assert all('civic_notice' not in row for row in council)
    tree = next(row for row in rows if row['id'].startswith('revize:72__'))
    assert 'civic' not in tree and 'civic_notice' not in tree
    assert not any(row['id'].startswith('revize:73__') for row in rows)
    assert 'unsupported_all_day_time' in capsys.readouterr().err


def test_expired_closure_is_not_returned():
    assert revize.parse([event('64')], now=datetime(2026, 11, 12, 12, tzinfo=timezone.utc), include_civic=True) == []


def test_moved_finite_office_notice_keeps_publisher_identity():
    original = event('64')
    moved = {**original, 'start': '2026-11-12T00:00:00'}
    before, = revize.parse([original], now=NOW, include_civic=True)
    after, = revize.parse([moved], now=NOW, include_civic=True)
    assert before['id'] == after['id'] == 'revize:notice:64'
    assert before['starts_on'] != after['starts_on']
