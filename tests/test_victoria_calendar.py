"""Strict venue holds and bounded, disclosed owner-authorized associations."""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from bs4 import BeautifulSoup
import pytest

from roomquest import victoria_calendar as victoria, preview_worker

NOW = datetime(2026, 11, 10, 10, tzinfo=timezone.utc)
FIXTURE = Path(__file__).parent / 'fixtures/south_hill_expansion/victoria-calendar.html'
SOURCE = {'source_key': victoria.SOURCE_KEY, 'feed_url': victoria.CALENDAR,
          'kind': 'html', 'platform_adapter': 'html', 'timezone': victoria.TIMEZONE}


@pytest.fixture(autouse=True)
def stable_test_clock(monkeypatch):
    monkeypatch.setattr(preview_worker, '_future_datetime', lambda value: value.astimezone(timezone.utc))


def with_location(text='Location: Victoria Community Center, 1421 6th Street, Victoria, VA 23974'):
    soup = BeautifulSoup(FIXTURE.read_text(), 'html.parser')
    tag = soup.new_tag('p')
    tag.string = text
    soup.select_one('#item_36080').append(tag)
    return str(soup)


def test_actual_four_cards_have_explicit_dates_but_all_remain_held_for_venue():
    notes = {}
    assert victoria.parse(FIXTURE.read_text(), now=NOW, diagnostics=notes) == []
    assert notes['cards'] == 4 and len(notes['held']) == 4
    assert {x['id'] for x in notes['held']} == {
        'victoria_calendar:32309', 'victoria_calendar:36080',
        'victoria_calendar:32356', 'victoria_calendar:32320'}
    assert {x['reason'] for x in notes['held']} == {'event_venue_unreviewed'}
    assert notes['held'][1]['starts_at'] == '2026-11-20T18:00:00-05:00'


def test_all_held_cards_do_not_certify_an_empty_healthy_source(capsys):
    fetch = Mock(return_value=FIXTURE.read_text())
    with pytest.raises(ValueError, match='victoria_event_venue_unreviewed'):
        victoria.collect(SOURCE, fetch, now=NOW)
    assert capsys.readouterr().err.count('"event": "victoria_held"') == 4
    fetch.assert_called_once_with(victoria.CALENDAR, 'text/html')


def test_future_explicit_location_is_scoped_to_its_own_card():
    # A synthetic future publisher edit, not a claim that today's card has it.
    notes = {}
    rows = victoria.parse(with_location(), now=NOW, diagnostics=notes)
    assert len(rows) == 1 and len(notes['held']) == 3
    assert rows[0]['id'] == 'victoria_calendar:36080'
    assert rows[0]['starts_at'] == '2026-11-20T23:00:00+00:00'
    assert rows[0]['ends_at'] == '2026-11-21T02:30:00+00:00'
    assert rows[0]['venue_address'] == '1421 6th Street, Victoria, VA 23974'
    assert rows[0]['lat'] is None and rows[0]['lng'] is None
    assert 'image_url' not in rows[0]


@pytest.mark.parametrize('text', [
    'Register at 1809 Main Street, Victoria, VA 23974',
    'Location: Main Street, Victoria, VA 23974',
    'Location: Town Office', 'Contact: 1809 Main Street, Victoria, VA 23974',
])
def test_registration_street_only_and_office_contact_are_not_event_addresses(text):
    assert victoria.parse(with_location(text), now=NOW) == []


def test_general_contact_and_old_announcement_never_supply_card_location():
    payload = FIXTURE.read_text().replace('</main>',
        '<aside>Location: Town Office, 1809 Main Street, Victoria, VA 23974</aside>'
        '<p>July 31 Skate Night: Victoria Community Center, 1421 6th Street, Victoria, VA 23974</p></main>')
    assert victoria.parse(payload, now=NOW) == []


