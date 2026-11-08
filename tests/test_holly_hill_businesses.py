from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from unittest.mock import Mock

from bs4 import BeautifulSoup
import pytest

from roomquest import holly_hill_businesses as businesses, preview_worker, publisher_evidence

FIXTURES = Path(__file__).parent / 'fixtures/holly_hill_businesses'
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


def freeze(monkeypatch, current):
    actual = datetime

    class Meta(type):
        def __instancecheck__(cls, value):
            return isinstance(value, actual)

    class Clock(actual, metaclass=Meta):
        @classmethod
        def now(cls, tz=None):
            return current.astimezone(tz) if tz else current.replace(tzinfo=None)

    monkeypatch.setattr(preview_worker, 'datetime', Clock)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    freeze(monkeypatch, NOW)


def source(key=businesses.D_AND_G):
    return {'source_key': key, 'feed_url': businesses.SOURCES[key], 'kind': 'html',
            'platform_adapter': 'html', 'timezone': businesses.TIMEZONE}


def fixture(name):
    return (FIXTURES / name).read_text()


def bundle():
    manifest = json.loads(fixture('manifest.json'))
    return {item['url']: fixture(item['file']) for item in manifest}


def run(data=None, *, key=businesses.D_AND_G, now=NOW, diagnostics=None, calls=None):
    data = bundle() if data is None else data

    def fetch(url, accept):
        if calls is not None:
            calls.append((url, accept))
        return data[url]

    return businesses.collect(source(key), fetch, now=now, diagnostics=diagnostics)


def outside_change(change):
    soup = BeautifulSoup(fixture('outside_inn.html'), 'html.parser')
    script = soup.select_one('script[type="application/ld+json"]')
    data = json.loads(script.get_text())
    change(data)
    script.string = json.dumps(data)
    return str(soup)


def public_outside(data):
    yoga = data['@graph'][2]
    yoga['startDate'] = '2026-12-05T09:00:00-05:00'
    return yoga


def test_actual_dated_product_preserves_schedule_price_unit_and_venue():
    diagnostics, calls = {}, []
    rows = run(diagnostics=diagnostics, calls=calls)
    assert len(rows) == 1
    row = rows[0]
    assert row['id'] == 'd_and_g_outdoors:2781'
    assert row['starts_at'] == '2026-12-12T14:00:00+00:00'
    assert row['ends_at'] == '2026-12-12T17:00:00+00:00'
    assert 'December 12, 2026' in row['title']
    assert row['venue_address'] == '3402 Bass Drive, Holly Hill, SC 29059'
    assert row['venue_city'] == 'Holly Hill'
    assert row['publisher_details']['cost'] == '$550.00 per station. Each station accommodates a maximum of four shooters.'
    assert 'Hunting License OR Preserve Permit Required!' in row['description']
    assert 'image_url' not in row and row['lat'] is None and row['lng'] is None
    assert row['details_evidence_url'] == row['event_url']
    assert row['publisher_status'] == 'scheduled'
    assert diagnostics == {'outside_window': 5, 'catalogue_products': 6}
    assert calls == [(businesses.SOURCES[businesses.D_AND_G], 'text/html'), (row['event_url'], 'text/html')]


def test_roll_forward_discovers_distinct_morning_and_afternoon_sessions(monkeypatch):
    current = datetime(2026, 12, 1, 12, tzinfo=timezone.utc)
    freeze(monkeypatch, current)
    rows = run(now=current)
    january = [row for row in rows if row['starts_at'].startswith('2027-01-09')]
    assert len(rows) == 3 and len(january) == 2
    assert {row['id'] for row in january} == {'d_and_g_outdoors:2785', 'd_and_g_outdoors:2789'}
    assert {row['starts_at'] for row in january} == {'2027-01-09T14:00:00+00:00', '2027-01-09T18:00:00+00:00'}
    assert {row['ends_at'] for row in january} == {'2027-01-09T17:00:00+00:00', '2027-01-09T21:00:00+00:00'}


