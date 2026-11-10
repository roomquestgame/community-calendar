from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from roomquest import civic_schedule as schedule
from roomquest.civic_notices import date_notice

NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
FIXTURE = Path(__file__).parent / 'fixtures/civic/south_hill_public_works.html'
RULE = schedule.ScheduleRule(
    schedule_id='sample-route-tuesday-trash', title='Tuesday route trash collection',
    source_url='https://town.example.gov/public-works', jurisdiction_id='us-test-town',
    jurisdiction_name='Example Town', weekday=1,
    service_area_id='tuesday-route', service_area_name='Published Tuesday route',
    description='Place carts at the curb by 6:00 AM.')


def test_weekly_rule_produces_eight_dates_without_inventing_an_arrival_time():
    rows = schedule.occurrences(RULE, now=NOW)
    assert len(rows) == 8
    assert rows[0]['starts_on'] == '2026-11-10'
    assert rows[-1]['starts_on'] == '2026-12-29'
    for row in rows:
        assert row['civic']['time_precision'] == 'date'
        assert row['civic']['recurrence_label'] == 'Every Tuesday'
        assert row['civic']['service_area_id'] == 'tuesday-route'
        assert row['civic']['valid_until'] == row['ends_at']
        assert row['civic']['verified_at'] == NOW.isoformat()
        assert row['venue_name'] == '' and row['lat'] is None and row['lng'] is None
        assert row['starts_at'].endswith('T05:00:00+00:00')  # Local DATE transport bound.
        assert '6:00 AM' in row['description']


def test_biweekly_requires_verified_anchor_and_does_not_guess_alternating_week():
    with pytest.raises(ValueError, match='anchor_missing'):
        schedule.occurrences(replace(RULE, interval=2), now=NOW)
    rows = schedule.occurrences(replace(RULE, interval=2, anchor=date(2026, 11, 17)), now=NOW)
    assert [row['starts_on'] for row in rows] == ['2026-11-17', '2026-12-01', '2026-12-15', '2026-12-29']
    with pytest.raises(ValueError, match='anchor_conflict'):
        schedule.occurrences(replace(RULE, interval=2, anchor=date(2026, 11, 18)), now=NOW)


def test_holiday_move_replaces_occurrence_with_same_identity():
    before = schedule.occurrences(RULE, now=NOW)
    change = schedule.ScheduleException(
        date(2026, 11, 24), 'https://town.example.gov/thanksgiving', NOW,
        replacement_date=date(2026, 11, 25), description='The town moved this collection to Wednesday.')
    after = schedule.occurrences(RULE, now=NOW, exceptions=[change])
    identity = 'civic-schedule:sample-route-tuesday-trash__20261124'
    assert {row['id'] for row in before} == {row['id'] for row in after}
    moved = next(row for row in after if row['id'] == identity)
    assert moved['starts_on'] == '2026-11-25' and moved['ends_on'] == '2026-11-26'
    assert moved['civic']['original_date'] == '2026-11-24'
    assert moved['civic']['schedule_exception'] == 'moved'
    assert moved['civic']['exception_source_url'] == change.source_url
    assert not any(row['starts_on'] == '2026-11-24' for row in after)


def test_cancelled_occurrence_emits_exact_status_update_not_silent_omission():
    change = schedule.ScheduleException(date(2026, 11, 10), 'https://town.example.gov/closure', NOW)
    rows = schedule.occurrences(RULE, now=NOW, exceptions=[change])
    cancelled = rows[0]
    assert cancelled['id'].endswith('__20261110')
    assert cancelled['publisher_status'] == 'cancelled'
    assert cancelled['civic']['schedule_exception'] == 'cancelled'


def test_delayed_original_before_window_is_still_included():
    today = datetime(2026, 11, 11, 13, tzinfo=timezone.utc)
    change = schedule.ScheduleException(date(2026, 11, 10), 'https://town.example.gov/delay', NOW,
                                         replacement_date=date(2026, 11, 12))
    rows = schedule.occurrences(RULE, now=today, exceptions=[change])
    assert rows[0]['id'].endswith('__20261110') and rows[0]['starts_on'] == '2026-11-12'


def test_move_beyond_display_window_still_updates_old_identity():
    change = schedule.ScheduleException(date(2026, 12, 29), 'https://town.example.gov/change', NOW,
                                         replacement_date=date(2027, 1, 5))
    rows = schedule.occurrences(RULE, now=NOW, exceptions=[change])
    moved = next(row for row in rows if row['id'].endswith('__20261229'))
    assert moved['starts_on'] == '2027-01-05' and moved['ends_on'] == '2027-01-06'
    assert moved['civic']['schedule_exception'] == 'moved'
    assert moved['civic']['valid_until'] == '2027-01-06T05:00:00+00:00'


def test_move_to_past_emits_expired_same_id_revision_to_remove_old_future_date():
    change = schedule.ScheduleException(date(2026, 11, 10), 'https://town.example.gov/change', NOW,
                                         replacement_date=date(2026, 11, 8))
    rows = schedule.occurrences(RULE, now=NOW, exceptions=[change])
    moved = next(row for row in rows if row['id'].endswith('__20261110'))
    assert moved['starts_on'] == '2026-11-08'
    assert datetime.fromisoformat(moved['civic']['valid_until']) < NOW
    assert 'publisher_status' not in moved  # Moved/ended does not mean cancelled.


