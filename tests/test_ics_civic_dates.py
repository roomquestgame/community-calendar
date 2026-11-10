from datetime import datetime, timezone

import pytest

from roomquest import ics_adapter

NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
SOURCE = {'source_key': 'reviewed_town', 'url': 'https://town.example.gov/calendar.ics',
          'civic_contract_version': 1, 'civic_jurisdiction_id': 'us-test-town',
          'civic_jurisdiction_name': 'Example Town', 'timezone': 'America/New_York'}


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    actual = datetime
    class Meta(type):
        def __instancecheck__(cls, item):
            return isinstance(item, actual)
    class Clock(actual, metaclass=Meta):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(ics_adapter, 'datetime', Clock)


def calendar(*events):
    return 'BEGIN:VCALENDAR\nVERSION:2.0\n' + '\n'.join(
        'BEGIN:VEVENT\n' + event + '\nEND:VEVENT' for event in events) + '\nEND:VCALENDAR'


def entry(title='Town offices closed', extra='', day='20261111', uid='notice-1'):
    return f'UID:{uid}\nDTSTART;VALUE=DATE:{day}\nSUMMARY:{title}\n{extra}'


def test_reviewed_source_has_date_only_closure_with_exclusive_end():
    row, = ics_adapter.parse(calendar(entry()), SOURCE)
    assert row['id'] == 'notice-1'
    assert row['starts_on'] == '2026-11-11' and row['ends_on'] == '2026-11-12'
    assert row['civic']['kind'] == 'service' and row['civic']['time_precision'] == 'date'
    assert row['civic_notice'] is True and row['venue_name'] == '' and row['lat'] is None
    assert row['civic']['valid_until'] == '2026-11-12T05:00:00+00:00'


def test_non_enrolled_calendar_keeps_legacy_all_day_hold():
    for source in ({'url': SOURCE['url']}, {**SOURCE, 'civic_contract_version': None}):
        with pytest.raises(ValueError, match='unsupported_all_day_time'):
            ics_adapter.parse(calendar(entry()), source)


def test_publisher_range_uses_exclusive_date_and_survives_device_zone_changes():
    row, = ics_adapter.parse(calendar(entry(extra='DTEND;VALUE=DATE:20261114')), SOURCE)
    assert row['starts_on'] == '2026-11-11' and row['ends_on'] == '2026-11-14'
    assert row['civic']['time_precision'] == 'window'


@pytest.mark.parametrize('title', ['Family holiday festival', 'Recycling workshop', 'Trash collection class'])
def test_regular_activity_is_not_reclassified_as_a_service(title):
    with pytest.raises(ValueError, match='unsupported_all_day_time'):
        ics_adapter.parse(calendar(entry(title=title)), SOURCE)


def test_meeting_without_advertised_time_is_held_for_agenda_evidence(caplog):
    with pytest.raises(ValueError, match='unsupported_all_day_time'):
        ics_adapter.parse(calendar(entry(title='Town Council meeting')), SOURCE)
    assert 'civic_meeting_time_unresolved' in caplog.text


def test_expired_verified_date_is_valid_empty_not_a_parser_failure():
    assert ics_adapter.parse(calendar(entry(day='20261108')), SOURCE) == []


def test_cancellation_updates_stable_id_and_has_no_false_venue():
    row, = ics_adapter.parse(calendar(entry(extra='STATUS:CANCELLED')), SOURCE)
    assert row['id'] == 'notice-1' and row['publisher_status'] == 'cancelled'
    assert row['lat'] is None and row['venue_address'] == ''


def test_explicit_duration_and_deadline_are_kept_as_date_facts():
    row, = ics_adapter.parse(calendar(entry(title='Voter registration deadline', extra='DURATION:P1D')), SOURCE)
    assert row['civic']['kind'] == 'deadline' and row['civic']['topic'] == 'voting'
    assert row['ends_on'] == '2026-11-12'


@pytest.mark.parametrize('extra', ['DTEND;VALUE=DATE:20261110', 'DURATION:PT3H',
                                  'DTEND:20261112T100000Z',
                                  'DTEND;VALUE=DATE:20261112\nDURATION:P1D'])
def test_conflicting_or_partial_date_bounds_do_not_become_midnight_events(extra):
    with pytest.raises((ValueError, TypeError)):
        ics_adapter.parse(calendar(entry(extra=extra)), SOURCE)


def test_conflicting_duplicate_uid_is_not_silently_overwritten():
    with pytest.raises(ValueError, match='conflicting_civic_identity'):
        ics_adapter.parse(calendar(entry(), entry(day='20261112')), SOURCE)


def test_unsupported_date_recurrence_is_explicitly_held(capsys, caplog):
    with pytest.raises(ValueError, match='unsupported_all_day_time'):
        ics_adapter.parse(calendar(entry(title='Trash collection', extra='RRULE:FREQ=WEEKLY;COUNT=4')), SOURCE)
    assert 'civic_date_recurrence_requires_review' in caplog.text


def test_municipal_venue_normalizer_never_assigns_address_to_notice():
    rows = ics_adapter.parse(calendar(entry()), SOURCE)
    assert ics_adapter.normalize_virginia_civic(rows, SOURCE['url']) == rows
    assert rows[0]['venue_name'] == ''
