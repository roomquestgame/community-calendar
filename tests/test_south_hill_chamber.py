from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from roomquest import ics_adapter, preview_worker, south_hill_chamber as chamber

FIXTURES = Path(__file__).parent / 'fixtures/south_hill'
NOW = datetime(2026, 11, 6, 13, tzinfo=timezone.utc)
SOURCE = {'source_key': chamber.SOURCE_KEY, 'feed_url': chamber.CALENDAR,
          'kind': 'html', 'platform_adapter': 'html', 'timezone': chamber.TIMEZONE}
SLUGS = {'customer': 'annual-customer-appreciation-day-1734865',
         'prompting': 'ai-for-business-practical-prompting-for-everyday-work-1927017',
         'marketing': 'build-a-marketing-plan-you-will-actually-use-1948864'}


def freeze(monkeypatch, value):
    actual = datetime

    class Meta(type):
        def __instancecheck__(cls, item):
            return isinstance(item, actual)

    class Clock(actual, metaclass=Meta):
        @classmethod
        def now(cls, tz=None):
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    for module in (chamber, preview_worker, ics_adapter):
        monkeypatch.setattr(module, 'datetime', Clock)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    freeze(monkeypatch, NOW)


def detail_url(name='customer'):
    return chamber.CALENDAR + '/Details/' + SLUGS[name]


def ics_url(name='customer'):
    return chamber.CALENDAR + '/ICal/' + SLUGS[name] + '.ics'


def captured(name, extension='html'):
    return (FIXTURES / f'chamber_{name}_20261106.{extension}').read_text()


def listing(names=None, *, total=None, following=None):
    soup = BeautifulSoup(captured('listing'), 'html.parser')
    wrapper = soup.select_one('.gz-events-cards')
    cards = list(wrapper.select('.gz-events-card'))
    if names is not None:
        cards = [card for card in cards if any(SLUGS[name] in str(card) for name in names)]
        wrapper.clear()
        for card in cards:
            wrapper.append(card)
    count = total if total is not None else len(cards)
    for node in soup.select('.gz-subtitle'):
        if node.get_text().startswith('Results:'):
            node.string = f'Results: {count}'
    if following:
        pager = soup.new_tag('nav', **{'class': 'gz-pagination'})
        anchor = soup.new_tag('a', href=following)
        anchor.string = 'Next'
        pager.append(anchor)
        soup.select_one('.gz-events-listing').append(pager)
    return str(soup)


def bundle(names=None):
    data = {chamber.CALENDAR: listing(names)}
    for name in names or SLUGS:
        data[detail_url(name)] = captured(name)
        if name != 'marketing':
            data[ics_url(name)] = captured(name, 'ics')
    return data


def run(data, *, calls=None):
    def fetch(url, accept):
        if calls is not None:
            calls.append((url, accept))
        return data[url]
    return chamber.collect(SOURCE, fetch)


def meta_change(payload, **changes):
    soup = BeautifulSoup(payload, 'html.parser')
    script = soup.select_one('script[type="application/ld+json"]')
    value = json.loads(script.get_text())
    value.update(changes)
    script.string = json.dumps(value)
    return str(soup)


def test_actual_snapshot_uses_linked_exports_and_actual_regional_venues(monkeypatch, capsys):
    calls, parser_calls = [], []
    original_parse = chamber.parse_ics
    def shared_parse(*args, **kwargs):
        parser_calls.append(kwargs)
        return original_parse(*args, **kwargs)
    monkeypatch.setattr(chamber, 'parse_ics', shared_parse)
    rows = run(bundle(), calls=calls)
    assert [r['id'] for r in rows] == ['e.4800.1637639', 'e.4800.1464252']
    assert rows[0]['venue_address'] == '715 Wilborn Avenue, South Boston, VA 24592'
    assert rows[0]['venue_city'] == 'South Boston'
    assert rows[1]['venue_name'] == 'Rent-E-Quip'
    assert rows[1]['venue_address'] == '710 W. Danville St, South Hill, VA 23970'
    assert rows[1]['starts_at'] == '2026-12-04T16:30:00+00:00'
    assert rows[1]['ends_at'] == '2026-12-04T19:00:00+00:00'
    assert 'Please RSVP by 11.28.26' in rows[1]['description']
    assert all(r['lat'] is None and r['lng'] is None for r in rows)
    assert all(r['event_url'] == r['details_evidence_url'] for r in rows)
    assert all(r['publisher_status'] == 'scheduled' for r in rows)
    assert all('image_url' not in r and r['image_extractor_version'] == 'publisher_event_candidates_v1' for r in rows)
    assert all(c == {'include_description': True} for c in parser_calls)
    assert len(calls) == 6
    assert all(url.startswith('https://members.southhillchamber.com/calendar') for url, _ in calls)
    assert 'publisher_schedule_conflict' in capsys.readouterr().err


