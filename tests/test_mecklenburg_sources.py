"""Captured public source facts, bounded intake, and scoped media handoff."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
import pytest

from roomquest import chase_city_chamber as chamber
from roomquest import ics_adapter, preview_worker, wordpress_adapter
from roomquest.publisher_evidence import family, image_url

FIXTURES = Path(__file__).with_name('fixtures')
ROSEMONT = json.loads((FIXTURES / 'rosemont_20261105.json').read_text())
ROSEMONT_FEATURED_IMAGE = 'https://rosemontofvirginia.com/wp-content/uploads/2026/04/ShortStacked-Logo.jpg'
CHASE_HTML = (FIXTURES / 'chase_city_20261105.html').read_text()
NOW = datetime(2026, 11, 6, 2, tzinfo=timezone.utc)  # November 5 in Virginia.
ROSEMONT_SOURCE = {
    'source_key': 'rosemont_of_virginia', 'kind': 'json', 'platform_adapter': 'wordpress',
    'feed_url': wordpress_adapter.ROSEMONT_URL, 'timezone': 'America/New_York',
}
CHASE_SOURCE = {
    'source_key': 'chase_city_chamber_va', 'kind': 'html', 'platform_adapter': 'html',
    'feed_url': chamber.CALENDAR, 'timezone': 'America/New_York',
}
LIBRARY_SOURCE = {
    'source_key': 'mecklenburg_va_libraries', 'kind': 'ical', 'platform_adapter': 'ical',
    'feed_url': ics_adapter.MECKLENBURG_LIBRARY_FEED, 'timezone': 'America/New_York',
}


class ClockMeta(type):
    def __instancecheck__(cls, value):
        return isinstance(value, datetime)


class FrozenDatetime(datetime, metaclass=ClockMeta):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    for module in (preview_worker, wordpress_adapter, chamber):
        monkeypatch.setattr(module, 'datetime', FrozenDatetime)


def wp(data=None, source=None):
    return wordpress_adapter.collect(source or ROSEMONT_SOURCE,
                                     lambda *_: json.dumps(data if data is not None else ROSEMONT))


def first_public_event():
    return deepcopy(ROSEMONT['events'][0])


def one_event(item):
    return {'events': [item], 'total': 1, 'total_pages': 1}


def test_rosemont_real_snapshot_holds_closures_private_missing_venues_and_time_conflict(capsys):
    rows = wp()
    assert {row['id'] for row in rows} == {'7745', '7988', '8121'}
    assert len(rows) == 3
    by_id = {row['id']: row for row in rows}
    assert by_id['7745']['starts_at'] == '2026-11-07T16:00:00+00:00'
    assert by_id['7745']['ends_at'] == '2026-11-07T22:00:00+00:00'
    assert by_id['7745']['venue_address'] == '1050 Blackridge Road, LaCrosse, VA, 23950'
    assert by_id['7988']['venue_address'] == '141 E South Main St, Littleton, NC, 27850'
    assert by_id['7988']['venue_name'] == 'Blue Jay Bistro'
    assert by_id['7988']['publisher_details'] == {'cost': '$160.00'}
    assert all(row['lat'] is None and row['lng'] is None for row in rows)
    assert all(row['description'] and len(row['description']) <= 2000 for row in rows)
    assert all(row['timezone'] == 'America/New_York' for row in rows)
    assert by_id['7745']['image_url'] == ROSEMONT_FEATURED_IMAGE
    assert by_id['7745']['image_provenance'] == 'publisher_event_candidates_v1'
    assert by_id['7745']['image_evidence_url'] == by_id['7745']['event_url']
    assert 'image_verified_at' not in by_id['7745']
    assert by_id['7988']['image_provenance'] == 'publisher_event_candidates_v1'
    assert by_id['8121']['starts_at'].startswith('2026-12-12')
    assert not any(row['starts_at'].startswith('2026-12-13') for row in rows)
    diagnostics = capsys.readouterr().err
    assert 'publisher_header_body_time_conflict' in diagnostics
    assert 'event_venue_unreviewed' in diagnostics
    assert '"excluded": 5' in diagnostics and '"held": 3' in diagnostics


def test_rosemont_contract_does_not_expand_other_wordpress_sources():
    item = first_public_event()
    item['description'] = '<p>Existing generic policy.</p>'
    source = dict(ROSEMONT_SOURCE, source_key='unrelated_wordpress')
    row = wp(one_event(item), source)[0]
    assert row['description'] == 'Existing generic policy.' and 'image_url' not in row
    assert 'details_extractor_version' not in row


@pytest.mark.parametrize('candidate', [
    'https://rosemontofvirginia.com/wp-content/uploads/2026/04/Rosemont-Logo.jpg',
    ROSEMONT_FEATURED_IMAGE.replace('/2026/04/', '/2026/05/'),
    ROSEMONT_FEATURED_IMAGE.replace('-Logo.jpg', '-Logo-300x300.jpg'),
    ROSEMONT_FEATURED_IMAGE.replace('-Logo.jpg', '-logo.jpg'),
    ROSEMONT_FEATURED_IMAGE.replace('.jpg', '.png'),
    ROSEMONT_FEATURED_IMAGE + '?size=1024',
    ROSEMONT_FEATURED_IMAGE + '#image',
    ROSEMONT_FEATURED_IMAGE.replace('https:', 'http:'),
    ROSEMONT_FEATURED_IMAGE.replace('https://', 'https://user@'),
    ROSEMONT_FEATURED_IMAGE.replace('.com/', '.com:443/'),
    ROSEMONT_FEATURED_IMAGE.replace('.com/', '.com:8443/'),
    ROSEMONT_FEATURED_IMAGE.replace('.com/', '.com.evil.test/'),
    ROSEMONT_FEATURED_IMAGE.replace('https://', 'https://www.'),
    ROSEMONT_FEATURED_IMAGE.replace('/04/', '/04/../04/'),
    ROSEMONT_FEATURED_IMAGE.replace('/04/', '/04/%2e%2e/04/'),
    ROSEMONT_FEATURED_IMAGE.replace('/04/', '/04%2f'),
    ROSEMONT_FEATURED_IMAGE.replace('ShortStacked', 'Short Stacked'),
])
def test_rosemont_reviewed_image_does_not_admit_generic_or_modified_assets(candidate):
    item = first_public_event()
    item['image']['url'] = candidate
    row = wp(one_event(item))[0]
    assert 'image_url' not in row
    assert 'image_provenance' not in row
    assert 'image_evidence_url' not in row


@pytest.mark.parametrize('featured', [None, {}, {'url': None}])
def test_rosemont_reviewed_image_is_not_injected_without_publisher_candidate(featured):
    item = first_public_event()
    item['image'] = featured
    assert 'image_url' not in wp(one_event(item))[0]


@pytest.mark.parametrize('field,value', [
    ('status', 'draft'), ('hide_from_listings', True), ('all_day', True),
    ('is_virtual', True), ('event_status', 'postponed'),
    ('title', 'Private event'), ('description', 'Members only.'),
])
def test_rosemont_explicit_nonpublic_records_are_excluded(field, value):
    item = first_public_event()
    item[field] = value
    assert wp(one_event(item)) == []


def test_rosemont_missing_venue_cannot_be_repaired_with_winery_location():
    item = first_public_event()
    item['venue'] = []
    with pytest.raises(ValueError, match='rosemont_event_evidence_unavailable'):
        wp(one_event(item))
    assert wp({'events': [], 'total_pages': 0}) == []


def test_rosemont_utc_and_local_schedule_must_agree():
    item = first_public_event()
    item['utc_start_date'] = '2026-11-07 17:00:00'
    with pytest.raises(ValueError, match='publisher_schedule_conflict'):
        wp(one_event(item))


def test_rosemont_narrative_is_real_sanitized_and_bounded():
    item = first_public_event()
    item['description'] = '<p>Learn &amp; enjoy.</p><script>bad()</script><style>bad</style><p>' + 'x' * 2200 + '</p>'
    row = wp(one_event(item))[0]
    assert row['description'].startswith('Learn & enjoy.\n')
    assert len(row['description']) == 2000 and 'bad' not in row['description']
    item['description'] = None
    assert wp(one_event(item))[0]['description'] == ''


def test_rosemont_feed_identity_checked_before_fetch():
    calls = []
    with pytest.raises(ValueError, match='unregistered_rosemont_source'):
        wordpress_adapter.collect(dict(ROSEMONT_SOURCE, feed_url='https://other.example/events'),
                                  lambda *args: calls.append(args))
    assert calls == []


def test_chase_real_snapshot_uses_exact_flyer_and_keeps_expired_rsvp_deadline():
    rows = chamber.parse(CHASE_HTML)
    assert len(rows) == 1
    row = rows[0]
    assert row['title'] == chamber.AWARDS_TITLE
    assert row['starts_at'] == chamber.AWARDS_START and row['ends_at'] == chamber.AWARDS_END
    assert row['venue_name'] == 'Estes Center Banquet Room'
    assert row['venue_address'] == '316 N Main St, Chase City, VA'
    assert row['lat'] is None and row['lng'] is None
    assert row['description'] == chamber.AWARDS_DESCRIPTION
    assert 'RSVP by October 30' in row['description']
    assert row['publisher_details'] == {'cost': '$25 per person'}
    assert row['image_url'] == chamber.AWARDS_IMAGE
    assert row['image_evidence_url'] == chamber.CALENDAR
    assert row['details_evidence_url'] == chamber.AWARDS_URL
    assert row['image_provenance'] == 'publisher_event_candidates_v1'
    assert row['location_provenance'] == 'reviewed_event_flyer_and_matched_venue_address'


def test_chase_source_fetches_one_allowed_html_page_with_transport_guards():
    calls = []
    def fetch(url, accept, **kwargs):
        calls.append((url, accept, kwargs))
        return CHASE_HTML
    with patch.object(preview_worker, 'fetch_publisher', fetch):
        result = preview_worker.preview_source(CHASE_SOURCE)
    assert result['p_future_count'] == 1
    assert result['p_parser_capability'] == 'publisher_event_candidates_v1'
    assert len(calls) == 1 and calls[0][0] == chamber.CALENDAR
    assert calls[0][1] == 'text/html'
    assert calls[0][2]['respect_robots'] is True
    assert calls[0][2]['allowed_hosts'] == ('chasecitychamber.com',)
    assert '?format=' not in calls[0][0]


def test_chase_unknown_future_venue_never_inherits_office_address(capsys):
    soup = BeautifulSoup(CHASE_HTML, 'html.parser')
    card = deepcopy(soup.select_one('article.eventlist-event'))
    title = card.select_one('a.eventlist-title-link')
    title.string = 'New community program'
    title['href'] = '/upcoming-events/new-community-program'
    export = card.select_one('a.eventlist-meta-export-google')
    parts = urlsplit(export['href'])
    query = parse_qs(parts.query)
    query['text'] = ['New community program']
    export['href'] = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), ''))
    soup.select_one('.eventlist').append(card)
    rows = chamber.parse(str(soup))
    assert len(rows) == 1 and rows[0]['event_url'] == chamber.AWARDS_URL
    assert 'event_venue_unreviewed' in capsys.readouterr().err


def test_chase_reviewed_flyer_change_requires_new_venue_review():
    changed = CHASE_HTML.replace(chamber.AWARDS_IMAGE, chamber.AWARDS_IMAGE.replace('4760210d', '5760210d'))
    with pytest.raises(ValueError, match='chase_city_event_evidence_unavailable'):
        chamber.parse(changed)


def test_chase_conflicting_visible_time_is_held():
    soup = BeautifulSoup(CHASE_HTML, 'html.parser')
    soup.select_one('time.event-time-localized-start').string = '7:00 PM'
    with pytest.raises(ValueError, match='chase_city_event_evidence_unavailable'):
        chamber.parse(str(soup))


def test_chase_unknown_pagination_and_oversized_listing_fail_closed():
    soup = BeautifulSoup(CHASE_HTML, 'html.parser')
    soup.append(soup.new_tag('a', href=chamber.CALENDAR + '?offset=123456'))
    with pytest.raises(ValueError, match='pagination_requires_review'):
        chamber.parse(str(soup))
    soup = BeautifulSoup(CHASE_HTML, 'html.parser')
    listing = soup.select_one('.eventlist')
    card = deepcopy(soup.select_one('article.eventlist-event'))
    for _ in range(101):
        listing.append(deepcopy(card))
    with pytest.raises(ValueError, match='source_record_limit'):
        chamber.parse(str(soup))


def test_chase_calendar_metadata_and_event_venue_evidence_are_required():
    with pytest.raises(ValueError, match='chase_city_calendar_identity_changed'):
        chamber.parse(CHASE_HTML.replace('America/New_York', 'America/Chicago'))
    with pytest.raises(ValueError, match='chase_city_event_evidence_unavailable'):
        chamber.parse(CHASE_HTML.replace('316 N Main St, Chase City, VA', 'An unknown office address'))
    assert chamber.parse(CHASE_HTML, now=NOW + timedelta(days=2)) == []


def test_media_enrollment_is_exact_source_event_and_image_host_scope():
    assert family('chase_city_chamber_va', chamber.AWARDS_URL) == 'chase_city_chamber'
    assert family('unrelated', chamber.AWARDS_URL) is None
    assert family('chase_city_chamber_va', chamber.CALENDAR) is None
    assert image_url(chamber.AWARDS_IMAGE, 'chase_city_chamber') == chamber.AWARDS_IMAGE
    assert image_url(chamber.AWARDS_IMAGE.replace('64921bef4a756810ab11ec54', 'other-site'), 'chase_city_chamber') is None
    assert image_url('https://other.example/flyer.jpg', 'rosemont') is None
    assert image_url('https://rosemontofvirginia.com/wp-content/uploads/ShortStacked-Logo.jpg', 'rosemont') is None


@pytest.mark.parametrize('source,body,count', [
    (ROSEMONT_SOURCE, json.dumps(ROSEMONT), 3), (CHASE_SOURCE, CHASE_HTML, 1),
])
def test_reviewed_sources_stage_before_v3_candidate_capability_handoff(source, body, count):
    calls = []
    def rpc(name, payload):
        calls.append((name, deepcopy(payload)))
        return len(payload.get('p_events', [])) if name == 'community_collector_record_staged_events' else None
    with patch.object(preview_worker, 'fetch_publisher', lambda *a, **kw: body), \
            patch.object(preview_worker, 'supabase_rpc', rpc):
        preview_worker._process_claimed_source(source)
    assert [name for name, _ in calls] == ['community_collector_record_staged_events', 'community_collector_record_preview_v3']
    assert len(calls[0][1]['p_events']) == count
    assert calls[1][1]['p_future_count'] == count
    assert calls[1][1]['p_parser_capability'] == 'publisher_event_candidates_v1'


def test_library_ics_records_pacing_without_new_media_host_permission():
    source = {'source_key': 'mecklenburg_va_libraries', 'kind': 'ical', 'platform_adapter': 'ical'}
    output = {'p_source_key': source['source_key'], 'p_events': [], 'p_samples': [],
              'p_future_count': 0, 'p_venue_count': 0, 'p_error': None}
    calls = []
    with patch.object(preview_worker, 'preview_source', return_value=output), \
            patch.object(preview_worker, 'supabase_rpc', side_effect=lambda name, payload: calls.append(name) or 0):
        preview_worker._process_claimed_source(source)
    assert calls[-1] == 'community_collector_record_preview_v2'
    assert family('mecklenburg_va_libraries', 'https://www.youseemore.com/mecklib/calendar.asp') is None


def test_library_robots_denial_stops_calendar_request_and_parser():
    # Actual Google Calendar robots response captured November 6, 2026.
    rules = RobotFileParser()
    rules.parse('User-agent: *\nAllow: /$\nDisallow: /\n'.splitlines())
    with patch.object(preview_worker, 'validate_public_dns'), \
            patch.object(preview_worker, '_robots_rules', return_value=rules) as robots, \
            patch.object(preview_worker.requests, 'Session') as session, \
            patch.object(ics_adapter, 'parse') as parse:
        with pytest.raises(preview_worker.PreviewError, match='^robots_denied$'):
            preview_worker.preview_source(LIBRARY_SOURCE)
    assert robots.call_args.args[0] == 'calendar.google.com'
    session.return_value.__enter__.return_value.get.assert_not_called()
    parse.assert_not_called()


def test_library_robots_policy_does_not_change_unrelated_legacy_ics():
    source = dict(LIBRARY_SOURCE, source_key='unrelated_legacy_ics')
    with patch.object(preview_worker, 'fetch_publisher', return_value='captured calendar') as fetch, \
            patch.object(ics_adapter, 'parse', return_value=[]):
        result = preview_worker.preview_source(source)
    assert fetch.call_args.kwargs['respect_robots'] is False
    assert result['p_future_count'] == 0