@pytest.mark.parametrize('new', ['11/20 - 6:00 PM', '11/20/2026 - 6:00', '11/20/2026 - 25:00 PM'])
def test_missing_year_or_clock_is_held_with_its_stable_publisher_id(new):
    notes = {}
    payload = with_location().replace('11/20/2026 - 6:00 PM', new)
    assert victoria.parse(payload, now=NOW, diagnostics=notes) == []
    note = next(n for n in notes['held'] if n['id'] == 'victoria_calendar:36080')
    assert note['reason'] == 'publisher_schedule_unresolved'


def test_end_before_start_never_becomes_an_invented_overnight_event():
    notes = {}
    payload = with_location().replace('11/20/2026 - 9:30 PM', '11/20/2026 - 5:30 PM')
    assert victoria.parse(payload, now=NOW, diagnostics=notes) == []
    assert any(n['reason'] == 'publisher_time_conflict' for n in notes['held'])


def test_same_publisher_id_with_changed_schedule_keeps_identity():
    original = victoria.parse(with_location(), now=NOW)[0]
    changed = victoria.parse(with_location().replace('11/20/2026 - 6:00 PM', '11/20/2026 - 6:30 PM'), now=NOW)[0]
    assert original['id'] == changed['id']
    assert original['starts_at'] != changed['starts_at']


def test_duplicate_publisher_ids_and_incomplete_list_shape_fail_closed():
    payload = FIXTURE.read_text()
    for text in (payload.replace('item_32320', 'item_32309'),
                 payload.replace('id="events_listing"', 'id="old_events"'),
                 payload.replace('<h2>Upcoming Events</h2>', '<h2>Upcoming Events</h2><a rel="next">More</a>')):
        with pytest.raises(ValueError):
            victoria.parse(text, now=NOW)


def test_calendar_items_do_not_generate_recurring_future_meetings():
    assert victoria.parse(FIXTURE.read_text(), now=datetime(2027, 11, 10, tzinfo=timezone.utc)) == []


def test_source_scope_deadline_and_transport_error_stop_before_other_requests():
    fetch = Mock()
    with pytest.raises(ValueError, match='unregistered_victoria_source'):
        victoria.collect({**SOURCE, 'feed_url': 'https://www.victoriava.net/calendar-of-events'}, fetch)
    with pytest.raises(ValueError, match='collection_deadline'):
        victoria.collect(SOURCE, fetch, deadline_at=-1)
    fetch.assert_not_called()
    error = preview_worker.PreviewError('publisher_http_403')
    fetch.side_effect = error
    with pytest.raises(preview_worker.PreviewError) as result:
        victoria.collect(SOURCE, fetch)
    assert result.value is error and fetch.call_count == 1


def test_reviewed_occurrences_receive_disclosed_associations_without_changing_dates():
    strict, notes = {}, {}
    victoria.parse(FIXTURE.read_text(), now=NOW, diagnostics=strict)
    rows = victoria.parse(FIXTURE.read_text(), now=NOW, diagnostics=notes, allow_inferred_venues=True)
    assert [row['id'] for row in rows] == [
        'victoria_calendar:32309', 'victoria_calendar:36080', 'victoria_calendar:32320']
    assert [item['id'] for item in notes['held']] == ['victoria_calendar:32356']
    assert len(notes['inferred']) == 3
    for row in rows:
        occurrence = next(item for item in strict['held'] if item['id'] == row['id'])
        assert datetime.fromisoformat(row['starts_at']) == datetime.fromisoformat(occurrence['starts_at'])
        assert datetime.fromisoformat(row['ends_at']) == datetime.fromisoformat(occurrence['ends_at'])
        receipt = row['venue_association']
        assert set(receipt) == {'method', 'evidence_urls', 'matched_activity', 'venue_name', 'venue_address'}
        assert receipt['method'] == row['location_provenance'] == victoria.ASSOCIATION_METHOD
        assert receipt['matched_activity'] == row['title']
        assert receipt['venue_name'] == row['venue_name'] and receipt['venue_address'] == row['venue_address']
        assert len(receipt['evidence_urls']) == 2 and all(url.startswith('https://') for url in receipt['evidence_urls'])
        assert row['description'].startswith('Venue inferred from')
        assert 'current calendar entry does not specify a venue' in row['description']
        assert row['lat'] is row['lng'] is None
        assert row['publisher_details'] == {} and 'image_url' not in row
        assert '$5' not in row['description'] and 'first 50' not in row['description']
    assert rows[0]['venue_address'] == rows[2]['venue_address'] == '1809 Main Street, Victoria, VA 23974'
    assert rows[1]['venue_address'] == '1421 6th Street, Victoria, VA 23974'