def test_new_future_event_is_discovered_without_hardcoded_event_allowlist():
    data = bundle(['customer'])
    soup = BeautifulSoup(data[chamber.CALENDAR], 'html.parser')
    card = deepcopy(soup.select_one('.gz-events-card'))
    old_title, new_title = 'Annual Customer Appreciation Day', 'New Community Open House'
    old_slug, new_slug = SLUGS['customer'], 'new-community-open-house-2000000'
    card = BeautifulSoup(str(card).replace(old_title, new_title).replace(old_slug, new_slug)
                         .replace('12/4/2026', '11/20/2026'), 'html.parser')
    card.select_one('.gz-card-month .gz-start-dt').string = 'November'
    card.select_one('.gz-card-dday .gz-start-dy').string = '20'
    soup.select_one('.gz-events-cards').append(card)
    soup.select_one('.gz-sort-toolbar .gz-subtitle').string = 'Results: 2'
    data[chamber.CALENDAR] = str(soup)
    new_url = chamber.CALENDAR + '/Details/' + new_slug
    new_ics = chamber.CALENDAR + '/ICal/' + new_slug + '.ics'
    data[new_url] = captured('customer').replace(old_title, new_title).replace(old_slug, new_slug) \
        .replace('December 4, 2026', 'November 20, 2026').replace('2026-12-04', '2026-11-20')
    data[new_ics] = captured('customer', 'ics').replace(old_title, new_title).replace(old_slug, new_slug) \
        .replace('20261204', '20261120').replace('e.4800.1464252', 'e.4800.9999999')
    rows = run(data)
    assert len(rows) == 2
    assert rows[0]['id'] == 'e.4800.9999999'
    assert rows[0]['title'] == new_title and rows[0]['event_url'] == new_url
    assert rows[0]['starts_at'] == '2026-11-20T16:30:00+00:00'


def test_advertised_pagination_is_complete_before_any_detail_fetch():
    data = bundle()
    page2 = chamber.CALENDAR + '?page=2'
    data[chamber.CALENDAR] = listing(['marketing', 'prompting'], total=4, following=page2)
    # The fourth, January listing remains discoverable without fetching its
    # outside-window detail. It is copied from the actual captured listing.
    soup = BeautifulSoup(captured('listing'), 'html.parser')
    cards = soup.select_one('.gz-events-cards')
    for node in list(cards.select('.gz-events-card'))[:2]:
        node.decompose()
    data[page2] = str(soup)
    calls = []
    assert len(run(data, calls=calls)) == 2
    assert calls[:2] == [(chamber.CALENDAR, 'text/html'), (page2, 'text/html')]


@pytest.mark.parametrize('payload', ['<html>Unavailable</html>', '<div class="gz-events-listing"></div>',
                                    listing(['customer'], total=2)])
def test_partial_or_broken_listing_is_not_healthy_empty(payload):
    calls = []
    with pytest.raises(ValueError, match='unsupported_chamber_listing|chamber_result_count_mismatch'):
        run({chamber.CALENDAR: payload}, calls=calls)
    assert len(calls) == 1


def test_explicit_complete_empty_is_healthy():
    assert run({chamber.CALENDAR: listing([])}) == []


def test_pagination_count_drift_and_unreviewed_routes_fail_before_details():
    data = bundle(['customer'])
    page2 = chamber.CALENDAR + '?page=2'
    data[chamber.CALENDAR] = listing(['customer'], total=2, following=page2)
    data[page2] = listing(['customer'], total=3)
    with pytest.raises(ValueError, match='chamber_result_count_changed'):
        run(data)
    data[chamber.CALENDAR] = listing(['customer'], following='https://other.example/calendar?page=2')
    with pytest.raises(ValueError, match='invalid_chamber_event_link'):
        run(data)


def test_pagination_and_detail_budgets_do_not_produce_partial_success(monkeypatch):
    data = bundle(['customer'])
    data[chamber.CALENDAR] = listing(['customer'], following=chamber.CALENDAR + '?page=2')
    for page in range(2, 7):
        data[chamber.CALENDAR + f'?page={page}'] = listing(['customer'], following=chamber.CALENDAR + f'?page={page+1}')
    with pytest.raises(ValueError, match='pagination_limit'):
        run(data)
    monkeypatch.setattr(chamber, 'MAX_DETAILS', 1)
    with pytest.raises(ValueError, match='source_record_limit'):
        run(bundle())


