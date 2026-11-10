"""Complete future coverage survives bounded detail work and interrupted retries."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from html import escape
import json

import pytest

from roomquest import discover_halifax as tourism
from roomquest import preview_worker


SOURCE = {'source_key': tourism.KEY, 'feed_url': tourism.URL,
          'timezone': tourism.ZONE, 'kind': 'html', 'platform_adapter': 'html'}
NOW = datetime(2026, 11, 8, 3, 36, 11, tzinfo=timezone.utc)
WOODBINE = ('Woodbine Vineyards, 1142, Hite Drive, Buffalo Springs, '
            'Mecklenburg County, Virginia, 24529, United States')


@pytest.fixture(autouse=True)
def fixed_shared_window(monkeypatch):
    # Exercise the real record/evidence normalizers without wall-clock aging of
    # the exact dated publisher repairs that this regression suite protects.
    monkeypatch.setattr(preview_worker, '_future_datetime',
                        lambda value: value.astimezone(timezone.utc)
                        if NOW <= value <= NOW + timedelta(days=preview_worker.LOOKAHEAD_DAYS)
                        else None)


def descriptor(number, day=None, title=None, clock='6:00 PM'):
    return (f'https://gohalifaxva.com/directory/event-{number}/',
            title or f'Public event {number}', day or date(2026, 11, 20), clock)


def listing(items, *, total=None):
    cards = ''.join(
        '<article class="directorist-listing-single">'
        f'<h2 class="directorist-listing-title"><a href="{url}">{escape(title)}</a></h2>'
        f'<span class="directorist-listing-card-date">{day:%B} {day.day}, {day.year}</span>'
        f'<span class="directorist-listing-card-time">{clock}</span></article>'
        for url, title, day, clock in items)
    return (f'<div class="directorist-header-found-title"><span>{len(items) if total is None else total}</span></div>'
            + cards)


def detail(item, *, address=WOODBINE, description='Synthetic public program details.',
           fields=None, website=None):
    url, title, day, clock = item
    values = {'Start Date': f'{day:%B} {day.day}, {day.year}',
              'Start Time': clock, 'End Time': '8:00 PM', 'Address': address}
    if website:
        values['Website'] = website
    values.update(fields or {})
    body = ''.join(
        '<div class="directorist-single-info">'
        f'<span class="directorist-single-info__label__text">{escape(key)}</span>'
        f'<span class="directorist-single-info__value">{escape(value)}</span></div>'
        for key, value in values.items())
    return (f'<link rel="canonical" href="{url}">'
            f'<h1 class="directorist-listing-details__listing-title">{escape(title)}</h1>'
            + body + f'<div class="directorist-card-general-section">Description {escape(description)}</div>')


def publisher(items):
    pages = {tourism.URL: listing(items), **{row[0]: detail(row) for row in items}}
    calls = []

    def fetch(url, accept):
        assert accept == 'text/html'
        calls.append(url)
        return pages[url]

    return pages, calls, fetch


def test_normal_window_includes_later_november_and_december_not_only_seven_days():
    anchor = date(2026, 11, 7)
    items = [descriptor(1, date(2026, 11, 14)), descriptor(2, date(2026, 11, 21)),
             descriptor(3, date(2026, 12, 12)), descriptor(4, date(2027, 1, 16))]
    assert tourism._directory(listing(items), anchor) == items[:3]


def test_more_than_eighteen_records_resume_without_publishing_a_partial_snapshot():
    items = [descriptor(i) for i in range(30)]
    _, calls, fetch = publisher(items)
    checkpoint, completed = None, None
    for expected_cursor in (6, 12, 18, 24, 30):
        output = tourism.collect_chunk(SOURCE, fetch, checkpoint=checkpoint, now=NOW)
        checkpoint = json.loads(json.dumps(output['checkpoint']))
        assert checkpoint['cursor'] == expected_cursor
        if expected_cursor < 30:
            assert output['complete'] is False
            assert output['events'] == []
        else:
            completed = output
    assert completed['complete'] is True
    assert {row['id'] for row in completed['events']} == {row[0] for row in items}
    assert len(completed['events']) == 30
    assert all(calls.count(row[0]) == 1 for row in items)
    assert calls.count(tourism.URL) == 5


def test_advertised_zero_is_a_complete_empty_snapshot_not_a_source_failure():
    output = tourism.collect_chunk(SOURCE, lambda *_: listing([]), now=NOW)
    assert output['complete'] is True and output['events'] == []
    assert output['checkpoint']['manifest_count'] == 0


def test_changed_manifest_discards_cached_facts_instead_of_combining_snapshots():
    items = [descriptor(i) for i in range(8)]
    pages, calls, fetch = publisher(items)
    first = tourism.collect_chunk(SOURCE, fetch, now=NOW)
    removed = sorted(items, key=lambda row: (row[2], row[0]))[0]
    replacement = descriptor(99)
    revised = [row for row in items if row != removed] + [replacement]
    pages[tourism.URL], pages[replacement[0]] = listing(revised), detail(replacement)
    resumed = tourism.collect_chunk(SOURCE, fetch, checkpoint=first['checkpoint'], now=NOW)
    assert resumed['complete'] is False
    assert resumed['checkpoint']['cursor'] == 6
    assert resumed['checkpoint']['manifest_hash'] != first['checkpoint']['manifest_hash']
    final = tourism.collect_chunk(SOURCE, fetch, checkpoint=resumed['checkpoint'], now=NOW)
    assert final['complete'] is True
    assert removed[0] not in {row['id'] for row in final['events']}
    assert replacement[0] in {row['id'] for row in final['events']}


def test_display_reordering_does_not_restart_durable_progress():
    items = [descriptor(i) for i in range(8)]
    pages, calls, fetch = publisher(items)
    first = tourism.collect_chunk(SOURCE, fetch, now=NOW)
    pages[tourism.URL] = listing(list(reversed(items)))
    final = tourism.collect_chunk(SOURCE, fetch, checkpoint=first['checkpoint'], now=NOW)
    assert final['complete'] is True and len(final['events']) == 8
    assert all(calls.count(row[0]) == 1 for row in items)


def test_later_network_failure_preserves_previous_checkpoint_and_never_certifies_prefix():
    items = [descriptor(i) for i in range(9)]
    _, calls, fetch = publisher(items)
    first = tourism.collect_chunk(SOURCE, fetch, now=NOW)
    saved = deepcopy(first['checkpoint'])
    remaining = sorted(items, key=lambda row: (row[2], row[0]))[7][0]

    def broken(url, accept):
        if url == remaining:
            raise preview_worker.PreviewError('publisher_http_403')
        return fetch(url, accept)

    with pytest.raises(preview_worker.PreviewError, match='publisher_http_403'):
        tourism.collect_chunk(SOURCE, broken, checkpoint=saved, now=NOW)
    assert saved == first['checkpoint']
    assert saved['cursor'] == 6
    recovered = tourism.collect_chunk(SOURCE, fetch, checkpoint=saved, now=NOW)
    assert recovered['complete'] is True and len(recovered['events']) == 9


def test_budget_returns_explicit_partial_without_spending_finish_reserve(monkeypatch):
    _, calls, fetch = publisher([descriptor(i) for i in range(9)])
    values = iter([0, 1, 2, 30])
    monkeypatch.setattr(tourism, 'monotonic', lambda: next(values))
    output = tourism.collect_chunk(SOURCE, fetch, now=NOW, deadline_at=35)
    assert output['complete'] is False and output['events'] == []
    assert output['checkpoint']['cursor'] == 2
    assert len(calls) == 3


def test_slow_detail_can_finish_before_the_next_detail_is_deferred(monkeypatch):
    """The transport's 18-second cap must fit before each requested detail."""
    _, calls, fetch = publisher([descriptor(i) for i in range(9)])
    elapsed = [0.0]
    monkeypatch.setattr(tourism, 'monotonic', lambda: elapsed[0])

    def slow(url, accept):
        elapsed[0] += 5 if url == tourism.URL else 18
        if elapsed[0] >= 35:
            raise preview_worker.PreviewError('source_fetch_deadline')
        return fetch(url, accept)

    output = tourism.collect_chunk(SOURCE, slow, now=NOW, deadline_at=35)
    assert output['complete'] is False
    assert output['checkpoint']['cursor'] == 1
    assert len(calls) == 2 and elapsed[0] == 23


