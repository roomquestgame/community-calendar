from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
import pytest

from roomquest import gulf_seasonal as seasonal
from roomquest.preview_worker import preview_source


FIXTURES = Path(__file__).parent / 'fixtures' / 'gulf_seasonal'
NOW = datetime(2026, 11, 14, 19, 0, tzinfo=timezone.utc)


class _ClockMeta(type):
    def __instancecheck__(cls, instance):
        return isinstance(instance, datetime)


class _Clock(datetime, metaclass=_ClockMeta):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def frozen_record_window(monkeypatch):
    monkeypatch.setattr('roomquest.preview_worker.datetime', _Clock)


def source(key):
    return dict(source_key=key, feed_url=seasonal.SOURCES[key], kind='html',
                platform_adapter='html', timezone=seasonal.ZONE, lat=29.99, lng=-90.09)


def payload(name):
    return (FIXTURES / name).read_text()


def city_pages():
    root = seasonal.SOURCES[seasonal.CITY_PARK]
    return {root: payload('city_park_page1.html'),
            root + 'list/page/2/': payload('city_park_page2.html')}


def run_city(pages=None):
    pages = pages or city_pages()
    fetch = Mock(side_effect=lambda url, accept: pages[url])
    rows = seasonal.collect(source(seasonal.CITY_PARK), fetch, now=NOW)
    return rows, fetch


def test_nola_all_published_sessions_roll_december_into_january():
    fetch = Mock(return_value=payload('nola_2026.html'))
    rows = seasonal.collect(source(seasonal.NOLA), fetch, now=NOW)
    assert len(rows) == len({r['id'] for r in rows}) == 18
    local = [(datetime.fromisoformat(row['starts_at']).astimezone(ZoneInfo(seasonal.ZONE)),
              datetime.fromisoformat(row['ends_at']).astimezone(ZoneInfo(seasonal.ZONE))) for row in rows]
    assert [(a.strftime('%m-%d %H:%M'), b.strftime('%H:%M')) for a, b in local] == [
        ('12-23 11:00', '15:30'), ('12-23 16:30', '21:00'), ('12-24 11:00', '15:30'),
        ('12-25 13:00', '17:00'), ('12-26 11:00', '15:30'), ('12-26 16:30', '21:00'),
        ('12-27 11:00', '15:30'), ('12-27 16:30', '21:00'), ('12-28 11:00', '15:30'),
        ('12-28 16:30', '21:00'), ('12-29 11:00', '15:30'), ('12-29 16:30', '21:00'),
        ('12-30 11:00', '15:30'), ('12-30 16:30', '21:00'), ('12-31 11:00', '15:30'),
        ('01-01 13:00', '17:00'), ('01-02 11:00', '15:30'), ('01-02 16:30', '21:00'),
    ]
    assert local[-1][0].year == 2027
    # The separate 09:30 Skating With Santa note is not an ordinary session.
    assert all(a.hour != 9 for a, _ in local)
    assert all(row['venue_address'] == '900 Convention Center Blvd, New Orleans, LA' for row in rows)
    assert all('Halls G–I' in row['venue_name'] for row in rows)
    assert all(row['lat'] is row['lng'] is None for row in rows)
    assert all(row['details_evidence_url'] == seasonal.SOURCES[seasonal.NOLA] for row in rows)
    fetch.assert_called_once_with(seasonal.SOURCES[seasonal.NOLA], 'text/html')


def test_nola_old_edition_does_not_become_current_year():
    soup = BeautifulSoup(payload('nola_2026.html'), 'html.parser')
    soup.select_one('#hours h2').string = '2025 Hours of Operation'
    for card in soup.select('.hours-list'):
        month, weekday = card.select('.month-day > span')
        day = int(card.select_one('.edate').get_text())
        value = datetime(2025 if month.get_text() == 'Dec' else 2026,
                         12 if month.get_text() == 'Dec' else 1, day)
        weekday.string = value.strftime('%a')
    assert seasonal.collect(source(seasonal.NOLA), lambda *_: str(soup), now=NOW) == []


