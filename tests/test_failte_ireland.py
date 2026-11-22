"""Official historical schema and explicit synthetic upcoming CSV occurrences."""
from copy import deepcopy
import csv
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import Mock

import pytest

from roomquest import failte_ireland as failte, feed_registration, preview_worker
from roomquest import registered_native_content as native

FIXTURES = Path(__file__).parent / 'fixtures' / 'failte_ireland'


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    value = [datetime.fromisoformat('2026-11-22T22:00:00+00:00')]

    class Meta(type):
        def __instancecheck__(cls, candidate):
            return isinstance(candidate, datetime)

    class Clock(datetime, metaclass=Meta):
        @classmethod
        def now(cls, tz=None):
            return value[0].astimezone(tz) if tz else value[0].replace(tzinfo=None)

    monkeypatch.setattr(preview_worker, 'datetime', Clock)
    return lambda instant: value.__setitem__(0, datetime.fromisoformat(instant))


def item(**changes):
    data = {key: '' for key in failte.FIELDS}
    data.update({'Name': 'Published winter concert', 'Event Type': 'Event',
                 'Description': '<p>The full native description, with a comma.</p>\n<p>A second paragraph.</p>',
                 'Contact URL': 'https://venue.example.ie/events/winter-concert',
                 'Booking URL': 'https://tickets.example.ie/book/winter-concert',
                 'Venue Name': 'Published Concert Hall', 'Address': '12 Example Street, Dublin',
                 'County': 'Dublin', 'Latitude': '53.3498', 'Longitude': '-6.2603',
                 'Is Free To Visit': 'No', 'Price': '12', 'Start Date': '2026-12-05T00:00:00',
                 'End Date': '2026-12-05T00:00:00', 'Start Time': '19:00', 'End Time': '21:00',
                 'Recurring Dates': 'No'})
    data.update(changes)
    return data


def payload(rows, *, fields=failte.FIELDS):
    buffer = StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator='\r\n', extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def parse(rows, **kwargs):
    return failte.parse(payload(rows), failte.registration_source(), **kwargs)


def test_explicit_csv_facts_keep_full_native_description_and_exact_link_provenance():
    text = '<p>' + 'Full publisher narrative. ' * 150 + '</p>\n<p>Final paragraph.</p>'
    [row] = parse([item(**{'Description': text})])
    assert row['starts_at'] == '2026-12-05T19:00:00+00:00'
    assert row['ends_at'] == '2026-12-05T21:00:00+00:00'
    assert row['timezone'] == 'Europe/Dublin'
    assert row['venue_address'] == '12 Example Street, Dublin, Ireland'
    assert row['venue_city'] == ''  # County is not a supplied town/city.
    assert row['lat'] == 53.3498 and row['lng'] == -6.2603
    assert len(row['description']) > 2000 and row['description'].endswith('Final paragraph.')
    proof = row['registered_native_content']
    assert proof['evidence_url'] == failte.URL and proof['extraction'] == failte.VERSION
    assert proof['description_field'] == 'Description'
    assert proof['event_url_field'] == 'Contact URL'
    assert proof['image_field'] is None and 'image_url' not in row
    native.validate_record(row, failte.registration_source())


def test_recurring_flag_does_not_generate_unpublished_dates_or_repeat_csv_rows():
    a = item(**{'Recurring Dates': 'Yes'})
    b = item(**{'Recurring Dates': 'Yes', 'Start Date': '2026-12-12T00:00:00',
                'End Date': '2026-12-12T00:00:00'})
    rows = parse([a, a, b])
    assert len(rows) == 2 and len({row['id'] for row in rows}) == 2
    assert [row['starts_at'][:10] for row in rows] == ['2026-12-05', '2026-12-12']
    assert len(parse([a])) == 1


