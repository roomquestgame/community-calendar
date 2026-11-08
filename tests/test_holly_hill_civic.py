"""Replay reviewed publisher data; reject incomplete/ambiguous local calendars."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from bs4 import BeautifulSoup

from roomquest import holly_hill_civic as h
from roomquest import preview_worker

FIXTURES = Path(__file__).parent / 'fixtures' / 'holly_hill_civic'
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    class DateMeta(type):
        def __instancecheck__(cls, instance):
            return isinstance(instance, datetime)
    class Frozen(datetime, metaclass=DateMeta):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(preview_worker, 'datetime', Frozen)


def fixture(name):
    return (FIXTURES / name).read_text()


def source(key):
    spec = h.SOURCES[key]
    return {'source_key': key, 'feed_url': spec['url'], 'kind': spec['kind'],
            'platform_adapter': spec['adapter'], 'timezone': h.ZONE}


def listing():
    return json.loads(BeautifulSoup(fixture('santee_calendar.html'), 'html.parser').script.string)


def santee_document(events):
    wrappers = [{'@type': 'ListItem', 'position': i, 'url': e['url'], 'item': e}
                for i, e in enumerate(events, 1)]
    return '<script type="application/ld+json">' + json.dumps({
        '@type': 'ItemList', 'numberOfItems': len(events), 'itemListElement': wrappers}) + '</script>'


def public_santee_event():
    return deepcopy(next(x['item'] for x in listing()['itemListElement']
                         if 'veterans-day-orangeburg-district' in x['url']))


def tec_event():
    return deepcopy(next(e for e in json.loads(fixture('sc250.json'))['events'] if e['id'] == 66231))


def test_santee_live_capture_preserves_corrected_times_and_source_evidence(caplog):
    fetch = Mock(return_value=fixture('santee_calendar.html'))
    rows = h.collect_santee(source(h.SANTEE), fetch, now=NOW)
    assert len(rows) == 46
    assert len({(e['id'], e['starts_at']) for e in rows}) == len(rows)
    by_url = {e['event_url']: e for e in rows}
    tour = next(e for u, e in by_url.items() if 'veterans-day-orangeburg-district' in u)
    roast = next(e for u, e in by_url.items() if 'veterans-day-oyster-roast' in u)
    assert tour['starts_at'] == '2026-11-11T17:30:00+00:00'
    assert roast['starts_at'] == '2026-11-11T21:00:00+00:00'
    assert tour['venue_address'] == '118 Sleep Inn Dr, Orangeburg, SC 29118'
    assert 'Free public bus tour' in tour['description']
    assert tour['lat'] == 33.5563557 and tour['lng'] == -80.8265323
    assert tour['details_evidence_url'] == tour['event_url']
    assert tour['image_url'].startswith('https://iti-images.s3.amazonaws.com/events/')
    assert all('crosswind-farm-turns' not in u and 'dg-outdoors-pheasant' not in u for u in by_url)
    assert 'publisher_weekday_date_conflict' in caplog.text
    assert 'placeholder_midnight_time' in caplog.text
    fetch.assert_called_once_with(h.SOURCES[h.SANTEE]['url'], 'text/html')


def test_santee_missing_street_is_held_without_reusing_source_pin():
    event = public_santee_event()
    event['location']['address']['streetAddress'] = 'Downtown'
    with pytest.raises(ValueError, match='publisher_event_evidence_unavailable'):
        h.parse_santee(santee_document([event]), now=NOW)


@pytest.mark.parametrize('change', ['count', 'position', 'foreign_url', 'timezone', 'midnight'])
def test_santee_incomplete_or_ambiguous_evidence_never_claims_empty(change):
    event = public_santee_event()
    if change == 'foreign_url':
        event['url'] = 'https://other.example/event/one'
    if change == 'timezone':
        event['startDate'] = '2026-11-11T12:30:00'
    if change == 'midnight':
        event['startDate'] = '2026-11-11T05:00:00Z'
    payload = santee_document([event])
    if change == 'count':
        payload = payload.replace('"numberOfItems": 1', '"numberOfItems": 2')
    if change == 'position':
        payload = payload.replace('"position": 1', '"position": 2')
    with pytest.raises(ValueError):
        h.parse_santee(payload, now=NOW)


def test_santee_explicit_empty_and_cancelled_are_valid_but_no_markup_is_error():
    assert h.parse_santee(santee_document([]), now=NOW) == []
    event = public_santee_event()
    event['eventStatus'] = 'https://schema.org/EventCancelled'
    assert h.parse_santee(santee_document([event]), now=NOW) == []
    with pytest.raises(ValueError, match='unsupported_santee_calendar_shape'):
        h.parse_santee('<html>No JSON-LD calendar loaded</html>', now=NOW)


def test_santee_conflicting_same_occurrence_fails_and_coordinates_do_not_fallback():
    first = public_santee_event()
    second = deepcopy(first)
    second['name'] += ' changed'
    with pytest.raises(ValueError, match='conflicting_event_occurrence'):
        h.parse_santee(santee_document([first, second]), now=NOW)
    first['location']['geo'] = {'latitude': 0, 'longitude': 0}
    row = h.parse_santee(santee_document([first]), now=NOW)[0]
    assert row['lat'] is None and row['lng'] is None
    assert row['venue_address'] == '118 Sleep Inn Dr, Orangeburg, SC 29118'


def test_beidler_three_actual_schedules_yield_only_advertised_current_occurrence():
    files = dict(zip(h.BEIDLER_PAGES, ['night', 'family', 'boo']))
    fetch = Mock(side_effect=lambda url, accept: fixture('beidler_' + files[url] + '.html'))
    rows = h.collect_beidler(source(h.BEIDLER), fetch, now=NOW)
    assert len(rows) == 1
    row = rows[0]
    assert row['id'] == 'beidler:night-exploration:2026-11-21'
    assert row['starts_at'] == '2026-11-21T22:15:00+00:00'
    assert row['ends_at'] == '2026-11-22T00:45:00+00:00'
    assert row['venue_address'] == '336 Sanctuary Road, Harleyville, SC 29448'
    assert row['lat'] is None and row['lng'] is None
    assert row['publisher_details']['cost'] == 'All Night Explorations are $18.00 per person.'
    assert 'under 10' in row['publisher_details']['audience']
    assert 'image_url' not in row
    assert len(fetch.call_args_list) == 3


@pytest.mark.parametrize('change', ['year', 'weekday', 'row', 'canonical'])
def test_beidler_never_invents_year_or_silently_skips_bad_schedule(change):
    payload = fixture('beidler_night.html')
    if change == 'year':
        payload = payload.replace('Schedule for 2026', 'Schedule coming soon')
    elif change == 'weekday':
        payload = payload.replace('Saturday November 21st', 'Friday November 21st')
    elif change == 'row':
        payload = payload.replace('5:15 PM to 7:45 PM', 'time to be announced')
    else:
        payload = payload.replace('rel="canonical"', 'rel="alternate"')
    with pytest.raises(ValueError):
        h.parse_beidler(payload, h.SOURCES[h.BEIDLER]['url'], now=NOW)


def test_beidler_past_seasonal_pages_are_empty_without_year_rollover():
    assert h.parse_beidler(fixture('beidler_family.html'), h.BEIDLER_ROOT + 'nocturnal-family-forays', now=NOW) == []
    assert h.parse_beidler(fixture('beidler_boo.html'), h.BEIDLER_ROOT + 'boo-swamp', now=NOW) == []


def test_tec_public_review_excludes_cancelled_virtual_and_preserves_actual_end():
    data = json.loads(fixture('sc250.json'))
    rows = h._parse_tec(data['events'], h.SC250, NOW)
    by_id = {e['id']: e for e in rows}
    assert '66665' not in by_id
    assert by_id['66234']['starts_at'] == '2026-11-11T17:30:00+00:00'
    assert by_id['66239']['starts_at'] == '2026-11-11T21:00:00+00:00'
    assert by_id['66242']['ends_at'] == '2026-11-12T20:31:00+00:00'
    assert by_id['66239']['venue_address'] == '12933 Old Number Six Hwy, Eutawville, SC 29048'
    assert all(e['lat'] is None and e['lng'] is None for e in rows)
    assert all(e['description'] and e['details_evidence_url'] == e['event_url'] for e in rows)


def test_tec_known_publisher_count_discrepancy_is_not_a_complete_snapshot():
    data = json.loads(fixture('sc250.json'))
    assert data['total'] > len(data['events'])
    assert source(h.SC250)['kind'] == 'ical'
    fetch = Mock(return_value=json.dumps(data))
    with pytest.raises(ValueError, match='unregistered_holly_hill_civic_source'):
        h.collect_tec(source(h.SC250), fetch, now=NOW)
    fetch.assert_not_called()


def test_eutawville_valid_empty_remains_enrolled_without_fake_events():
    fetch = Mock(return_value=fixture('eutawville.json'))
    assert h.collect_tec(source(h.EUTAWVILLE), fetch, now=NOW) == []
    assert parse_qs(urlsplit(fetch.call_args.args[0]).query)['start_date'] == ['2026-11-08']


def test_tec_pagination_uses_registered_host_and_rejects_changed_snapshot():
    first, second = tec_event(), tec_event()
    first['url'] = 'https://townofeutawville.gov/event/public-program/'
    second['url'] = 'https://townofeutawville.gov/event/second-public-program/'
    second['id'] = 99000
    calls = []
    def fetch(url, accept):
        calls.append(url)
        page = int(parse_qs(urlsplit(url).query)['page'][0])
        return json.dumps({'events': [first if page == 1 else second], 'total': 2,
                           'total_pages': 2, 'next_rest_url': 'http://127.0.0.1/private' if page == 1 else None})
    assert len(h.collect_tec(source(h.EUTAWVILLE), fetch, now=NOW)) == 2
    assert len(calls) == 2 and all(urlsplit(u).hostname == 'townofeutawville.gov' for u in calls)
    data = {'events': [first], 'total': 2, 'total_pages': 1}
    with pytest.raises(ValueError, match='wordpress_snapshot_changed'):
        h.collect_tec(source(h.EUTAWVILLE), lambda *_: json.dumps(data), now=NOW)


@pytest.mark.parametrize('change', ['timezone', 'utc', 'venue'])
def test_tec_conflicts_cannot_be_repaired_with_invented_time_or_location(change):
    event = tec_event()
    if change == 'timezone':
        event['timezone'] = 'UTC'
    elif change == 'utc':
        event['utc_start_date'] = '2026-11-10 19:00:00'
    else:
        event['venue']['address'] = ''
    with pytest.raises(ValueError, match='publisher_event_evidence_unavailable'):
        h._parse_tec([event], h.SC250, NOW)


def test_elloree_actual_api_both_shapes_exclude_closures_and_keep_blank_ends():
    payload = fixture('elloree.json')
    rows = h.parse_elloree(payload, source(h.ELLOREE), now=NOW)
    wrapped = h.parse_elloree(json.dumps({'data': json.loads(payload)}), source(h.ELLOREE), now=NOW)
    assert rows == wrapped and len(rows) == 2
    assert [e['starts_at'] for e in rows] == ['2026-11-09T22:30:00+00:00', '2026-12-14T22:30:00+00:00']
    assert all(e['ends_at'] is None and e['lat'] is None and e['lng'] is None for e in rows)
    assert all(e['venue_address'] == '2719 West Cleveland Street, Elloree, SC 29047' for e in rows)
    assert all(e['event_url'] == h.SOURCES[h.ELLOREE]['url'] for e in rows)
    assert h.parse_elloree('{"data":[]}', source(h.ELLOREE), now=NOW) == []


def test_elloree_direct_public_api_avoids_repeating_town_html_and_validates_identity():
    callback = Mock(return_value=fixture('elloree.json'))
    fetch = Mock(side_effect=AssertionError('town HTML must not be refetched'))
    assert len(h.collect_elloree(source(h.ELLOREE), fetch, fetch_json=callback, now=NOW)) == 2
    callback.assert_called_once_with()
    fetch.assert_not_called()
    callback.reset_mock()
    changed = source(h.ELLOREE) | {'feed_url': 'https://other.example/calendar'}
    with pytest.raises(ValueError, match='unregistered_holly_hill_civic_source'):
        h.collect_elloree(changed, fetch, fetch_json=callback, now=NOW)
    callback.assert_not_called()
    with pytest.raises(ValueError, match='elloree_public_post_transport_required'):
        h.collect_elloree(source(h.ELLOREE), fetch, now=NOW)


def test_elloree_unknown_venue_and_ambiguous_dst_do_not_get_town_defaults():
    item = deepcopy(next(e for e in json.loads(fixture('elloree.json')) if e['id'] == '6a384e9eebe02d6cbc173ff6'))
    item['location'] = 'Somewhere else'
    with pytest.raises(ValueError, match='publisher_event_evidence_unavailable'):
        h.parse_elloree(json.dumps([item]), source(h.ELLOREE), now=NOW)
    item['location'] = 'Elloree Town Hall'
    item['start_date'] = '2026-11-01T01:30'
    with pytest.raises(ValueError, match='publisher_event_evidence_unavailable'):
        h.parse_elloree(json.dumps([item]), source(h.ELLOREE), now=datetime(2026,10,31,tzinfo=timezone.utc))


@pytest.mark.parametrize('key', list(h.SOURCES))
def test_source_identity_is_exact_before_any_transport(key):
    value = source(key)
    value['feed_url'] += '?unreviewed=1'
    fetch = Mock()
    collect = {h.SANTEE: h.collect_santee, h.BEIDLER: h.collect_beidler,
               h.SC250: h.collect_sc250_ics, h.EUTAWVILLE: h.collect_tec, h.SCWORKS: h.collect_tec, h.ELLOREE: h.collect_elloree}[key]
    with pytest.raises(ValueError, match='unregistered_holly_hill_civic_source'):
        collect(value, fetch, now=NOW)
    fetch.assert_not_called()


def test_public_evidence_never_accepts_foreign_tracking_or_source_logo_images():
    valid = 'https://iti-images.s3.amazonaws.com/events/1234-abcd.webp'
    assert h.image_url(h.SANTEE, valid) == valid
    assert h.image_url(h.SANTEE, valid + '?tracking=1') is None
    assert h.image_url(h.SANTEE, 'https://other.example/events/1234.webp') is None
    assert h.image_url(h.SC250, 'https://southcarolina250.com/wp-content/uploads/logo.png') is None
    assert not h.event_url(h.SANTEE, h.SOURCES[h.SANTEE]['url'] + 'e/%2e%2e/private/')


def test_pending_calendar_sources_have_explicit_holds_not_empty_parsers():
    assert h.PENDING_SOURCES['world_grits_festival_sc'][1] == 'future_annual_dates_outside_window_no_clock_times'
    assert 'old_santee_canal_park_sc' not in h.PENDING_SOURCES
    assert not set(h.PENDING_SOURCES).intersection(h.SOURCES)


def sc250_ics_fetcher():
    files = {
        h.SOURCES[h.SC250]['url']: 'sc250_calendar.ics',
        'https://southcarolina250.com/events/list/page/2/?ical=1': 'ics_page2.ics',
        'https://southcarolina250.com/events/list/page/3/?ical=1': 'sc250_ics_page3.ics',
    }
    return Mock(side_effect=lambda url, accept: fixture(files[url]))


def test_sc250_ics_pages_complete_window_but_hold_conflicting_series_months(caplog):
    fetch = sc250_ics_fetcher()
    rows = h.collect_sc250_ics(source(h.SC250), fetch, now=NOW)
    assert len(fetch.call_args_list) == 3
    assert all(call.args[1] == 'text/calendar' for call in fetch.call_args_list)
    assert len({e['id'] for e in rows}) == len(rows)
    assert len(rows) == 29
    assert not any(e['title'] == 'Screening: Ken Burns The Revolutionary War' for e in rows)
    assert caplog.text.count('publisher_series_month_conflict') == 9
    roast = next(e for e in rows if 'Oyster Roast' in e['title'])
    assert roast['starts_at'] == '2026-11-11T21:00:00+00:00'
    assert roast['venue_address'] == '12933 Old Number Six Hwy, Eutawville, SC 29048'
    assert 'NEW TIME 4:00PM-7:00PM' in roast['description']
    assert roast['image_url'].startswith('https://southcarolina250.com/wp-content/uploads/')
    assert 'free and open to the public' in roast['publisher_details']['cost']
    assert not any('CANCELLED' in e['title'] for e in rows)
    assert all(e['lat'] is None and e['lng'] is None for e in rows)


def test_sc250_recurrences_recover_only_when_publisher_month_evidence_agrees():
    captured = sc250_ics_fetcher()
    def corrected(url, accept):
        return captured(url, accept).replace('April and May', 'November, December and January')
    rows = h.collect_sc250_ics(source(h.SC250), corrected, now=NOW)
    screenings = [e for e in rows if e['title'] == 'Screening: Ken Burns The Revolutionary War']
    assert len(screenings) == 9
    assert len({e['id'] for e in screenings}) == 9
    assert screenings[-1]['starts_at'] == '2027-01-06T23:00:00+00:00'


def test_sc250_ics_does_not_misreport_repeated_or_gapped_exports_as_complete():
    first = fixture('sc250_calendar.ics')
    with pytest.raises(ValueError, match='sc250_ical_pagination_changed'):
        h.collect_sc250_ics(source(h.SC250), lambda *_: first, now=NOW)
    fetch = sc250_ics_fetcher()
    def gap(url, accept):
        result = fetch(url, accept)
        if '/page/2/' in url:
            from icalendar import Calendar
            parsed = Calendar.from_ical(result)
            parsed.subcomponents.remove(parsed.walk('VEVENT')[0])
            return parsed.to_ical().decode()
        return result
    with pytest.raises(ValueError, match='sc250_ical_pagination_changed'):
        h.collect_sc250_ics(source(h.SC250), gap, now=NOW)


def test_sc250_ics_explicit_empty_is_valid_but_malformed_payload_is_not():
    assert h.collect_sc250_ics(source(h.SC250), lambda *_: 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n', now=NOW) == []
    with pytest.raises(ValueError, match='invalid_calendar_payload'):
        h.collect_sc250_ics(source(h.SC250), lambda *_: '<html>calendar unavailable</html>', now=NOW)
