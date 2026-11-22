from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup
import pytest

from roomquest import registered_listings as listings
from roomquest import registered_schedule_calendars as schedules
from roomquest.feed_registration import classify, register
from roomquest.preview_worker import PreviewError
from roomquest.publisher_robots_policy import PublisherRobotsPolicy

FIXTURES = Path(__file__).parent / 'fixtures' / 'registered_schedules'
TODAY = date(2026, 11, 22)


class FrozenMeta(type):
    def __instancecheck__(cls, value):
        return isinstance(value, datetime)


class FrozenDateTime(datetime, metaclass=FrozenMeta):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 11, 22, 12, tzinfo=timezone.utc)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def freeze_clock(monkeypatch):
    monkeypatch.setattr('roomquest.preview_worker.datetime', FrozenDateTime)
    monkeypatch.setattr(listings, 'datetime', FrozenDateTime)


def body(name):
    return (FIXTURES / (name + '.html')).read_text()


def soup(name):
    return BeautifulSoup(body(name), 'html.parser')


def source(url):
    return {'feed_url': url, 'source_key': listings.source_key(url)}


def test_observed_forest_schedule_retains_only_explicit_dates_hours_and_address():
    rows = list(schedules.forest(soup('forest'), TODAY))
    assert [row['starts_at'] for row in rows] == ['2026-12-12T14:00:00+00:00', '2027-01-09T14:00:00+00:00']
    assert [row['ends_at'] for row in rows] == ['2026-12-12T17:00:00+00:00', '2027-01-09T17:00:00+00:00']
    assert all(row['timezone'] == 'America/New_York' for row in rows)
    assert all(row['venue_address'] == '15583 Forest Road, Forest, VA 24551'
               and row['lat'] is None and row['lng'] is None for row in rows)
    assert len(schedules.explicit_year_schedule(schedules.text(soup('forest').select_one('[data-testid]')))) == 7


def test_generic_weekly_text_does_not_expand_the_market_schedule():
    page = BeautifulSoup(body('forest') + '<p>Visit us every Saturday, all season long.</p>', 'html.parser')
    assert list(schedules.forest(page, TODAY)) == list(schedules.forest(soup('forest'), TODAY))


@pytest.mark.parametrize('label', [
    'December 12 9am to noon',
    '2026 SEASON December 12',
    '2026 SEASON Every Saturday 9am to noon',
    '2026 SEASON December 12 9am to noon December 12 10am to noon',
    '2026 SEASON December 12 noon to 9am',
    '2026 SEASON December 32 9am to noon',
])
def test_incomplete_or_conflicting_market_schedule_is_held(label):
    with pytest.raises(ValueError):
        schedules.explicit_year_schedule(label)


@pytest.mark.parametrize('before,after', [
    ('15583 Forest Road', '15585 Forest Road'),
    ('2026 SEASON', 'SEASON'),
])
def test_market_requires_current_address_and_explicit_year(before, after):
    with pytest.raises(ValueError):
        list(schedules.forest(BeautifulSoup(body('forest').replace(before, after), 'html.parser'), TODAY))


def test_responsive_market_schedule_conflict_is_held():
    changed = body('forest').replace('December 12', 'December 19', 1)
    with pytest.raises(ValueError, match='market_schedule_conflict'):
        list(schedules.forest(BeautifulSoup(changed, 'html.parser'), TODAY))


def test_forest_registered_source_reuses_listing_without_more_network():
    with patch('roomquest.registered_listings.datetime', FrozenDateTime):
        rows = listings.collect(source(schedules.FOREST), lambda *_: pytest.fail('unexpected fetch'), listing=body('forest'))
    assert len(rows) == 2


def test_observed_algonquin_list_has_17_performances_and_only_six_detail_fetches():
    requests = []
    def fetch(url, accept):
        requests.append((url, accept))
        return body('algonquin-' + url.split('=')[1])
    rows = listings.collect(source(schedules.ALGONQUIN), fetch, listing=body('algonquin-listing'))
    assert len(rows) == 17
    assert all(row['timezone'] == 'America/New_York' for row in rows)
    assert [url for url, _ in requests] == [schedules.ALGONQUIN + '?id=' + value
                                           for value in ('424', '407', '441', '425', '416', '408')]
    assert all(accept == 'text/html' for _, accept in requests)
    assert all(row['venue_address'] == '60 Abe Voorhees Drive, Manasquan, NJ 08736'
               and row['ends_at'] is None and row['lat'] is None and row['lng'] is None for row in rows)
    frozen = [row for row in rows if row['title'] == "Disney's Frozen"]
    assert len(frozen) == 10
    assert len({row['id'] for row in frozen}) == 10
    assert len([row for row in rows if row['title'].startswith('Zepplin')]) == 2
    assert not any(row['starts_at'].startswith('2027-01-22') for row in rows)
    assert 'No one under the age of four' in rows[0]['description']


