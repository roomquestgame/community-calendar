"""Native UK street evidence must survive direct registered-iCal intake."""
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from roomquest import ics_adapter, preview_worker
from roomquest.ical_venue_address import extract_venue_addresses
from roomquest.registration_formats import source_key
from scripts import combine_ics


FEED = 'https://www.phcl.org/events.ics'
FIXTURE = Path(__file__).parent / 'fixtures' / 'uk_ical_address' / 'phcl-20261123.ics'
DEFAULT_NAME = ('Primrose Hill Community Library, Primrose Hill Community Library, '
                '11-16 Sharples Hall St, Primrose Hill, London, Greater London, NW1 8YN, United Kingdom')
DEFAULT_ADDRESS = '11-16 Sharples Hall St, Primrose Hill, London, Greater London, NW1 8YN, United Kingdom'
CHESS_NAME = 'Primrose Hill Library, 11-16 Sharples Hall Street, London , NW1 8YN, United Kingdom'
CHESS_ADDRESS = '11-16 Sharples Hall Street, London, NW1 8YN, United Kingdom'
FILM_LOCATION = 'https://goo.gl/maps/vdiRTuBHU8PBzVLy8'


@pytest.fixture(autouse=True)
def fixed_clock_and_no_network(monkeypatch):
    class ClockMeta(type):
        def __instancecheck__(cls, value):
            return isinstance(value, datetime)

    class Clock(datetime, metaclass=ClockMeta):
        @classmethod
        def now(cls, tz=None):
            value = datetime(2026, 11, 23, tzinfo=timezone.utc)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    class Day(date):
        @classmethod
        def today(cls):
            return date(2026, 11, 23)

    monkeypatch.setattr(preview_worker, 'datetime', Clock)
    monkeypatch.setattr(ics_adapter, 'datetime', Clock)
    monkeypatch.setattr(combine_ics, 'date', Day)

    def forbidden(*_args, **_kwargs):
        raise AssertionError('address fixture attempted live transport')

    monkeypatch.setattr('socket.getaddrinfo', forbidden)
    monkeypatch.setattr('urllib.request.urlopen', forbidden)
    monkeypatch.setattr('requests.sessions.Session.request', forbidden)


def test_all_fifty_native_events_keep_identity_default_binding_and_other_facts():
    raw = FIXTURE.read_text()
    source = dict(source_key=source_key(FEED), feed_url=FEED, kind='ical', platform_adapter='ical')
    with patch.object(preview_worker, 'fetch_publisher', return_value=raw) as fetch:
        with patch('roomquest.ical_venue_address._gb_address', return_value=None):
            before = preview_worker.preview_source(source)
        after = preview_worker.preview_source(source)
    assert before['p_future_count'] == after['p_future_count'] == 50
    assert before['p_error'] is after['p_error'] is None
    assert all(call.kwargs['respect_robots'] is True for call in fetch.call_args_list)
    assert len({row['id'] for row in after['p_events']}) == 50
    counts = {DEFAULT_NAME: 0, CHESS_NAME: 0, FILM_LOCATION: 0}
    for old, new in zip(before['p_events'], after['p_events'], strict=True):
        name = new['venue_name']
        counts[name] += 1
        expected = {DEFAULT_NAME: DEFAULT_ADDRESS, CHESS_NAME: CHESS_ADDRESS, FILM_LOCATION: ''}[name]
        assert new['venue_address'] == expected
        assert {k: v for k, v in new.items() if k != 'venue_address'} == {
            k: v for k, v in old.items() if k != 'venue_address'}
        # Only evidence is extracted. The existing source default or a supported
        # explicit venue review must still supply the actual physical point.
        assert new['lat'] is None and new['lng'] is None
        assert not any(key.startswith('override_') for key in new)
    assert counts == {DEFAULT_NAME: 47, CHESS_NAME: 2, FILM_LOCATION: 1}
    assert after['p_venue_count'] == 0
    repeated = deepcopy(after['p_events'])
    extract_venue_addresses(repeated)
    assert repeated == after['p_events']


@pytest.mark.parametrize(('location', 'expected'), [
    ("Hall, 11–16 Queen's Road, Cambridge, CB2 1TN, UK", "11–16 Queen's Road, Cambridge, CB2 1TN, UK"),
    ('Library\n323 Norwood Rd\nLondon\nse249aq\nUnited Kingdom', '323 Norwood Rd, London, SE24 9AQ, United Kingdom'),
    ('Venue, London, NW1 8YN, United Kingdom', ''),  # No numbered street.
    ('Venue, 11 Main St, London, NW1, United Kingdom', ''),  # Outward code only.
    ('Venue, 11 Main St, London, NW1 8YN, Ireland', ''),
    ('Venue, 11 Main St, London, NW1 8YN', ''),  # Country cannot be guessed.
    ('Online, 11 Main St, London, NW1 8YN, UK', ''),
    ('Venue, 11 Main St, 20 Other Road, London, NW1 8YN, UK', ''),
    ('Venue, 10 Downing Street London SW1A 2AA, 11 Main St, London, NW1 8YN, UK', ''),
    ('Venue, 14 North Boulevard, 11 Main St, London, NW1 8YN, UK', ''),
    ('Venue SW1A 2AA, 11 Main St, London, NW1 8YN, UK', ''),
    ('Venue, 11 Main St or 20 Other Road, London, NW1 8YN, UK', ''),
    ('Venue, P.O. Box 11, London, NW1 8YN, UK', ''),
    (FILM_LOCATION, ''),
    ('x' * 160, ''),
])
def test_bounded_physical_address_evidence(location, expected):
    row = dict(venue_name=location, venue_address='', lat=None, lng=None)
    extract_venue_addresses([row])
    assert row == dict(venue_name=location, venue_address=expected, lat=None, lng=None)


def test_existing_address_point_and_manual_decisions_are_never_replaced():
    for decision in ('hold', 'exclude', 'include'):
        row = dict(venue_name=DEFAULT_NAME, venue_address='Reviewed different event address',
                   venue_city='Reviewed town', lat=51.5, lng=-0.1,
                   override_decision=decision, override_note='Retain the current review')
        before = deepcopy(row)
        extract_venue_addresses([row])
        assert row == before
        row['venue_address'] = ''
        before = deepcopy(row)
        extract_venue_addresses([row])
        assert row['venue_address'] == DEFAULT_ADDRESS
        assert {k: v for k, v in row.items() if k != 'venue_address'} == {
            k: v for k, v in before.items() if k != 'venue_address'}
