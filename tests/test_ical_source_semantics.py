from datetime import date, datetime, timezone
from unittest.mock import patch

from icalendar import Calendar, Event

from roomquest.ical_source_semantics import capture
from roomquest.incremental_snapshot import parser_context
from scripts.combine_ics import _serialize_vevent


def test_moved_exception_retains_original_anchor_and_existing_uid_contract():
    event = Event()
    event.add('uid', 'series@example.test')
    event.add('dtstart', datetime(2026, 12, 4, 15, tzinfo=timezone.utc))
    event.add('recurrence-id', datetime(2026, 12, 3, 15, tzinfo=timezone.utc))
    text = _serialize_vevent(event, True)
    restored = Calendar.from_ical('BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\n' + text + '\nEND:VEVENT\nEND:VCALENDAR').walk('VEVENT')[0]
    facts = capture(restored)
    assert str(restored['UID']) == 'series@example.test__20261204'
    assert facts['original_uid'] == 'series@example.test'
    assert facts['recurrence_anchor'] == '2026-12-03T15:00:00+00:00'
    assert facts['is_all_day'] is False
    assert str(event['UID']) == 'series@example.test'
    assert event.get('X-EVENTQUEST-ORIGINAL-UID') is None


def test_date_semantics_keep_exclusive_end_without_inventing_a_clock():
    event = Event()
    event.add('uid', 'all-day')
    event.add('dtstart', date(2026, 12, 3))
    event.add('dtend', date(2026, 12, 5))
    facts = capture(event)
    assert facts['is_all_day'] is True
    assert facts['all_day_start_date'] == '2026-12-03'
    assert facts['all_day_end_date_exclusive'] == '2026-12-05'


def test_missing_date_end_stays_unknown():
    event = Event()
    event.add('uid', 'unknown-end')
    event.add('dtstart', date(2026, 12, 3))
    assert capture(event)['all_day_end_date_exclusive'] is None


def test_publisher_coordinates_are_a_separate_immutable_copy():
    event = Event()
    event.add('uid', 'gps')
    event.add('dtstart', datetime(2026, 12, 3, 15, tzinfo=timezone.utc))
    event.add('geo', (35.7, -78.6))
    facts = capture(event)
    event['GEO'] = (0, 0)
    assert float(facts['source_latitude']) == 35.7
    assert float(facts['source_longitude']) == -78.6


def test_unrelated_python_changes_do_not_change_enrolled_semantic_version():
    source = {'source_key': 'municipal_mapsee_' + 'a' * 24,
              'kind': 'ical', 'platform_adapter': 'ical', 'ical_optimization_enabled': True}
    first = parser_context(source)
    with patch('roomquest.incremental_snapshot._scoped_ical_parser_context', side_effect=AssertionError('must not inspect source code')):
        assert parser_context(source) == first
    with patch('roomquest.incremental_snapshot._global_parser_context', return_value='legacy'):
        assert parser_context({**source, 'ical_optimization_enabled': False}) == 'legacy'


def test_ordinary_ics_poll_carries_original_evidence_through_legacy_staging():
    from datetime import timedelta
    from time import monotonic

    from roomquest import preview_worker as worker
    from roomquest.ical_source_semantics import staging_enabled

    start = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=2)
    calendar = Calendar()
    event = Event()
    event.add("uid", "ordinary-facts-test")
    event.add("summary", "Test concert")
    event.add("dtstart", start)
    calendar.add_component(event)
    payload = calendar.to_ical().decode()
    source = {"kind": "ical", "platform_adapter": "ical", "source_key": "ordinary-test"}

    def collect(source, *args, **kwargs):
        rows = worker.parse_ics_preview(payload)
        assert len(rows) == 1
        assert rows[0]["source_semantics_v1"]["original_uid"] == "ordinary-facts-test"
        assert "attendance_mode" not in rows[0]
        with patch.object(worker, "supabase_rpc", return_value=1) as rpc:
            assert worker._stage_legacy_events(
                source, rows, native_content=False, deadline=monotonic() + 30, observe_phase=None,
            ) == 1
        assert rpc.call_args.args[1]["p_events"] == rows
        return rows

    with patch.object(worker, "_process_claimed_source_with_pacing", side_effect=collect):
        worker._process_claimed_source(source)
    assert not staging_enabled()
    assert "source_semantics_v1" not in worker.parse_ics_preview(payload)[0]
