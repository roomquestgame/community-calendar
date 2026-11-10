"""Only explicit Shady cards become bounded, identifiable occurrences."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

from bs4 import BeautifulSoup
import pytest

from roomquest import preview_worker
from roomquest import shady_shack as shady


NOW = datetime(2026, 11, 10, 2, tzinfo=timezone.utc)
SOURCE = {'source_key': shady.SOURCE_KEY, 'feed_url': shady.CALENDAR,
          'kind': 'html', 'platform_adapter': 'html', 'timezone': shady.TIMEZONE}
FIXTURE = Path(__file__).parent / 'fixtures/south_hill_recovery/shady_events.html'


@pytest.fixture(autouse=True)
def source_window_controls_dated_fixtures(monkeypatch):
    # The Shady adapter applies its own exact rolling window before calling the
    # shared factual normalizer. Keep fixture dates independent of test-run day.
    monkeypatch.setattr(preview_worker, '_future_datetime',
                        lambda value: value.astimezone(timezone.utc))


def card(*, day=None, clock=None, title=None, prose=None, image=None):
    page = BeautifulSoup(FIXTURE.read_text(), 'html.parser')
    holders = page.select('.events-holder')
    for holder in holders[1:]:
        holder.decompose()
    first = holders[0]
    for selector, value in (('.event-day', day), ('.event-time', clock), ('h2', title)):
        if value is not None:
            first.select_one(selector).string = value
    if prose is not None:
        info = first.select_one('.event-info-text')
        meta = str(info.select_one('[data-event-id]'))
        info.clear()
        info.append(BeautifulSoup(meta + prose, 'html.parser'))
    if image is not None:
        first.select_one('.event-image')['src'] = image
    return str(page)


def resolved_day(text, now=NOW):
    diagnostics = {}
    day = shady._day(text, now, diagnostics, 'shady_shack:123')
    return day, diagnostics


def test_observed_eight_cards_keep_dates_images_address_and_stable_identity():
    diagnostics = {}
    rows = shady.parse(FIXTURE.read_text(), now=NOW, diagnostics=diagnostics)
    assert len(rows) == 8
    assert rows[0]['id'] == 'shady_shack:3657972:2026-11-12'
    assert rows[0]['starts_at'] == '2026-11-12T23:00:00+00:00'
    assert rows[0]['ends_at'] == '2026-11-13T01:00:00+00:00'
    assert rows[-1]['starts_at'] == '2026-12-18T23:00:00+00:00'
    assert all(row['venue_address'] == shady.ADDRESS for row in rows)
    assert all(row['lat'] is None and row['lng'] is None for row in rows)
    assert all(row['image_extractor_version'] == 'publisher_event_candidates_v1' for row in rows)
    assert all(row['image_evidence_url'] == shady.CALENDAR for row in rows)
    assert len(diagnostics['year_assumptions']) == 8
    assert all(note['reason'] == shady.YEAR_RULE for note in diagnostics['year_assumptions'])
    assert all('owner_authorized' not in row['description'] for row in rows)


def test_weekly_labels_do_not_generate_additional_unlisted_dates():
    rows = shady.parse(card(), now=NOW)
    assert len(rows) == 1
    assert 'Every Thursday' in rows[0]['description']
    again = shady.parse(card(), now=NOW + timedelta(days=1))
    assert again[0]['id'] == rows[0]['id']


@pytest.mark.parametrize(('text', 'now', 'expected'), [
    ('November 13', NOW, date(2026, 11, 13)),
    ('December 4', NOW, date(2026, 12, 4)),
    ('January 2', NOW, date(2027, 1, 2)),
    ('January 2', datetime(2026, 12, 30, tzinfo=timezone.utc), date(2027, 1, 2)),
    ('January 2', datetime(2027, 1, 1, 6, tzinfo=timezone.utc), date(2027, 1, 2)),
    ('November 1', NOW, date(2026, 11, 1)),
    ('October 31', NOW, date(2026, 10, 31)),
    ('February 1', NOW, date(2026, 2, 1)),
])
def test_year_rule_only_rolls_a_date_in_the_current_new_year_window(text, now, expected):
    actual, notes = resolved_day(text, now)
    assert actual == expected
    assert notes['year_assumptions'][0]['assigned_year'] == expected.year


def test_venue_local_midnight_controls_rollover_and_inference_provenance():
    # UTC January 1 is still December 31 in Bracey.
    day, notes = resolved_day('January 2', datetime(2027, 1, 1, 2, tzinfo=timezone.utc))
    assert day == date(2027, 1, 2)
    assert notes['year_assumptions'][0]['reference_local_date'] == '2026-12-31'


def test_old_explicit_flyer_year_never_slides_to_current_year():
    day, notes = resolved_day('November 13, 2025')
    assert day == date(2025, 11, 13)
    assert 'year_assumptions' not in notes
    assert shady.parse(card(day='November 13, 2025'), now=NOW) == []
    assert shady.parse(card(day='October 31'), now=NOW) == []


def test_next_year_ordinary_yearless_schedule_keeps_working_without_manual_renewal():
    later = datetime(2027, 11, 9, 12, tzinfo=timezone.utc)
    rows = shady.parse(card(day='November 12'), now=later)
    assert rows[0]['id'] == 'shady_shack:3657972:2027-11-12'
    assert rows[0]['starts_at'] == '2027-11-12T23:00:00+00:00'


def test_explicit_year_and_weekday_conflict_is_held_without_changing_year():
    with pytest.raises(shady.EventHold, match='publisher_date_weekday_conflict'):
        resolved_day('Thursday November 12, 2027')
    day, notes = resolved_day('Friday November 12')
    assert day == date(2026, 11, 12)
    assert notes['warnings'][0]['reason'] == 'weekday_differs_from_owner_assigned_year'


@pytest.mark.parametrize('clock', ['6-9', '10-12am', '6 PM - 5 PM', '25:00 PM', 'All day'])
def test_missing_meridiem_and_invalid_ranges_stay_held(clock):
    diagnostics = {}
    assert shady.parse(card(clock=clock), now=NOW, diagnostics=diagnostics) == []
    assert diagnostics['held'][0]['reason'] in {'publisher_time_unresolved', 'publisher_time_conflict'}


def test_explicit_start_without_end_remains_null_and_expires_after_three_hours():
    rows = shady.parse(card(clock='6 PM'), now=NOW)
    assert rows[0]['ends_at'] is None
    assert shady.parse(card(clock='6 PM'), now=datetime(2026, 11, 13, 2, tzinfo=timezone.utc)) == []


def test_ongoing_card_remains_until_explicit_end_and_not_after():
    payload = card()
    assert len(shady.parse(payload, now=datetime(2026, 11, 13, 0, tzinfo=timezone.utc))) == 1
    assert shady.parse(payload, now=datetime(2026, 11, 13, 1, tzinfo=timezone.utc)) == []


def test_private_offsite_and_cancellation_facts_do_not_become_ordinary_public_cards():
    assert shady.parse(card(prose='<p>Private party</p>'), now=NOW) == []
    notes = {}
    assert shady.parse(card(prose='<p>Moved to a new location</p>'), now=NOW, diagnostics=notes) == []
    assert notes['held'][0]['reason'] == 'event_venue_unreviewed'
    row = shady.parse(card(title='Cancelled: Thirsty Thursday Trivia'), now=NOW)[0]
    assert row['publisher_status'] == 'cancelled'
    assert row['title'] == 'Thirsty Thursday Trivia'


def test_age_and_session_description_stays_with_its_card():
    row = shady.parse(card(prose='<p>Adults 18+ only. Main performance 6 PM to 8 PM.</p>'), now=NOW)[0]
    assert row['description'] == 'Adults 18+ only. Main performance 6 PM to 8 PM.'
    assert row['starts_at'] == '2026-11-12T23:00:00+00:00'


def test_unreviewed_image_is_omitted_without_blocking_verified_event():
    notes = {}
    rows = shady.parse(card(image='https://example.com/flyer.jpg'), now=NOW, diagnostics=notes)
    assert len(rows) == 1 and 'image_url' not in rows[0]
    assert notes['warnings'][0]['reason'] == 'event_image_candidate_unverified'


def test_structural_or_identity_changes_never_claim_a_complete_snapshot():
    payload = FIXTURE.read_text()
    for changed in (payload.replace('data-event-id="3657972"', 'data-event-id="999"'),):
        notes = {}
        rows = shady.parse(changed, now=NOW, diagnostics=notes)
        assert len(rows) == 7
        assert notes['held'][0]['reason'] == 'publisher_card_structure_unverified'
    for changed in (payload.replace('<h1>Events</h1>', '<h1>Archive</h1>'),
                    payload.replace('<h1>Events</h1>', '<h1>Events</h1><a rel="next">More</a>')):
        with pytest.raises(ValueError):
            shady.parse(changed, now=NOW)


def test_collect_uses_only_exact_source_and_preserves_transport_errors():
    fetch = Mock(return_value=FIXTURE.read_text())
    assert len(shady.collect(SOURCE, fetch, now=NOW)) == 8
    fetch.assert_called_once_with(shady.CALENDAR, 'text/html')
    with pytest.raises(ValueError, match='unregistered_shady_source'):
        shady.collect({**SOURCE, 'feed_url': 'https://example.com/'}, fetch, now=NOW)
    error = preview_worker.PreviewError('robots_denied')
    fetch.side_effect = error
    with pytest.raises(preview_worker.PreviewError, match='robots_denied'):
        shady.collect(SOURCE, fetch, now=NOW)