def test_dublin_timezone_uses_event_date_not_a_current_or_fixed_offset(clock):
    clock('2027-06-01T00:00:00+00:00')
    [row] = parse([item(**{'Start Date': '2027-07-01T00:00:00', 'End Date': '2027-07-01T00:00:00',
                          'Start Time': '14:00', 'End Time': '16:00'})])
    assert row['starts_at'] == '2027-07-01T13:00:00+00:00'
    assert row['ends_at'] == '2027-07-01T15:00:00+00:00'


def test_missing_clocks_do_not_turn_date_midnight_into_event_time():
    diagnostics = {}
    assert parse([item(**{'Start Time': '', 'End Time': ''})], diagnostics=diagnostics) == []
    assert diagnostics['omitted'] == [{'csv_record': 1, 'reason': 'missing_start_time'}]
    [row] = parse([item(**{'End Time': ''})])
    assert row['ends_at'] is None
    diagnostics = {}
    [row] = parse([item(**{'End Time': '19:00'})], diagnostics=diagnostics)
    assert row['ends_at'] is None
    assert diagnostics['warnings'][0]['reason'] == 'equal_end_time_omitted'


def test_unknown_multiday_envelope_is_not_a_continuous_event_or_daily_expansion():
    diagnostics = {}
    assert parse([item(**{'End Date': '2026-12-31T00:00:00', 'Recurring Dates': 'Yes'})],
                 diagnostics=diagnostics) == []
    assert diagnostics['omitted'][0]['reason'] == 'multi_day_schedule_unresolved'


def test_https_booking_fallback_is_explicit_and_http_is_never_rewritten():
    [row] = parse([item(**{'Contact URL': 'http://venue.example.ie/event'})])
    assert row['event_url'] == 'https://tickets.example.ie/book/winter-concert'
    assert row['registered_native_content']['event_url_field'] == 'Booking URL'
    diagnostics = {}
    assert parse([item(**{'Contact URL': 'http://venue.example.ie/event', 'Booking URL': ''})],
                 diagnostics=diagnostics) == []
    assert diagnostics['omitted'][0]['reason'] == 'no_public_https_event_url'


@pytest.mark.parametrize('county', ['Antrim', 'Down', 'Fermanagh', '', 'Northern Ireland'])
def test_uncertain_or_northern_ireland_county_is_not_asserted_as_republic_coverage(county):
    diagnostics = {}
    assert parse([item(**{'County': county})], diagnostics=diagnostics) == []
    assert diagnostics['omitted'][0]['reason'] == 'venue_or_jurisdiction_unresolved'


def test_missing_pin_can_remain_unresolved_but_bad_or_partial_pin_holds():
    [row] = parse([item(**{'Latitude': '', 'Longitude': ''})])
    assert row['lat'] is None and row['lng'] is None
    for updates in ({'Latitude': 'nan'}, {'Longitude': ''}, {'Latitude': '0', 'Longitude': '0'}):
        with pytest.raises(ValueError, match='failte_venue_geo_unverified'):
            parse([item(**updates)])


@pytest.mark.parametrize('updates,reason', [
    ({'End Time': '18:00'}, 'end_time_conflict'),
    ({'End Date': ''}, 'end_date_missing'),
    ({'Start Time': '25:00'}, 'time_unverified'),
    ({'Start Date': '2026-12-05T12:00:00'}, 'date_unverified'),
    ({'End Date': '2026-12-04T00:00:00'}, 'end_date_conflict'),
    ({'Recurring Dates': 'FREQ=DAILY'}, 'recurrence_field_unverified'),
])
def test_invalid_final_record_never_returns_an_earlier_valid_prefix(updates, reason):
    with pytest.raises(ValueError, match='failte_' + reason):
        parse([item(), item(**updates)])