@pytest.mark.parametrize('before,after,reason', [
    ('Sunday, November 22, 2026', 'Sunday, November 22', 'date_range'),
    ('60 Abe Voorhees Drive', '62 Abe Voorhees Drive', 'address'),
    ('3:00 PM', 'Doors 3:00 PM', 'performance_time'),
    ('Sunday, November 22</div>', 'Monday, November 22</div>', 'performance_date'),
    ('Sunday, November 22</div>', 'Sunday, November 29</div>', 'performance_date'),
    ('Christmas with the King', 'Different performance', 'title'),
])
def test_theatre_ambiguous_or_changed_evidence_is_held(before, after, reason):
    page = BeautifulSoup(body('algonquin-424').replace(before, after), 'html.parser')
    with pytest.raises(ValueError, match=reason):
        list(schedules.theatre_performances(page, schedules.ALGONQUIN + '?id=424', 'Christmas with the King', TODAY))


def test_theatre_detail_targets_are_exact_same_host_and_bounded():
    invalid = body('algonquin-listing').replace('calendar.php?id=424', 'https://other.example/calendar.php?id=424')
    with pytest.raises(ValueError, match='detail_url'):
        list(schedules.algonquin(BeautifulSoup(invalid, 'html.parser'), lambda *_: pytest.fail('fetch before validation'), TODAY))
    cards = ''.join('<div class="calendar-full-container"><div class="calendar-full-title">'
                    f'<a href="calendar.php?id={n}">Show {n}</a></div>'
                    '<div class="calendar-full-dates">December 1</div></div>' for n in range(1, 14))
    with pytest.raises(ValueError, match='detail_limit'):
        list(schedules.algonquin(BeautifulSoup(cards, 'html.parser'), lambda *_: pytest.fail('unbounded fetch'), TODAY))


def test_theatre_deadline_stops_before_request():
    with pytest.raises(ValueError, match='source_fetch_deadline'):
        list(schedules.algonquin(soup('algonquin-listing'), lambda *_: pytest.fail('expired fetch'), TODAY, deadline_at=0))


def test_theatre_does_not_infer_year_for_listing_without_detail():
    assert schedules.dated_span('December 5 - December 20', optional_year=True) is None
    with pytest.raises(ValueError, match='date_range'):
        schedules.dated_span('December 5 - December 20')
    assert schedules.dated_span('December 5 - December 20, 2026') == (date(2026, 12, 5), date(2026, 12, 20))


def test_theatre_explicit_listing_and_detail_years_must_agree():
    with pytest.raises(ValueError, match='date_range_conflict'):
        list(schedules.theatre_performances(soup('algonquin-424'), schedules.ALGONQUIN + '?id=424',
             'Christmas with the King', TODAY, (date(2027, 11, 22), date(2027, 11, 22))))


@pytest.mark.parametrize('url', schedules.URLS)
def test_unregistered_or_mismatched_source_identity_is_rejected(url):
    with pytest.raises(ValueError, match='unregistered_html_source'):
        listings.collect(dict(source(url), source_key='other'), lambda *_: pytest.fail('network before identity check'))
    with pytest.raises(ValueError, match='unregistered_html_source'):
        listings.collect(source(url + '?private=true'), lambda *_: pytest.fail('network before identity check'))


def test_algonquin_navigation_requires_actual_link_from_exact_original_url():
    origin = 'https://www.algonquinarts.org/'
    link = '<a href="/calendar.php">Shows</a>'
    assert classify(origin, link) == {'calendar_page': schedules.ALGONQUIN}
    assert 'calendar_page' not in classify(origin, '<p>No calendar</p>')
    assert 'calendar_page' not in classify(origin, link, endpoint_only=True)
    assert 'calendar_page' not in classify(origin + '?venue=other', link)
    assert 'calendar_page' not in classify('https://www.algonquinarts.org.attacker.test/', link)


@pytest.mark.parametrize('url,expected', [(schedules.FOREST, 'verified'),
    (schedules.GRAVEGARDEN, 'verified'), ('https://www.algonquinarts.org/', 'discovered')])
