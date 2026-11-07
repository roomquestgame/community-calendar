"""Captured public HTML replay, venue holds and publisher-bound evidence."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
from bs4 import BeautifulSoup

from roomquest import preview_worker
from roomquest import raleigh_html as r
from roomquest.publisher_evidence import family, image_url

FIXTURES = Path(__file__).parent / 'fixtures' / 'raleigh'
NOW = datetime(2026, 11, 7, tzinfo=timezone.utc)
FILES = dict(zip(r.SOURCES, ('ponysaurus', 'black_chamber', 'volumes_vices', 'makrs',
                            'triangle_popup', 'city_farm', 'quail_ridge', 'blackbird')))


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    class DateMeta(type):
        def __instancecheck__(cls, obj):
            return isinstance(obj, datetime)
    class Frozen(datetime, metaclass=DateMeta):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(preview_worker, 'datetime', Frozen)


def html(name):
    return (FIXTURES / (name + '.html')).read_text()


def source(key):
    return dict(source_key=key, feed_url=r.SOURCES[key][0], kind='html', platform_adapter='html')


def fetcher(key):
    base = r.SOURCES[key][0]
    pages = {base: html(FILES[key])}
    if key == 'quail_ridge_books_nc':
        pages[base + '/2026/12'] = html('quail-dec')
        pages[base + '/2027/01'] = html('quail-jan')
    if key == 'blackbird_books_nc':
        pages[base + '?page=1'] = html('blackbird-page1')
    def fetch(url, accept):
        assert accept == 'text/html'
        assert r.page_url(key, url) or r.event_url(key, url)
        assert 'format=' not in url
        if url not in pages:
            raise OSError('detail_not_in_capture')
        return pages[url]
    return Mock(side_effect=fetch)


@pytest.mark.parametrize('key', [k for k in r.SOURCES if k != 'black_chamber_raleigh_nc'])
def test_real_calendars_preserve_actual_addresses_and_candidate_evidence(key):
    fetch = fetcher(key)
    rows = r.collect(source(key), fetch, now=NOW)
    assert rows
    assert len({(x['id'], x['starts_at']) for x in rows}) == len(rows)
    for row in rows:
        assert r.event_url(key, row['event_url'])
        assert row['lat'] is None and row['lng'] is None
        assert row['venue_address'] and row['venue_city']
        assert len(row['description']) <= 2000
        assert row['timezone'] == r.TIMEZONE
        assert family(key, row['event_url']) == 'raleigh:' + key
        assert row['details_evidence_url'] == row['event_url']
        if row.get('image_url'):
            assert image_url(row['image_url'], 'raleigh:' + key) == row['image_url']
            assert row['image_extractor_version'] == 'publisher_event_candidates_v1'
    assert len(fetch.call_args_list) <= r.MAX_PAGES + r.MAX_DETAILS


def test_black_chamber_missing_street_is_held_not_pinned_to_office():
    with pytest.raises(ValueError, match='publisher_event_evidence_unavailable'):
        r.collect(source('black_chamber_raleigh_nc'), fetcher('black_chamber_raleigh_nc'), now=NOW)


def test_ponysaurus_incomplete_venues_are_held(capsys):
    rows = r.collect(source('ponysaurus_raleigh_nc'), fetcher('ponysaurus_raleigh_nc'), now=NOW)
    assert 0 < len(rows) < 23
    assert 'event_venue_unreviewed' in capsys.readouterr().err


def test_regional_markets_keep_offsite_cities():
    rows = r.collect(source('makrs_society_nc'), fetcher('makrs_society_nc'), now=NOW)
    assert len({x['venue_city'] for x in rows}) > 1


def test_explicit_conflicting_holiday_schedule_is_held():
    with pytest.raises(r.EventHold, match='publisher_schedule_conflict'):
        r._description_schedule('Event Times: Friday, December 19', datetime(2026,12,19,18,tzinfo=timezone.utc))


@pytest.mark.parametrize('suffix', ['?format=json', '?format=ical', '#detail', '/%2e%2e/private', '/%2fprivate'])
def test_event_urls_reject_exports_and_encoded_traversal(suffix):
    assert not r.event_url('ponysaurus_raleigh_nc', r.SOURCES['ponysaurus_raleigh_nc'][0] + '/event' + suffix)


@pytest.mark.parametrize('key', r.SOURCES)
def test_source_identity_is_exact(key):
    bad = source(key); bad['feed_url'] += '?format=json'
    with pytest.raises(ValueError, match='unregistered_raleigh_source'):
        r.collect(bad, Mock(), now=NOW)


def test_missing_or_foreign_pagination_never_claims_complete_snapshot():
    key = 'blackbird_books_nc'
    fetch = Mock(side_effect=[html('blackbird'), OSError('network_failure')])
    with pytest.raises(OSError):
        r.collect(source(key), fetch, now=NOW)
    mutated = html('blackbird').replace('?page=1', '?page=99')
    with pytest.raises(ValueError, match='pagination_requires_review'):
        r.collect(source(key), Mock(return_value=mutated), now=NOW)


def test_empty_calendar_requires_explicit_empty_marker():
    key='quail_ridge_books_nc'
    rows, _, holds = r.indiecommerce(html('quail-jan'), key, r.SOURCES[key][0] + '/2027/01', now=NOW)
    assert rows == [] and holds == []
    with pytest.raises(ValueError, match='unproven_empty_calendar'):
        r.indiecommerce('<div class="view-indiecommerce-event-list"></div>', key, r.SOURCES[key][0], now=NOW)


def test_image_candidates_cannot_cross_publishers_or_use_tracking_query():
    key='ponysaurus_raleigh_nc'
    image='https://images.squarespace-cdn.com/content/v1/' + r.SOURCES[key][2] + '/event.jpg'
    assert r.photo_url(key, image) == image
    assert r.photo_url('triangle_popup_nc', image) is None
    assert r.photo_url(key, image + '?token=secret') is None
    assert r.photo_url(key, image.replace('event.jpg', 'logo.jpg')) is None
    assert r.photo_url(key, image.replace('https://', 'https://user@')) is None
    book='https://quailridgebooks.com/sites/default/files/styles/event/public/event.jpg?itok=abc_123'
    assert r.photo_url('quail_ridge_books_nc', book) == book
    assert r.photo_url('blackbird_books_nc', book) is None


def test_registration_cost_facts_never_infer_free_from_free_drinks():
    assert 'cost' not in r.facts_from_text('Enjoy a free drink with your $10 ticket.')
    assert r.facts_from_text('Free admission. RSVP required. All ages welcome.') == {
        'cost':'Free admission.', 'registration':'RSVP required.', 'audience':'All ages welcome.'}


def test_expired_or_changed_collection_never_becomes_healthy():
    key='ponysaurus_raleigh_nc'
    with pytest.raises(ValueError, match='publisher_calendar_identity_changed'):
        r.collect(source(key), Mock(return_value=html('ponysaurus').replace(r.SOURCES[key][1], 'other')), now=NOW)
    with pytest.raises(ValueError, match='collection_deadline'):
        r.collect(source(key), Mock(), now=NOW, deadline_at=0)


def test_conflicting_duplicate_occurrences_fail():
    rows=r.collect(source('volumes_vices_nc'), fetcher('volumes_vices_nc'), now=NOW)
    with pytest.raises(ValueError, match='conflicting_event_occurrence'):
        r._finish([rows[0], dict(rows[0], venue_name='Other place')], [], 'volumes_vices_nc', 2)


def test_detail_enrichment_uses_matching_event_and_ignores_broken_jsonld_address():
    key='blackbird_books_nc'
    rows=r.collect(source(key),fetcher(key),now=NOW)
    crochet=next(x for x in rows if x['event_url'].endswith('/coffee-crochet'))
    original_address=crochet['venue_address']
    enriched=r._enrich_books([crochet],key,Mock(return_value=html('blackbird-crochet')),float('inf'))[0]
    assert datetime.fromisoformat(enriched['ends_at']).astimezone(timezone.utc)==datetime(2026,11,12,tzinfo=timezone.utc)
    assert enriched['venue_address']==original_address
    assert enriched['lat'] is None and enriched['lng'] is None
    assert len(enriched['description'])>100
    before=dict(enriched)
    r._enrich_books([enriched],key,Mock(return_value=html('quail-story-future')),float('inf'))
    assert enriched==before


def test_worker_dispatch_preserves_real_transport_guards(monkeypatch):
    key='volumes_vices_nc'
    calls=[]
    def transport(url,accept,**kwargs):
        calls.append((url,accept,kwargs))
        return html('volumes_vices')
    monkeypatch.setattr(preview_worker,'fetch_publisher',transport)
    output=preview_worker.preview_source(source(key))
    assert output['p_parser_capability']=='publisher_event_candidates_v1'
    assert output['p_events']
    assert len(calls)==1
    assert calls[0][2]['respect_robots'] is True
    assert calls[0][2]['allowed_hosts']==('www.volumesandvices.com',)
    assert calls[0][2]['deadline_at']>0