def test_move_then_cancel_after_original_day_retires_replacement():
    delayed = schedule.ScheduleException(date(2026, 11, 10), 'https://town.example.gov/change', NOW,
                                          replacement_date=date(2026, 11, 12))
    old = next(row for row in schedule.occurrences(RULE, now=NOW, exceptions=[delayed])
               if row['id'].endswith('__20261110'))
    later = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)
    cancelled = schedule.ScheduleException(date(2026, 11, 10), 'https://town.example.gov/cancellation', later)
    update = next(row for row in schedule.occurrences(RULE, now=later, exceptions=[cancelled])
                  if row['id'] == old['id'])
    assert update['publisher_status'] == 'cancelled'
    assert update['civic']['schedule_exception'] == 'cancelled'
    assert datetime.fromisoformat(update['civic']['valid_until']) < later


@pytest.mark.parametrize('change', [
    schedule.ScheduleException(date(2026, 11, 11), 'https://town.example.gov/change', NOW),
    schedule.ScheduleException(date(2026, 11, 10), 'javascript:alert(1)', NOW),
    schedule.ScheduleException(date(2026, 11, 10), 'https://town.example.gov/change', NOW + timedelta(days=1)),
])
def test_unverified_or_conflicting_exception_is_rejected(change):
    with pytest.raises(ValueError):
        schedule.occurrences(RULE, now=NOW, exceptions=[change])


def test_duplicate_exception_cannot_choose_a_winner_silently():
    change = schedule.ScheduleException(date(2026, 11, 10), 'https://town.example.gov/change', NOW)
    with pytest.raises(ValueError, match='exception_conflict'):
        schedule.occurrences(RULE, now=NOW, exceptions=[change, change])


def test_monthly_date_and_dst_bounds_keep_local_calendar_dates():
    rule = replace(RULE, frequency='monthly', weekday=2, nth=3)
    rows = schedule.occurrences(rule, now=NOW)
    assert [row['starts_on'] for row in rows] == ['2026-11-18', '2026-12-16']
    spring = schedule.occurrences(replace(RULE, weekday=6), now=datetime(2027, 3, 1, 12, tzinfo=timezone.utc))
    transition = next(row for row in spring if row['starts_on'] == '2027-03-14')
    assert transition['starts_at'] == '2027-03-14T05:00:00+00:00'
    assert transition['ends_at'] == '2027-03-15T04:00:00+00:00'
    assert transition['ends_on'] == '2027-03-15'


def test_effective_range_and_fifth_weekday_are_not_fabricated():
    limited = replace(RULE, effective_from=date(2026, 11, 17), effective_until=date(2026, 12, 1))
    assert [row['starts_on'] for row in schedule.occurrences(limited, now=NOW)] == ['2026-11-17', '2026-11-24']
    fifth = replace(RULE, frequency='monthly', nth=5, weekday=1)
    assert [row['starts_on'] for row in schedule.occurrences(fifth, now=NOW)] == ['2026-12-29']


def test_expired_dates_and_unbounded_generation_are_rejected():
    assert date_notice(identity='expired', title='Expired', starts_on=date(2026, 11, 8),
                       jurisdiction_id=RULE.jurisdiction_id, jurisdiction_name=RULE.jurisdiction_name,
                       source_url=RULE.source_url, now=NOW) is None
    with pytest.raises(ValueError, match='window_limit'):
        schedule.occurrences(RULE, now=NOW, horizon_days=365)


def test_reviewed_public_works_rule_generates_only_bookable_bulk_collection():
    rows = schedule.parse_public_works(FIXTURE.read_text(), now=NOW)
    assert [row['starts_on'] for row in rows] == ['2026-11-18', '2026-12-16']
    assert all('request required' in row['title'] for row in rows)
    assert all(row['civic']['applicability'] == 'address' for row in rows)
    assert all(row['civic']['lookup_url'] == schedule.LOOKUP_URL for row in rows)
    assert all('447-3191' in row['description'] for row in rows)
    assert all(row['civic']['recurrence_label'] == 'Third Wednesday of each month' for row in rows)


@pytest.mark.parametrize('old,new', [
    ('third Wednesday', 'second Wednesday'), ('collected by request', 'collected automatically'),
    ('Town of South Hill', 'Town of Elsewhere'),
    ('pickup on the third Wednesday of the month', 'pickup on the third Wednesday of the month except holidays'),
])
def test_changed_publisher_rule_is_held_for_review(old, new):
    with pytest.raises(ValueError):
        schedule.parse_public_works(FIXTURE.read_text().replace(old, new), now=NOW)


def test_public_works_requires_registered_civic_contract_and_exact_url():
    fetched = []
    def fetch(url, accept):
        fetched.append((url, accept))
        return FIXTURE.read_text()
    assert len(schedule.collect_public_works(schedule.public_works_source(), fetch, now=NOW)) == 2
    assert fetched == [(schedule.PUBLIC_WORKS_URL, 'text/html')]
    # The registry owns display names. Stable jurisdiction identity, not its
    # current label, authorizes the source contract.
    assert len(schedule.collect_public_works({**schedule.public_works_source(),
                 'civic_jurisdiction_name': 'South Hill, Virginia'}, fetch, now=NOW)) == 2
    for key, value in [('civic_contract_version', None), ('feed_url', 'https://other.example.gov/')]:
        source = {**schedule.public_works_source(), key: value}
        with pytest.raises(ValueError, match='unregistered_public_works_source'):
            schedule.collect_public_works(source, fetch, now=NOW)
    with pytest.raises(ValueError, match='unregistered_public_works_source'):
        schedule.collect_public_works({**schedule.public_works_source(), 'civic_contract_version': True}, fetch, now=NOW)