@pytest.mark.parametrize('url', [
    'https://members.southhillchamber.com/calendar/Details/event-12?unreviewed=1',
    'https://members.southhillchamber.com/calendar/Details/event-12?sourceTypeId=Website&sourceTypeId=Hub',
    'https://members.southhillchamber.com/calendar/Details/event-12#fragment',
    'https://members.southhillchamber.com:444/calendar/Details/event-12',
    'https://other.example/calendar/Details/event-12',
    'http://members.southhillchamber.com/calendar/Details/event-12',
])
def test_only_reviewed_detail_aliases_are_normalized(url):
    with pytest.raises(ValueError, match='invalid_chamber_event_link'):
        chamber.canonical_event_url(url)


def test_observed_hub_website_and_path_aliases_share_one_canonical_identity():
    expected = (detail_url(), '1734865')
    for path, query in [('calendar', 'Website'), ('events', 'Hub')]:
        assert chamber.canonical_event_url('https://' + chamber.HOST + '/' + path + '/Details/'
                                           + SLUGS['customer'] + '?sourceTypeId=' + query) == expected


def test_external_or_wrong_event_export_is_never_fetched():
    for replacement in ('https://other.example/event.ics', ics_url('prompting')):
        data = bundle(['customer'])
        data[detail_url()] = data[detail_url()].replace(ics_url(), replacement)
        calls = []
        with pytest.raises(ValueError, match='invalid_chamber_event_link|chamber_export_identity_mismatch'):
            run(data, calls=calls)
        assert all(url != replacement for url, _ in calls)


@pytest.mark.parametrize('change,reason', [
    (lambda s: s.replace('e.4800.1464252', ''), 'chamber_export_identity_missing'),
    (lambda s: s.replace(SLUGS['customer'], SLUGS['prompting']), 'chamber_export_identity_mismatch'),
    (lambda s: s.replace('END:VCALENDAR', ''), 'invalid_calendar_payload'),
    (lambda s: s.replace('SUMMARY:Annual Customer Appreciation Day', 'SUMMARY:An unrelated event'), 'publisher_event_identity_conflict'),
])
def test_ics_identity_or_shape_failure_is_not_a_successful_partial_calendar(change, reason):
    data = bundle()
    data[ics_url()] = change(data[ics_url()])
    with pytest.raises(ValueError, match=reason):
        run(data)


def test_multiple_vevents_cannot_silently_become_one_record():
    data = bundle(['customer'])
    payload = data[ics_url()]
    component = payload.split('BEGIN:VEVENT', 1)[1].split('END:VEVENT', 1)[0]
    data[ics_url()] = payload.replace('END:VCALENDAR', 'BEGIN:VEVENT' + component + 'END:VEVENT\nEND:VCALENDAR')
    with pytest.raises(ValueError, match='chamber_export_record_count'):
        run(data)


@pytest.mark.parametrize('field,value', [('DTSTART;TZID=America/New_York:20261204T113000', 'DTSTART;TZID=America/New_York:20261204T123000'),
                                       ('LOCATION:710 W. Danville St South Hill VA 23970', 'LOCATION:201 S Mecklenburg Avenue South Hill VA 23970')])
def test_conflicting_time_or_venue_holds_only_that_event(field, value, capsys):
    data = bundle()
    data[ics_url()] = data[ics_url()].replace(field, value)
    rows = run(data)
    assert [r['id'] for r in rows] == ['e.4800.1637639']
    assert 'event_held' in capsys.readouterr().err


def test_unknown_venue_does_not_inherit_office_or_source_defaults(capsys):
    data = bundle(['customer'])
    data[detail_url()] = meta_change(data[detail_url()], location={'@type': 'Place', 'name': 'Unknown room'})
    with pytest.raises(ValueError, match='south_hill_chamber_event_evidence_unavailable'):
        run(data)
    assert 'event_venue_unreviewed' in capsys.readouterr().err


def test_explicit_virtual_event_remains_held_after_status_check(capsys):
    data = bundle(['customer'])
    data[detail_url()] = meta_change(data[detail_url()], location={'@type': 'Place', 'name': 'Zoom'})
    calls = []
    with pytest.raises(ValueError, match='south_hill_chamber_event_evidence_unavailable'):
        run(data, calls=calls)
    assert 'virtual_event' in capsys.readouterr().err
    assert len(calls) == 3


def test_all_day_ics_is_held_without_midnight_invention(capsys):
    data = bundle(['customer'])
    data[ics_url()] = data[ics_url()].replace('DTSTART;TZID=America/New_York:20261204T113000', 'DTSTART;VALUE=DATE:20261204') \
        .replace('DTEND;TZID=America/New_York:20261204T140000', 'DTEND;VALUE=DATE:20261205')
    with pytest.raises(ValueError, match='south_hill_chamber_event_evidence_unavailable'):
        run(data)
    assert 'unsupported_all_day_time' in capsys.readouterr().err


