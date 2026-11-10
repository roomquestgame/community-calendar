from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from roomquest import preview_worker, virginia_civic as civic

FIXTURES = Path(__file__).parent / 'fixtures' / 'civic'
NOW = datetime(2026, 11, 9, 10, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    class ClockMeta(type):
        def __instancecheck__(cls, value):
            return isinstance(value, datetime)

    class Frozen(datetime, metaclass=ClockMeta):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    for module in (civic, preview_worker):
        monkeypatch.setattr(module, 'datetime', Frozen)
        monkeypatch.setattr(module, 'monotonic', lambda: 100.0)


def fixture(name):
    return (FIXTURES / name).read_text()


def test_captured_commonwealth_window_has_complete_factual_records():
    rows = civic.parse_commonwealth(fixture('commonwealth.html'), now=NOW)
    assert len(rows) == 69
    assert sum('starts_on' in row for row in rows) == 0
    assert sum(row['publisher_status'] == 'cancelled' for row in rows) == 3
    assert all(row['lat'] is None and row['lng'] is None for row in rows)
    assert len({row['id'] for row in rows}) == 69


def test_actual_meeting_location_wins_over_wrong_map_city_and_contact_addresses():
    rows = civic.parse_commonwealth(fixture('commonwealth.html'))
    row = next(row for row in rows if row['id'] == 'commonwealth:78475')
    assert '1601 Orange Road Culpeper, VA 22701' in row['venue_address']
    assert 'Richmond' not in row['venue_address']
    assert 'November 30, 2026' in row['description']
    assert '1221 East Broad Street, Richmond' in row['description']
    assert row['ends_at'] is None


def test_all_day_board_meetings_with_unknown_time_are_held(caplog):
    rows = civic.parse_commonwealth(fixture('commonwealth.html'))
    assert all(row['id'] != 'commonwealth:75384' for row in rows)
    assert caplog.text.count('commonwealth_meeting_time_unresolved') == 3


def test_explicit_nonmeeting_date_window_has_exclusive_end_and_permitted_notice_kind():
    # Synthetic format case: a publisher-marked all-day comment window, not
    # one of the three captured meetings with missing structured times.
    payload = fixture('commonwealth.html').replace('VDDHH Advisory Board Meeting', 'Public comment window')
    soup = BeautifulSoup(payload, 'html.parser')
    node = soup.find('a', href='/Event/Details/75384').find_parent('li')
    node.select_one('.schedule__event__category').string = 'Public Comment'
    row = next(row for row in civic.parse_commonwealth(str(soup)) if row['id'] == 'commonwealth:75384')
    assert row['starts_on'] == '2026-11-10' and row['ends_on'] == '2026-11-11'
    assert row['civic']['time_precision'] == 'date'
    assert row['civic']['kind'] == 'window'
    assert row['civic']['timezone'] == civic.ZONE
    assert row['starts_at'] == '2026-11-10T05:00:00+00:00'  # Transport/query bound only.
    assert row['civic']['source_url'] == row['event_url']
    assert row['civic']['valid_until'] == row['ends_at']


def test_literal_hash_room_number_in_publisher_template_is_not_lost():
    row = next(row for row in civic.parse_commonwealth(fixture('commonwealth.html'))
               if row['id'] == 'commonwealth:79062')
    assert row['venue_address'] == '209 W Criser Rd #300 Front Royal, VA 22630'
    assert row['ends_at'] == '2026-11-10T17:00:00+00:00'


def test_commonwealth_only_fetches_its_registered_page_not_google_or_detail_pages():
    calls = []

    def fetch(url, accept):
        calls.append((url, accept))
        return fixture('commonwealth.html')

    rows = civic.collect(civic.source_payload(civic.COMMONWEALTH), fetch, now=NOW, deadline_at=125)
    assert len(rows) == 69
    assert calls == [('https://commonwealthcalendar.virginia.gov/', 'text/html')]


def test_stale_or_noncalendar_page_is_a_failure():
    with pytest.raises(ValueError, match='commonwealth_window_stale'):
        civic.parse_commonwealth(fixture('commonwealth.html'), now=datetime(2026, 12, 1, tzinfo=timezone.utc))
    with pytest.raises(ValueError, match='commonwealth_window_missing'):
        civic.parse_commonwealth('<html>Access denied</html>')


def test_conflicting_visible_time_is_held_while_good_records_survive(caplog):
    soup = BeautifulSoup(fixture('commonwealth.html'), 'html.parser')
    node = soup.find('a', href='/Event/Details/78475').find_parent('li')
    node.select('.schedule__event__time')[1].string = '3:00 PM'
    rows = civic.parse_commonwealth(str(soup))
    assert len(rows) == 68 and all(row['id'] != 'commonwealth:78475' for row in rows)
    assert 'commonwealth_event_time_conflict' in caplog.text


def test_duplicate_commonwealth_identity_rejects_snapshot():
    soup = BeautifulSoup(fixture('commonwealth.html'), 'html.parser')
    soup.ul.append(BeautifulSoup(str(soup.select_one('li')), 'html.parser'))
    with pytest.raises(ValueError, match='commonwealth_duplicate_identity'):
        civic.parse_commonwealth(str(soup))


def test_dmv_keeps_published_hours_lunch_and_appointment_conditions():
    rows = civic.parse_dmv(fixture('dmv_connect.html'))
    assert len(rows) == 10
    salem = next(row for row in rows if row['venue_name'] == 'Salem Civic Center' and row['starts_at'].startswith('2026-11-10'))
    assert salem['starts_at'] == '2026-11-10T14:00:00+00:00'
    assert salem['ends_at'] == '2026-11-10T21:00:00+00:00'
    assert '12:30 p.m. to 1:30 p.m.' in salem['description']
    assert 'no appointment' in salem['description']
    assert salem['civic']['kind'] == 'service'
    assert salem['civic']['valid_until'] == salem['ends_at']
    assert salem['venue_address'] == '1000 Roanoke Boulevard, Salem, VA 24153'


def test_dmv_first_page_never_requests_robots_excluded_pagination():
    calls = []
    rows = civic.collect(civic.source_payload(civic.DMV),
                         lambda url, accept: calls.append(url) or fixture('dmv_connect.html'))
    assert len(rows) == 10
    assert calls == ['https://www.dmv.virginia.gov/locations/dmv-connects']
    assert civic.SOURCES[civic.DMV]['scope'] == 'publisher_first_page'


def test_dmv_unknown_hours_are_not_guessed(caplog):
    soup = BeautifulSoup(fixture('dmv_connect.html'), 'html.parser')
    soup.select_one('.c-connect-teaser__info').string = 'Open to the public. Hours to be announced.'
    rows = civic.parse_dmv(str(soup))
    assert len(rows) == 9 and 'dmv_connect_hours_unresolved' in caplog.text


def test_dmv_changed_page_shape_is_not_a_complete_snapshot():
    payload = fixture('dmv_connect.html').replace('Displaying 1 - 10 of 15', 'Displaying 11 - 20 of 25')
    with pytest.raises(ValueError, match='dmv_connect_page_scope_changed'):
        civic.parse_dmv(payload)


@pytest.mark.parametrize('key', [civic.COMMONWEALTH, civic.DMV])
@pytest.mark.parametrize('field,value', [('timezone', 'UTC'), ('kind', 'json'), ('platform_adapter', 'wordpress'),
                                        ('feed_url', 'https://example.com/')])
def test_source_tuple_change_fails_before_fetch(key, field, value):
    source = civic.source_payload(key)
    source[field] = value
    with pytest.raises(ValueError, match='unregistered_virginia_civic_source'):
        civic.collect(source, lambda *_: pytest.fail('Network must not be used'))


@pytest.mark.parametrize('key', [civic.COMMONWEALTH, civic.DMV])
@pytest.mark.parametrize('field,value', [
    ('civic_contract_version', None), ('civic_contract_version', 2),
    ('civic_contract_version', True), ('civic_contract_version', '1'),
    ('civic_jurisdiction_id', None), ('civic_jurisdiction_id', 'us-va-richmond-city'),
])
def test_new_civic_routes_require_server_capability_before_fetch(key, field, value):
    source = civic.source_payload(key)
    if value is None:
        source.pop(field)
    else:
        source[field] = value
    with pytest.raises(ValueError, match='unregistered_virginia_civic_source'):
        civic.collect(source, lambda *_: pytest.fail('Network must not be used'))


@pytest.mark.parametrize('key,name,count', [
    (civic.COMMONWEALTH, 'commonwealth.html', 69), (civic.DMV, 'dmv_connect.html', 10),
])
def test_claim_display_name_does_not_override_stable_jurisdiction(key, name, count):
    source = {**civic.source_payload(key), 'action': 'collect',
              'civic_jurisdiction_name': 'Commonwealth of Virginia'}
    rows = civic.collect(source, lambda *_: fixture(name))
    assert len(rows) == count
    assert all(row['civic']['jurisdiction_id'] == 'us-va' for row in rows)
