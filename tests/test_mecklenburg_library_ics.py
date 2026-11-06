"""Synthetic contracts for the reviewed Mecklenburg public-library ICS source."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from icalendar import Calendar, Event

from roomquest.ics_adapter import (
    MECKLENBURG_LIBRARY_CALENDAR,
    MECKLENBURG_LIBRARY_FEED,
    MECKLENBURG_LIBRARY_KEY,
    _prune_expired_until_groups,
    parse,
)

ZONE = ZoneInfo('America/New_York')
NOW = datetime.now(timezone.utc).replace(microsecond=0)
START = (NOW + timedelta(days=2)).astimezone(ZONE).replace(hour=10, minute=30, second=0)
SOURCE = {'source_key': MECKLENBURG_LIBRARY_KEY, 'url': MECKLENBURG_LIBRARY_FEED}
BOOK = '2vuprkgguf4ea6u7mljhjcbgsv@google.com'
BOYDTON = '54gq15h3o25rhbnss876dj7s81_R20260716T143000@google.com'
BURNETT = 'Burnett Library & Learning Center'


def event(uid='single', title='Community program', start=START, *, location=None,
          rule=None, end=None, description=None, url=None, status=None, recurrence_id=None):
    item = Event()
    item.add('uid', uid)
    item.add('summary', title)
    item.add('dtstart', start)
    item.add('dtend', end if end is not None else start + timedelta(hours=1))
    for key, value in [('location', location), ('rrule', rule), ('description', description),
                       ('url', url), ('status', status), ('recurrence-id', recurrence_id)]:
        if value is not None:
            item.add(key, value)
    return item


def feed(*items, tz='America/New_York'):
    cal = Calendar()
    cal.add('version', '2.0')
    cal.add('x-wr-timezone', tz)
    for item in items:
        cal.add_component(item)
    return cal.to_ical().decode()


def old(uid):
    return event(uid, start=NOW-timedelta(days=600),
                 rule={'freq': 'weekly', 'until': NOW-timedelta(days=500)})


def test_expired_archive_passes_only_for_exact_enrolled_source_without_changing_ids():
    upcoming = event(BOOK, 'Clarksville Book Club', rule={'freq': 'weekly', 'count': 3},
                     description='Publisher narrative')
    raw = feed(*[old('old-'+str(i)) for i in range(51)], upcoming)
    records = parse(raw, SOURCE, legacy=True)
    assert len(records) == 3
    assert {r['id'] for r in records} == {
        BOOK+'__'+(START+timedelta(days=7*i)).strftime('%Y%m%d') for i in range(3)
    }
    assert all(r['description'] == 'Publisher narrative' for r in records)
    assert all(r['venue_address'] == '914 Virginia Avenue, Clarksville, VA 23927' for r in records)
    with pytest.raises(ValueError, match='recurrence_record_limit'):
        parse(raw, {'source_key': 'unrelated_ical', 'url': MECKLENBURG_LIBRARY_FEED}, legacy=True)


def test_51_active_masters_still_fail():
    raw = feed(*[event(str(i), location=BURNETT, rule={'freq': 'weekly'}) for i in range(51)])
    with pytest.raises(ValueError, match='recurrence_record_limit'):
        parse(raw, SOURCE)


def test_library_narrative_cap_matches_shared_staging_without_changing_other_sources():
    description = 'Useful publisher narrative. ' * 100
    raw = feed(event(location=BURNETT, description=description))
    assert parse(raw, SOURCE)[0]['description'] == description[:2000]
    other = {'source_key': 'unrelated_ical', 'url': MECKLENBURG_LIBRARY_FEED}
    assert parse(raw, other, include_description=True)[0]['description'] == description.strip()


def test_original_raw_component_limit_cannot_be_evaded_by_archive_pruning():
    raw = feed(*[old('old-'+str(i)) for i in range(1001)])
    with pytest.raises(ValueError, match='source_record_limit'):
        parse(raw, SOURCE)


def test_normalizer_component_cap_cannot_produce_a_successful_partial_snapshot():
    raw = feed(event(location=BURNETT, rule={'freq': 'daily', 'byhour': list(range(20))}))
    with pytest.raises(ValueError, match='source_record_limit'):
        parse(raw, SOURCE)


def test_500_output_limit_is_retained():
    raw = feed(*[event(str(i), location=BURNETT) for i in range(501)])
    with pytest.raises(ValueError, match='source_record_limit'):
        parse(raw, SOURCE)


@pytest.mark.parametrize('all_day', [False, True])
def test_dense_historical_recurrence_is_validated_before_pruning(all_day):
    start = NOW-timedelta(days=600)
    if all_day:
        start = start.date()
    raw = feed(event(start=start, end=start+timedelta(days=1),
                     rule={'freq': 'secondly', 'until': NOW-timedelta(days=500)}))
    with pytest.raises(ValueError, match='unsupported_dense_recurrence'):
        parse(raw, SOURCE)


def test_future_rdate_prevents_expired_master_pruning():
    base = old('rdate')
    base.add('rdate', START)
    base.add('location', BURNETT)
    result = parse(feed(base), SOURCE)
    assert len(result) == 1
    assert result[0]['starts_at'] == START.astimezone(timezone.utc).isoformat()


def test_future_moved_override_retains_own_time_description_url_and_offsite_venue():
    base = old(BOOK)
    offsite = 'Community Hall, 123 Example Street, Boydton, VA 23917'
    override = event(BOOK, 'Special off-site meeting', location=offsite,
                     recurrence_id=NOW-timedelta(days=550),
                     description='Occurrence-specific narrative', url='https://example.org/program')
    override.add('geo', (36.5, -78.4))
    result = parse(feed(base, override), SOURCE, legacy=True)
    assert len(result) == 1
    actual = result[0]
    assert actual['title'] == 'Special off-site meeting'
    assert actual['description'] == 'Occurrence-specific narrative'
    assert actual['event_url'] == 'https://example.org/program'
    assert actual['venue_name'] == offsite and actual['venue_address'] == offsite
    assert (actual['lat'], actual['lng']) == (36.5, -78.4)


def test_count_all_day_range_and_competing_master_shapes_are_not_pruned():
    counted = event('counted', start=NOW-timedelta(days=600), rule={'freq': 'daily', 'count': 3})
    all_day = event('all-day', start=(NOW-timedelta(days=600)).date(),
                    end=(NOW-timedelta(days=599)).date(),
                    rule={'freq': 'daily', 'until': (NOW-timedelta(days=500)).date()})
    ranged = old('ranged')
    override = event('ranged', start=NOW-timedelta(days=550),
                     recurrence_id=NOW-timedelta(days=550))
    override['recurrence-id'].params['RANGE'] = 'THISANDFUTURE'
    duplicate = [old('competing'), old('competing')]
    cal = Calendar.from_ical(feed(counted, all_day, ranged, override, *duplicate))
    result = _prune_expired_until_groups(cal, NOW)
    assert result.to_ical() == cal.to_ical()


def test_long_final_occurrence_and_unresolved_end_are_not_pruned():
    ongoing = event('long', start=NOW-timedelta(days=10), end=NOW+timedelta(days=5),
                     rule={'freq': 'weekly', 'until': NOW-timedelta(days=3)})
    unknown = old('unknown-end')
    del unknown['DTEND']
    cal = Calendar.from_ical(feed(ongoing, unknown))
    assert _prune_expired_until_groups(cal, NOW).to_ical() == cal.to_ical()


def test_exdates_and_occurrence_ids_survive_pruning():
    recurring = event(BOOK, 'Clarksville Book Club', rule={'freq': 'daily', 'count': 3})
    recurring.add('exdate', START+timedelta(days=1))
    override = event(BOOK, 'Updated meeting', start=START+timedelta(days=2, hours=1),
                     recurrence_id=START+timedelta(days=2), location=BURNETT,
                     description='Updated occurrence')
    actual = parse(feed(old('archive'), recurring, override), SOURCE)
    assert len(actual) == 2
    moved = next(e for e in actual if e['title'] == 'Updated meeting')
    assert moved['starts_at'] == (START+timedelta(days=2, hours=1)).astimezone(timezone.utc).isoformat()
    assert moved['description'] == 'Updated occurrence'


@pytest.mark.parametrize('name,address,city', [
    ('Boydton Public Library', '1294 Jefferson Street, Boydton, VA 23917', 'Boydton'),
    ('Burnett Library & Learning Center, 914 Virginia Ave, Clarksville, VA 23927, USA',
     '914 Virginia Avenue, Clarksville, VA 23927', 'Clarksville'),
    ('R. T. Arnold Public Library', '110 East Danville Street, South Hill, VA 23970', 'South Hill'),
    ('Butler Memorial Library', '515 Marshall Street, Chase City, VA 23924', 'Chase City'),
])
def test_explicit_branch_locations_use_verified_directory_without_coordinates(name, address, city, caplog):
    with caplog.at_level('INFO'):
        result = parse(feed(event(location=name)), SOURCE)
    assert result[0]['venue_address'] == address and result[0]['venue_city'] == city
    assert result[0]['lat'] is None and result[0]['lng'] is None
    assert 'basis=event_location' in caplog.text
    assert 'https://www.youseemore.com/mecklib/directory.asp' in caplog.text


def test_unknown_or_changed_series_remain_unlocated_for_existing_review_gates(caplog):
    result = parse(feed(event('unknown'), event(BOOK, 'Changed off-site program')), SOURCE)
    assert len(result) == 2
    assert all(not e['venue_name'] and not e['venue_address'] and e['lat'] is None for e in result)
    assert 'publisher_branch_unresolved' in caplog.text


def test_date_only_closure_withholds_conflicting_program_without_invented_time(caplog):
    closure = event('closure', 'Closed', start=START.date(), end=START.date()+timedelta(days=1))
    result = parse(feed(event(BOYDTON, 'Boydton Storytime'), closure), SOURCE)
    assert result == []
    assert 'publisher_closure_overlap' in caplog.text
    assert 'publisher_closure_record' in caplog.text


def test_timed_closure_filters_only_overlap_and_its_own_listing(caplog):
    noon = START.replace(hour=12, minute=0)
    closure = event('closure', 'closed', start=noon, end=noon+timedelta(hours=6))
    morning = event('morning', location=BURNETT)
    afternoon = event('afternoon', start=noon+timedelta(hours=1), location=BURNETT)
    result = parse(feed(morning, afternoon, closure), SOURCE)
    assert [r['id'] for r in result] == ['morning']
    assert 'publisher_closure_overlap' in caplog.text and 'publisher_closure_record' in caplog.text


def test_branch_closure_does_not_hide_another_branch_and_cancelled_closure_has_no_effect():
    closure = event('closure', 'closed', location='Boydton Public Library')
    cancelled = event('cancelled-closure', 'Closed', status='CANCELLED')
    boydton = event(BOYDTON, 'Boydton Storytime')
    clarksville = event(BOOK, 'Clarksville Book Club')
    result = parse(feed(boydton, clarksville, closure, cancelled), SOURCE)
    assert [r['id'] for r in result] == [BOOK]


def test_date_end_is_exclusive_in_new_york_and_closure_only_is_valid_empty():
    day = START.date()
    closure = event('closure', 'closed', start=day, end=day+timedelta(days=1))
    next_day = event('next-day', start=START+timedelta(days=1), location=BURNETT)
    assert len(parse(feed(closure, next_day), SOURCE)) == 1
    assert parse(feed(closure), SOURCE) == []


def test_no_end_time_on_future_timed_closure_is_not_guessed():
    closure = event('closure', 'closed')
    del closure['DTEND']
    with pytest.raises(ValueError, match='library_closure_time_unresolved'):
        parse(feed(event(location=BURNETT), closure), SOURCE)


def test_source_url_and_calendar_timezone_identity_are_enforced():
    with pytest.raises(ValueError, match='unregistered_mecklenburg_library_source'):
        parse(feed(event()), dict(SOURCE, url='https://example.org/calendar.ics'))
    with pytest.raises(ValueError, match='publisher_timezone_conflict'):
        parse(feed(event(location=BURNETT), tz='America/Chicago'), SOURCE)


def test_description_official_fallback_and_explicit_image_are_preserved_without_fabrication():
    item = event(BOOK, 'Clarksville Book Club', description='Actual narrative\nSecond line')
    item.add('attach', 'https://www.youseemore.com/mecklib/program.jpg', parameters={'FMTTYPE': 'image/jpeg'})
    actual = parse(feed(item), SOURCE, legacy=True)[0]
    assert actual['description'] == 'Actual narrative\nSecond line'
    assert actual['event_url'] == MECKLENBURG_LIBRARY_CALENDAR
    assert actual['image_url'] == 'https://www.youseemore.com/mecklib/program.jpg'
    assert parse(feed(event(location=BURNETT)), SOURCE)[0]['description'] == ''


def test_duplicate_occurrence_ids_fail_instead_of_overwriting_a_snapshot():
    raw = feed(event('same', location=BURNETT),
               event('same', start=START+timedelta(days=1), location=BURNETT))
    with pytest.raises(ValueError, match='recurrence_identity_conflict'):
        parse(raw, SOURCE)
