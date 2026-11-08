"""Public publisher fixture replay; no network or live database writes."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

from bs4 import BeautifulSoup
import pytest

from roomquest import preview_worker
from roomquest import santee_town_calendar as parser

FIXTURES = Path(__file__).with_name('fixtures') / 'santee_town_calendar'
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
EVENT = 'https://www.townofsantee-sc.org/event/town-santee-christmas-parade'
POSTER = parser.HOST + '/sites/default/files/uploads/News/santee-christmas-parade-poster.png'


class ClockMeta(type):
    def __instancecheck__(cls, value):
        return isinstance(value, datetime)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    class FrozenDatetime(datetime, metaclass=ClockMeta):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(parser, 'datetime', FrozenDatetime)
    monkeypatch.setattr(preview_worker, 'datetime', FrozenDatetime)


def fixture(name):
    return (FIXTURES / name).read_text()


def source():
    return dict(source_key=parser.KEY, feed_url=parser.URL, kind='html',
                platform_adapter='html', timezone=parser.ZONE)


def listed():
    return parser.parse_feed(fixture('calendar_feed.json'), now=NOW)[0]


def detail(body=None, title=None, location=None):
    soup = BeautifulSoup(fixture('parade_detail.html'), 'html.parser')
    if body is not None:
        field = soup.select_one('.node--type-calendar-event .field--name-body')
        field.clear()
        field.append(BeautifulSoup(body, 'html.parser'))
    if title:
        soup.h1.string = title
    if location:
        soup.select_one('.node--type-calendar-event').append(BeautifulSoup(location, 'html.parser'))
    return str(soup)


def collect(feed=None, event=None):
    feed_url = parser.calendar_feed_url(fixture('calendar_page.html'), now=NOW)
    responses = {
        parser.URL: fixture('calendar_page.html'),
        feed_url: fixture('calendar_feed.json') if feed is None else feed,
        EVENT: fixture('parade_detail.html') if event is None else event,
    }
    fetch = Mock(side_effect=lambda url, accept: responses[url])
    return parser.collect(source(), fetch, now=NOW), fetch


def test_fixture_capture_hashes_match():
    for item in json.loads(fixture('capture_manifest.json'))['fixtures']:
        data = (FIXTURES / item['name']).read_bytes()
        assert len(data) == item['bytes']
        assert hashlib.sha256(data).hexdigest() == item['sha256']


def test_observed_calendar_contract_uses_bounded_window_and_guarded_fetches():
    rows, fetch = collect()
    assert len(rows) == 1
    assert fetch.call_args_list[0].args == (parser.URL, 'text/html')
    assert fetch.call_args_list[1].args == (
        parser.HOST + '/vc3-fullcalendar-events-feed?id=events_calendar&display=all_events&start=2026-11-08&end=2027-01-08',
        'application/json')
    assert fetch.call_args_list[2].args == (EVENT, 'text/html')
    assert fetch.call_count == 3


def test_parade_has_truthful_approximate_point_and_no_footer_address():
    row = collect()[0][0]
    assert (row['starts_at'], row['ends_at']) == ('2026-12-12T21:00:00+00:00', '2026-12-12T23:00:00+00:00')
    assert row['id'] == 'santee-town-314'
    assert row['venue_name'] == 'Town of Santee — approximate town center'
    assert (row['venue_address'], row['venue_city']) == ('', 'Santee')
    assert (row['lat'], row['lng']) == (33.484582, -80.48998)
    assert row['location_provenance'] == 'reviewed_town_center_fallback'
    assert row['location_accuracy'] == 'approximate'
    assert row['location_geoid'] == '4563790'
    assert row['location_evidence_url'] == parser.CENSUS_EVIDENCE
    assert row['description'].startswith(parser.APPROXIMATE_DESCRIPTION)
    assert '194 Municipal' not in row['description'] + row['venue_address']
    assert row['publisher_details'] == {}
    assert row['publisher_categories'] == []
    assert row['reason'] is None
    assert row['image_url'] == POSTER
    assert row['image_evidence_url'] == EVENT
    assert 'town-hall' not in row['image_url']
    assert row['details_evidence_url'] == EVENT


@pytest.mark.parametrize('field,value', [
    ('source_key', 'another_town_sc'), ('feed_url', parser.URL + '/'),
    ('kind', 'json'), ('platform_adapter', 'wordpress'), ('timezone', 'UTC'),
])
def test_fallback_is_not_available_to_other_source_contracts(field, value):
    candidate = source()
    candidate[field] = value
    fetch = Mock()
    with pytest.raises(ValueError, match='unregistered_santee'):
        parser.collect(candidate, fetch, now=NOW)
    fetch.assert_not_called()


@pytest.mark.parametrize('replacement', [
    'https://evil.example/calendar', '/different-feed',
])
def test_changed_drupal_feed_contract_is_rejected(replacement):
    payload = fixture('calendar_page.html').replace(parser.FEED_PATH, replacement)
    with pytest.raises(ValueError, match='calendar_contract_changed'):
        parser.calendar_feed_url(payload, now=NOW)


@pytest.mark.parametrize('url', [
    'https://evil.example/event/parade', '//evil.example/event/parade',
    '/event/../event/parade', '/event/parade?redirect=x', '/event/parade/',
    'https://www.townofsantee-sc.org:443/event/parade', '/event/%2e%2e/parade',
])
def test_event_identity_cannot_expand_fetch_scope(url):
    events = json.loads(fixture('calendar_feed.json'))
    events[0]['url'] = url
    with pytest.raises(ValueError, match='event_identity_changed'):
        parser.parse_feed(json.dumps(events), now=NOW)


@pytest.mark.parametrize('change', [
    {'allDay': True}, {'start': '2026-12-12'},
    {'start': '2026-12-12T16:00:00'}, {'end': '2026-12-12T15:00:00-0500'},
])
def test_missing_or_conflicting_clock_evidence_cannot_create_events(change):
    events = json.loads(fixture('calendar_feed.json'))
    events[0].update(change)
    with pytest.raises(ValueError, match='santee_event_time'):
        parser.parse_feed(json.dumps(events), now=NOW)


def test_feed_detail_disagreement_fails_whole_collection():
    payload = fixture('parade_detail.html').replace('2026-12-12T16:00:00-05:00', '2026-12-12T17:00:00-05:00')
    with pytest.raises(ValueError, match='feed_detail_time_conflict'):
        collect(event=payload)


def test_published_body_address_wins_and_still_requires_normal_geocoding():
    row = parser.parse_event(detail('<p>Meet at 194 Municipal Way, Santee, SC 29142.</p>'), listed())
    assert row['venue_address'] == '194 Municipal Way, Santee, SC 29142'
    assert row['lat'] is row['lng'] is None
    assert row['location_provenance'] == 'publisher_event_address_pending_geocode'
    assert 'location_accuracy' not in row
    assert not row['description'].startswith(parser.APPROXIMATE_DESCRIPTION)
    assert row['reason'] == 'missing_verified_venue_geo'


@pytest.mark.parametrize('body', [
    '<p>Mail parade entry forms to 194 Municipal Way, Santee, SC 29142.</p>',
    '<p>Registration office: 194 Municipal Way, Santee, SC 29142. Parade location to be announced.</p>',
    '<p>194 Municipal Way, Santee, SC 29142.</p>',
    '<p>Send entries for the event at 194 Municipal Way, Santee, SC 29142.</p>',
])
def test_contact_or_ambiguous_body_address_is_never_promoted_to_the_event_venue(body):
    with pytest.raises(ValueError, match='santee_event_location_context_required'):
        parser.parse_event(detail(body), listed())


def test_published_structured_address_wins_over_fallback():
    event = {'@type': 'Event', 'name': listed()['title'], 'url': EVENT,
             'location': {'@type': 'Place', 'name': 'Actual event room',
                          'address': {'@type': 'PostalAddress', 'streetAddress': '194 Municipal Way',
                                      'addressLocality': 'Santee', 'addressRegion': 'SC', 'postalCode': '29142'}}}
    payload = fixture('parade_detail.html').replace('</head>', '<script type="application/ld+json">' + json.dumps(event) + '</script></head>')
    row = parser.parse_event(payload, listed())
    assert row['venue_name'] == 'Actual event room'
    assert row['venue_address'] == '194 Municipal Way, Santee, SC 29142'
    assert row['lat'] is row['lng'] is None


def test_explicit_structured_third_party_organizer_cannot_get_town_fallback():
    event = {'@type': 'Event', 'name': listed()['title'], 'url': EVENT,
             'organizer': {'@type': 'Organization', 'name': 'Example Club'}}
    payload = fixture('parade_detail.html').replace('</head>', '<script type="application/ld+json">' + json.dumps(event) + '</script></head>')
    with pytest.raises(ValueError, match='town_run_evidence_required'):
        parser.parse_event(payload, listed())


def test_explicit_online_event_is_not_assigned_a_town_pin():
    event = {'@type': 'Event', 'name': listed()['title'], 'url': EVENT,
             'eventAttendanceMode': 'https://schema.org/OnlineEventAttendanceMode'}
    payload = fixture('parade_detail.html').replace('</head>', '<script type="application/ld+json">' + json.dumps(event) + '</script></head>')
    assert parser.parse_event(payload, listed()) is None


def test_published_drupal_address_fields_are_used():
    location = '<div class="field--name-field-location"><span class="street-address">194 Municipal Way</span><span class="locality">Santee</span><span class="administrative-area">SC</span><span class="postal-code">29142</span></div>'
    row = parser.parse_event(detail(location=location), listed())
    assert row['venue_address'] == '194 Municipal Way, Santee, SC 29142'
    assert row['lat'] is None


@pytest.mark.parametrize('body', [
    '<p>Meet at 194 Municipal Way.</p>',
    '<p>Offsite holiday celebration.</p>',
    '<p>Organized by Example Club.</p>',
])
def test_incomplete_addresses_and_non_town_or_offsite_events_do_not_get_fallback(body):
    with pytest.raises(ValueError, match='published_address_incomplete|town_run_evidence_required'):
        parser.parse_event(detail(body), listed())


def test_guest_calendar_listing_without_town_organizer_is_held():
    item = listed()
    item['title'] = 'Community Toy Drive'
    with pytest.raises(ValueError, match='town_run_evidence_required'):
        parser.parse_event(detail(title=item['title']), item)


def test_explicit_offsite_address_is_retained_without_town_point():
    row = parser.parse_event(detail('<p>Offsite event at 309 Avian Pavilion Lane, Ridgeville, SC 29472.</p>'), listed())
    assert row['venue_city'] == 'Ridgeville'
    assert row['lat'] is row['lng'] is None
    assert row['venue_address'] == '309 Avian Pavilion Lane, Ridgeville, SC 29472'


def test_cancellation_and_private_events_are_not_mapped():
    assert parser.parse_event(detail('<p>This event is cancelled.</p>'), listed()) is None
    assert parser.parse_event(detail('<p>Private party; invitation-only.</p>'), listed()) is None


def test_empty_complete_feed_is_distinct_from_malformed_response():
    rows, fetch = collect(feed='[]')
    assert rows == []
    assert fetch.call_count == 2
    for payload in ['{}', 'null', '<html>temporarily unavailable</html>']:
        with pytest.raises(ValueError, match='santee_feed_invalid'):
            collect(feed=payload)


def test_outside_horizon_and_ended_occurrences_do_not_fetch_details():
    events = json.loads(fixture('calendar_feed.json'))
    events[0].update(start='2027-04-12T16:00:00-0400', end='2027-04-12T18:00:00-0400')
    assert collect(feed=json.dumps(events))[1].call_count == 2
    events[0].update(start='2026-10-12T16:00:00-0400', end='2026-10-12T18:00:00-0400')
    assert collect(feed=json.dumps(events))[0] == []


def test_duplicate_or_oversized_feed_is_not_a_complete_snapshot():
    events = json.loads(fixture('calendar_feed.json'))
    with pytest.raises(ValueError, match='duplicate_occurrence'):
        parser.parse_feed(json.dumps(events + deepcopy(events)), now=NOW)
    with pytest.raises(ValueError, match='feed_invalid'):
        parser.parse_feed(json.dumps(events * (parser.MAX_RECORDS + 1)), now=NOW)


def test_network_failures_and_exhausted_deadlines_are_not_successful_empty(monkeypatch):
    fetch = Mock(side_effect=TimeoutError('guarded transport timeout'))
    with pytest.raises(TimeoutError, match='guarded transport'):
        parser.collect(source(), fetch, now=NOW)
    fetch = Mock()
    with pytest.raises(TimeoutError, match='santee_collection_deadline'):
        parser.collect(source(), fetch, deadline_at=0, now=NOW)
    fetch.assert_not_called()
    clock = [100.0]
    monkeypatch.setattr(parser, 'monotonic', lambda: clock[0])

    def slow_fetch(url, accept):
        clock[0] = 131.0
        return fixture('calendar_page.html')
    with pytest.raises(TimeoutError, match='santee_collection_deadline'):
        parser.collect(source(), slow_fetch, now=NOW)
