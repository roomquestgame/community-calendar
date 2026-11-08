from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
import pytest

from roomquest import iowa_tourism as tourism
from roomquest.preview_worker import preview_source, _process_claimed_source
from roomquest.publisher_evidence import family, image_url

FIXTURES = Path(__file__).parent / 'fixtures' / 'iowa_tourism'
NOW = datetime(2026, 11, 6, tzinfo=timezone.utc)
THINK = {'source_key': 'think_iowa_city_ia', 'kind': 'json', 'platform_adapter': 'wordpress',
         'timezone': 'America/Chicago', 'feed_url': 'https://thinkiowacity.com/wp-json/tribe/events/v1/events'}


@pytest.fixture(autouse=True)
def factual_fixture_clock(monkeypatch):
    # Exercise the actual normalizer while keeping archived publisher fixtures
    # independent of the date a unit test runs. Calendar-window tests pass NOW.
    monkeypatch.setattr('roomquest.preview_worker._future_datetime',
                        lambda value: value.astimezone(timezone.utc) if isinstance(value, datetime) and value.tzinfo else None)


def source(key):
    return {'source_key': key, 'kind': 'html', 'platform_adapter': 'html',
            'timezone': 'America/Chicago', 'feed_url': tourism.SOURCES[key]}


def test_real_council_sample_preserves_distinct_sessions_real_venues_and_optional_end():
    rows = tourism.parse_council((FIXTURES/'council-sample.html').read_text(), now=NOW, expected_month='2026-11')
    by_title = {r['title']: r for r in rows}
    bison = by_title['Bison Fest at Botna Bend']
    assert bison['starts_at'] == '2026-11-07T17:00:00+00:00'
    assert bison['ends_at'] == '2026-11-07T20:00:00+00:00'
    assert bison['venue_address'] == '42926 Mahogany Road, Hancock, IA'
    assert 'This event is free with a $3 park entry fee' in bison['description']
    assert bison['lat'] is None and bison['lng'] is None
    assert by_title['Council Bluffs Veterans Day Parade']['ends_at'] is None
    sewing = [r for r in rows if r['title'] == 'How to Sew: a Quilted Table Topper']
    assert len(sewing) == 2 and sewing[0]['id'] != sewing[1]['id']
    assert not any('Auto Dealer Renewal' in r['title'] for r in rows)
    assert all(r.get('image_evidence_url') == r['event_url'] for r in rows if r.get('image_url'))


def test_council_missing_description_warns_without_losing_the_occurrence(caplog):
    soup = BeautifulSoup((FIXTURES/'council-sample.html').read_text(), 'html.parser')
    title = soup.find('a', string='Bison Fest at Botna Bend')
    card = title.find_parent(class_='event-overlay')
    for node in card.select('h3, p, ul, ol'):
        if node is not title.parent:
            node.decompose()
    rows = tourism.parse_council(str(soup), now=NOW, expected_month='2026-11')
    event = next(r for r in rows if r['title'] == 'Bison Fest at Botna Bend')
    assert event['description'] == ''
    assert event['venue_address'] == '42926 Mahogany Road, Hancock, IA'
    assert 'field=description reason=missing' in caplog.text


@pytest.mark.parametrize('value,start,end', [('5:00 to 9:00PM', 17, 21),
    ('11:00AM to 2:00PM', 11, 14), ('8:30AM', 8.5, None), ('11PM to 1AM', 23, 25)])
def test_council_time_inference_requires_one_short_unambiguous_interval(value, start, end):
    begins, ends = tourism.council_times(NOW.date(), value)
    assert begins.hour + begins.minute / 60 == start
    if end is None:
        assert ends is None
    else:
        assert (ends - begins.replace(hour=0, minute=0)).total_seconds()/3600 == end


def test_calendar_month_must_match_request_and_verified_empty_month_is_supported():
    html = (FIXTURES/'council-sample.html').read_text()
    with pytest.raises(ValueError, match='month_conflict'):
        tourism.parse_council(html, now=NOW, expected_month='2026-12')
    assert tourism.parse_council('<h2>Events for December 2026</h2>', now=NOW, expected_month='2026-12') == []
    with pytest.raises(ValueError):
        tourism.parse_council('<h1>Access denied</h1>', now=NOW)


def test_mason_rejects_actual_dst_label_and_export_conflicts():
    links = json.loads((FIXTURES/'mason-links.json').read_text())
    for n in (1, 3):
        with pytest.raises(ValueError, match='timezone_review'):
            tourism.parse_mason((FIXTURES/f'mason-{n}.html').read_text(),
                                'https://www.visitmasoncityiowa.com'+links[n-1], now=NOW)


def test_mason_actual_card_has_venue_address_and_does_not_invent_export_default_end():
    links = json.loads((FIXTURES/'mason-links.json').read_text())
    expo = tourism.parse_mason((FIXTURES/'mason-2.html').read_text(),
                              'https://www.visitmasoncityiowa.com'+links[1], now=NOW)
    assert expo['ends_at'] == '2026-11-06T23:00:00+00:00'
    music = tourism.parse_mason((FIXTURES/'mason-5.html').read_text(),
                               'https://www.visitmasoncityiowa.com'+links[4], now=NOW)
    assert music['venue_address'] == '17 North Federal Avenue, Mason City, IA 50401'
    assert music['starts_at'] == '2026-11-07T01:00:00+00:00' and music['ends_at'] is None
    assert family('visit_mason_city_ia', music['event_url']) == 'mason_city'
    assert image_url(music['image_url'], 'mason_city')