def test_sku_is_not_a_schedule_and_woocommerce_virtual_is_not_online():
    data = bundle()
    url = businesses.SOURCES[businesses.D_AND_G] + 'december-12-2026-200-birds/'
    data[url] = data[url].replace('2026-12-13', 'inventory-batch-999')
    row = run(data)[0]
    assert row['starts_at'].startswith('2026-12-12')
    assert row['attendance_mode'] == 'in_person'


@pytest.mark.parametrize('old,new,reason', [
    ('9:00am-12:00pm', 'time to be announced', 'publisher_time_unresolved'),
    ('9:00am-12:00pm', '9:00am-1:00pm', 'publisher_time_conflict'),
    ('3402 Bass Drive', '3403 Bass Drive', 'publisher_venue_unreviewed'),
    ('include a BBQ buffet lunch.', 'include a BBQ buffet lunch. Moved to another venue.', 'publisher_venue_unreviewed'),
    ('include a BBQ buffet lunch.', 'include a BBQ buffet lunch. Location: Another field.', 'publisher_venue_unreviewed'),
    ('include a BBQ buffet lunch.', 'include a BBQ buffet lunch. May be cancelled in bad weather.', 'publisher_status_unresolved'),
])
def test_incomplete_or_conflicting_product_facts_are_held(old, new, reason):
    data, diagnostics = bundle(), {}
    url = businesses.SOURCES[businesses.D_AND_G] + 'december-12-2026-200-birds/'
    data[url] = data[url].replace(old, new)
    with pytest.raises(ValueError, match='evidence_unavailable'):
        run(data, diagnostics=diagnostics)
    assert diagnostics['held'][0]['reason'] == reason


def test_listing_and_detail_dates_must_agree():
    data = bundle()
    url = businesses.SOURCES[businesses.D_AND_G] + 'december-12-2026-200-birds/'
    data[url] = data[url].replace('December 12, 2026', 'December 13, 2026')
    with pytest.raises(ValueError, match='identity_unverified'):
        run(data)


def test_unknown_listing_url_cannot_be_fetched():
    data, calls = bundle(), []
    url = businesses.SOURCES[businesses.D_AND_G]
    data[url] = data[url].replace('https://dandgoutdoors.com/hunt/december-12-2026-200-birds/',
                                  'https://example.com/hunt/december-12-2026-200-birds/')
    with pytest.raises(ValueError, match='identity_unverified'):
        run(data, calls=calls)
    assert calls == [(url, 'text/html')]


def test_pagination_and_catalogue_loss_fail_instead_of_partial_success():
    data = bundle()
    url = businesses.SOURCES[businesses.D_AND_G]
    data[url] = data[url].replace('</main>', '<nav class="woocommerce-pagination"></nav></main>')
    with pytest.raises(ValueError, match='pagination'):
        run(data)
    data = bundle()
    data[url] = data[url].replace('Showing all 6 results', 'Showing all 7 results')
    with pytest.raises(ValueError, match='count_unverified'):
        run(data)


def test_exact_status_retracts_existing_product_with_same_identity():
    data = bundle()
    url = businesses.SOURCES[businesses.D_AND_G] + 'december-12-2026-200-birds/'
    data[url] = data[url].replace('Price is per station', 'Cancelled. Price is per station')
    row = run(data)[0]
    assert row['publisher_status'] == 'cancelled'
    assert row['id'] == 'd_and_g_outdoors:2781'
    assert row['starts_at'] == '2026-12-12T14:00:00+00:00'


def test_outside_inn_live_snapshot_is_empty_without_generated_recurrences():
    calls, diagnostics = [], {}
    assert run(key=businesses.OUTSIDE_INN, calls=calls, diagnostics=diagnostics) == []
    assert diagnostics == {'outside_window': 4, 'jsonld_events': 4}
    assert calls == [(businesses.SOURCES[businesses.OUTSIDE_INN], 'text/html')]


def test_outside_inn_new_explicit_public_occurrence_ignores_global_geo_and_images():
    payload = outside_change(public_outside)
    rows = run({businesses.SOURCES[businesses.OUTSIDE_INN]: payload}, key=businesses.OUTSIDE_INN)
    assert len(rows) == 1
    row = rows[0]
    assert row['starts_at'] == '2026-12-05T14:00:00+00:00'
    assert row['ends_at'] is None
    assert row['venue_address'] == '1074 Woolbright Rd, Santee, SC, 29142'
    assert row['lat'] is None and row['lng'] is None and 'image_url' not in row
    assert row['event_url'] == businesses.SOURCES[businesses.OUTSIDE_INN]
    assert row['publisher_details']['cost'] == '$20 per person'


