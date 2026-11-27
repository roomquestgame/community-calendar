"""Observed NWT date/time DOM with explicitly synthetic narrative controls."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from roomquest import preview_worker as worker, wildlife_trusts as wildlife
from roomquest.registration_formats import source_key

FIXTURES = Path(__file__).parent / 'fixtures' / 'national_feeds'
BODY = (FIXTURES / 'wildlife-nwt-date-clock.html').read_text()
FEED = 'https://www.nwt.org.uk/events'
DETAIL = FEED + '/2026-11-25-wansbeck-natural-history-group-update-on-beavers-and-other-animals-wallington'
SOURCE = {'feed_url': FEED, 'source_key': source_key(FEED), 'kind': 'html',
          'platform_adapter': 'html', 'registered_native_content_version': 1}
ITEM = {'url': DETAIL, 'title': 'Northumberland date and clock template control',
        'start': '2026-11-25', 'end': '2026-11-25'}
NOW = datetime(2026, 11, 22, 9, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fixed_window(monkeypatch):
    monkeypatch.setattr(worker, '_future_datetime', lambda value: value.astimezone(timezone.utc)
                        if NOW <= value <= NOW + timedelta(days=60) else None)


def parse(body=BODY, item=None):
    return wildlife.parse_detail(body, ITEM if item is None else item, source=SOURCE)


def test_observed_date_only_and_separate_clock_preserve_native_fields():
    [row], reason = parse()
    assert reason == 'included'
    assert row['starts_at'] == '2026-11-25T19:00:00+00:00'
    assert row['ends_at'] == '2026-11-25T20:15:00+00:00'
    assert row['timezone'] == 'Europe/London'
    assert (row['lat'], row['lng']) == (55.160758, -1.908005)
    assert row['venue_name'] == 'Middleton Village Hall'
    assert 'Morpeth' in row['venue_address'] and 'NE61 4RA' in row['venue_address']
    assert 'original publisher description is preserved in full' in row['description']
    assert row['description'].endswith(
        'This second paragraph verifies that adding a date-only template does not flatten or discard native prose.')
    assert row['event_url'] == DETAIL
    assert row['registered_native_content']['evidence_url'] == DETAIL
    wildlife.validate_native(row, SOURCE)


def test_aware_datetime_still_accepts_the_observed_clock_field_alias():
    body = BODY.replace('datetime="2026-11-25"', 'datetime="2026-11-25T19:00:00+00:00"')
    [row], reason = parse(body)
    assert reason == 'included'
    assert row['starts_at'] == '2026-11-25T19:00:00+00:00'


@pytest.mark.parametrize('clock', ['', 'TBC', 'Afternoon', '7 to 8pm', '19:00 - TBC',
                                   '19:00 or 20:00', '25:00 - 26:00', '19:60 - 20:15'])
def test_missing_and_ambiguous_native_clocks_still_hold(clock):
    assert parse(BODY.replace('19:00 - 20:15', clock)) == ([], 'wildlife_event_clock_unresolved')


@pytest.mark.parametrize('value', ['2026/11/25', '25 November 2026', '2026-11',
                                   '2026-02-30', '2026-11-25T19:00:00'])
def test_only_strict_full_dates_or_aware_datetimes_are_accepted(value):
    assert parse(BODY.replace('datetime="2026-11-25"', f'datetime="{value}"')) == (
        [], 'wildlife_event_clock_unresolved')


def test_date_only_without_the_native_clock_field_holds():
    assert parse(BODY.replace('field--name-field-event-time', 'unreviewed-time')) == (
        [], 'wildlife_event_clock_unresolved')


@pytest.mark.parametrize('value', ['2026-11-25T12:00:00Z', '2026-11-25T00:00:00+00:00'])
def test_explicit_datetime_conflicts_are_never_replaced_with_the_visible_clock(value):
    assert parse(BODY.replace('datetime="2026-11-25"', f'datetime="{value}"')) == (
        [], 'wildlife_event_clock_unresolved')


@pytest.mark.parametrize('name', ['event-time', 'event-time-value'])
def test_conflicting_duplicate_native_clock_fields_hold(name):
    extra = f'<div class="field--name-field-{name}"><div class="field__item">18:00 - 20:15</div></div>'
    assert parse(BODY.replace('</h1>', '</h1>' + extra)) == ([], 'wildlife_event_clock_unresolved')


def test_identical_aliases_agree_without_choosing_a_preferred_field():
    extra = '<div class="field--name-field-event-time-value">7pm - 8.15pm</div>'
    [row], reason = parse(BODY.replace('</h1>', '</h1>' + extra))
    assert reason == 'included' and row['ends_at'] == '2026-11-25T20:15:00+00:00'


@pytest.mark.parametrize('value', ['2026-11-25', '2026-11-25T19:00:00Z'])
def test_duplicate_start_date_fields_still_hold(value):
    extra = f'<time datetime="{value}" itemprop="startDate"></time>'
    assert parse(BODY.replace('</time>', '</time>' + extra, 1)) == (
        [], 'wildlife_event_dates_unresolved')


def test_manifest_date_conflict_and_multiple_dates_still_hold():
    assert parse(item=dict(ITEM, start='2026-11-26', end='2026-11-26')) == (
        [], 'wildlife_detail_date_conflict')
    assert parse(item=dict(ITEM, end='2026-11-26')) == ([], 'wildlife_multiple_dates_unresolved')


def test_explicit_conflicting_end_datetime_is_not_overwritten():
    extra = '<time datetime="2026-11-25T20:00:00Z" itemprop="endDate"></time>'
    assert parse(BODY.replace('</time>', '</time>' + extra, 1)) == (
        [], 'wildlife_detail_time_conflict')


def test_date_only_end_uses_only_the_published_end_clock():
    extra = '<time datetime="2026-11-25" itemprop="endDate"></time>'
    body = BODY.replace('</time>', '</time>' + extra, 1)
    [row], reason = parse(body)
    assert reason == 'included' and row['ends_at'] == '2026-11-25T20:15:00+00:00'
    assert parse(body.replace('19:00 - 20:15', '19:00')) == (
        [], 'wildlife_event_clock_unresolved')


def test_multiple_published_dates_and_overnight_ranges_still_hold():
    extra = '<time datetime="2026-11-26" itemprop="endDate"></time>'
    assert parse(BODY.replace('</time>', '</time>' + extra, 1)) == (
        [], 'wildlife_multiple_dates_unresolved')
    assert parse(BODY.replace('19:00 - 20:15', '19:00 - 18:00')) == (
        [], 'wildlife_detail_time_conflict')


def test_single_explicit_start_does_not_invent_an_end():
    [row], reason = parse(BODY.replace('19:00 - 20:15', '19:00'))
    assert reason == 'included' and row['ends_at'] is None


@pytest.mark.parametrize('day', ['2027-03-28', '2026-10-25'])
def test_date_plus_clock_rejects_nonexistent_and_ambiguous_london_times(day):
    body = BODY.replace('datetime="2026-11-25"', f'datetime="{day}"')
    body = body.replace('19:00 - 20:15', '01:30 - 02:30')
    assert parse(body, dict(ITEM, start=day, end=day)) == (
        [], 'wildlife_event_clock_unresolved')


def test_date_plus_clock_uses_london_summer_offset(monkeypatch):
    day = '2027-06-25'
    monkeypatch.setattr(worker, '_future_datetime', lambda value: value.astimezone(timezone.utc))
    body = BODY.replace('datetime="2026-11-25"', f'datetime="{day}"')
    [row], reason = parse(body, dict(ITEM, start=day, end=day))
    assert reason == 'included'
    assert row['starts_at'] == '2027-06-25T18:00:00+00:00'
    assert row['ends_at'] == '2027-06-25T19:15:00+00:00'


@pytest.mark.parametrize(('field', 'value'), [
    ('latitude', '91'), ('latitude', 'NaN'), ('latitude', 'unknown'),
    ('longitude', '-181'), ('longitude', 'Infinity'),
])
def test_invalid_publisher_coordinates_remain_held(field, value):
    old = '55.160758' if field == 'latitude' else '-1.908005'
    body = BODY.replace(f'itemprop="{field}" content="{old}"',
                        f'itemprop="{field}" content="{value}"')
    assert parse(body) == ([], 'wildlife_event_location_unresolved')


def test_wildlife_date_clock_fingerprint_retains_local_source_time():
    [row], reason = parse()
    assert reason == 'included'
    facts = row['collector_event_content_v1']['facts']
    assert facts['starts_at_local'] == '2026-11-25T19:00:00'
    assert facts['ends_at_local'] == '2026-11-25T20:15:00'
    assert 'starts_at_utc' not in facts
