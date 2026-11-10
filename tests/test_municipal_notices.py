from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from roomquest import municipal_notices as notices, preview_worker as worker

FIXTURES = Path(__file__).parent / 'fixtures' / 'civic'
NOW = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    class ClockMeta(type):
        def __instancecheck__(cls, value):
            return isinstance(value, datetime)

    class Frozen(datetime, metaclass=ClockMeta):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    for module in (notices, worker):
        monkeypatch.setattr(module, 'datetime', Frozen)
        monkeypatch.setattr(module, 'monotonic', lambda: 100.0)


def fixture(name):
    return (FIXTURES / name).read_text()


def candidate():
    return notices.candidates(fixture('clarksville_news.html'), now=NOW)[0]


def test_actual_first_page_selects_dated_closure_and_ignores_publication_dates_and_general_news():
    selected = notices.candidates(fixture('clarksville_news.html'), now=NOW)
    assert len(selected) == 1
    assert selected[0]['id'] == '7444'
    assert selected[0]['day'].isoformat() == '2026-11-11'
    # The article was published November 5; the November 9 drought news,
    # utility enrollment post and unbounded leaf-start announcement are not events.
    assert selected[0]['url'] == 'https://clarksvilleva.org/7444-2/'


def test_closure_uses_exclusive_local_date_bounds_with_published_reopening_conditions():
    row = notices.parse_notice(fixture('clarksville_closure.html'), candidate(), now=NOW)
    assert row['id'] == 'municipal:clarksville:7444'
    assert row['starts_on'] == '2026-11-11' and row['ends_on'] == '2026-11-12'
    assert row['starts_at'] == '2026-11-11T05:00:00+00:00'
    assert row['ends_at'] == row['civic']['valid_until'] == '2026-11-12T05:00:00+00:00'
    assert '8:30 a.m.' in row['description']
    assert row['civic']['time_precision'] == 'date'
    assert row['civic']['kind'] == 'service' and row['civic']['topic'] == 'public_services'
    assert row['civic']['source_url'] == row['event_url']
    assert row['civic']['jurisdiction_id'] == 'us-va-clarksville'
    assert row['lat'] is None and row['lng'] is None
    assert row['venue_name'] == row['venue_address'] == ''


@pytest.mark.parametrize('replacement', ['November 11', 'Tuesday, November 11, 2026', 'November 31, 2026'])
def test_missing_year_conflicting_weekday_and_invalid_date_are_held(replacement):
    soup = BeautifulSoup(fixture('clarksville_news.html'), 'html.parser')
    node = soup.select_one('article.post-7444')
    node.select_one('.elementor-post__title a').string = 'Town Hall Office Closed On ' + replacement
    with pytest.raises(ValueError, match='municipal_notice_evidence_unavailable'):
        notices.candidates(str(node))


@pytest.mark.parametrize('replacement', [
    'https://example.com/7444-2/', 'http://clarksvilleva.org/7444-2/',
    'https://clarksvilleva.org:443/7444-2/', 'https://clarksvilleva.org/news/page/2/',
    'https://clarksvilleva.org/7444-2/?preview=1',
])
def test_candidate_links_do_not_widen_host_or_route_scope(replacement):
    soup = BeautifulSoup(fixture('clarksville_news.html'), 'html.parser')
    node = soup.select_one('article.post-7444')
    node.select_one('.elementor-post__title a')['href'] = replacement
    with pytest.raises(ValueError, match='municipal_notice_evidence_unavailable'):
        notices.candidates(str(node))


@pytest.mark.parametrize('old,new,reason', [
    ('https://clarksvilleva.org/7444-2/', 'https://clarksvilleva.org/other/', 'detail_identity_mismatch'),
    ('Wednesday, November 11th', 'Thursday, November 12th', 'closure_date_conflict'),
    ('Thursday, November 12', 'Wednesday, November 11', 'reopening_date_conflict'),
])
def test_detail_identity_and_event_date_conflicts_are_held(old, new, reason):
    with pytest.raises(ValueError, match='municipal_.*' + reason):
        notices.parse_notice(fixture('clarksville_closure.html').replace(old, new), candidate())


def test_expired_articles_are_ignored_without_becoming_recurring_anniversaries():
    assert notices.candidates(fixture('clarksville_news.html'),
                              now=datetime(2027, 11, 10, tzinfo=timezone.utc)) == []


def test_unknown_timed_meeting_end_and_venue_remain_unknown():
    item = candidate()
    item.update(kind='meeting', title='Town Council Regular Meeting November 11, 2026 @ 6:30 p.m.')
    soup = BeautifulSoup(fixture('clarksville_closure.html'), 'html.parser')
    soup.h1.string = item['title']
    soup.select_one('.elementor-widget-theme-post-content .elementor-widget-container').string = 'Council meeting agenda.'
    row = notices.parse_notice(str(soup), item)
    assert row['starts_at'] == '2026-11-11T23:30:00+00:00'
    assert row['ends_at'] is None and row['venue_address'] == ''
    assert row['civic']['time_precision'] == 'timed'
    assert row['civic']['valid_until'] == '2026-11-12T02:30:00+00:00'  # Internal visibility only.
    item['title'] = item['title'].replace(' @ 6:30 p.m.', '')
    soup.h1.string = item['title']
    with pytest.raises(ValueError, match='municipal_meeting_time_unresolved'):
        notices.parse_notice(str(soup), item)