def test_normal_registration_automatically_validates_adapter_and_preserves_robots(url, expected):
    calls = []
    def fetch(target, accept, **kwargs):
        calls.append((target, kwargs))
        if target == schedules.FOREST:
            return body('forest')
        if target == schedules.GRAVEGARDEN:
            return body('gravegarden')
        if target == 'https://www.algonquinarts.org/':
            return '<a href="/calendar.php">Shows</a>'
        if target == schedules.ALGONQUIN:
            return body('algonquin-listing')
        return body('algonquin-' + target.split('=')[1])
    with patch('roomquest.feed_registration.supabase_rpc', side_effect=[{'url': url}, True]) as rpc, \
         patch('roomquest.feed_registration.fetch_publisher', side_effect=fetch):
        assert register('ticket') == {'outcome': expected}
    result = rpc.call_args.args[1]
    assert result['p_type'] == 'html'
    assert result['p_endpoint'] == (schedules.ALGONQUIN if expected == 'discovered' else url)
    assert len(calls) == (8 if expected == 'discovered' else 1)
    assert all(kwargs['respect_robots'] and kwargs['deadline_at'] for _, kwargs in calls)
    assert all(kwargs['allowed_hosts'] == ('www.algonquinarts.org',) for _, kwargs in calls[1:])


@pytest.mark.parametrize('reason,outcome', [('robots_denied', 'disabled'), ('publisher_http_403', 'disabled'), ('publisher_rate_limited', 'retry')])
def test_normal_registration_keeps_access_holds(reason, outcome):
    pages = ['<a href="/calendar.php">Shows</a>', body('algonquin-listing'), PreviewError(reason)]
    with patch('roomquest.feed_registration.supabase_rpc', side_effect=[{'url': 'https://www.algonquinarts.org/'}, True]), \
         patch('roomquest.feed_registration.fetch_publisher', side_effect=pages):
        assert register('ticket')['outcome'] == outcome


def test_captured_robots_permits_only_the_reviewed_requests():
    for name, urls in [('forest', [schedules.FOREST]), ('gravegarden', [schedules.GRAVEGARDEN]),
                       ('algonquin', ['https://www.algonquinarts.org/', schedules.ALGONQUIN, schedules.ALGONQUIN + '?id=424'])]:
        policy = PublisherRobotsPolicy((FIXTURES / (name + '-robots.txt')).read_text().splitlines())
        assert all(policy.can_fetch('RoomQuestCommunityCalendar', url) for url in urls)


def test_observed_cemetery_expands_only_explicit_nightly_bounds_and_noon_ceremony():
    rows = listings.collect(source(schedules.GRAVEGARDEN), lambda *_: pytest.fail('unexpected fetch'), listing=body('gravegarden'))
    assert len(rows) == 30
    assert all(row['timezone'] == 'America/New_York' for row in rows)
    nightly = [row for row in rows if row['title'].startswith('Grand Illumination')]
    assert len(nightly) == 29
    assert nightly[0]['starts_at'] == '2026-12-04T22:00:00+00:00'
    assert nightly[-1]['starts_at'] == '2027-01-01T22:00:00+00:00'
    assert nightly[-1]['ends_at'] == '2027-01-02T00:00:00+00:00'
    ceremony = next(row for row in rows if row['title'] == 'Wreaths Across America Ceremony')
    assert ceremony['starts_at'] == '2026-12-19T17:00:00+00:00'
    assert ceremony['ends_at'] is None and ceremony['venue_name'] == 'Old City Cemetery Chapel'
    assert all(row['venue_address'] == '401 Taylor Street, Lynchburg, VA 24501'
               and row['lat'] is None and row['lng'] is None for row in rows)


@pytest.mark.parametrize('before,after', [
    ('nightly', 'on selected evenings'),
    ('December 2026', 'December'),
    ('401 Taylor Street', '403 Taylor Street'),
    ('5:00 pm', '5:00'),
    ('January 1', 'April 1'),
    ('Noon.', 'Afternoon.'),
    ('NEW!', 'NEW! Cancelled.'),
])
def test_cemetery_missing_year_bounds_hours_or_location_is_held(before, after):
    changed = BeautifulSoup(body('gravegarden').replace(before, after), 'html.parser')
    with pytest.raises(ValueError):
        list(schedules.gravegarden(changed, TODAY))


def test_nightly_expansion_is_bounded_and_inclusive():
    assert list(schedules.bounded_nightly_dates(date(2026, 12, 30), date(2027, 1, 1), date(2026, 12, 31))) == [date(2026, 12, 31), date(2027, 1, 1)]
    with pytest.raises(ValueError, match='nightly_season'):
        list(schedules.bounded_nightly_dates(date(2026, 12, 1), date(2027, 6, 1), TODAY))


def test_cemetery_final_january_night_survives_its_december_heading():
    rows = list(schedules.gravegarden(soup('gravegarden'), date(2027, 1, 1)))
    assert len(rows) == 1 and rows[0]['starts_at'] == '2027-01-01T22:00:00+00:00'