def test_mason_fetches_only_canonical_first_page_links_and_accounts_for_all_15():
    links = json.loads((FIXTURES/'mason-links.json').read_text())
    calls = []
    def fetch(url, accept):
        calls.append(url)
        if url == tourism.SOURCES['visit_mason_city_ia']:
            return (FIXTURES/'mason-listing.html').read_text()
        n = links.index(url.replace('https://www.visitmasoncityiowa.com', ''))+1
        return (FIXTURES/f'mason-{n}.html').read_text()
    rows = tourism.collect(source('visit_mason_city_ia'), fetch, now=NOW)
    assert len(rows) == 11 and len(calls) == 16
    assert len({r['id'] for r in rows}) == 11
    assert all(r['venue_address'] and r['description'] for r in rows)


def test_mason_detail_transport_failure_is_not_reported_as_a_complete_partial_snapshot():
    def fetch(url, accept):
        if url == tourism.SOURCES['visit_mason_city_ia']:
            return (FIXTURES/'mason-listing.html').read_text()
        raise OSError('transport unavailable')
    with pytest.raises(OSError):
        tourism.collect(source('visit_mason_city_ia'), fetch, now=NOW)


def test_think_sample_does_not_turn_multi_date_entries_into_continuous_attendance():
    data = (FIXTURES/'think-sample.json').read_text()
    rows = tourism.collect_think(THINK, lambda *_: data)
    assert rows
    assert not any('BEARS BEARS' in r['title'] or 'Open Studio Weekend' in r['title'] for r in rows)
    assert all(datetime.fromisoformat(r['ends_at']) - datetime.fromisoformat(r['starts_at']) <= timedelta(hours=16) for r in rows)
    assert any(r['venue_address'] == '' and r['lat'] is None for r in rows)
    assert all(r['description'] and 'publisher_categories' in r for r in rows)


def test_think_missing_description_keeps_public_event_but_not_hidden_event(caplog):
    payload = json.loads((FIXTURES/'think-sample.json').read_text())
    rows = tourism.collect_think(THINK, lambda *_: json.dumps(payload), now=NOW)
    item = next(item for item in payload['events'] if str(item['id']) == rows[0]['id'])
    item.pop('description')
    hidden = {**item, 'id': 99999991, 'hide_from_listings': True}
    rows = tourism.collect_think(THINK, lambda *_: json.dumps({'events': [item, hidden]}), now=NOW)
    row, = rows
    assert row['id'] == str(item['id'])
    assert row['description'] == ''
    assert 'field=description reason=missing' in caplog.text


def test_think_bounded_pagination_rebuilds_registered_url_and_preserves_distinct_dates():
    payload = json.loads((FIXTURES/'think-sample.json').read_text())
    item = next(e for e in payload['events'] if e.get('start_date','').endswith('18:00:00') and e.get('end_date','').endswith('20:00:00'))
    second = {**item, 'id': 99999991, 'title': 'Different session'}
    calls = []
    def fetch(url, accept):
        calls.append(url);page=int(parse_qs(urlsplit(url).query)['page'][0])
        return json.dumps({'events': [item if page == 1 else second], 'total_pages': 2,
                           'next_rest_url': 'http://127.0.0.1/' if page == 1 else None})
    rows = tourism.collect_think(THINK, fetch)
    assert len(rows) == 2 and len(calls) == 2
    assert all(u.startswith(THINK['feed_url']+'?') for u in calls)


@pytest.mark.parametrize('key', ['unleashcb_ia','visit_mason_city_ia','think_iowa_city_ia'])
def test_enrollment_identity_cannot_be_redirected_to_an_arbitrary_source(key):
    s = THINK if key == 'think_iowa_city_ia' else source(key)
    fetch = Mock(side_effect=AssertionError('No fetch allowed'))
    collector = tourism.collect_think if key == 'think_iowa_city_ia' else tourism.collect
    with pytest.raises(ValueError, match='unregistered'):
        collector({**s, 'feed_url': 'https://unrelated.example.org/calendar/'}, fetch)
    fetch.assert_not_called()


def test_wordpress_dispatch_sends_think_evidence_to_staging_and_versioned_completion():
    def rpc(name, payload):
        return len(payload['p_events']) if name.endswith('record_staged_events') else None
    with patch('roomquest.preview_worker.fetch_publisher', return_value=(FIXTURES/'think-sample.json').read_text()), \
         patch('roomquest.preview_worker.supabase_rpc', side_effect=rpc) as db:
        assert _process_claimed_source(THINK)['complete'] == 1
    assert db.call_args_list[-1].args[0] == 'community_collector_record_preview_v3'
    assert db.call_args_list[-1].args[1]['p_parser_capability'] == 'publisher_event_candidates_v1'
    assert all('description' in r for r in db.call_args_list[0].args[1]['p_events'])


def test_think_requests_local_calendar_dates_across_utc_midnight():
    calls = []
    def fetch(url, accept):
        calls.append(url)
        return json.dumps({'events': [], 'total_pages': 1})
    assert tourism.collect_think(THINK, fetch, now=NOW) == []
    query = parse_qs(urlsplit(calls[0]).query)
    assert query['start_date'] == ['2026-11-05']
    assert query['end_date'] == ['2027-01-04']
