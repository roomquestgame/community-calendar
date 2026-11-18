"""Santa Cruz publisher calendar adapter and guarded preview contract."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import json
import pytest

from roomquest import santa_cruz_sources as sc
from roomquest import preview_worker
from roomquest.preview_worker import PreviewError

NOW = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def freeze_preview(monkeypatch):
    monkeypatch.setattr(preview_worker, '_future_datetime',
                        lambda date: date.astimezone(timezone.utc))


def source(key=sc.KUUMBWA):
    url, kind, adapter = sc.SOURCES[key]
    return {'source_key': key, 'feed_url': url, 'kind': kind,
            'platform_adapter': adapter, 'timezone': sc.ZONE}


def event(key=sc.KUUMBWA, **changes):
    local = (NOW + timedelta(days=2)).astimezone(ZoneInfo(sc.ZONE))
    start = local.replace(minute=0, second=0, microsecond=0)
    root = 'https://www.kuumbwajazz.org/calendar/' if key == sc.KUUMBWA else 'https://events.ucsc.edu/event/'
    row = {'id': 10001, 'status': 'publish', 'title': 'Jazz Ensemble Concert',
           'start_date': start.strftime('%Y-%m-%d %H:%M:%S'),
           'utc_start_date': start.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
           'end_date': (start + timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S'),
           'utc_end_date': (start + timedelta(hours=2)).astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
           'timezone': sc.ZONE, 'description': '<p>Full <b>musical</b> program and guest performers.</p>',
           'url': root + 'jazz-ensemble-concert/',
           'venue': {'venue': 'Kuumbwa Jazz Center' if key == sc.KUUMBWA else 'Merrill College Office',
                     'address': '320 Cedar St.' if key == sc.KUUMBWA else '641 Merrill Road',
                     'city': 'Santa Cruz', 'state': '', 'zip': '95060'},
           'image': {'url': ('https://www.kuumbwajazz.org' if key == sc.KUUMBWA else 'https://events.ucsc.edu')
                     + '/wp-content/uploads/2026/11/concert.jpg', 'width': 1000},
           'categories': [{'name': 'Concerts'}]}
    row.update(changes)
    return row


def mock_fetch(events, total=1):
    def fetch(url, accept):
        assert accept == 'application/json' and 'per_page=100' in url
        return json.dumps({'events': events, 'total_pages': total})
    return fetch


def test_source_and_endpoints_locked():
    for changes in ({'timezone': 'America/New_York'}, {'kind': 'html'},
                    {'feed_url': 'https://example.com/events'}):
        with pytest.raises(ValueError, match='unregistered_santa_cruz_source'):
            sc.collect(dict(source(), **changes), mock_fetch([]), now=NOW)
    assert sc.event_url(sc.KUUMBWA, 'https://www.kuumbwajazz.org/calendar/jazz-ensemble-concert/')
    assert sc.event_url(sc.UCSC, 'https://events.ucsc.edu/event/jazz-ensemble-concert/')
    assert not sc.event_url(sc.UCSC, 'https://bad.example.com/event/jazz-ensemble-concert/')


def test_full_text_event_street_and_publisher_picture():
    full = '<p>' + 'This is a comprehensive performance description. ' * 60 + '</p>'
    rows = sc.collect(source(), mock_fetch([event(description=full)]), now=NOW)
    assert len(rows) == 1
    row = rows[0]
    assert len(row['description']) > 2000
    assert '<' not in row['description']
    assert row['venue_address'] == '320 Cedar St, Santa Cruz, CA 95060'
    assert row['image_url'].endswith('/concert.jpg')
    assert row['image_provenance'] == 'publisher_event_candidates_v1'
    assert row['publisher_categories'] == ['Concerts']
    assert row['timezone'] == sc.ZONE


def test_offsite_uses_own_street_and_numberless_streets_held():
    offsite = event(venue={'venue': 'Rio Theatre', 'address': '1205 Soquel Avenue',
                           'city': 'Santa Cruz', 'state': 'California'})
    no_street = event(id=10002, venue={'venue': 'Kuumbwa Jazz Center',
                                       'address': 'Cedar Street', 'city': 'Santa Cruz'})
    no_description = event(id=10003, description='<div>  </div>')
    impossible_city = event(id=10004, venue={'venue': 'Bay Hall', 'address': '100 Market Street',
                                             'city': 'San Jose', 'state': 'CA'})
    rows = sc.collect(source(), mock_fetch([offsite, no_street, no_description, impossible_city]), now=NOW)
    assert len(rows) == 1 and rows[0]['venue_address'] == '1205 Soquel Avenue, Santa Cruz, CA'
    assert rows[0]['venue_name'] == 'Rio Theatre'


def test_campus_building_prefix_extracts_published_street_only():
    address = sc._street({'address': 'Engineering 2 1156 High Street',
                          'city': 'Santa Cruz', 'state': 'CA'})
    assert address == '1156 High Street, Santa Cruz, CA'
    assert sc._street({'address': 'Engineering 2 on High Street', 'city': 'Santa Cruz'}) is None


def test_photo_never_promotes_logo_or_thumbnail():
    good = 'https://events.ucsc.edu/wp-content/uploads/2026/11/concert.jpg'
    assert sc.photo_url(sc.UCSC, good) == good
    for bad in (good + '?resize=100', 'https://bad.com/wp-content/uploads/2026/11/concert.jpg',
                'https://events.ucsc.edu/wp-content/uploads/2026/11/school-logo.jpg',
                'https://events.ucsc.edu/wp-content/uploads/2026/11/concert-150x150.jpg'):
        assert sc.photo_url(sc.UCSC, bad) is None


def test_pagination_fails_closed_and_no_fabricated_description():
    with pytest.raises(ValueError, match='pagination_limit'):
        sc.collect(source(sc.KUUMBWA), mock_fetch([], total=2), now=NOW)
    assert sc._full_description('<p>' + 'word ' * 4000 + '</p>') is None


def test_preview_worker_requires_street_and_full_text(monkeypatch):
    monkeypatch.setattr(preview_worker, 'fetch_publisher',
                        lambda url, accept, **kwargs: mock_fetch([event()])(url, accept))
    result = preview_worker.preview_source(source())
    assert result['p_future_count'] == len(result['p_events']) == 1
    assert result['p_parser_capability'] == 'publisher_event_candidates_v1'

    monkeypatch.setattr(sc, 'collect', lambda *args, **kw: [{'description': '', 'venue_address': 'x'}])
    with pytest.raises(PreviewError, match='santa_cruz_incomplete_event'):
        preview_worker.preview_source(source())
