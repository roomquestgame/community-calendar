"""Real Locable snapshot, precise occurrence evidence, and bounded failures."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import base64
import json
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import quote, unquote

from bs4 import BeautifulSoup
from icalendar import Calendar
import pytest

from roomquest import clarksville_tourism as parser, preview_worker

FIXTURES = Path(__file__).with_name('fixtures') / 'clarksville_tourism'
NOW = datetime(2026, 11, 6, 15, tzinfo=timezone.utc)
SOURCE = {'source_key': parser.SOURCE_KEY, 'feed_url': parser.CALENDAR,
          'kind': 'html', 'platform_adapter': 'html', 'timezone': parser.TIMEZONE}
FINAL, TEASER, POKER = '667469', '636949', '482506'


class ClockMeta(type):
    def __instancecheck__(cls, value):
        return isinstance(value, datetime)


class FrozenDatetime(datetime, metaclass=ClockMeta):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def fixed_normalizer_clock(monkeypatch):
    monkeypatch.setattr(preview_worker, 'datetime', FrozenDatetime)


def fixture(name):
    return (FIXTURES / name).read_text()


def listings():
    return {item.identity: item for item in
            parser._listing_page(fixture('calendar_1.html'), parser.CALENDAR)[2]}


def single_page(ids):
    soup = BeautifulSoup(fixture('calendar_1.html'), 'html.parser')
    for card in soup.select('.event-block'):
        if parser.canonical_event_url('https://' + parser.HOST + card.select_one('a.title')['href'])[1] not in ids:
            card.decompose()
    soup.select_one('.event-count').string = f'Displaying {len(ids)} Events:'
    for node in soup.select('.pagination'):
        node.decompose()
    return str(soup)


def bundle(ids=None):
    receipt = json.loads(fixture('capture_receipt.json'))
    data = {row['url']: fixture(row['file']) for row in receipt['responses'] if row['file'].endswith('.html')}
    if ids is not None:
        data = {url: body for url, body in data.items() if '/connections/' in url}
        data[parser.CALENDAR] = single_page(ids)
    return data


def run(data, *, calls=None, now=NOW):
    def fetch(url, accept):
        if calls is not None:
            calls.append((url, accept))
        return data[url]
    return parser.collect(SOURCE, fetch, now=now)


def detail(name='cocoa_final.html'):
    return BeautifulSoup(fixture(name), 'html.parser')


def inline_change(soup, callback):
    links = soup.select('.add-to-calendar a[href^="data:text/calendar"]')
    calendar = Calendar.from_ical(unquote(links[0]['href'].split(',', 1)[1]))
    callback(calendar.walk('VEVENT')[0])
    encoded = 'data:text/calendar;charset=utf8,' + quote(calendar.to_ical().decode(), safe='')
    for link in links:
        link['href'] = encoded


def parse(soup=None, identity=FINAL, *, listing=None, now=NOW):
    return parser.parse_detail(str(soup or detail()), listing or listings()[identity], now=now)


def test_real_five_page_snapshot_yields_one_final_event_and_accounts_for_every_listing(capsys):
    calls = []
    rows = run(bundle(), calls=calls)
    assert len(rows) == 1
    row = rows[0]
    assert row['id'] == 'locable_clarksville:667469'
    assert row['starts_at'] == '2026-12-05T15:00:00+00:00'
    assert row['ends_at'] == '2026-12-05T20:00:00+00:00'
    assert row['timezone'] == 'America/New_York'
    assert row['venue_name'] == 'Historic Downtown Clarksville'
    assert row['venue_address'] == '321 Virginia Avenue, Clarksville, VA 23927'
    assert row['venue_city'] == 'Clarksville'
    assert row['lat'] is None and row['lng'] is None
    assert row['publisher_categories'] == [] and row['publisher_status'] == 'scheduled'
    assert row['event_url'] == row['details_evidence_url'] == row['image_evidence_url'] == listings()[FINAL].url
    assert row['publisher_details'] == {
        'cost': '$40.00', 'audience': 'Bring the family.',
        'registration': 'Tickets required. Tickets: https://www.zeffy.com/en-US/ticketing/cookie-and-cocoa-crawl'}
    assert 'Check-In: 10:00 AM – 12:00 PM' in row['description']
    assert 'Town Hall, 321 Virginia Avenue' in row['description']
    assert len(row['description']) <= 2000
    assert row['image_url'].startswith('https://images.locable.com/')
    assert row['image_url'].endswith('==')
    assert row['image_provenance'] == 'publisher_event_candidates_v1'
    assert 'image_verified_at' not in row
    assert calls[:5] == [(parser.CALENDAR, 'text/html')] + [
        (parser.CALENDAR + '?page=' + str(page), 'text/html') for page in range(2, 6)]
    assert len(calls) == 15 and all(url.startswith('https://' + parser.HOST + '/') for url, _ in calls)
    diagnostic = json.loads(capsys.readouterr().err.splitlines()[-1])
    assert (diagnostic['upstream_records'], diagnostic['pages'], diagnostic['details'], diagnostic['outside_window']) == (54, 5, 10, 44)
    assert len(diagnostic['held']) == 8
    assert {row['reason'] for row in diagnostic['held']} == {'publisher_activity_conflict'}
    assert diagnostic['duplicates'] == [{'id': TEASER, 'replaced_by': FINAL,
                                         'reason': 'reviewed_matching_teaser_and_final'}]


def test_new_event_is_discovered_without_a_fixed_event_allowlist_and_keeps_actual_geography():
    data = bundle([FINAL])
    new_id, old = '777777', listings()[FINAL]
    new_url = old.url.replace('/667469/', '/777777/').replace('historic-downtown-clarksvilles-1st-annual-cookie-cocoa-crawl', 'community-holiday-lunch')
    soup = detail()
    title = 'Community Holiday Lunch'
    soup.select_one('h1[itemprop="name"]').string = title
    soup.select_one('[itemprop="description"]').string = 'A public community lunch at the guest venue.'
    soup.select_one('.page-header h3').decompose()
    soup.select_one('.event-details [itemprop="location"]').string = 'Guest Community Hall'
    address = '200 Main Street, Littleton, NC 27850'
    soup.select_one('.event-details [itemprop="address"]').string = address
    def facts(event):
        event['SUMMARY'] = title
        event['LOCATION'] = address
    inline_change(soup, facts)
    data[new_url] = str(soup)
    listing = BeautifulSoup(data[parser.CALENDAR], 'html.parser')
    copy = deepcopy(listing.select_one('.event-block'))
    for anchor in copy.select('a[href]'):
        anchor['href'] = new_url
    copy.select_one('a.title').string = title
    copy.select_one('.street1').string = '200 Main Street'
    copy.select_one('.city-state-zip').string = 'Littleton, NC 27850'
    listing.select_one('.event-block').parent.append(copy)
    listing.select_one('.event-count').string = 'Displaying 2 Events:'
    data[parser.CALENDAR] = str(listing)
    rows = run(data)
    assert len(rows) == 2
    row = next(row for row in rows if row['id'].endswith(new_id))
    assert row['title'] == title and row['event_url'] == new_url
    assert row['venue_address'] == address and row['venue_city'] == 'Littleton'
    assert row['lat'] is None and row['lng'] is None


def test_teaser_is_not_globally_excluded_and_unrelated_records_are_not_collapsed():
    assert [r['id'] for r in run(bundle([TEASER]))] == ['locable_clarksville:' + TEASER]
    teaser, final = parse(detail('cocoa_teaser.html'), TEASER), parse()
    diagnostics = {}
    teaser.title = 'Save the Date Community Craft Fair'
    teaser.row['title'] = teaser.title
    rows = parser._deduplicate([teaser, final], diagnostics)
    assert len(rows) == 2 and not diagnostics


@pytest.mark.parametrize('field,value', [
    ('starts_at', '2026-12-05T16:00:00+00:00'),
    ('ends_at', '2026-12-05T21:00:00+00:00'),
    ('venue_address', '999 Virginia Avenue, Clarksville, VA 23927'),
    ('venue_name', 'Different venue'), ('publisher_status', 'cancelled'),
])
def test_reviewed_duplicate_requires_matching_current_facts(field, value):
    teaser, final = parse(detail('cocoa_teaser.html'), TEASER), parse()
    teaser.row[field] = value
    diagnostics = {}
    assert len(parser._deduplicate([teaser, final], diagnostics)) == 2
    assert not diagnostics


def test_poker_activity_and_same_named_profile_address_conflicts_are_independent_holds():
    soup = detail('poker_conflict.html')
    with pytest.raises(parser.EventHold, match='activity_conflict'):
        parse(soup, POKER)
    narrative = soup.select_one('[itemprop="description"]')
    narrative.string = 'Join our weekly poker tournament.'
    with pytest.raises(parser.EventHold, match='venue_address_conflict'):
        parse(soup, POKER)


def test_start_only_listing_never_uses_locables_synthetic_one_hour_end():
    soup = detail('poker_conflict.html')
    soup.select_one('[itemprop="description"]').string = 'Join our weekly poker tournament.'
    profile = soup.select_one('.adr [itemprop="address"]')
    profile.string = '600 Virginia Avenue, Clarksville, VA 23927'
    event = parse(soup, POKER)
    assert event.row['ends_at'] is None
    assert event.row['starts_at'] == '2026-11-11T23:00:00+00:00'


@pytest.mark.parametrize('mutate,reason', [
    (lambda s: setattr(s.select_one('[itemprop="startDate"]'), 'string', 'Dec 05'), 'year_or_date'),
    (lambda s: setattr(s.select_one('[itemprop="startDate"]'), 'string', 'Dec 05, 2027'), 'date_conflict'),
    (lambda s: setattr(s.select_one('[itemprop="doorTime"]'), 'string', '10:00 AM EDT'), 'timezone_conflict'),
    (lambda s: setattr(s.select_one('[itemprop="doorTime"]'), 'string', 'All Day'), 'time_or_timezone'),
    (lambda s: s.select_one('[itemprop="address"]').decompose(), 'street_venue'),
    (lambda s: setattr(s.select_one('[itemprop="address"]'), 'string', 'Clarksville, VA'), 'street_venue'),
    (lambda s: setattr(s.select_one('[itemprop="location"]'), 'string', 'Online via Zoom'), 'street_venue'),
    (lambda s: setattr(s.select_one('h1[itemprop="name"]'), 'string', 'Unrelated Event'), 'title_conflict'),
    (lambda s: setattr(s.select_one('.page-header h3'), 'string', 'Event Hours: 11:00 AM – 3:00 PM'), 'narrative_schedule_conflict'),
])
def test_undated_conflicting_all_day_and_unlocated_records_are_held(mutate, reason):
    soup = detail()
    mutate(soup)
    with pytest.raises(parser.EventHold, match=reason):
        parse(soup)


@pytest.mark.parametrize('change,reason', [
    (lambda e: e.__setitem__('SUMMARY', 'Unrelated Event'), 'identity_conflict'),
    (lambda e: e.__setitem__('LOCATION', '999 Elsewhere Road, Clarksville, VA 23927'), 'address_conflict'),
    (lambda e: setattr(e['DTSTART'], 'dt', datetime(2026, 12, 5, 16, tzinfo=timezone.utc)), 'time_conflict'),
    (lambda e: setattr(e['DTEND'], 'dt', datetime(2026, 12, 5, 19, tzinfo=timezone.utc)), 'end_conflict'),
    (lambda e: e.__delitem__('DTEND'), 'end_conflict'),
    (lambda e: e.__setitem__('RRULE', {'freq': 'WEEKLY'}), 'recurrence_unreviewed'),
])
def test_inline_export_must_describe_the_same_exact_displayed_occurrence(change, reason):
    soup = detail()
    inline_change(soup, change)
    with pytest.raises(parser.EventHold, match=reason):
        parse(soup)


def test_timezone_validation_uses_real_new_york_dst_not_a_fixed_est_offset():
    assert parser._clock(datetime(2027, 7, 7).date(), '6:00 PM', 'EDT').utcoffset() == timedelta(hours=-4)
    with pytest.raises(parser.EventHold, match='timezone_conflict'):
        parser._clock(datetime(2027, 7, 7).date(), '6:00 PM', 'EST')
    for day, clock, zone in [(datetime(2027, 3, 14).date(), '2:30 AM', 'EST'),
                             (datetime(2026, 11, 1).date(), '1:30 AM', 'EDT')]:
        with pytest.raises(parser.EventHold, match='time_or_timezone'):
            parser._clock(day, clock, zone)


@pytest.mark.parametrize('status', ['cancelled', 'postponed'])
def test_exact_status_survives_missing_end_and_venue_then_refresh_restores_same_identity(status):
    original = parse().row
    soup = detail()
    soup.select_one('h1[itemprop="name"]').string = status.title() + ': ' + original['title']
    for node in soup.select('.event-details [itemprop="location"], .event-details [itemprop="address"]'):
        node.decompose()
    inline_change(soup, lambda e: e.__delitem__('DTEND'))
    # The publisher left the visible old range but removed DTEND and venue.
    # Exact status/start remains useful without filling those missing facts.
    now = datetime(2026, 12, 5, 19, tzinfo=timezone.utc)
    row = parse(soup, now=now).row
    assert row['publisher_status'] == status
    assert row['id'] == original['id'] and row['starts_at'] == original['starts_at']
    assert row['event_url'] == original['event_url']
    assert row['ends_at'] is None and not row['venue_address'] and not row['venue_name']
    restored = parse().row
    assert restored['publisher_status'] == 'scheduled' and restored['id'] == row['id']
    assert restored['ends_at'] == original['ends_at']


def test_explicit_ics_cancellation_and_conflicting_status_are_not_silently_discarded():
    soup = detail()
    inline_change(soup, lambda e: e.__setitem__('STATUS', 'CANCELLED'))
    assert parse(soup).row['publisher_status'] == 'cancelled'
    soup.select_one('h1[itemprop="name"]').string = 'Postponed: ' + parse().title
    with pytest.raises(parser.EventHold, match='status_conflict'):
        parse(soup)


@pytest.mark.parametrize('notice', ['This event has been cancelled.', 'The event is postponed.'])
def test_direct_body_cancellation_notice_cannot_publish_as_scheduled(notice):
    soup = detail()
    soup.select_one('[itemprop="description"]').append(notice)
    with pytest.raises(parser.EventHold, match='narrative_status_unreviewed'):
        parse(soup)


def test_held_final_body_cancellation_also_holds_its_exact_reviewed_teaser(capsys):
    data = bundle([FINAL, TEASER])
    soup = detail()
    soup.select_one('[itemprop="description"]').append('This event has been cancelled.')
    data[listings()[FINAL].url] = str(soup)
    with pytest.raises(ValueError, match='event_evidence_unavailable'):
        run(data)
    diagnostic = json.loads(capsys.readouterr().err.splitlines()[-1])
    assert {item['id']: item['reason'] for item in diagnostic['held']} == {
        FINAL: 'publisher_narrative_status_unreviewed',
        TEASER: 'reviewed_teaser_final_status_unresolved'}


def test_cancellation_policy_language_does_not_cancel_a_valid_event():
    soup = detail()
    soup.select_one('[itemprop="description"]').append('Cancellation policy: tickets are refundable if this event is cancelled.')
    # The conditional "if this event is cancelled" is not a current notice.
    assert parse(soup).row['publisher_status'] == 'scheduled'


@pytest.mark.parametrize('remove_venue', [False, True])
def test_cancelled_final_never_resurrects_older_scheduled_teaser(remove_venue):
    data = bundle([FINAL, TEASER])
    soup = detail()
    inline_change(soup, lambda e: e.__setitem__('STATUS', 'CANCELLED'))
    if remove_venue:
        for node in soup.select('.event-details [itemprop="location"], .event-details [itemprop="address"]'):
            node.decompose()
        inline_change(soup, lambda e: e.__delitem__('DTEND'))
    data[listings()[FINAL].url] = str(soup)
    rows = run(data)
    assert len(rows) == 1 and rows[0]['id'] == 'locable_clarksville:' + FINAL
    assert rows[0]['publisher_status'] == 'cancelled'
    assert all(row['id'] != 'locable_clarksville:' + TEASER for row in rows)


@pytest.mark.parametrize('suffix', ['Private event.', 'Members-only event.', 'Exclusively for members.'])
def test_full_description_is_checked_before_bounding_output(suffix):
    soup = detail()
    soup.select_one('[itemprop="description"]').append(' Background information. ' * 150 + suffix)
    with pytest.raises(parser.EventExcluded, match='nonpublic'):
        parse(soup)


def test_no_image_is_valid_and_other_page_artwork_is_not_a_fallback():
    soup = detail()
    for image in soup.select('.blog-show-image img'):
        image.decompose()
    row = parse(soup).row
    assert 'image_url' not in row and row['image_extractor_version'] == 'publisher_event_candidates_v1'
    soup = detail()
    soup.select_one('.blog-show-image img')['src'] = 'https://unreviewed.example/banner.jpg'
    assert 'image_url' not in parse(soup).row


def test_encoded_locable_default_logo_is_not_mistaken_for_event_artwork():
    soup = detail()
    image = soup.select_one('.blog-show-image img')
    data = json.loads(base64.b64decode(image['src'].rsplit('/', 1)[1]))
    data['key'] = '_originals/fffbae96-d13a-44d9-a469-b45adb59452c/default-logo.png'
    image['src'] = 'https://images.locable.com/' + base64.b64encode(json.dumps(data).encode()).decode()
    assert 'image_url' not in parse(soup).row


@pytest.mark.parametrize('subtitle', ['Date: Saturday, December 5, 2027',
                                     'Date: Friday, December 5, 2026'])
def test_explicit_narrative_year_or_weekday_conflict_is_held(subtitle):
    soup = detail()
    soup.select_one('.page-header h3').string = subtitle
    with pytest.raises(parser.EventHold, match='narrative_date_conflict'):
        parse(soup)


def test_ongoing_event_retains_verified_end_and_exact_status_lookback_is_bounded():
    assert parse(now=datetime(2026, 12, 5, 19, tzinfo=timezone.utc)).row['ends_at'] == '2026-12-05T20:00:00+00:00'
    assert parse(now=datetime(2026, 12, 5, 20, tzinfo=timezone.utc)) is None
    soup = detail()
    inline_change(soup, lambda e: e.__setitem__('STATUS', 'CANCELLED'))
    assert parse(soup, now=datetime(2026, 12, 12, 14, tzinfo=timezone.utc)) is not None
    assert parse(soup, now=datetime(2026, 12, 12, 16, tzinfo=timezone.utc)) is None


def test_malformed_detail_and_export_fail_the_snapshot_instead_of_becoming_healthy_empty():
    data = bundle([FINAL])
    url = listings()[FINAL].url
    data[url] = '<html><h1>Temporary server error</h1></html>'
    with pytest.raises(ValueError, match='unsupported_tourism_event_page'):
        run(data)
    soup = detail()
    for anchor in soup.select('.add-to-calendar a[href^="data:text/calendar"]'):
        anchor['href'] = 'data:text/calendar;charset=utf8,BEGIN:VCALENDAR%0ABEGIN:VEVENT'
    data[url] = str(soup)
    with pytest.raises(ValueError, match='inline_calendar_invalid'):
        run(data)


def test_all_held_is_not_healthy_empty_but_an_explicit_complete_empty_catalog_is():
    with pytest.raises(ValueError, match='event_evidence_unavailable'):
        run(bundle([POKER]))
    assert run(bundle([])) == []


def test_pagination_drift_truncation_and_scope_rollover_fail_before_detail_reads():
    data = bundle()
    page2 = parser.CALENDAR + '?page=2'
    data[page2] = data[page2].replace('Displaying 54 Events:', 'Displaying 55 Events:')
    calls = []
    with pytest.raises(ValueError, match='result_count_changed'):
        run(data, calls=calls)
    assert len(calls) == 2
    data = bundle()
    data[page2] = data[page2].replace('Nov 06 2026', 'Nov 07 2026')
    with pytest.raises(ValueError, match='scope_changed'):
        run(data)
    data = bundle([FINAL])
    data[parser.CALENDAR] = data[parser.CALENDAR].replace('Displaying 1 Events:', 'Displaying 2 Events:')
    with pytest.raises(ValueError, match='result_count_mismatch'):
        run(data)


def test_pagination_and_record_caps_fail_without_returning_a_partial_snapshot(monkeypatch):
    data = bundle()
    data[parser.CALENDAR] = data[parser.CALENDAR].replace('?page=5', '?page=6')
    with pytest.raises(ValueError, match='pagination_limit'):
        run(data)
    monkeypatch.setattr(parser, 'MAX_DETAILS', 1)
    calls = []
    with pytest.raises(ValueError, match='detail_limit'):
        run(bundle([FINAL, TEASER]), calls=calls)
    assert len(calls) == 1
    monkeypatch.setattr(parser, 'MAX_LISTINGS', 53)
    with pytest.raises(ValueError, match='source_record_limit'):
        run(bundle())


@pytest.mark.parametrize('url', [
    'https://other.example/calendar/?page=2',
    'http://tourism.visitclarksvilleva.com/calendar/?page=2',
    'https://tourism.visitclarksvilleva.com:444/calendar/?page=2',
    'https://tourism.visitclarksvilleva.com/calendar/?page=2&start_date=today',
    'https://tourism.visitclarksvilleva.com/calendar/?page=2#anchor',
    'https://tourism.visitclarksvilleva.com/preview/?page=2',
])
def test_unreviewed_pagination_urls_are_never_fetched(url):
    data = bundle()
    data[parser.CALENDAR] = data[parser.CALENDAR].replace('/calendar/?page=2', url)
    calls = []
    with pytest.raises(ValueError, match='invalid_tourism_link|unsupported_tourism_pagination'):
        run(data, calls=calls)
    assert len(calls) == 1


def test_conflicting_event_identity_and_external_detail_url_fail_before_fetch():
    soup = BeautifulSoup(single_page([FINAL]), 'html.parser')
    duplicate = deepcopy(soup.select_one('.event-block'))
    duplicate.select_one('.date').string = 'Dec 06, 2026'
    for anchor in duplicate.select('a[href]'):
        anchor['href'] = anchor['href'].replace('/2026/12/5/', '/2026/12/6/')
    soup.select_one('.event-block').parent.append(duplicate)
    soup.select_one('.event-count').string = 'Displaying 2 Events:'
    with pytest.raises(ValueError, match='conflicting_event_identity'):
        run({parser.CALENDAR: str(soup)})
    data = bundle([FINAL])
    data[parser.CALENDAR] = data[parser.CALENDAR].replace('/connections/', 'https://other.example/connections/')
    with pytest.raises(ValueError, match='invalid_tourism_link'):
        run(data)


@pytest.mark.parametrize('field,value', [
    ('source_key', 'other_source'), ('feed_url', parser.CALENDAR + '?page=2'),
    ('kind', 'json'), ('platform_adapter', 'jsonld'), ('timezone', 'UTC'),
])
def test_source_identity_fails_before_any_network_call(field, value):
    fetch = Mock()
    with pytest.raises(ValueError, match='unregistered'):
        parser.collect(dict(SOURCE, **{field: value}), fetch, now=NOW)
    fetch.assert_not_called()


def test_failed_detail_and_expired_deadline_cannot_return_partial_success(monkeypatch):
    data = bundle([FINAL])
    fetch = Mock(side_effect=[data[parser.CALENDAR], OSError('publisher unavailable')])
    with pytest.raises(OSError, match='unavailable'):
        parser.collect(SOURCE, fetch, now=NOW)
    fetch = Mock()
    with pytest.raises(ValueError, match='collection_deadline'):
        parser.collect(SOURCE, fetch, now=NOW, deadline_at=0)
    fetch.assert_not_called()
    clock = [0]
    monkeypatch.setattr(parser, 'monotonic', lambda: clock[0])
    def slow(url, accept):
        clock[0] = parser.MAX_SECONDS + 1
        return data[url]
    with pytest.raises(ValueError, match='collection_deadline'):
        parser.collect(SOURCE, slow, now=NOW)
