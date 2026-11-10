from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from roomquest import legistar, preview_worker

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

    for module in (legistar, preview_worker):
        monkeypatch.setattr(module, 'datetime', Frozen)
        monkeypatch.setattr(module, 'monotonic', lambda: 100.0)


def data(client='richmondva'):
    return json.loads((FIXTURES / f'{client}_legistar.json').read_text())


@pytest.mark.parametrize('key,client,count', [
    ('richmond_va_legistar', 'richmondva', 13),
    ('alexandria_va_legistar', 'alexandria', 5),
])
def test_captured_meetings_keep_publisher_identity_timezone_and_unknown_end(key, client, count):
    rows, held = legistar.parse_page(data(client), legistar.source_payload(key), now=NOW)
    assert len(rows) == count and held == 0
    assert len({row['id'] for row in rows}) == count
    assert all(row['ends_at'] is None for row in rows)
    assert all(row['lat'] is None and row['lng'] is None for row in rows)
    assert all(row['civic']['time_precision'] == 'timed' for row in rows)
    assert rows[0]['civic']['valid_until'] == (datetime.fromisoformat(rows[0]['starts_at']) +
                                              timedelta(hours=3)).isoformat()
    assert rows[0]['starts_at'].endswith('+00:00')
    assert rows[0]['event_url'].startswith(f'https://{client}.legistar.com/MeetingDetail.aspx?')


def test_only_exact_reviewed_richmond_room_gets_its_documented_address():
    rows, _ = legistar.parse_page(data(), legistar.source_payload('richmond_va_legistar'))
    council = next(row for row in rows if row['venue_name'] == 'Council Chamber, 2nd Floor - City Hall')
    assert council['venue_address'] == '900 E. Broad Street, Richmond, VA 23219'
    different_room = next(row for row in rows if row['venue_name'].startswith('5th Floor'))
    assert different_room['venue_address'] == different_room['venue_name']
    assert different_room['venue_city'] == ''


def test_reschedule_keeps_id_and_explicit_cancellation_can_update_past_occurrence():
    original = data()[0]
    changed = deepcopy(original)
    changed['EventTime'] = '5:00 PM'
    source = legistar.source_payload('richmond_va_legistar')
    first, _ = legistar.parse_page([original], source)
    second, _ = legistar.parse_page([changed], source)
    assert first[0]['id'] == second[0]['id']
    assert first[0]['starts_at'] != second[0]['starts_at']
    changed.update(EventDate='2026-11-08T00:00:00', EventAgendaStatusName='Cancelled', EventLocation=None)
    cancelled, held = legistar.parse_page([changed], source)
    assert held == 0 and cancelled[0]['publisher_status'] == 'cancelled'
    assert cancelled[0]['venue_address'] == ''


@pytest.mark.parametrize('time_value', [None, '', 'TBD', 'Immediately following', '13:00 PM'])
def test_unknown_meeting_time_is_held_without_becoming_all_day(time_value):
    item = data()[0]
    item['EventTime'] = time_value
    rows, held = legistar.parse_page([item], legistar.source_payload('richmond_va_legistar'))
    assert rows == [] and held == 1


def test_ambiguous_local_wall_time_is_held():
    item = data()[0]
    item.update(EventDate='2026-11-01T00:00:00', EventTime='1:30 AM')
    rows, held = legistar.parse_page([item], legistar.source_payload('richmond_va_legistar'),
                                    now=datetime(2026, 10, 31, tzinfo=timezone.utc))
    assert rows == [] and held == 1


def test_collector_uses_bounded_odata_and_never_follows_response_urls():
    source = legistar.source_payload('richmond_va_legistar')
    calls = []

    def fetch(url, accept):
        calls.append((url, accept))
        return json.dumps(data())

    rows = legistar.collect(source, fetch, deadline_at=125, now=NOW)
    assert len(rows) == 13 and len(calls) == 1
    parsed = urlsplit(calls[0][0])
    params = parse_qs(parsed.query)
    assert parsed.netloc == legistar.HOST and parsed.path == '/v1/richmondva/events'
    assert params['$top'] == ['100'] and params['$skip'] == ['0']
    assert '2026-11-02' in params['$filter'][0] and '2027-01-09' in params['$filter'][0]
    assert calls[0][1] == 'application/json'