def test_dst_ambiguity_and_nonexistence_remain_shared_normalizer_holds(clock):
    clock('2027-03-01T00:00:00+00:00')
    with pytest.raises(ValueError, match='timezone_nonexistent'):
        parse([item(**{'Start Date': '2027-03-28T00:00:00', 'End Date': '2027-03-28T00:00:00',
                       'Start Time': '01:30', 'End Time': ''})])
    clock('2027-10-01T00:00:00+00:00')
    with pytest.raises(ValueError, match='timezone_ambiguous'):
        parse([item(**{'Start Date': '2027-10-31T00:00:00', 'End Date': '2027-10-31T00:00:00',
                       'Start Time': '01:30', 'End Time': ''})])


def test_more_than_500_complete_occurrences_reach_normal_native_legacy_staging(monkeypatch):
    body = payload([item(**{'Name': 'Published event ' + str(i)}) for i in range(600)])
    fetch = Mock(return_value=body)
    database = Mock(side_effect=lambda operation, args, **kwargs:
                    len(args['p_events']) if operation == 'community_collector_record_staged_events' else True)
    monkeypatch.setattr(preview_worker, 'fetch_publisher', fetch)
    monkeypatch.setattr(preview_worker, 'supabase_rpc', database)
    monkeypatch.setattr(preview_worker, 'current_snapshot', lambda: None)
    with preview_worker.capture_publisher_pacing() as pacing:
        result = preview_worker._process_claimed_source_with_pacing(failte.registration_source(), pacing)
    assert result['complete'] == 1 and result['staged'] == 600
    assert fetch.call_count == 1
    assert fetch.call_args.args == (failte.URL, failte.ACCEPT)
    assert fetch.call_args.kwargs['allowed_hosts'] == (failte.HOST,)
    assert fetch.call_args.kwargs['respect_robots'] is True
    writes = [call.args[1] for call in database.call_args_list
              if call.args[0] == 'community_collector_record_staged_events']
    assert len(writes) == 30 and sum(len(v['p_events']) for v in writes) == 600
    assert all(v['p_registered_native_content_version'] == 1 for v in writes)
    operation, receipt = database.call_args_list[-1].args
    assert operation == 'community_collector_record_preview_v3'
    assert receipt['p_future_count'] == 600 and receipt['p_venue_count'] == 600
    assert receipt['p_error'] is None and receipt['p_parser_capability'] == native.VERSION


def test_stale_official_mirror_never_registers_as_current_events(monkeypatch):
    body = (FIXTURES / 'historical-schema.csv').read_text()
    diagnostics = {}
    assert failte.parse(body, failte.registration_source(), diagnostics=diagnostics) == []
    assert diagnostics['rows'] == 1589
    database = Mock(side_effect=[{'url': failte.URL}, True])
    monkeypatch.setattr(feed_registration, 'supabase_rpc', database)
    monkeypatch.setattr(feed_registration, 'fetch_publisher', Mock(return_value=body))
    assert feed_registration.register('ticket')['outcome'] == 'review'
    assert database.call_args.args[1]['p_reason'] == 'no_extractable_events'


def test_admin_registration_uses_exact_csv_receipt_and_only_one_guarded_fetch(monkeypatch):
    fetch = Mock(return_value=payload([item()]))
    database = Mock(side_effect=[{'url': failte.URL}, True])
    monkeypatch.setattr(feed_registration, 'supabase_rpc', database)
    monkeypatch.setattr(feed_registration, 'fetch_publisher', fetch)
    assert feed_registration.register('ticket')['outcome'] == 'verified'
    assert database.call_args.args[1] == {'p_ticket': 'ticket', 'p_outcome': 'verified',
                                        'p_endpoint': failte.URL, 'p_type': 'jsonld', 'p_reason': failte.VERSION}
    assert fetch.call_count == 1 and fetch.call_args.args == (failte.URL, failte.ACCEPT)
    assert fetch.call_args.kwargs['respect_robots'] is True
    assert fetch.call_args.kwargs['allowed_hosts'] == (failte.HOST,)