@pytest.mark.parametrize('alteration, error', [
    (lambda s: s.replace('<span>Wed</span>', '<span>Thu</span>', 1), 'date_conflict'),
    (lambda s: s.replace('900 Convention Center Blvd', '400 Calliope Street'), 'schedule_unverified'),
    (lambda s: s.replace('4:30pm - 9:00pm', '2:30pm - 9:00pm', 1), 'session_conflict'),
    (lambda s: s.replace('1:00pm - 5:00pm', 'Hours coming soon', 1), 'session_unverified'),
])
def test_nola_rejects_conflicting_or_unverified_schedules(alteration, error):
    with pytest.raises(ValueError, match=error):
        seasonal.collect(source(seasonal.NOLA), lambda *_: alteration(payload('nola_2026.html')), now=NOW)


def test_city_park_completes_horizon_in_two_pages_with_actual_venues():
    rows, fetch = run_city()
    assert len(rows) == len({row['id'] for row in rows}) == 18
    assert fetch.call_count == 2
    titles = {row['title'] for row in rows}
    assert {'CPC-CPIA Board Meeting', 'Jingle Bells and Beer', 'Holiday Open House'} <= titles
    assert not {'Fit Fête', 'Celebration in the Oaks', 'Merry Maker Mixer'} & titles
    market = next(row for row in rows if row['title'] == 'Crescent City Farmers Market')
    assert market['venue_name'] == 'City Putt, New Orleans City Park'
    assert market['venue_address'] == '33 Dreyfous Drive, New Orleans, LA, 70119'
    assert market['description'] == 'Synthetic market description.'
    beer = next(row for row in rows if row['title'] == 'Jingle Bells and Beer')
    assert beer['venue_address'] == '7 Victory Avenue, New Orleans, LA, 70124'
    assert beer['publisher_details']['audience'] == 'Adults only'
    assert all(row['lat'] is row['lng'] is None for row in rows)
    assert all('2027-01-17' not in row['starts_at'] for row in rows)
    assert all(row['details_evidence_url'] == row['event_url'] for row in rows)


def _alter_events(page, change):
    soup = BeautifulSoup(page, 'html.parser')
    script = soup.select_one('script[type="application/ld+json"]')
    events = json.loads(script.string)
    change(events)
    script.string = json.dumps(events)
    return str(soup)


@pytest.mark.parametrize('change, error', [
    (lambda events: events.pop(), 'incomplete_jsonld'),
    (lambda events: events[1].update(startDate='2026-11-15T09:00:00-06:00'), 'schedule_conflict'),
    (lambda events: events[1].update(startDate='2026-11-15T08:00:00Z'), 'timezone_conflict'),
    (lambda events: events[1].update(url='https://example.org/event/market/'), 'identity_conflict'),
])
def test_city_park_does_not_accept_partial_or_conflicting_jsonld(change, error):
    pages = city_pages()
    root = seasonal.SOURCES[seasonal.CITY_PARK]
    pages[root] = _alter_events(pages[root], change)
    with pytest.raises(ValueError, match=error):
        run_city(pages)


def test_city_park_unknown_venue_does_not_inherit_source_location():
    pages = city_pages()
    root = seasonal.SOURCES[seasonal.CITY_PARK]
    pages[root] = _alter_events(pages[root], lambda events: events[1].update(location={}))
    rows, _ = run_city(pages)
    assert len(rows) == 17
    assert not any('2026-11-15' in row['starts_at'] for row in rows)


def _single_city_page(number, *, next_page=True):
    root = seasonal.SOURCES[seasonal.CITY_PARK]
    day = (NOW + timedelta(days=number)).date()
    canonical = root if number == 1 else root + f'page/{number}/'
    url = f'https://neworleanscitypark.org/event/market/{day}/'
    event = dict(**{'@type': 'Event'}, name='Market', url=url,
                 startDate=f'{day}T08:00:00-06:00', endDate=f'{day}T12:00:00-06:00',
                 location=dict(name='City Putt', address=dict(streetAddress='33 Dreyfous Drive',
                               addressLocality='New Orleans', addressRegion='LA')))
    nav = f'<a class="tribe-events-c-nav__next" href="{root}list/page/{number + 1}/">Next</a>' if next_page else ''
    return f'''<link rel="canonical" href="{canonical}">
    <article class="tribe-events-calendar-list__event">
      <a class="tribe-events-calendar-list__event-title-link" href="{url}">Market</a>
      <time class="tribe-events-calendar-list__event-datetime" datetime="{day}">{day} @ 8:00 am - 12:00 pm</time>
    </article>{nav}<script type="application/ld+json">{json.dumps([event])}</script>'''


