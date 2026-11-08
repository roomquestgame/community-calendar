"""Town fixtures through guarded dispatch, exact evidence routing and staging."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from bs4 import BeautifulSoup
import pytest

from roomquest import holly_hill_civic as civic
from roomquest import holly_hill_sources as sources
from roomquest import preview_worker as worker
from roomquest import publisher_evidence as evidence
from roomquest import santee_town_calendar as parser

FIXTURES = Path(__file__).parent / 'fixtures' / 'santee_town_calendar'
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
EVENT = parser.HOST + '/event/town-santee-christmas-parade'
POSTER = parser.HOST + '/sites/default/files/uploads/News/santee-christmas-parade-poster.png'


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    class ClockMeta(type):
        def __instancecheck__(cls, value):
            return isinstance(value, datetime)

    class Frozen(datetime, metaclass=ClockMeta):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    for module in (parser, worker):
        monkeypatch.setattr(module, 'datetime', Frozen)
        monkeypatch.setattr(module, 'monotonic', lambda: 100.0)


def fixture(name):
    return (FIXTURES / name).read_text()


def transport(monkeypatch, *, detail=None):
    feed = parser.calendar_feed_url(fixture('calendar_page.html'), now=NOW)
    responses = {
        parser.URL: ('text/html', fixture('calendar_page.html')),
        feed: ('application/json', fixture('calendar_feed.json')),
        EVENT: ('text/html', fixture('parade_detail.html') if detail is None else detail),
    }

    def fetch(url, accept, **kwargs):
        assert kwargs['respect_robots'] is True
        assert kwargs['allowed_hosts'] == ('www.townofsantee-sc.org',)
        assert kwargs['deadline_at'] is not None
        expected_accept, body = responses[url]
        assert accept == expected_accept
        return body

    get = Mock(side_effect=fetch)
    monkeypatch.setattr(worker, 'fetch_publisher', get)
    return get


def test_registered_town_reaches_normal_guarded_preview_with_approved_approximation(monkeypatch):
    get = transport(monkeypatch)
    result = worker.preview_source(sources.source_payload(parser.KEY), deadline_at=120)
    assert get.call_count == 3
    assert all(call.kwargs['deadline_at'] == 112.0 for call in get.call_args_list)
    assert result['p_error'] is None and result['p_future_count'] == result['p_venue_count'] == 1
    assert result['p_parser_capability'] == evidence.IMAGE_VERSION
    row = result['p_events'][0]
    assert row['venue_name'] == parser.APPROXIMATE_VENUE and row['venue_address'] == ''
    assert (row['lat'], row['lng']) == parser.TOWN_CENTER
    assert row['location_provenance'] == 'reviewed_town_center_fallback'
    assert row['location_accuracy'] == 'approximate' and row['location_geoid'] == parser.TOWN_GEOID
    assert row['location_evidence_url'] == parser.CENSUS_EVIDENCE
    assert row['description'].startswith(parser.APPROXIMATE_DESCRIPTION)
    assert row['publisher_details'] == {}  # Approximation is not a publisher meeting-location claim.
    assert row['details_evidence_url'] == row['image_evidence_url'] == row['event_url'] == EVENT
    assert evidence.family(parser.KEY, EVENT) == 'holly_hill:' + parser.KEY
    assert evidence.image_url(row['image_url'], evidence.family(parser.KEY, EVENT)) == POSTER


def test_approved_approximation_and_provenance_survive_staging_before_success(monkeypatch):
    transport(monkeypatch)
    calls = []

    def rpc(name, payload):
        calls.append((name, deepcopy(payload)))
        return len(payload.get('p_events', []))

    monkeypatch.setattr(worker, 'supabase_rpc', rpc)
    result = worker._process_claimed_source(sources.source_payload(parser.KEY))
    assert (result['complete'], result['failed'], result['staged']) == (1, 0, 1)
    assert [name for name, _ in calls] == [
        'community_collector_record_staged_events', 'community_collector_record_preview_v3']
    staged = calls[0][1]
    assert staged['p_source_key'] == parser.KEY
    row = staged['p_events'][0]
    assert row['event_url'] == EVENT and row['image_url'] == POSTER
    assert (row['lat'], row['lng'], row['venue_address']) == (*parser.TOWN_CENTER, '')
    assert row['location_provenance'] == 'reviewed_town_center_fallback'
    assert row['location_accuracy'] == 'approximate' and row['location_geoid'] == parser.TOWN_GEOID
    assert row['location_evidence_url'] == parser.CENSUS_EVIDENCE
    assert row['description'].startswith(parser.APPROXIMATE_DESCRIPTION)
    status = calls[-1][1]
    assert status['p_error'] is None and status['p_future_count'] == status['p_venue_count'] == 1
    assert status['p_parser_capability'] == evidence.IMAGE_VERSION and 'p_events' not in status


def test_published_meeting_address_uses_normal_geocoding_without_approximate_point(monkeypatch):
    soup = BeautifulSoup(fixture('parade_detail.html'), 'html.parser')
    body = soup.select_one('.node--type-calendar-event .field--name-body')
    body.clear()
    body.string = 'Meet at 194 Municipal Way, Santee, SC 29142.'
    transport(monkeypatch, detail=str(soup))
    result = worker.preview_source(sources.source_payload(parser.KEY))
    row = result['p_events'][0]
    assert result['p_venue_count'] == 0
    assert row['venue_address'] == '194 Municipal Way, Santee, SC 29142'
    assert row['lat'] is row['lng'] is None
    assert row['location_provenance'] == 'publisher_event_address_pending_geocode'
    assert 'location_accuracy' not in row and 'location_geoid' not in row
    assert row['reason'] == 'missing_verified_venue_geo'


def test_contact_address_only_records_location_hold_without_staging(monkeypatch):
    soup = BeautifulSoup(fixture('parade_detail.html'), 'html.parser')
    body = soup.select_one('.node--type-calendar-event .field--name-body')
    body.clear()
    body.string = 'Mail parade entry forms to 194 Municipal Way, Santee, SC 29142.'
    transport(monkeypatch, detail=str(soup))
    calls = []
    monkeypatch.setattr(worker, 'supabase_rpc', lambda name, payload: calls.append((name, payload)))
    result = worker._process_claimed_source(sources.source_payload(parser.KEY))
    assert (result['complete'], result['failed'], result['staged']) == (0, 1, 0)
    assert len(calls) == 1 and calls[0][0] == 'community_collector_record_preview_v3'
    assert calls[0][1]['p_error'] == 'santee_event_location_context_required'


@pytest.mark.parametrize('field,value', [
    ('feed_url', parser.URL + '?unreviewed=1'), ('kind', 'json'),
    ('platform_adapter', 'wordpress'), ('timezone', 'UTC'),
])
def test_changed_registered_identity_is_rejected_before_fetch(monkeypatch, field, value):
    source = sources.source_payload(parser.KEY)
    source[field] = value
    get = Mock(side_effect=AssertionError('changed source identity must not fetch'))
    monkeypatch.setattr(worker, 'fetch_publisher', get)
    with pytest.raises(worker.PreviewError, match='unregistered_holly_hill_source'):
        worker.preview_source(source)
    assert not sources.publisher_media(source)
    get.assert_not_called()


@pytest.mark.parametrize('url', [
    EVENT + '/', EVENT + '?id=314', EVENT.replace('https:', 'http:'),
    EVENT.replace('www.townofsantee-sc.org', 'www.townofsantee-sc.org.evil.example'),
    EVENT.replace('www.townofsantee-sc.org', 'www.townofsantee-sc.org:443'),
    parser.URL, 'https://santeecoopercountry.org/events/',
])
def test_town_evidence_rejects_noncanonical_or_cross_publisher_event_urls(url):
    assert evidence.family(parser.KEY, url) is None
    with pytest.raises(ValueError, match='publisher_evidence_identity_mismatch'):
        evidence.attach({'event_url': url}, parser.KEY, candidate=POSTER)


@pytest.mark.parametrize('url', [
    POSTER + '?size=1', POSTER.replace('/News/', '/'),
    POSTER.replace('www.townofsantee-sc.org', 'elsewhere.example'),
    POSTER.replace('santee-christmas-parade-poster', 'town-logo'),
    POSTER.replace('.png', '.svg'),
])
def test_town_artwork_keeps_exact_reviewed_host_path_and_file_contract(url):
    family = evidence.family(parser.KEY, EVENT)
    assert evidence.image_url(url, family) is None
    attached = evidence.attach({'event_url': EVENT}, parser.KEY, candidate=url)
    assert 'image_url' not in attached


def test_town_and_regional_santee_evidence_remain_distinct():
    assert evidence.family(civic.SANTEE, EVENT) is None
    attached = evidence.attach({'event_url': EVENT}, parser.KEY, candidate=POSTER)
    assert attached['image_url'] == POSTER
    assert attached['details_evidence_url'] == attached['image_evidence_url'] == EVENT


def test_required_transport_failure_records_hold_without_staging(monkeypatch):
    monkeypatch.setattr(worker, 'fetch_publisher', Mock(side_effect=worker.PreviewError('robots_denied')))
    calls = []
    monkeypatch.setattr(worker, 'supabase_rpc', lambda name, payload: calls.append((name, payload)))
    result = worker._process_claimed_source(sources.source_payload(parser.KEY))
    assert (result['complete'], result['failed'], result['staged']) == (0, 1, 0)
    assert len(calls) == 1 and calls[0][0] == 'community_collector_record_preview_v3'
    assert calls[0][1]['p_error'] == 'robots_denied'