def test_explicit_cancellation_refresh_retains_uid_occurrence_and_evidence():
    data = bundle(['customer'])
    before = run(data)[0]
    data[detail_url()] = meta_change(data[detail_url()], eventStatus='https://schema.org/EventCancelled')
    data[ics_url()] = data[ics_url()].replace('BEGIN:VEVENT\n', 'BEGIN:VEVENT\nSTATUS:CANCELLED\n')
    after = run(data)[0]
    assert after['publisher_status'] == 'cancelled' and before['publisher_status'] == 'scheduled'
    for key in ('id', 'event_url', 'starts_at', 'ends_at', 'venue_address', 'details_evidence_url'):
        assert after[key] == before[key]
    assert after['description'] == before['description']


def test_explicit_ics_cancellation_is_not_lost_to_generic_scheduled_metadata():
    data = bundle()
    data[ics_url()] = data[ics_url()].replace('BEGIN:VEVENT\n', 'BEGIN:VEVENT\nSTATUS:CANCELLED\n')
    rows = run(data)
    assert rows[1]['id'] == 'e.4800.1464252' and rows[1]['publisher_status'] == 'cancelled'


def test_conflicting_explicit_negative_statuses_are_held(capsys):
    data = bundle()
    data[detail_url()] = meta_change(data[detail_url()], eventStatus='https://schema.org/EventPostponed')
    data[ics_url()] = data[ics_url()].replace('BEGIN:VEVENT\n', 'BEGIN:VEVENT\nSTATUS:CANCELLED\n')
    assert [r['id'] for r in run(data)] == ['e.4800.1637639']
    assert 'publisher_status_conflict' in capsys.readouterr().err


def test_exact_ics_cancellation_survives_removed_venue_and_end():
    data = bundle(['customer'])
    before = run(data)[0]
    # The generic EventScheduled JSON-LD template may remain unchanged. The
    # exact linked ICS explicitly cancels this same UID/URL/start occurrence.
    data[detail_url()] = meta_change(data[detail_url()], location=None)
    data[ics_url()] = data[ics_url()].replace('BEGIN:VEVENT\n', 'BEGIN:VEVENT\nSTATUS:CANCELLED\n') \
        .replace('DTEND;TZID=America/New_York:20261204T140000\n', '') \
        .replace('LOCATION:710 W. Danville St South Hill VA 23970\n', '')
    after = run(data)[0]
    for key in ('id', 'starts_at', 'event_url', 'details_evidence_url'):
        assert after[key] == before[key]
    assert after['publisher_status'] == 'cancelled' and after['ends_at'] is None
    assert after['venue_address'] == after['venue_city'] == after['venue_name'] == ''
    assert after['lat'] is None and after['lng'] is None


def test_ongoing_event_retained_until_advertised_end(monkeypatch):
    freeze(monkeypatch, datetime(2026, 12, 4, 18, 45, tzinfo=timezone.utc))
    assert len(run(bundle(['customer']))) == 1
    freeze(monkeypatch, datetime(2026, 12, 4, 19, tzinfo=timezone.utc))
    assert run(bundle(['customer'])) == []


def test_original_native_categories_and_bounded_real_description_survive():
    data = bundle(['customer'])
    data[ics_url()] = data[ics_url()].replace('BEGIN:VEVENT\n', 'BEGIN:VEVENT\nCATEGORIES:Community Events,Food\n')
    row = run(data)[0]
    assert row['publisher_categories'] == ['Community Events', 'Food']
    assert row['category'] == 'Community Events, Food'
    assert 0 < len(row['description']) <= 2000 and '<' not in row['description']
    assert row['publisher_details'] == {} and 'image_url' not in row


def test_required_detail_fetch_failure_aborts_whole_snapshot():
    data = bundle()
    def fetch(url, accept):
        if url == ics_url():
            raise TimeoutError('publisher unavailable')
        return data[url]
    with pytest.raises(TimeoutError):
        chamber.collect(SOURCE, fetch)


@pytest.mark.parametrize('field,value', [('source_key', 'other'), ('feed_url', chamber.CALENDAR + '?page=2'),
                                        ('kind', 'json'), ('platform_adapter', 'ical'), ('timezone', 'UTC')])
def test_source_scope_is_validated_before_fetch(field, value):
    calls = []
    with pytest.raises(ValueError, match='unregistered_south_hill_chamber_source'):
        chamber.collect({**SOURCE, field: value}, lambda *args: calls.append(args))
    assert calls == []


def test_deadline_checked_after_fetch_before_parsing_success(monkeypatch):
    ticks = iter([0, 0, 31])
    monkeypatch.setattr(chamber, 'monotonic', lambda: next(ticks))
    with pytest.raises(ValueError, match='collection_deadline'):
        chamber.collect(SOURCE, lambda *args: listing([]))