def test_quota_or_auth_denial_is_preserved_without_fallback_or_repeat(monkeypatch):
    fetch = Mock(side_effect=preview_worker.PreviewError('publisher_http_403'))
    database = Mock(side_effect=[{'url': failte.URL}, True])
    monkeypatch.setattr(feed_registration, 'supabase_rpc', database)
    monkeypatch.setattr(feed_registration, 'fetch_publisher', fetch)
    assert feed_registration.register('ticket')['outcome'] == 'disabled'
    assert database.call_args.args[1]['p_reason'] == 'publisher_http_403'
    assert fetch.call_count == 1


@pytest.mark.parametrize('field,value', [('feed_url', failte.URL + '?limit=1'),
                                       ('feed_url', 'https://data.gov.ie/dataset/events'),
                                       ('source_key', 'municipal_wrong'),
                                       ('registered_native_content_version', True),
                                       ('timezone', 'Europe/London')])
def test_source_aliases_and_invalid_capabilities_cannot_fetch(field, value):
    source = failte.registration_source()
    source[field] = value
    fetch = Mock()
    with pytest.raises(ValueError, match='failte_source_unregistered'):
        failte.collect(source, fetch)
    fetch.assert_not_called()


@pytest.mark.parametrize('mutation', ['url_field', 'extraction', 'evidence', 'date', 'venue', 'url', 'image'])
def test_native_proof_and_bound_occurrence_facts_cannot_be_swapped(mutation):
    [row] = parse([item()])
    row = deepcopy(row)
    proof = row['registered_native_content']
    if mutation == 'url_field': proof['event_url_field'] = 'Some URL'
    elif mutation == 'extraction': proof['extraction'] = 'registered_html_jsonld_v1'
    elif mutation == 'evidence': proof['evidence_url'] = row['event_url']
    elif mutation == 'date': row['starts_at'] = '2026-12-06T19:00:00+00:00'
    elif mutation == 'venue': row['venue_name'] = 'Another venue'
    elif mutation == 'url': row['event_url'] = 'https://other.example.ie/event'
    else: row['image_url'] = 'https://venue.example.ie/image.jpg'
    with pytest.raises(ValueError, match='failte_native_evidence_invalid'):
        native.validate_record(row, failte.registration_source())
    assert not native.media_claim({**failte.registration_source(), 'candidate_only': True,
                                   'extraction_url': failte.URL, 'event_url': row['event_url']})


def test_schema_byte_row_occurrence_and_description_bounds_hold_complete_capture(monkeypatch):
    with pytest.raises(ValueError, match='failte_csv_schema_unverified'):
        failte.parse(payload([item()], fields=failte.FIELDS[:-1]), failte.registration_source())
    with pytest.raises(ValueError, match='failte_csv_invalid'):
        failte.parse(payload([item()]) + '"unfinished', failte.registration_source())
    with pytest.raises(ValueError, match='registered_native_description_too_long'):
        parse([item(**{'Description': 'N' * 12001})])
    with pytest.raises(ValueError, match='failte_csv_payload_invalid'):
        failte.parse('N' * (failte.MAX_BYTES + 1), failte.registration_source())
    monkeypatch.setattr(failte, 'MAX_ROWS', 1)
    with pytest.raises(ValueError, match='failte_csv_row_limit'):
        parse([item(), item(**{'Name': 'Second event'})])
    monkeypatch.setattr(failte, 'MAX_ROWS', 10000)
    monkeypatch.setattr(failte, 'MAX_EVENTS', 1)
    with pytest.raises(ValueError, match='failte_occurrence_limit'):
        parse([item(), item(**{'Name': 'Second event'})])


def test_conflicting_duplicates_and_deadline_do_not_return_a_valid_prefix(monkeypatch):
    with pytest.raises(ValueError, match='failte_conflicting_occurrence'):
        parse([item(), item(**{'Description': 'Conflicting native narrative.'})])
    ticks = iter((0, 0, 36))
    monkeypatch.setattr(failte, 'monotonic', lambda: next(ticks))
    with pytest.raises(ValueError, match='collection_deadline'):
        parse([item(), item(**{'Name': 'Second event'})], deadline_at=35)
