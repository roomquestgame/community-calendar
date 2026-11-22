from datetime import datetime, timezone
from html import escape
import json
from unittest.mock import Mock

import pytest

from roomquest import designmynight_listing as dmn
from roomquest import preview_worker
from roomquest import uk_registered_listings as uk


class FrozenMeta(type):
    def __instancecheck__(cls, value):
        return isinstance(value, datetime)


class FrozenDateTime(datetime, metaclass=FrozenMeta):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 11, 22, 10, tzinfo=timezone.utc)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    for module in (dmn, uk, preview_worker):
        monkeypatch.setattr(module, 'datetime', FrozenDateTime)


def ticket(slug='gundam', dates='Tue, 1st Dec 2026 @ 18:30 - 21:30', hours='18:30 - 21:30',
           start='2026-12-01T21:30:00+00:00', end='2026-12-01T21:30:00+00:00'):
    event = {'@type': 'Event', 'name': 'Box Room event', 'url': dmn.TICKET_PREFIX + slug,
             'startDate': start, 'endDate': end, 'eventStatus': 'https://schema.org/EventScheduled',
             'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
             'organizer': {'name': 'The Box Room Board Game Cafe', 'url': 'http://theboxroombgc.co.uk'},
             'location': {'name': dmn.VENUE, 'address': {'streetAddress': dmn.VENUE + ', 58 Regent St',
                                                       'postalCode': 'CB2 1DP', 'addressCountry': 'GB'}}}
    return (f'<h1>{escape(event["name"])}</h1><script type="application/ld+json">{json.dumps(event)}</script>'
            f'<li title="Dates">{dates}</li><li title="Time">{hours}</li>'
            '<table class="table-borderless table-condensed margin-none"><tbody><tr><td>Calendar</td>'
            f'<td>{dates}</td></tr></tbody></table>'
            '<table class="table-condensed table-striped"><thead><tr><th>Ticket</th><th>Event time</th>'
            f'<th>Cost</th></tr></thead><tbody><tr><td>Entry</td><td>{hours}</td><td>£11</td></tr></tbody></table>'
            '<div id="tab-description"><div class="tabs__description"><p>Play games at the café.</p></div></div>')


def listing(*slugs):
    return ''.join(f'<a href="{dmn.TICKET_PREFIX + slug}?t=tickets">Tickets</a>' for slug in slugs)


def collect(body, fetch):
    return uk.collect({'feed_url': dmn.URL, 'source_key': uk.source_key(dmn.URL)}, fetch, listing=body)


def test_zero_duration_schema_defect_requires_two_agreeing_public_clock_fields():
    fetch = Mock(return_value=ticket())
    rows = collect(listing('gundam', 'gundam'), fetch)
    assert len(rows) == 1
    assert rows[0]['starts_at'] == '2026-12-01T18:30:00+00:00'
    assert rows[0]['ends_at'] == '2026-12-01T21:30:00+00:00'
    assert rows[0]['timezone'] == 'Europe/London'
    assert rows[0]['venue_address'] == dmn.STREET
    assert rows[0]['lat'] is None and rows[0]['lng'] is None
    assert rows[0]['event_url'] == dmn.TICKET_PREFIX + 'gundam'
    assert rows[0]['description'] == 'Play games at the café.'
    fetch.assert_called_once_with(dmn.TICKET_PREFIX + 'gundam?t=tickets', 'text/html')


@pytest.mark.parametrize('dates,start,end,first,last,count', [
    ('Every Friday', '2026-04-24T19:00:00+01:00', '2026-04-24T22:00:00+01:00', '2026-11-27', '2027-01-15', 8),
    ('Every 1st Friday of the month', '2026-07-03T19:00:00+01:00', '2026-07-03T22:00:00+01:00', '2026-12-04', '2027-01-01', 2),
])
def test_explicit_written_recurrence_bounded_to_window(dates, start, end, first, last, count):
    page = ticket(dates=dates, hours='19:00 - 22:00', start=start, end=end)
    rows = collect(listing('gundam'), Mock(return_value=page))
    assert len(rows) == count
    assert rows[0]['starts_at'] == first + 'T19:00:00+00:00'
    assert rows[-1]['starts_at'] == last + 'T19:00:00+00:00'
    assert all(row['timezone'] == 'Europe/London' for row in rows)


def test_undated_other_tuesdays_are_not_inferred(caplog):
    page = ticket(dates='Tuesday 24th November 2026 and 2 other Tuesdays',
                  start='2026-11-24T21:30:00+00:00', end='2026-11-24T21:30:00+00:00')
    rows = collect(listing('gundam'), Mock(return_value=page))
    assert len(rows) == 1 and rows[0]['starts_at'] == '2026-11-24T18:30:00+00:00'
    assert '2 additional undated occurrences' in caplog.text