def test_repeated_page_is_a_failed_snapshot(monkeypatch):
    monkeypatch.setattr(legistar, 'PAGE_SIZE', 2)
    with pytest.raises(ValueError, match='legistar_pagination_repeated'):
        legistar.collect(legistar.source_payload('richmond_va_legistar'),
                         lambda *_: json.dumps(data()[:2]), deadline_at=125)


def test_full_final_page_is_not_silently_called_complete(monkeypatch):
    monkeypatch.setattr(legistar, 'PAGE_SIZE', 2)
    monkeypatch.setattr(legistar, 'MAX_PAGES', 1)
    with pytest.raises(ValueError, match='legistar_pagination_limit'):
        legistar.collect(legistar.source_payload('richmond_va_legistar'), lambda *_: json.dumps(data()[:2]))


@pytest.mark.parametrize('payload', ['{}', '{"Message":"Unauthorized"}', 'null', '<html>Sign in</html>'])
def test_error_payload_never_becomes_healthy_empty(payload):
    with pytest.raises(ValueError, match='invalid_legistar_payload'):
        legistar.collect(legistar.source_payload('richmond_va_legistar'), lambda *_: payload)


@pytest.mark.parametrize('field,value', [
    ('feed_url', 'https://webapi.legistar.com/v1/unreviewed/events'),
    ('timezone', 'UTC'), ('kind', 'html'), ('platform_adapter', 'html'),
])
def test_changed_source_tuple_is_rejected_before_network(field, value):
    source = legistar.source_payload('richmond_va_legistar')
    source[field] = value
    with pytest.raises(ValueError, match='unregistered_legistar_source'):
        legistar.collect(source, lambda *_: pytest.fail('Network must not be used'))


def test_cross_publisher_event_url_is_held():
    item = data()[0]
    item['EventInSiteURL'] = 'https://evil.example/MeetingDetail.aspx?LEGID=5167'
    rows, held = legistar.parse_page([item], legistar.source_payload('richmond_va_legistar'))
    assert rows == [] and held == 1


@pytest.mark.parametrize('field,value', [
    ('civic_contract_version', None), ('civic_contract_version', 2),
    ('civic_contract_version', True), ('civic_contract_version', '1'),
    ('civic_jurisdiction_id', None), ('civic_jurisdiction_id', 'us-va-alexandria-city'),
])
def test_new_adapter_requires_server_civic_capability_before_fetch(field, value):
    source = legistar.source_payload('richmond_va_legistar')
    if value is None:
        source.pop(field)
    else:
        source[field] = value
    with pytest.raises(ValueError, match='unregistered_legistar_source'):
        legistar.collect(source, lambda *_: pytest.fail('Network must not be used'))


def test_claim_display_name_is_not_part_of_stable_source_identity():
    source = {**legistar.source_payload('richmond_va_legistar'),
              'action': 'collect', 'civic_jurisdiction_name': 'City of Richmond'}
    rows = legistar.collect(source, lambda *_: json.dumps(data()))
    assert len(rows) == 13
    assert all(row['civic']['jurisdiction_id'] == 'us-va-richmond-city' for row in rows)


def test_reusable_parser_uses_each_reviewed_clients_own_timezone(monkeypatch):
    monkeypatch.setitem(legistar.SOURCES, 'west_coast_test', {
        'url': 'https://webapi.legistar.com/v1/test-west/events', 'client': 'test-west',
        'jurisdiction_id': 'test-west', 'jurisdiction_name': 'Test only',
        'timezone': 'America/Los_Angeles',
    })
    item = data()[0]
    item['EventInSiteURL'] = item['EventInSiteURL'].replace('richmondva.', 'test-west.')
    rows, held = legistar.parse_page([item], legistar.source_payload('west_coast_test'))
    assert held == 0 and rows[0]['starts_at'] == '2026-11-10T00:00:00+00:00'
    assert rows[0]['civic']['timezone'] == 'America/Los_Angeles'
