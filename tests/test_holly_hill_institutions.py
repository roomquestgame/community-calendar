"""Publisher fixtures, location boundaries, class-session semantics and holds."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from unittest.mock import Mock

from bs4 import BeautifulSoup
from icalendar import Calendar
import pytest

from roomquest import holly_hill_institutions as parser
from roomquest import ics_adapter, preview_worker

FIXTURES = Path(__file__).with_name('fixtures') / 'holly_hill_institutions'
NOW = datetime(2026, 11, 8, 2, 7, tzinfo=timezone.utc)


class ClockMeta(type):
    def __instancecheck__(cls, value):
        return isinstance(value, datetime)


def freeze(monkeypatch, value):
    class FrozenDatetime(datetime, metaclass=ClockMeta):
        @classmethod
        def now(cls, tz=None):
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)
    for module in (parser, ics_adapter, preview_worker):
        monkeypatch.setattr(module, 'datetime', FrozenDatetime)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    freeze(monkeypatch, NOW)


def source(key):
    kind = 'ical' if key in parser.ICS else 'html'
    return dict(source_key=key, feed_url=parser.SOURCES[key], kind=kind,
                platform_adapter=kind, timezone=parser.ZONE)


def fixture(name):
    return (FIXTURES / name).read_text()


def calendar(name='st_george.ics'):
    return Calendar.from_ical(fixture(name))


def collect_calendar(cal, key=parser.ST_GEORGE):
    return parser.collect_ics(source(key), cal.to_ical().decode())


def listing():
    return parser._listing(fixture('octech_browse.html'), 1)[0][0]


def course(value=None):
    return parser.parse_course(str(value) if value is not None else fixture('defensive-driving17.html'), listing())


def test_st_george_real_feed_preserves_narrative_and_literal_location():
    rows = collect_calendar(calendar())
    assert len(rows) == 3
    assert {row['venue_address'] for row in rows} == {'506 N Parler Ave, St. George, SC 29477'}
    assert all(row['timezone'] == 'America/New_York' for row in rows)
    assert rows[0]['starts_at'] == '2026-11-09T15:00:00+00:00'
    assert rows[0]['description'].startswith('Fitness program for senior adults.')
    assert rows[0]['event_url'] == 'https://dorchesterlibrarysc.libcal.com/event/17312240'
    assert rows[0]['publisher_categories'] == []
    assert all(row['lat'] is None and row['lng'] is None and 'image_url' not in row for row in rows)
    assert not any('CLOSED' in row['title'] or 'Closed' in row['title'] for row in rows)


def test_moncks_offsite_fair_keeps_its_actual_college_venue():
    rows = collect_calendar(calendar('moncks_corner.ics'), parser.MONCKS)
    assert len(rows) == 3
    fair = next(row for row in rows if 'Career Fair' in row['title'])
    assert fair['venue_name'] == 'Trident Technical College Thornley Campus'
    assert fair['venue_address'] == '7000 Rivers Avenue, Building 410, 2nd Floor, North Charleston, SC 29406'
    assert fair['venue_city'] == 'North Charleston'
    assert fair['starts_at'] == '2026-11-10T15:00:00+00:00'
    assert 'General Public: 10:30 A.M.' in fair['description']
    story = next(row for row in rows if row['title'] == 'Storytime')
    assert story['venue_address'] == '1003 Highway 52, Moncks Corner, SC 29461'
    assert story['publisher_categories'] == ['Children']
    assert story['category'] == 'Children'


@pytest.mark.parametrize('location', ['', 'Activity Room', 'Unknown Community Park'])
def test_unknown_or_missing_location_is_never_assigned_branch_address(location):
    cal = calendar()
    event = cal.walk('VEVENT')[0]
    event['LOCATION'] = location
    row = next(row for row in collect_calendar(cal) if row['id'] == str(event['UID']))
    assert row['venue_name'] == location
    assert row['venue_address'] == row['venue_city'] == ''
    assert row['lat'] is row['lng'] is None


def test_explicit_offsite_location_survives_without_branch_substitution():
    cal = calendar()
    event = cal.walk('VEVENT')[0]
    event['LOCATION'] = 'Community Hall, 20 Main Street, Eutawville, SC 29048'
    row = next(row for row in collect_calendar(cal) if row['id'] == str(event['UID']))
    assert (row['venue_name'], row['venue_address'], row['venue_city']) == (
        'Community Hall', '20 Main Street, Eutawville, SC 29048', 'Eutawville')


def test_private_cancelled_and_long_description_private_notice_are_excluded():
    cal = calendar()
    events = cal.walk('VEVENT')
    events[0]['CLASS'] = 'PRIVATE'
    events[1]['SUMMARY'] = 'Postponed: Coffee Talk with Ms. Darlene - St. George'
    events[3]['DESCRIPTION'] = 'Program background. ' * 300 + 'Private event.'
    assert collect_calendar(cal) == []


def test_published_closure_blocks_a_conflicting_branch_program():
    cal = calendar()
    event = cal.walk('VEVENT')[0]
    event['DTSTART'].dt = datetime(2026, 11, 11, 15, tzinfo=timezone.utc)
    event['DTEND'].dt = datetime(2026, 11, 11, 16, tzinfo=timezone.utc)
    rows = collect_calendar(cal)
    assert len(rows) == 2
    assert str(event['UID']) not in {row['id'] for row in rows}


def test_closure_does_not_cancel_an_explicit_offsite_program():
    cal = calendar()
    event = cal.walk('VEVENT')[0]
    event['DTSTART'].dt = datetime(2026, 11, 11, 15, tzinfo=timezone.utc)
    event['DTEND'].dt = datetime(2026, 11, 11, 16, tzinfo=timezone.utc)
    event['LOCATION'] = 'Community Hall, 20 Main Street, Eutawville, SC 29048'
    assert str(event['UID']) in {row['id'] for row in collect_calendar(cal)}


def test_date_only_public_program_is_not_given_an_invented_time():
    cal = calendar('moncks_corner.ics')
    cal.subcomponents = [e for e in cal.walk('VEVENT') if 'Cypress Gardens' in str(e['SUMMARY'])]
    with pytest.raises(ValueError, match='unsupported_all_day_time'):
        collect_calendar(cal, parser.MONCKS)


def test_library_identity_and_timezone_fail_closed():
    cal = calendar()
    cal.walk('VEVENT')[0]['URL'] = 'https://other.example/event/17312240'
    with pytest.raises(ValueError, match='library_event_identity_unverified'):
        collect_calendar(cal)
    cal = calendar()
    cal.subcomponents = cal.walk('VEVENT')[:1]
    cal.walk('VEVENT')[0]['DTSTART'].dt = datetime(2026, 11, 9, 15)
    with pytest.raises(ValueError, match='timezone_unresolved'):
        collect_calendar(cal)


@pytest.mark.parametrize('field,value', [
    ('feed_url', 'https://other.example/feed.ics'), ('timezone', 'UTC'),
    ('kind', 'html'), ('platform_adapter', 'library'), ('source_key', 'unknown_library'),
])
def test_source_tuple_guard_runs_before_fetch(field, value):
    config = source(parser.ST_GEORGE)
    config[field] = value
    fetch = Mock()
    with pytest.raises(ValueError, match='unregistered_holly_hill_institution'):
        parser.collect(config, fetch)
    fetch.assert_not_called()


def test_library_collect_only_uses_injected_feed_fetch():
    fetch = Mock(return_value=fixture('st_george.ics'))
    assert len(parser.collect(source(parser.ST_GEORGE), fetch)) == 3
    fetch.assert_called_once_with(parser.ICS[parser.ST_GEORGE], 'text/calendar')


def test_real_course_has_two_four_hour_sessions_not_continuous_multiday_time():
    rows = course()
    assert [(row['starts_at'], row['ends_at']) for row in rows] == [
        ('2026-11-10T23:00:00+00:00', '2026-11-11T03:00:00+00:00'),
        ('2026-11-12T23:00:00+00:00', '2026-11-13T03:00:00+00:00'),
    ]
    assert len({row['id'] for row in rows}) == 2
    assert all(row['event_url'].endswith('/course/defensive-driving17') for row in rows)
    assert all(row['venue_address'] == '3250 St. Matthews Road, Orangeburg, SC 29118' for row in rows)
    assert all(row['venue_city'] == 'Orangeburg' and row['timezone'] == parser.ZONE for row in rows)
    assert 'Room: T-0115' in rows[0]['description']
    assert 'Tue and Thu' in rows[0]['description']
    assert all(row['lat'] is row['lng'] is None and 'image_url' not in row for row in rows)


@pytest.mark.parametrize('old,new,error', [
    ('Tue and Thu', 'Tue and Wed', 'octech_schedule_conflict'),
    ('6:00 - 10:00 pm', '7:00 - 10:00 pm', 'octech_schedule_conflict'),
    ('6:00 - 10:00 pm', '11:00 - 1:00 pm', 'octech_time_unresolved'),
    ('6:00 - 10:00 pm', 'Evening session', 'octech_time_unresolved'),
    ('Tue and Thu', 'Whenever convenient', 'octech_weekdays_unresolved'),
    ('3250 St. Matthews Road, Orangeburg, SC 29118', '3250 St. Matthews Road, Another Town, SC 29118', 'octech_venue_unverified'),
    ('Continuing Education<br/>3250 St. Matthews Road', 'Continuing Education<br/>99 Different Road', 'octech_venue_unverified'),
])
def test_course_conflicting_or_incomplete_evidence_is_held(old, new, error):
    payload = fixture('defensive-driving17.html')
    assert old in payload
    with pytest.raises(ValueError, match=error):
        course(payload.replace(old, new))


def test_course_schema_address_conflict_is_not_repaired_from_footer():
    soup = BeautifulSoup(fixture('defensive-driving17.html'), 'html.parser')
    block = soup.select_one('script[type="application/ld+json"]')
    data = json.loads(block.string)
    event = next(node for node in data['@graph'] if node['@type'] == 'Event')
    event['location']['address']['addressLocality'] = '99 Different Road'
    block.string = json.dumps(data)
    with pytest.raises(ValueError, match='octech_venue_conflict'):
        course(soup)


def test_course_listing_time_must_match_an_advertised_session():
    item = listing()
    item['next_start'] += timedelta(hours=1)
    with pytest.raises(ValueError, match='octech_listing_detail_conflict'):
        parser.parse_course(fixture('defensive-driving17.html'), item)


def test_course_private_or_cancelled_notice_is_read_before_truncation():
    soup = BeautifulSoup(fixture('defensive-driving17.html'), 'html.parser')
    soup.select_one('.description').append('Background. ' * 300 + 'This class is cancelled.')
    assert course(soup) == []


def test_bounded_course_collection_filters_later_pages_before_detail_fetch():
    soup = BeautifulSoup(fixture('octech_browse.html'), 'html.parser')
    soup.select('.course-item')[1].decompose()  # Isolate one real eligible detail.
    responses = {parser.HTML[parser.OCTECH]: str(soup), listing()['url']: fixture('defensive-driving17.html')}
    fetch = Mock(side_effect=lambda url, accept: responses[url])
    assert len(parser.collect_html(source(parser.OCTECH), fetch, now=NOW)) == 2
    assert [call.args[0] for call in fetch.call_args_list] == [parser.HTML[parser.OCTECH], listing()['url']]
    assert all(call.args[1] == 'text/html' for call in fetch.call_args_list)


def test_empty_second_detail_does_not_report_partial_healthy_catalog():
    responses = {parser.HTML[parser.OCTECH]: fixture('octech_browse.html'),
                 listing()['url']: fixture('defensive-driving17.html'),
                 'https://octech.coursestorm.com/course/defensive-driving18': ''}
    fetch = Mock(side_effect=lambda url, accept: responses[url])
    with pytest.raises(ValueError, match='octech_document_invalid'):
        parser.collect_html(source(parser.OCTECH), fetch, now=NOW)
    assert fetch.call_count == 3


def test_listing_order_or_unsafe_pagination_cannot_hide_future_courses():
    soup = BeautifulSoup(fixture('octech_browse.html'), 'html.parser')
    cards = soup.select('.course-item')
    cards[0].insert_before(cards[1])
    with pytest.raises(ValueError, match='octech_listing_order_conflict'):
        parser._listing(str(soup), 1)
    text = fixture('octech_browse.html').replace('/browse?page=2', 'https://other.example/browse?page=2')
    with pytest.raises(ValueError, match='octech_pagination_unverified'):
        parser._listing(text, 1)


def test_changed_detail_host_and_expired_deadline_are_rejected():
    text = fixture('octech_browse.html').replace('https://octech.coursestorm.com/course/defensive-driving17',
                                               'https://other.example/course/defensive-driving17')
    with pytest.raises(ValueError, match='octech_listing_event_unverified'):
        parser._listing(text, 1)
    fetch = Mock()
    with pytest.raises(ValueError, match='collection_deadline'):
        parser.collect_html(source(parser.OCTECH), fetch, deadline_at=0.1, now=NOW)
    fetch.assert_not_called()


def test_cane_bay_real_past_calendar_is_empty_without_generated_first_fridays():
    fetch = Mock(return_value=fixture('cane_bay_events.html'))
    assert parser.collect_html(source(parser.CANE_BAY), fetch, now=NOW) == []
    fetch.assert_called_once_with(parser.HTML[parser.CANE_BAY], 'text/html')


def test_cane_bay_dated_cards_keep_actual_times_and_do_not_default_unknown_venues(monkeypatch):
    before_events = datetime(2026, 10, 1, tzinfo=timezone.utc)
    freeze(monkeypatch, before_events)
    rows = parser.parse_cane_bay(fixture('cane_bay_events.html'), now=before_events)
    assert len(rows) == 4
    fall = next(row for row in rows if row['title'] == 'Fall Community Extravaganza')
    assert fall['starts_at'] == '2026-10-31T16:00:00+00:00'
    assert fall['ends_at'] == '2026-10-31T19:00:00+00:00'
    assert fall['venue_address'] == '1655 Cane Bay Blvd., Summerville, SC 29486'
    coffee = next(row for row in rows if 'Coffee' in row['title'])
    assert coffee['starts_at'] == '2026-11-06T15:00:00+00:00'
    assert coffee['ends_at'] == '2026-11-06T17:00:00+00:00'
    assert coffee['event_url'] == parser.HTML[parser.CANE_BAY]
    assert coffee['venue_address'] == '' and coffee['lat'] is coffee['lng'] is None
    assert len({row['id'] for row in rows}) == 4


@pytest.mark.parametrize('old,new,error', [
    ('November 6, 2026', 'November 6', 'cane_bay_date_unresolved'),
    ('10:00 AM - 12:00 PM', 'Morning', 'octech_time_unresolved'),
    ('https://ymcagc.org/events/discover-cane-bay/', 'https://other.example/events/discover-cane-bay/', 'cane_bay_event_identity_unverified'),
    ('CANE BAY YMCA UPCOMING EVENTS', 'Page not available', 'cane_bay_calendar_unverified'),
])
def test_cane_bay_invalid_payload_is_not_reported_as_healthy_empty(old, new, error):
    text = fixture('cane_bay_events.html')
    assert old in text
    with pytest.raises(ValueError, match=error):
        parser.parse_cane_bay(text.replace(old, new), now=NOW)