def test_city_park_page_bound_raises_instead_of_returning_partial_success():
    root = seasonal.SOURCES[seasonal.CITY_PARK]
    pages = {root if n == 1 else root + f'list/page/{n}/': _single_city_page(n) for n in range(1, 4)}
    with pytest.raises(ValueError, match='incomplete_horizon'):
        run_city(pages)


def test_city_park_complete_third_page_is_valid():
    root = seasonal.SOURCES[seasonal.CITY_PARK]
    pages = {root if n == 1 else root + f'list/page/{n}/': _single_city_page(n, next_page=n != 3) for n in range(1, 4)}
    rows, fetch = run_city(pages)
    assert len(rows) == fetch.call_count == 3


def test_city_park_uses_shared_lookahead_horizon(monkeypatch):
    monkeypatch.setattr('roomquest.preview_worker.LOOKAHEAD_DAYS', 7)
    rows, fetch = run_city()
    assert fetch.call_count == 1
    assert len(rows) == 4


def test_city_park_valid_empty_calendar_is_distinct_from_missing_events():
    root = seasonal.SOURCES[seasonal.CITY_PARK]
    empty = f'<link rel="canonical" href="{root}"><p class="tribe-events-c-messages__message">No upcoming events.</p>'
    assert run_city({root: empty})[0] == []
    with pytest.raises(ValueError, match='calendar_unverified'):
        run_city({root: f'<link rel="canonical" href="{root}"><p>Please enable JavaScript</p>'})


def test_deadline_or_fetch_failure_never_becomes_partial_success(monkeypatch):
    fetch = Mock()
    monkeypatch.setattr(seasonal, 'monotonic', lambda: 101)
    with pytest.raises(ValueError, match='collection_deadline'):
        seasonal.collect(source(seasonal.CITY_PARK), fetch, deadline_at=100, now=NOW)
    fetch.assert_not_called()
    failing = Mock(side_effect=[payload('city_park_page1.html'), TimeoutError('publisher deadline')])
    with pytest.raises(TimeoutError, match='publisher deadline'):
        seasonal.collect(source(seasonal.CITY_PARK), failing, now=NOW)


@pytest.mark.parametrize('key', [seasonal.NOLA, seasonal.CITY_PARK])
def test_preview_dispatch_uses_paced_fetcher_and_publisher_evidence(monkeypatch, key):
    pages = city_pages() if key == seasonal.CITY_PARK else {
        seasonal.SOURCES[key]: payload('nola_2026.html')}
    fetch = Mock(side_effect=lambda url, accept, **kwargs: pages[url])
    monkeypatch.setattr('roomquest.preview_worker.fetch_publisher', fetch)
    preview = preview_source(source(key))
    assert preview['p_future_count'] == 18
    assert preview['p_parser_capability'] == 'publisher_event_candidates_v1'
    assert preview['p_venue_count'] == 0
    for call in fetch.call_args_list:
        assert call.kwargs['respect_robots']
        assert call.kwargs['allowed_hosts'] == seasonal.allowed_hosts(key)
        assert call.kwargs['deadline_at']


def test_exact_source_and_publisher_url_contracts():
    assert seasonal.allowed_hosts(seasonal.NOLA) == {'nolachristmasfest.com'}
    assert seasonal.allowed_hosts(seasonal.CITY_PARK) == {'neworleanscitypark.org'}
    assert seasonal.event_url(seasonal.NOLA, seasonal.SOURCES[seasonal.NOLA])
    assert seasonal.event_url(seasonal.CITY_PARK, 'https://neworleanscitypark.org/event/market/2026-12-06/')
    for url in ('https://neworleanscitypark.org/calendar/',
                'https://neworleanscitypark.org/event/market/?next=https://other.test/',
                'https://neworleanscitypark.org@other.test/event/market/',
                'https://neworleanscitypark.org/event/../calendar/'):
        assert not seasonal.event_url(seasonal.CITY_PARK, url)
    assert seasonal.photo_url(seasonal.CITY_PARK, 'https://neworleanscitypark.org/photo.jpg') is None
    for field, value in [('feed_url', 'https://neworleanscitypark.org/calendar/?ical=1'),
                         ('kind', 'ics'), ('timezone', 'UTC'), ('platform_adapter', 'wordpress')]:
        unregistered = source(seasonal.CITY_PARK)
        unregistered[field] = value
        with pytest.raises(ValueError, match='unregistered_gulf_seasonal'):
            seasonal.collect(unregistered, lambda *_: '', now=NOW)