def test_explicit_cancellation_updates_same_notice_and_ambiguous_prose_is_held():
    item = candidate()
    item['title'] += ' — CANCELLED'
    soup = BeautifulSoup(fixture('clarksville_closure.html'), 'html.parser')
    soup.h1.string = item['title']
    row = notices.parse_notice(str(soup), item)
    assert row['publisher_status'] == 'cancelled' and row['id'] == 'municipal:clarksville:7444'
    soup.h1.string = candidate()['title']
    body = soup.select_one('.elementor-widget-theme-post-content .elementor-widget-container')
    body.append(' A previous office closure was cancelled.')
    with pytest.raises(ValueError, match='municipal_notice_status_requires_review'):
        notices.parse_notice(str(soup), candidate())


def test_listing_shape_identity_and_detail_limits_are_enforced(monkeypatch):
    with pytest.raises(ValueError, match='municipal_notice_listing_shape_changed'):
        notices.candidates('<html>Access denied</html>')
    soup = BeautifulSoup(fixture('clarksville_news.html'), 'html.parser')
    node = soup.select_one('article.post-7444')
    with pytest.raises(ValueError, match='municipal_notice_identity_conflict'):
        notices.candidates(str(node) + str(node))
    monkeypatch.setattr(notices, 'MAX_DETAILS', 0)
    with pytest.raises(ValueError, match='municipal_notice_detail_limit'):
        notices.candidates(str(node))


def test_required_detail_fetch_failure_propagates_instead_of_a_healthy_empty_snapshot():
    calls = []

    def fetch(url, accept):
        calls.append(url)
        if len(calls) == 1:
            return fixture('clarksville_news.html')
        raise worker.PreviewError('http_503')

    with pytest.raises(worker.PreviewError, match='http_503'):
        notices.collect(notices.source_payload(), fetch)
    assert calls == [notices.URL, candidate()['url']]


@pytest.mark.parametrize('field,value', [
    ('timezone', 'UTC'), ('kind', 'json'), ('platform_adapter', 'wordpress'),
    ('feed_url', 'https://townofclarksville.com/news/'),
])
def test_changed_tuple_fails_before_network(field, value):
    source = notices.source_payload()
    source[field] = value
    with pytest.raises(ValueError, match='unregistered_municipal_notice_source'):
        notices.collect(source, lambda *_: pytest.fail('Network must not be used'))


@pytest.mark.parametrize('field,value', [
    ('civic_contract_version', None), ('civic_contract_version', 2),
    ('civic_contract_version', True), ('civic_contract_version', '1'),
    ('civic_jurisdiction_id', None), ('civic_jurisdiction_id', 'us-va-south-hill'),
])
def test_notice_route_requires_server_capability_before_fetch(field, value):
    source = notices.source_payload()
    if value is None:
        source.pop(field)
    else:
        source[field] = value
    with pytest.raises(ValueError, match='unregistered_municipal_notice_source'):
        notices.collect(source, lambda *_: pytest.fail('Network must not be used'))


def test_claim_display_name_is_tolerated_without_changing_jurisdiction():
    source = {**notices.source_payload(), 'action': 'collect',
              'civic_jurisdiction_name': 'Town of Clarksville'}
    rows = notices.collect(source, lambda url, _: fixture(
        'clarksville_news.html' if url == notices.URL else 'clarksville_closure.html'))
    assert len(rows) == 1 and rows[0]['civic']['jurisdiction_id'] == 'us-va-clarksville'


def test_new_adapter_uses_guarded_transport_and_existing_token_scoped_staging(monkeypatch):
    requests, calls = [], []

    def fetch(url, accept, **kwargs):
        requests.append(url)
        assert accept == 'text/html'
        assert kwargs == {'respect_robots': True, 'allowed_hosts': ('clarksvilleva.org',), 'deadline_at': 125.0}
        return fixture('clarksville_news.html' if url == notices.URL else 'clarksville_closure.html')

    monkeypatch.setattr(worker, 'fetch_publisher', fetch)
    monkeypatch.setattr(worker, 'supabase_rpc', lambda name, payload: calls.append((name, deepcopy(payload))) or 1)
    result = worker._process_claimed_source(notices.source_payload())
    assert result['complete'] == 1 and result['staged'] == 1
    assert requests == [notices.URL, candidate()['url']]
    assert [name for name, _ in calls] == ['community_collector_record_staged_events', 'community_collector_record_preview_v2']
    assert calls[0][1]['p_events'][0]['starts_on'] == '2026-11-11'
    assert 'p_parser_capability' not in calls[-1][1]
