"""Venue evidence and real multi-session boundary regressions for Halifax."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from html import escape
import importlib.util
import json
from pathlib import Path

import pytest

from roomquest import discover_halifax as tourism
from roomquest import halifax_venue_enrichment as enrichment
from roomquest import preview_worker

FIXTURES = Path(__file__).parent / 'fixtures/halifax_venue_enrichment'
CASES = json.loads((FIXTURES / 'publisher_cases.json').read_text())['cases']
NOW = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
SOURCE = {'source_key': tourism.KEY, 'feed_url': tourism.URL, 'kind': 'html',
          'platform_adapter': 'html', 'timezone': tourism.ZONE,
          'fetch_checkpoint_version': 1, 'venue_association_contract_version': 1}


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    """Keep the actual shared future/ongoing normalizer, changing only its clock."""
    value = [NOW]

    class Meta(type):
        def __instancecheck__(cls, obj):
            return isinstance(obj, datetime)

    class Frozen(datetime, metaclass=Meta):
        @classmethod
        def now(cls, tz=None):
            return value[0].astimezone(tz) if tz else value[0].replace(tzinfo=None)

    monkeypatch.setattr(preview_worker, 'datetime', Frozen)
    return lambda instant: value.__setitem__(0, instant)


def case(group):
    return deepcopy(next(item for item in CASES if item['expected_group'] == group))


def descriptor(item):
    return item['url'], item['title'], date.fromisoformat(item['date']), item['clock']


def detail(item, *, captured=True):
    if captured and item.get('html_fixture'):
        return (FIXTURES / item['html_fixture']).read_text()
    rows = ''.join('<div class="directorist-single-info">'
                   f'<span class="directorist-single-info__label__text">{escape(k)}</span>'
                   f'<span class="directorist-single-info__value">{escape(v)}</span></div>'
                   for k, v in item['fields'].items())
    return (f'<link rel="canonical" href="{item["url"]}">'
            f'<h1 class="directorist-listing-details__listing-title">{escape(item["title"])}</h1>'
            + rows + '<div class="directorist-card-general-section">Description '
            + escape(item['description']) + '</div>')


def listing(cases):
    cards = []
    for item in cases:
        url, title, day, clock = descriptor(item)
        cards.append('<article class="directorist-listing-single">'
                     f'<h2 class="directorist-listing-title"><a href="{url}">{escape(title)}</a></h2>'
                     f'<span class="directorist-listing-card-date">{day:%B} {day.day}, {day.year}</span>'
                     f'<span class="directorist-listing-card-time">{clock}</span></article>')
    return (f'<div class="directorist-header-found-title"><span>{len(cases)}</span></div>'
            + ''.join(cards))


def publisher(cases):
    pages = {tourism.URL: listing(cases), **{item['url']: detail(item) for item in cases}}
    calls = []

    def fetch(url, accept):
        assert accept == 'text/html'
        calls.append(url)
        return pages[url]

    return pages, calls, fetch


def complete(cases, *, source=SOURCE, now=NOW):
    _, calls, fetch = publisher(cases)
    state = None
    for _ in range(10):
        output = tourism.collect_chunk(source, fetch, checkpoint=state, now=now)
        state = json.loads(json.dumps(output['checkpoint']))
        if output['complete']:
            return output, calls
        assert output['events'] == []
    pytest.fail('bounded fixture did not finish')


@pytest.mark.parametrize('item', CASES, ids=lambda item: item['url'].rsplit('/', 2)[1])
def test_reviewed_venue_shapes_have_bound_receipts_and_no_coordinates(item):
    diagnostics = []
    rows = tourism._detail(detail(item), *descriptor(item), diagnostics=diagnostics,
                           venue_associations=True, include_sessions=True)
    if item['expected_group'] is None:
        assert rows is None and diagnostics[-1]['reason'] == 'event_address_unresolved'
        return
    assert rows
    for row in rows:
        receipt = row['venue_association']
        assert receipt['method'] == enrichment.METHOD
        assert receipt['matched_activity'] == row['title']
        assert receipt['venue_name'] == row['venue_name']
        assert receipt['venue_address'] == row['venue_address']
        assert row['event_url'] in receipt['evidence_urls']
        assert 1 <= len(receipt['evidence_urls']) <= 3
        assert len(json.dumps(receipt, ensure_ascii=False).encode()) <= 1800
        assert row['description'].startswith('Venue inferred from ')
        assert row['lat'] is None and row['lng'] is None
        assert 'latitude' not in row and 'longitude' not in row


def test_complete_23_parent_manifest_resolves_22_address_holds_and_preserves_route_hold():
    output, calls = complete(CASES)
    assert output['complete'] and output['checkpoint']['cursor'] == 23
    assert output['checkpoint']['manifest_count'] == 23
    # The school contributes two actual sessions; the parade remains held.
    assert len(output['events']) == 23
    assert len({row['id'] for row in output['events']}) == 23
    assert all(row.get('venue_association') for row in output['events'])
    assert [d['event_url'] for d in output['checkpoint']['diagnostics'] if d['disposition'] == 'held'] == [
        'https://gohalifaxva.com/directory/south-boston-christmas-parade/']
    assert calls.count(tourism.URL) == 4
    assert all(calls.count(item['url']) == 1 for item in CASES)


@pytest.mark.parametrize('version', [None, False, True, 1.0, '1', 0, 2, -1])
def test_non_integer_capabilities_keep_legacy_address_holds(version):
    source = {**SOURCE, 'venue_association_contract_version': version}
    if version is None:
        source.pop('venue_association_contract_version')
    output, _ = complete([case('farmers_market')], source=source)
    assert not output['events']
    assert output['checkpoint']['diagnostics'][0]['reason'] == 'event_address_unresolved'


def test_existing_complete_street_is_not_overwritten_by_an_association():
    item = case('the_light')
    item['fields']['Address'] = 'The Light Spiritual Wellness, 500, Main Street, South Boston, Virginia, 24592, United States'
    row = tourism._detail(detail(item), *descriptor(item), venue_associations=True)
    assert row['venue_address'] == '500 Main Street, South Boston, VA 24592'
    assert 'venue_association' not in row


@pytest.mark.parametrize('suffix', [
    ' Relocated to another hall.', ' Off-site event.', ' Venue: Other Hall.',
    ' Location: Another Center.', ' Venue changed to another building.',
])
def test_conflicting_event_venue_text_does_not_receive_reviewed_address(suffix):
    item = case('the_light')
    item['description'] += suffix
    assert tourism._detail(detail(item), *descriptor(item), venue_associations=True) is None


@pytest.mark.parametrize('location', ['Roanoke Station Visitor Center',
                                    '6000 Roanoke Station Road', 'Mulberry Hill', 'north trailhead', 'picnic shelter'])
def test_clover_program_title_cannot_override_another_explicit_access_point(location):
    item = case('battlefield')
    item['description'] = 'The program starts at ' + location + '.'
    assert tourism._detail(detail(item), *descriptor(item), venue_associations=True) is None


def test_enabled_contract_cannot_fall_back_to_legacy_one_off_light_exception():
    item = case('the_light')
    item.update(url=tourism.THE_LIGHT_EVENT, title='Still Life Drawing at The Light', date='2026-11-12', clock='6:00 PM')
    item['fields'].update({'Start Date': 'November 12, 2026', 'Start Time': '6:00 PM', 'End Time': '9:00 PM'})
    row = tourism._detail(detail(item), *descriptor(item), venue_associations=True)
    assert row['venue_association']['method'] == enrichment.METHOD
    item['description'] += ' Venue: Another Hall.'
    assert tourism._detail(detail(item), *descriptor(item), venue_associations=True) is None


def test_wrong_website_and_new_address_tokens_stay_held():
    for field, value in [('Website', 'https://evil.example/thelightspiritualwellness.com'),
                         ('Address', 'The Light Spiritual Wellness, 999 Other Street')]:
        item = case('the_light')
        item['fields'][field] = value
        assert tourism._detail(detail(item), *descriptor(item), venue_associations=True) is None


def test_actual_school_dom_becomes_two_printed_daily_sessions_not_overnight_event():
    output, _ = complete([case('middle_school')])
    assert [(r['starts_at'], r['ends_at']) for r in output['events']] == [
        ('2026-11-14T14:00:00+00:00', '2026-11-14T21:00:00+00:00'),
        ('2026-11-15T18:00:00+00:00', '2026-11-15T21:00:00+00:00')]
    assert [r['id'] for r in output['events']] == [
        enrichment.HOLIDAY_URL + '#session-2026-11-14', enrichment.HOLIDAY_URL + '#session-2026-11-15']


@pytest.mark.parametrize('instant', ['2026-11-14T22:00:00+00:00', '2026-11-15T14:00:00+00:00',
                                   '2026-11-15T19:00:00+00:00'])
def test_second_session_survives_between_days_and_while_ongoing(clock, instant):
    now = datetime.fromisoformat(instant)
    clock(now)
    output, _ = complete([case('middle_school')], now=now)
    assert [r['id'] for r in output['events']] == [enrichment.HOLIDAY_URL + '#session-2026-11-15']
    excluded = [d for d in output['checkpoint']['diagnostics'] if d['disposition'] == 'excluded']
    assert [d['occurrence_id'] for d in excluded] == [enrichment.HOLIDAY_URL + '#session-2026-11-14']
    tourism._accounted_prefix(output['checkpoint'], [descriptor(case('middle_school'))], venue_associations=True)


def test_second_session_beyond_horizon_is_accounted_but_not_emitted(clock):
    now = datetime(2026, 9, 15, 14, tzinfo=timezone.utc)
    clock(now)
    output, _ = complete([case('middle_school')], now=now)
    assert [r['id'] for r in output['events']] == [enrichment.HOLIDAY_URL + '#session-2026-11-14']
    assert any(d.get('occurrence_id') == enrichment.HOLIDAY_URL + '#session-2026-11-15'
               and d['disposition'] == 'excluded' for d in output['checkpoint']['diagnostics'])
    tourism._accounted_prefix(output['checkpoint'], [descriptor(case('middle_school'))], venue_associations=True)


def test_each_expired_session_is_explicitly_accounted(clock):
    now = datetime(2026, 11, 15, 22, tzinfo=timezone.utc)
    clock(now)
    output, _ = complete([case('middle_school')], now=now)
    assert output['events'] == []
    assert len([d for d in output['checkpoint']['diagnostics'] if d['disposition'] == 'excluded']) == 2
    tourism._accounted_prefix(output['checkpoint'], [descriptor(case('middle_school'))], venue_associations=True)


def test_earlier_first_clock_has_current_listing_evidence_and_does_not_shift_sunday():
    item = case('middle_school')
    item['clock'] = '8:00 AM'  # Actual listing clock; detail and narrative still say 9 a.m.
    output, _ = complete([item])
    assert output['events'][0]['starts_at'] == '2026-11-14T13:00:00+00:00'
    assert output['events'][1]['starts_at'] == '2026-11-15T18:00:00+00:00'
    assert any(d['reason'] == 'earlier_published_start_selected' for d in output['checkpoint']['diagnostics'])


def test_all_six_light_show_urls_keep_their_own_single_evening_identity():
    cases = [c for c in CASES if c['expected_group'] == 'fairgrounds']
    output, _ = complete(cases)
    assert {r['id'] for r in output['events']} == {c['url'] for c in cases}
    assert len(output['events']) == 6
    for row in output['events']:
        assert datetime.fromisoformat(row['ends_at']) - datetime.fromisoformat(row['starts_at']) == timedelta(hours=3)


@pytest.mark.parametrize('mutation', ['wrong_weekday', 'missing_sunday', 'wrong_end_date'])
def test_changed_school_schedule_is_held_instead_of_inferred(mutation):
    item = case('middle_school')
    if mutation == 'wrong_weekday':
        item['description'] = item['description'].replace('Saturday', 'Friday')
    elif mutation == 'missing_sunday':
        item['description'] = item['description'].replace('Sunday November 15th from 1:00pm to 4:00 pm', 'Sunday time to be announced')
    else:
        item['fields']['End Date'] = 'November 16, 2026'
    diagnostics = []
    assert tourism._detail(detail(item, captured=False), *descriptor(item), venue_associations=True,
                           diagnostics=diagnostics) is None
    assert diagnostics[-1]['reason'] == 'publisher_session_schedule_unresolved'


def test_capability_change_restarts_checkpoint_in_both_directions():
    _, _, fetch = publisher(CASES)
    legacy = {k: v for k, v in SOURCE.items() if k != 'venue_association_contract_version'}
    old = tourism.collect_chunk(legacy, fetch, now=NOW)
    new = tourism.collect_chunk(SOURCE, fetch, checkpoint=old['checkpoint'], now=NOW)
    assert new['checkpoint']['cursor'] == 6
    assert new['checkpoint']['manifest_hash'] != old['checkpoint']['manifest_hash']
    assert new['checkpoint']['events'] and all(r.get('venue_association') for r in new['checkpoint']['events'])
    reverted = tourism.collect_chunk(legacy, fetch, checkpoint=new['checkpoint'], now=NOW)
    assert reverted['checkpoint']['cursor'] == 6 and reverted['checkpoint']['events'] == []


def test_missing_or_wrong_day_split_session_cannot_certify_checkpoint():
    _, _, fetch = publisher(CASES)
    first = tourism.collect_chunk(SOURCE, fetch, now=NOW)
    for mutation in ('remove', 'wrong_day'):
        changed = deepcopy(first['checkpoint'])
        row = next(r for r in changed['events'] if r['id'].endswith('#session-2026-11-15'))
        if mutation == 'remove':
            changed['events'].remove(row)
        else:
            row['starts_at'] = '2026-11-14T18:00:00+00:00'
        with pytest.raises(ValueError, match='halifax_checkpoint_invalid'):
            tourism.collect_chunk(SOURCE, fetch, checkpoint=changed, now=NOW)


def test_resume_after_first_session_closes_rechecks_only_real_sessions(clock):
    now = datetime(2026, 11, 14, 20, tzinfo=timezone.utc)
    clock(now)
    cases = [case('middle_school'), case('vir')]
    _, _, fetch = publisher(cases)
    first = tourism.collect_chunk(SOURCE, fetch, now=now, max_details=1)
    assert len(first['checkpoint']['events']) == 2
    later = now + timedelta(hours=2)
    clock(later)
    output = tourism.collect_chunk(SOURCE, fetch, checkpoint=first['checkpoint'], now=later)
    assert output['complete'] and len(output['events']) == 2  # Sunday + later VIR event.
    assert not any(r['id'].endswith('#session-2026-11-14') for r in output['events'])
    assert any(d.get('occurrence_id', '').endswith('#session-2026-11-14') for d in output['checkpoint']['diagnostics'])


def test_recovery_audit_profiles_capabilities_and_preserves_receipt():
    path = Path(__file__).parents[1] / 'scripts/capture_south_hill_recovery.py'
    spec = importlib.util.spec_from_file_location('halifax_recovery_receipt_test', path)
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    source = audit._source(tourism.KEY, audit.SOURCES[tourism.KEY])
    assert type(source['venue_association_contract_version']) is int and source['venue_association_contract_version'] == 1
    assert source['fetch_checkpoint_version'] == 1
    output, _ = complete([case('farmers_market')])
    row = output['events'][0]
    assert audit._candidate_receipt(row)['venue_association'] == row['venue_association']