def test_slow_listing_does_not_start_a_zero_progress_continuation_loop(monkeypatch):
    _, calls, fetch = publisher([descriptor(i) for i in range(9)])
    elapsed = [0.0]
    monkeypatch.setattr(tourism, 'monotonic', lambda: elapsed[0])

    def slow(url, accept):
        elapsed[0] += 20
        return fetch(url, accept)

    with pytest.raises(ValueError, match='collection_deadline'):
        tourism.collect_chunk(SOURCE, slow, now=NOW, deadline_at=35)
    assert calls == [tourism.URL]


def test_legacy_collector_preserves_seven_day_bound_without_checkpoint_rpc(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    monkeypatch.setattr(tourism, 'datetime', Clock)
    early = descriptor(1, date(2026, 11, 12))
    later = descriptor(2, date(2026, 11, 20))
    _, calls, fetch = publisher([early, later])
    result = tourism.collect_legacy(SOURCE, fetch)
    assert [row['event_url'] for row in result] == [early[0]]
    assert calls == [tourism.URL, early[0]]


def test_legacy_collector_keeps_detail_limit_before_unbounded_network_work(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    monkeypatch.setattr(tourism, 'datetime', Clock)
    _, calls, fetch = publisher([descriptor(i, date(2026, 11, 12)) for i in range(19)])
    with pytest.raises(ValueError, match='halifax_directory_detail_limit'):
        tourism.collect_legacy(SOURCE, fetch)
    assert calls == [tourism.URL]


def test_midnight_resume_keeps_the_original_eastern_window():
    items = [descriptor(i) for i in range(8)]
    _, _, fetch = publisher(items)
    first = tourism.collect_chunk(SOURCE, fetch, now=NOW)
    after_midnight = datetime(2026, 11, 8, 5, 10, tzinfo=timezone.utc)
    last = tourism.collect_chunk(SOURCE, fetch, checkpoint=first['checkpoint'], now=after_midnight)
    assert first['checkpoint']['window_start'] == '2026-11-07'
    assert last['checkpoint']['window_start'] == '2026-11-07'
    assert last['complete'] is True


@pytest.mark.parametrize('mutation', [
    {'source_key': 'different_source'}, {'version': 2}, {'version': True}, {'cursor': -1},
    {'cursor': True}, {'manifest_count': 201}, {'manifest_hash': 'bad'},
    {'events': {}}, {'diagnostics': {}}, {'started_at': '2026-11-07'},
])
def test_invalid_checkpoint_cannot_inject_or_skip_snapshot_work(mutation):
    _, _, fetch = publisher([descriptor(i) for i in range(9)])
    first = tourism.collect_chunk(SOURCE, fetch, now=NOW)
    state = {**first['checkpoint'], **mutation}
    with pytest.raises(ValueError, match='halifax_checkpoint_invalid'):
        tourism.collect_chunk(SOURCE, fetch, checkpoint=state, now=NOW)


def test_stale_progress_restarts_instead_of_finishing_an_old_snapshot():
    _, calls, fetch = publisher([descriptor(i) for i in range(9)])
    first = tourism.collect_chunk(SOURCE, fetch, now=NOW)
    output = tourism.collect_chunk(SOURCE, fetch, checkpoint=first['checkpoint'],
                                   now=NOW + timedelta(hours=5))
    assert output['complete'] is False and output['checkpoint']['cursor'] == 6
    assert output['checkpoint']['started_at'] != first['checkpoint']['started_at']


@pytest.mark.parametrize('mutation', ['missing_row', 'foreign_row', 'duplicate_row',
                                     'future_cursor', 'warning_without_decision'])
def test_cursor_requires_an_accounted_manifest_prefix(mutation):
    _, _, fetch = publisher([descriptor(i) for i in range(9)])
    first = tourism.collect_chunk(SOURCE, fetch, now=NOW)
    state = deepcopy(first['checkpoint'])
    if mutation == 'missing_row':
        state['events'].pop()
    elif mutation == 'foreign_row':
        state['events'][0]['event_url'] = descriptor(99)[0]
    elif mutation == 'duplicate_row':
        state['events'].append(deepcopy(state['events'][0]))
    elif mutation == 'future_cursor':
        state['cursor'] = 9
    else:
        dropped = state['events'].pop()
        state['diagnostics'].append({'event_url': dropped['event_url'],
                                     'reason': 'publisher_end_unverified', 'disposition': 'warning'})
    with pytest.raises(ValueError, match='halifax_checkpoint_invalid'):
        tourism.collect_chunk(SOURCE, fetch, checkpoint=state, now=NOW)


def test_held_detail_is_accounted_when_resuming():
    items = [descriptor(i) for i in range(9)]
    pages, _, fetch = publisher(items)
    held = sorted(items, key=lambda row: (row[2], row[0]))[2]
    pages[held[0]] = detail(held, address='Named venue without street')
    first = tourism.collect_chunk(SOURCE, fetch, now=NOW)
    last = tourism.collect_chunk(SOURCE, fetch, checkpoint=first['checkpoint'], now=NOW)
    assert last['complete'] is True and len(last['events']) == 8
    assert last['checkpoint']['diagnostics'] == [
        {'event_url': held[0], 'reason': 'event_address_unresolved', 'disposition': 'held'}]


def test_the_light_exact_reviewed_occurrence_gets_address_without_coordinates():
    item = (tourism.THE_LIGHT_EVENT, 'Still Life Drawing at The Light', date(2026, 11, 12), '6:00 PM')
    row = tourism._detail(detail(item, address='The Light Spiritual Wellness',
                                 fields={'End Time': '9:00 PM'}, website='thelightspiritualwellness.com'), *item)
    assert row['venue_address'] == tourism.THE_LIGHT_ADDRESS
    assert row['venue_city'] == 'South Boston'
    assert row['lat'] is None and row['lng'] is None


@pytest.mark.parametrize('change', [
    {'website': 'unrelated.example'}, {'address': 'Another venue'},
    {'fields': {'End Time': '10:00 PM'}},
    {'description': 'This event is relocated to another venue.'},
])
def test_the_light_review_does_not_overwrite_unverified_or_changed_facts(change):
    item = (tourism.THE_LIGHT_EVENT, 'Still Life Drawing at The Light', date(2026, 11, 12), '6:00 PM')
    values = {'address': 'The Light Spiritual Wellness', 'fields': {'End Time': '9:00 PM'},
              'website': 'thelightspiritualwellness.com'}
    values.update(change)
    assert tourism._detail(detail(item, **values), *item) is None


def test_explicit_publisher_street_is_preserved_instead_of_replaced_by_review():
    item = (tourism.THE_LIGHT_EVENT, 'Still Life Drawing at The Light', date(2026, 11, 12), '6:00 PM')
    street = 'The Light Spiritual Wellness, 500, Main Street, South Boston, Virginia, 24592, United States'
    row = tourism._detail(detail(item, address=street, fields={'End Time': '9:00 PM'},
                                 website='thelightspiritualwellness.com'), *item)
    assert row['venue_address'] == '500 Main Street, South Boston, VA 24592'


def test_christmas_market_keeps_the_earlier_published_time_after_owner_resolution():
    item = ('https://gohalifaxva.com/directory/woodbine-christmas-market/',
            'Woodbine Christmas Market', date(2026, 11, 15), '11:00 AM')
    diagnostics = []
    row = tourism._detail(detail(item, fields={'End Time': '5:00 PM'}), *item, diagnostics=diagnostics)
    assert row['starts_at'] == '2026-11-15T16:00:00+00:00'
    assert row['ends_at'] == '2026-11-15T22:00:00+00:00'
    assert not diagnostics


def test_same_event_date_uses_earlier_explicit_listing_or_detail_clock():
    item = descriptor(1, date(2026, 11, 15), clock='12:00 PM')
    diagnostics = []
    row = tourism._detail(detail(item, fields={'Start Time': '11:00 AM', 'End Time': '5:00 PM'}),
                          *item, diagnostics=diagnostics)
    assert row['starts_at'] == '2026-11-15T16:00:00+00:00'
    assert diagnostics[0]['reason'] == 'earlier_published_start_selected'


def test_different_published_dates_or_unparseable_clocks_are_not_earlier_time_resolutions():
    item = descriptor(1, date(2026, 11, 15), clock='12:00 PM')
    assert tourism._detail(detail(item, fields={'Start Date': 'November 16, 2026'}), *item) is None
    with pytest.raises(ValueError):
        tourism._detail(detail(item, fields={'Start Time': 'Afternoon'}), *item)


def test_missing_street_and_cancellation_are_observable_and_not_published():
    items = [descriptor(1), descriptor(2)]
    diagnostics = []
    assert tourism._detail(detail(items[0], address='A named venue'), *items[0], diagnostics=diagnostics) is None
    assert tourism._detail(detail(items[1], description='Cancelled.'), *items[1], diagnostics=diagnostics) is None
    assert [row['reason'] for row in diagnostics] == ['event_address_unresolved', 'publisher_status_or_attendance_excluded']


def test_faire_and_adult_ball_are_distinct_occurrences_with_independent_audiences():
    item = (tourism.FAIRE_EVENT, 'Wine and Whimsey Renaissance Faire', date(2026, 11, 21), '11:00 AM')
    prose = ('Synthetic event narrative: Renaissance Faire from 11:00 AM–5:00 PM. '
             'Fantasy Ball from 7:00 PM–11:00 PM.')
    pages, _, fetch = publisher([item])
    pages[item[0]] = detail(item, description=prose, fields={'End Time': '11:00 PM'})
    output = tourism.collect_chunk(SOURCE, fetch, now=NOW)
    faire, ball = output['events']
    assert output['complete'] is True
    assert faire['id'].endswith('#faire-20261121') and ball['id'].endswith('#fantasy-ball-20261121')
    assert faire['event_url'] == ball['event_url'] == item[0]
    assert (faire['starts_at'], faire['ends_at']) == ('2026-11-21T16:00:00+00:00', '2026-11-21T22:00:00+00:00')
    assert (ball['starts_at'], ball['ends_at']) == ('2026-11-22T00:00:00+00:00', '2026-11-22T04:00:00+00:00')
    assert 'All ages' in faire['publisher_details']['audience']
    assert '18 and older' in ball['publisher_details']['audience']
    assert 'children' not in ball['description'].lower()
    assert 'All ages' not in ball['description']


def test_changed_faire_schedule_is_held_instead_of_using_reviewed_old_times():
    item = (tourism.FAIRE_EVENT, 'Wine and Whimsey Renaissance Faire', date(2026, 11, 21), '11:00 AM')
    row = tourism._detail(detail(item, description='New hours require review.',
                                 fields={'End Time': '11:00 PM'}), *item)
    diagnostics = []
    assert tourism._reviewed_sessions(row, diagnostics) == []
    assert diagnostics[0]['reason'] == 'reviewed_session_schedule_conflict'
