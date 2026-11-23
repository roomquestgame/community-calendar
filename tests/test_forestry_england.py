"""Captured all-network scope plus adversarial schedule/completeness fixtures."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from time import monotonic
from unittest.mock import Mock

from bs4 import BeautifulSoup
import pytest

from roomquest import feed_registration, forestry_england as forestry
from roomquest import preview_worker, registered_html_calendar as calendar
from roomquest import registered_native_content as native
from roomquest.registration_formats import source_key

FIXTURES = Path(__file__).parent / 'fixtures' / 'forestry_england'
MANIFEST = json.loads((FIXTURES / 'manifest.json').read_text())
BASE = 'https://www.forestryengland.uk'
WESTONBIRT = BASE + '/westonbirt/events'
BEDGEBURY = BASE + '/bedgebury/events'
CARDINHAM = BASE + '/cardinham-woods/venue/events-cardinham-woods'
LANTERN = BASE + '/forest-event/events-cardinham-woods/fundraising-christmas-woodland-lantern-walk-badger-forest'
ALICE = BASE + '/alice-holt-forest/venue/events-alice-holt'
ALICE_RUN = BASE + '/forest-event/events-alice-holt/this-woman-runs-alice-holt-forest'
HALDON = BASE + '/haldon-forest-park/venue/events-haldon-forest-park'
PARKRUN = BASE + '/forest-event/events-haldon-forest-park/parkrun-haldon-forest-park'
HIGH_LODGE = BASE + '/high-lodge/venue/events-high-lodge'
BEFORE_CHRISTMAS = BASE + '/forest-event/events-high-lodge/twas-the-run-christmas'


def source(url):
    return {'feed_url': url, 'source_key': source_key(url), 'kind': 'html',
            'platform_adapter': 'html', calendar.CAPABILITY: 1, native.CAPABILITY: 1}


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    value = [datetime.fromisoformat(MANIFEST['replay_time_utc'])]

    class ClockMeta(type):
        def __instancecheck__(cls, candidate):
            return isinstance(candidate, datetime)

    class Clock(datetime, metaclass=ClockMeta):
        @classmethod
        def now(cls, tz=None):
            return value[0].astimezone(tz) if tz else value[0].replace(tzinfo=None)

    monkeypatch.setattr(preview_worker, 'datetime', Clock)
    return lambda instant: value.__setitem__(0, datetime.fromisoformat(instant))


@pytest.fixture
def pages():
    return {page['url']: (FIXTURES / page['file']).read_text() for page in MANIFEST['pages']}


def fetcher(pages):
    return Mock(side_effect=lambda url, _accept, **_kwargs: pages[url])


def audit():
    return {'omitted': [], 'warnings': []}


def change_event(payload, **updates):
    soup = BeautifulSoup(payload, 'html.parser')
    script = soup.select_one('script[type="application/ld+json"]')
    data = json.loads(script.string)
    data['@graph'][0].update(updates)
    script.string = json.dumps(data)
    return str(soup)


@pytest.mark.parametrize('url', MANIFEST['calendar_urls'])
def test_all_66_discovered_forest_scopes_are_recognized_and_complete(pages, url):
    assert calendar.supports_listing(url, pages[url])
    diagnostics = {}
    fetch = fetcher(pages)
    rows = forestry.collect(source(url), fetch, diagnostics=diagnostics)
    assert diagnostics['pages'] >= 1
    assert diagnostics['cards'] == diagnostics['fetched_details'] + len(diagnostics['outside_horizon'])
    for row in rows:
        native.validate_record(row, source(url))
        assert row['timezone'] == 'Europe/London'
        assert row['lat'] is not None and row['lng'] is not None
        assert row['image_extractor_version'] == native.VERSION
        assert not row.get('image_url')
        assert row['registered_native_content']['image_field'] is None


def test_four_pages_complete_before_details_and_horizon_filter_keeps_original_scope(pages):
    diagnostics = {}
    fetch = fetcher(pages)
    rows = forestry.collect(source(WESTONBIRT), fetch, diagnostics=diagnostics)
    urls = [call.args[0] for call in fetch.call_args_list]
    assert urls[:4] == [WESTONBIRT, *[WESTONBIRT + '?page=' + str(n) for n in (1, 2, 3)]]
    assert diagnostics['pages'] == 4 and diagnostics['cards'] == 31
    assert diagnostics['fetched_details'] == 15
    assert len(diagnostics['outside_horizon']) == 16
    assert len(rows) == 32
    assert len(urls) == 19  # Fits the normal 35-second registration budget at ordinary pacing.
    assert all(row['registered_native_content']['feed_url'] == WESTONBIRT for row in rows)
    assert all(row['event_url'] not in diagnostics['outside_horizon'] for row in rows)
    assert {row['venue_name'] for row in rows} == {'Westonbirt, The National Arboretum'}


def test_array_venue_name_preserves_full_name_and_occurrence_identity(pages):
    url = BASE + '/westonbirt/nordic-walk'
    soup = BeautifulSoup(pages[url], 'html.parser')
    event = json.loads(soup.select_one('script[type="application/ld+json"]').string)['@graph'][0]
    venue = deepcopy(event['location'])
    assert venue['name'] == ['Westonbirt', 'The National Arboretum']
    rows = forestry.detail(source(WESTONBIRT), pages[url], url, diagnostics=audit())
    venue['name'] = 'Westonbirt, The National Arboretum'
    equivalent_text = change_event(pages[url], location=venue)
    assert rows
    assert rows == forestry.detail(source(WESTONBIRT), equivalent_text, url, diagnostics=audit())


@pytest.mark.parametrize('name', [[], ['Westonbirt', ' '], ['Westonbirt', {'name': 'Unknown'}]])
def test_invalid_array_venue_name_is_not_stringified(pages, name):
    url = BASE + '/westonbirt/nordic-walk'
    soup = BeautifulSoup(pages[url], 'html.parser')
    venue = json.loads(soup.select_one('script[type="application/ld+json"]').string)['@graph'][0]['location']
    venue['name'] = name
    with pytest.raises(ValueError, match='forestry_venue_facts_unverified'):
        forestry.detail(source(WESTONBIRT), change_event(pages[url], location=venue), url, diagnostics=audit())


def test_registration_and_recurring_worker_share_the_same_html_native_contract(pages, monkeypatch):
    fetch = fetcher(pages)
    monkeypatch.setattr(feed_registration, 'fetch_publisher', fetch)
    result = feed_registration.verify_html_calendar(CARDINHAM, pages[CARDINHAM], monotonic() + 35)
    assert result == {'p_outcome': 'verified', 'p_endpoint': CARDINHAM,
                      'p_type': 'html', 'p_reason': calendar.VERSION}
    assert [call.args[0] for call in fetch.call_args_list] == [LANTERN]
    assert fetch.call_args.kwargs['respect_robots'] is True
    assert fetch.call_args.kwargs['allowed_hosts'] == (forestry.HOST,)
    monkeypatch.setattr(preview_worker, 'fetch_publisher', fetcher(pages))
    output = preview_worker.preview_source(source(CARDINHAM))
    assert output['p_parser_capability'] == native.VERSION
    assert output['p_future_count'] == 1 and output['p_venue_count'] == 1
    [row] = output['p_events']
    assert 'Additional full event description' in row['description']
    assert row['registered_native_content']['description_field'] == forestry.DESCRIPTION_FIELD
    assert row['registered_native_content']['evidence_url'] == LANTERN
    assert row['registered_native_content']['extraction'] == calendar.VERSION
    assert row['venue_address'] == 'Cardinham Woods, Bodmin, PL30 4AL, GB'
    native.validate_record(row, source(CARDINHAM))


def test_complete_empty_forest_can_register_without_claiming_future_events(pages, monkeypatch):
    url = BASE + '/new-forest/venue/events-the-new-forest'
    monkeypatch.setattr(feed_registration, 'fetch_publisher', fetcher(pages))
    result = feed_registration.verify_html_calendar(url, pages[url], monotonic() + 35)
    assert result == {'p_outcome': 'verified', 'p_endpoint': url,
                      'p_type': 'html', 'p_reason': calendar.VERSION}


def test_empty_forestry_capture_acknowledges_native_staging_before_preview(pages, monkeypatch):
    url = BASE + '/new-forest/venue/events-the-new-forest'
    monkeypatch.setattr(preview_worker, 'fetch_publisher', fetcher(pages))
    database = Mock(return_value=0)
    monkeypatch.setattr(preview_worker, 'supabase_rpc', database)
    with preview_worker.capture_publisher_pacing() as pacing:
        output = preview_worker._process_claimed_source_with_pacing(source(url), pacing)
    assert output['complete'] == 1 and output['staged'] == 0
    assert database.call_args_list[0].args == ('community_collector_record_staged_events', {
        'p_source_key': source_key(url), 'p_events': [], 'p_registered_native_content_version': 1})
    final_name, final_payload = database.call_args_list[-1].args
    assert final_name == 'community_collector_record_preview_v3'
    assert final_payload['p_future_count'] == 0 and final_payload['p_venue_count'] == 0
    assert final_payload['p_parser_capability'] == native.VERSION
    assert final_payload['p_error'] is None


def test_seasonal_selected_dates_are_not_continuous_events_or_invented_sessions(pages):
    diagnostics = {}
    rows = forestry.collect(source(BEDGEBURY), fetcher(pages), diagnostics=diagnostics)
    assert not any(row['event_url'] == BASE + '/bedgebury/christmas' for row in rows)
    assert any(row['url'] == BASE + '/bedgebury/christmas'
               and row['reason'] == 'recurrence_exceptions_unresolved' for row in diagnostics['omitted'])
    assert len(rows) == 2  # Other fully dated events survive this eligibility exclusion.
    assert all('[' not in row['venue_address'] for row in rows)  # Native street lines joined as address facts.


def test_published_weekly_clock_overrides_stored_envelope_clock_and_uses_dst(pages, clock):
    clock('2027-03-20T22:00:00+00:00')
    rows = forestry.detail(source(HALDON), pages[PARKRUN], PARKRUN, diagnostics=audit())
    dates = {row['starts_at'][:10]: row['starts_at'][11:16] for row in rows}
    assert dates['2027-03-27'] == '09:00'
    assert dates['2027-04-03'] == '08:00'  # 09:00 Europe/London after the published local clock's DST change.
    assert all(row['ends_at'] is None for row in rows)


def test_weekly_envelope_becomes_separate_sessions_and_term_time_stays_unresolved(pages):
    rows = forestry.detail(source(ALICE), pages[ALICE_RUN], ALICE_RUN, diagnostics=audit())
    assert len(rows) == 7
    assert all(datetime.fromisoformat(row['starts_at']).weekday() == 6 for row in rows)
    assert all(row['ends_at'] is None for row in rows)
    feed = BASE + '/beechenhurst/venue/events-beechenhurst'
    url = BASE + '/forest-event/events-beechenhurst/forest-fit-eb-w-fitness'
    diagnostics = audit()
    assert forestry.detail(source(feed), pages[url], url, diagnostics=diagnostics) == []
    assert diagnostics['omitted'] == [{'url': url, 'reason': 'recurrence_exceptions_unresolved'}]


def test_visible_ordered_dates_with_weekday_checks_outlive_stale_schema_envelope(pages, clock):
    url = BASE + '/westonbirt/willow-sculpture'
    diagnostics = audit()
    rows = forestry.detail(source(WESTONBIRT), pages[url], url, diagnostics=diagnostics)
    assert [row['starts_at'] for row in rows] == ['2026-12-12T10:00:00+00:00']
    [warning] = diagnostics['warnings']
    assert warning['reason'] == 'schema_envelope_ends_before_visible_dates'
    assert warning['schema_end'] == '2027-02-20'
    assert warning['visible_dates_after_end'][0] == '2027-03-13'
    clock('2027-02-21T22:00:00+00:00')
    later = forestry.detail(source(WESTONBIRT), pages[url], url, diagnostics=audit())
    assert [row['starts_at'] for row in later] == ['2027-03-13T10:00:00+00:00']


def test_dates_with_conflicting_weekdays_are_held_not_shifted_to_another_year(pages):
    body = pages[LANTERN].replace('Saturday 19 December', 'Sunday 19 December')
    with pytest.raises(ValueError, match='forestry_schedule_weekday_conflict'):
        forestry.detail(source(CARDINHAM), body, LANTERN, diagnostics=audit())


def test_explicit_all_day_activity_is_diagnosed_not_assigned_midnight(pages):
    feed = BASE + '/dalby-forest/venue/events-dalby-forest'
    url = BASE + '/forest-event/events-dalby-forest/malton-sculpture-trail-dalby-forest'
    diagnostics = audit()
    assert forestry.detail(source(feed), pages[url], url, diagnostics=diagnostics) == []
    assert diagnostics['omitted'] == [{'url': url, 'reason': 'all_day_not_supported'}]


def test_hourly_published_starts_are_distinct_without_invented_end_times(pages):
    feed = BASE + '/whinlatter-forest/venue/events-whinlatter'
    url = BASE + '/forest-event/events-whinlatter/wild-sauna-forest-plunge-nov-29-26'
    rows = forestry.detail(source(feed), pages[url], url, diagnostics=audit())
    assert [row['starts_at'][11:16] for row in rows] == ['09:00', '10:00', '11:00', '12:00', '13:00', '14:00']
    assert len({row['id'] for row in rows}) == 6
    assert all(row['ends_at'] is None for row in rows)


@pytest.mark.parametrize('target', ['https://elsewhere.example/events?page=1',
                                  BASE + '/bedgebury/events?page=1',
                                  WESTONBIRT + '?page=1&category=music', WESTONBIRT + '?page=10'])
def test_pager_cannot_change_scope_or_exceed_its_bound(pages, target):
    body = pages[WESTONBIRT].replace('href="?page=1"', 'href="' + target + '"')
    fetch = Mock()
    with pytest.raises(ValueError, match='forestry_(?:link_scope_conflict|pagination_)'):
        forestry.collect(source(WESTONBIRT), fetch, listing=body)
    fetch.assert_not_called()


def test_stalled_page_and_missing_final_page_never_return_partial_rows(pages):
    changed = dict(pages)
    changed[WESTONBIRT + '?page=1'] = pages[WESTONBIRT]
    with pytest.raises(ValueError, match='forestry_pagination_stalled'):
        forestry.collect(source(WESTONBIRT), fetcher(changed))
    fetch = fetcher(pages)

    def missing(url, accept):
        if url == WESTONBIRT + '?page=3':
            raise preview_worker.PreviewError('publisher_http_403')
        return pages[url]

    fetch.side_effect = missing
    with pytest.raises(preview_worker.PreviewError, match='publisher_http_403'):
        forestry.collect(source(WESTONBIRT), fetch)
    assert fetch.call_count == 4


def test_final_detail_transport_failure_and_deadline_cannot_return_valid_prefix(pages, monkeypatch):
    def fetch(url, accept):
        if url == BEFORE_CHRISTMAS:
            raise preview_worker.PreviewError('publisher_http_401')
        return pages[url]

    with pytest.raises(preview_worker.PreviewError, match='publisher_http_401'):
        forestry.collect(source(HIGH_LODGE), fetch)
    elapsed = [0]
    monkeypatch.setattr(forestry, 'monotonic', lambda: elapsed[0])

    def slow(url, accept):
        if url == LANTERN:
            elapsed[0] = 36
        return pages[url]

    with pytest.raises(ValueError, match='collection_deadline'):
        forestry.collect(source(CARDINHAM), slow, deadline_at=35)


@pytest.mark.parametrize('change', ['canonical', 'title', 'venue', 'body', 'body_limit'])
def test_detail_and_native_description_identity_cannot_be_swapped(pages, change):
    body = pages[LANTERN]
    if change == 'canonical':
        body = body.replace('rel="canonical" href="' + LANTERN + '"', 'rel="canonical" href="' + ALICE_RUN + '"')
        # BeautifulSoup may retain canonical attributes in either order.
        soup = BeautifulSoup(body, 'html.parser')
        soup.select_one('link[rel="canonical"]')['href'] = ALICE_RUN
        body = str(soup)
    elif change == 'title':
        body = change_event(body, name='Different activity')
    elif change == 'venue':
        soup = BeautifulSoup(body, 'html.parser')
        data = json.loads(soup.select_one('script').string)
        venue = deepcopy(data['@graph'][0]['location'])
        venue['url'] = ALICE
        body = change_event(body, location=venue)
    elif change == 'body':
        body = body.replace('Synthetic publisher summary for this event.</p>', 'Unrelated body.</p>')
    else:
        body = body.replace('Additional full event description', 'X' * 12001 + ' Additional full event description')
    with pytest.raises(ValueError, match='forestry_|registered_native_description_too_long'):
        forestry.detail(source(CARDINHAM), body, LANTERN, diagnostics=audit())


def test_forestry_native_body_field_is_not_permission_for_other_publishers(pages):
    [row] = forestry.detail(source(CARDINHAM), pages[LANTERN], LANTERN, diagnostics=audit())
    other = source('https://venue.example.org/events')
    row['event_url'] = 'https://venue.example.org/event/one'
    with pytest.raises(ValueError, match='registered_native_evidence_invalid'):
        native.attach(row, other, description_value='Unrelated text',
                      description_field=forestry.DESCRIPTION_FIELD, evidence_url=row['event_url'])


@pytest.mark.parametrize('url', [BASE + '/events-music-and-arts',
                               BASE + '/seasonal-events-the-forest', WESTONBIRT + '?page=1',
                               'https://forestryengland.uk/westonbirt/events', LANTERN])
def test_marketing_hubs_paginated_subsets_aliases_and_event_pages_are_not_calendar_sources(url):
    assert not forestry.owns_url(url)