@pytest.mark.parametrize('version', [None, True, False, '1', 0, 2, 1.0])
def test_missing_or_unrecognized_backend_capability_preserves_all_holds(version):
    configured = {**SOURCE, 'venue_association_contract_version': version}
    fetch = Mock(return_value=FIXTURE.read_text())
    with pytest.raises(ValueError, match='victoria_event_venue_unreviewed'):
        victoria.collect(configured, fetch, now=NOW)
    fetch.assert_called_once_with(victoria.CALENDAR, 'text/html')


def test_capability_enabled_collection_uses_only_the_original_calendar_request(capsys):
    fetch = Mock(return_value=FIXTURE.read_text())
    rows = victoria.collect({**SOURCE, 'venue_association_contract_version': 1}, fetch, now=NOW)
    assert len(rows) == 3
    fetch.assert_called_once_with(victoria.CALENDAR, 'text/html')
    log = capsys.readouterr().err
    assert log.count('"event": "victoria_inferred"') == 3
    assert '"inferred": 3' in log and '"held": 1' in log


def test_explicit_own_card_address_overrides_reviewed_association():
    rows = victoria.parse(with_location('Location: Alternate Hall, 123 New Road, Victoria, VA 23974'),
                          now=NOW, allow_inferred_venues=True)
    skate = next(row for row in rows if row['id'] == 'victoria_calendar:36080')
    assert skate['venue_name'] == 'Alternate Hall'
    assert skate['venue_address'] == '123 New Road, Victoria, VA 23974'
    assert skate['location_provenance'] == 'publisher_event_address_pending_geocode'
    assert 'venue_association' not in skate and 'Venue inferred from' not in skate['description']


@pytest.mark.parametrize('text', [
    'Location: Main Street, Victoria, VA 23974', 'Location: Unknown Hall',
    'Venue: Different Hall', 'Skate Night moved to another venue.',
    'This activity has a new location.',
])
def test_association_cannot_override_unresolved_or_changed_publisher_location(text):
    rows = victoria.parse(with_location(text), now=NOW, allow_inferred_venues=True)
    assert {row['id'] for row in rows} == {'victoria_calendar:32309', 'victoria_calendar:32320'}


@pytest.mark.parametrize(('old', 'new'), [
    ('item_36080', 'item_36081'), ('Skate Night', 'Special Skate Night'),
    ('11/20/2026', '11/21/2026'), ('11/20/2026 - 6:00 PM', '11/20/2026 - 6:30 PM'),
    ('11/20/2026 - 9:30 PM', '11/20/2026 - 9:00 PM'),
])
def test_associations_do_not_extend_to_unreviewed_identity_title_date_or_clock(old, new):
    rows = victoria.parse(FIXTURE.read_text().replace(old, new), now=NOW, allow_inferred_venues=True)
    assert {row['id'] for row in rows} == {'victoria_calendar:32309', 'victoria_calendar:32320'}


def test_association_does_not_generate_occurrences_after_current_listing_expires():
    notes = {}
    assert victoria.parse(FIXTURE.read_text(), now=datetime(2027, 11, 10, tzinfo=timezone.utc),
                          diagnostics=notes, allow_inferred_venues=True) == []
    assert len(notes['excluded']) == 4 and not notes.get('inferred')