def test_written_recurrence_exception_is_not_silently_ignored(caplog):
    page = ticket(dates='Every Friday', hours='19:00 - 22:00',
                  start='2026-04-24T19:00:00+01:00', end='2026-04-24T22:00:00+01:00')
    page = page.replace('Play games at the café.', 'Every Friday except Christmas Day.')
    with pytest.raises(ValueError, match='no_extractable_events'):
        collect(listing('gundam'), Mock(return_value=page))
    assert 'exceptions_require_review' in caplog.text


def test_conflicting_ticket_end_is_held_without_changing_valid_event(caplog):
    wrong = ticket('conflict').replace('<td>18:30 - 21:30</td>', '<td>18:30 - 20:30</td>')
    rows = collect(listing('conflict', 'gundam'), Mock(side_effect=[wrong, ticket()]))
    assert len(rows) == 1 and rows[0]['event_url'].endswith('/gundam')
    assert 'box_event_schedule_conflict' in caplog.text
    assert '/conflict' in caplog.text


@pytest.mark.parametrize('old,new', [
    ('Tue, 1st Dec', 'Mon, 1st Dec'),
    ('2026-12-01T21:30:00+00:00', '2026-12-01T21:30:00+01:00'),
    ('2026-12-01T21:30:00+00:00', '2026-12-01T20:30:00+00:00'),
    ('<li title="Time">18:30 - 21:30', '<li title="Time">18:00 - 21:30'),
    ('<td>Tue, 1st Dec 2026', '<td>Tue, 8th Dec 2026'),
])
def test_schedule_conflicts_do_not_publish(old, new):
    with pytest.raises(ValueError, match='no_extractable_events'):
        collect(listing('gundam'), Mock(return_value=ticket().replace(old, new)))


@pytest.mark.parametrize('old,new', [
    ('CB2 1DP', 'CB1 1AA'),
    ('58 Regent St', '99 Regent St'),
    ('http://theboxroombgc.co.uk', 'https://another-organizer.test'),
    ('<h1>Box Room event', '<h1>Another event'),
])
def test_identity_or_venue_change_requires_review(old, new):
    with pytest.raises(ValueError, match='box_event_identity_unverified'):
        collect(listing('gundam'), Mock(return_value=ticket().replace(old, new)))


def test_expired_and_outside_window_pages_do_not_create_occurrences():
    expired = ticket('expired', dates='This event has taken place.')
    future = ticket('future', dates='Sunday 24th and Tuesday 26th January 2027')
    rows = collect(listing('expired', 'future', 'gundam'), Mock(side_effect=[expired, future, ticket()]))
    assert len(rows) == 1 and rows[0]['event_url'].endswith('/gundam')


def test_unresolved_multiple_sessions_are_held_when_they_enter_window(caplog):
    page = ticket('multiple', dates='Sunday 6th and Tuesday 8th December 2026')
    rows = collect(listing('multiple', 'gundam'), Mock(side_effect=[page, ticket()]))
    assert len(rows) == 1
    assert 'multiple_sessions_requires_review' in caplog.text


@pytest.mark.parametrize('url', [
    dmn.TICKET_PREFIX.replace('the-box-room-board-game-cafe', 'other-venue') + 'event?t=tickets',
    dmn.TICKET_PREFIX + '../event?t=tickets',
    dmn.TICKET_PREFIX + 'event?t=tickets&all=1',
    dmn.TICKET_PREFIX + 'event#tickets',
    dmn.TICKET_PREFIX.replace('https://', 'http://') + 'event?t=tickets',
])
def test_unreviewed_ticket_routes_never_fetch(url):
    fetch = Mock()
    with pytest.raises(ValueError, match='box_ticket_url_unreviewed'):
        collect(f'<a href="{url}">Tickets</a>', fetch)
    fetch.assert_not_called()


def test_excess_detail_batch_fails_before_any_fetch():
    fetch = Mock()
    with pytest.raises(ValueError, match='box_calendar_detail_limit'):
        collect(listing(*(f'event-{i}' for i in range(dmn.MAX_DETAILS + 1))), fetch)
    fetch.assert_not_called()


def test_30_second_limit_cannot_return_a_completed_partial_batch(monkeypatch):
    monkeypatch.setattr(dmn, 'monotonic', iter([0, 0, 0, 31]).__next__)
    fetch = Mock(return_value=ticket())
    with pytest.raises(ValueError, match='collection_deadline'):
        collect(listing('gundam', 'later'), fetch)
    fetch.assert_called_once()


def test_cross_host_transport_allowance_applies_only_to_exact_reviewed_source():
    assert uk.allowed_hosts(dmn.URL) == ('theboxroombgc.co.uk', 'www.designmynight.com')
    assert uk.allowed_hosts(uk.WINE) == ('www.cambridgewineacademy.com',)
    with pytest.raises(ValueError, match='unregistered_html_source'):
        uk.allowed_hosts(dmn.URL + '?all=1')