@pytest.mark.parametrize('change,reason', [
    (lambda e: e.update(startDate='2026-12-05'), 'publisher_time_unresolved'),
    (lambda e: e.update(description='Live music at the campground.'), 'publisher_public_access_unresolved'),
    (lambda e: e['location']['address'].update(streetAddress='Another property'), 'publisher_venue_unreviewed'),
    (lambda e: e.update(url='https://unreviewed.example/event'), 'publisher_event_link_unreviewed'),
])
def test_outside_inn_missing_event_facts_are_not_inferred(change, reason):
    def edit(data):
        change(public_outside(data))
    payload = outside_change(edit)
    diagnostics = {}
    with pytest.raises(ValueError, match='evidence_unavailable'):
        run({businesses.SOURCES[businesses.OUTSIDE_INN]: payload}, key=businesses.OUTSIDE_INN,
            diagnostics=diagnostics)
    assert diagnostics['held'][0]['reason'] == reason


@pytest.mark.parametrize('description', [
    'For overnight guests. Guests only, free with stay.',
    'Open to all overnight guests. Free with any overnight stay.',
])
def test_future_guest_only_activity_is_excluded(description):
    def edit(data):
        public_outside(data)['description'] = description
    diagnostics = {}
    assert run({businesses.SOURCES[businesses.OUTSIDE_INN]: outside_change(edit)},
               key=businesses.OUTSIDE_INN, diagnostics=diagnostics) == []
    assert diagnostics['excluded'][0]['reason'] == 'nonpublic_or_appointment_activity'


def test_duplicate_jsonld_conflict_does_not_silently_pick_one():
    def edit(data):
        yoga = public_outside(data)
        other = deepcopy(yoga)
        other['description'] += ' Additional publisher information.'
        data['@graph'].append(other)
    with pytest.raises(ValueError, match='conflicting_occurrence'):
        run({businesses.SOURCES[businesses.OUTSIDE_INN]: outside_change(edit)}, key=businesses.OUTSIDE_INN)


@pytest.mark.parametrize('field,value', [
    ('source_key', 'unrelated'), ('feed_url', 'https://dandgoutdoors.com/'),
    ('kind', 'json'), ('platform_adapter', 'wordpress'), ('timezone', 'UTC'),
])
def test_source_allowlist_precedes_fetch(field, value):
    fetch = Mock()
    with pytest.raises(ValueError, match='unregistered'):
        businesses.collect(dict(source(), **{field: value}), fetch)
    fetch.assert_not_called()


def test_document_and_deadline_limits(monkeypatch):
    with pytest.raises(ValueError, match='document_limit'):
        businesses.parse_outside_inn('x' * (businesses.MAX_DOCUMENT + 1))
    clock = iter([0, 0, 31])
    monkeypatch.setattr(businesses, 'monotonic', lambda: next(clock))
    fetch = Mock(return_value=fixture('d_and_g_listing.html'))
    with pytest.raises(ValueError, match='collection_deadline'):
        businesses.collect(source(), fetch, now=NOW)
    assert fetch.call_count == 1


def test_unrecognized_page_cannot_be_successful_empty():
    with pytest.raises(ValueError, match='structure_unverified'):
        run({businesses.SOURCES[businesses.OUTSIDE_INN]: '<html>Unavailable</html>'}, key=businesses.OUTSIDE_INN)


def test_evidence_family_is_registered_for_both_publishers():
    for key, url in [(businesses.D_AND_G, businesses.SOURCES[businesses.D_AND_G] + 'december-12-2026-200-birds/'),
                     (businesses.OUTSIDE_INN, businesses.SOURCES[businesses.OUTSIDE_INN])]:
        assert publisher_evidence.family(key, url)
        assert publisher_evidence.family(key, 'https://unrelated.example/event') is None
