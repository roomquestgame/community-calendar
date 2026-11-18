"""Capitola Village direct TEC REST publisher adapter: event-specific evidence only."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import json
import pytest

from roomquest import santa_cruz_sources as s
from roomquest import preview_worker

NOW = datetime(2026, 11, 18, 21, tzinfo=timezone.utc)
ZONE = ZoneInfo(s.ZONE)


def source(**changes):
    url, kind, adapter = s.SOURCES[s.CAPITOLA_VILLAGE]
    return dict(source_key=s.CAPITOLA_VILLAGE, feed_url=url, kind=kind,
                platform_adapter=adapter, timezone=s.ZONE, **changes)


def occurrence(*, day=0, **changes):
    start = datetime(2026, 11, 19, 19, 0, tzinfo=ZONE) + timedelta(days=day)
    end = start + timedelta(hours=2)
    item = dict(id=10003472, status='publish',
                title='Thursday Night Wine Down With DJ Ryan James',
                start_date=start.strftime('%Y-%m-%d %H:%M:%S'),
                utc_start_date=start.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                end_date=end.strftime('%Y-%m-%d %H:%M:%S'),
                utc_end_date=end.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                timezone=s.ZONE,
                description='<p>Enjoy live music at Cocoa Vino in Capitola. DJ Ryan James spins ' +
                            'classic tracks for the local Thursday wine-down gathering.</p>',
                url='https://capitolavillage.com/event/thursday-night-wine-down-with-dj-ryan-james/2026-11-19/',
                venue=dict(venue='Cocoa Vino', address='312 Capitola Avenue', city='Capitola',
                           state='CA', zip='95010', geo_lat=None, geo_lng=None),
                image=dict(url='https://capitolavillage.com/wp-content/uploads/2026/11/DJ-Ryan.jpg',
                           width=900), categories=[])
    item.update(changes)
    return item


def fetch_rows(events, pages=1):
    def fetch(url, accept):
        assert url.startswith(s.SOURCES[s.CAPITOLA_VILLAGE][0] + '?')
        assert 'start_date=' in url and 'end_date=' in url and 'per_page=100' in url
        assert accept == 'application/json'
        return json.dumps(dict(total_pages=pages, events=events))
    return fetch


def test_source_is_first_party_locked_and_exact_event_id():
    assert s.event_url(s.CAPITOLA_VILLAGE,
                       'https://capitolavillage.com/event/thursday-night-wine-down-with-dj-ryan-james/2026-11-19/')
    assert not s.event_url(s.CAPITOLA_VILLAGE,
                           'https://another.example/event/thursday-night-wine-down-with-dj-ryan-james/2026-11-19/')
    assert not s.event_url(s.CAPITOLA_VILLAGE,
                           'http://capitolavillage.com/event/thursday-night-wine-down-with-dj-ryan-james/2026-11-19/')
    for change in ({'feed_url': 'https://bad.example/events'},
                   {'kind': 'html'}, {'timezone': 'America/Tijuana'}):
        src = source()
        src.update(change)
        with pytest.raises(ValueError, match='unregistered_santa_cruz_source'):
            s.collect(src, fetch_rows([]), now=NOW)


def test_authoritative_native_clocks_complete_text_street_and_image_candidate():
    rows = s.collect(source(), fetch_rows([occurrence()]), now=NOW)
    assert len(rows) == 1
    row = rows[0]
    assert row['starts_at'].startswith('2026-11-20T03:00:00')
    assert row['ends_at'].startswith('2026-11-20T05:00:00')
    assert row['venue_address'] == '312 Capitola Avenue, Capitola, CA 95010'
    assert row['venue_name'] == 'Cocoa Vino'
    assert row['lat'] is None and row['lng'] is None
    assert 'DJ Ryan James spins' in row['description']
    assert row['publisher_categories'] == []
    assert row['image_url'].endswith('/DJ-Ryan.jpg')
    assert row['image_provenance'] == 'publisher_event_candidates_v1'


def test_offsite_or_incomplete_records_are_held_not_invented():
    badstreet = occurrence(id=1, venue=dict(venue='Capitola Beach', city='Capitola'))
    offsite = occurrence(id=2, venue=dict(venue='Other', address='55 Pacific Avenue',
                                           city='Santa Cruz', state='CA'))
    empty = occurrence(id=3, description='<p>   </p>')
    mismatch = occurrence(id=4, utc_start_date='2026-11-20 01:00:00')
    outside = occurrence(id=5, venue=dict(venue='Elsewhere', address='100 Main Street',
                                          city='San Jose', state='CA'))
    accepted = s.collect(source(), fetch_rows([badstreet, offsite, empty, mismatch, outside]), now=NOW)
    assert len(accepted) == 1
    assert accepted[0]['venue_address'] == '55 Pacific Avenue, Santa Cruz, CA'


def test_recurrence_dates_remain_distinct_and_conflicts_abort():
    one = occurrence(id=33)
    two = occurrence(id=33, day=1, url='https://capitolavillage.com/event/thursday-night-wine-down-with-dj-ryan-james/2026-11-20/')
    rows = s.collect(source(), fetch_rows([one, two, one]), now=NOW)
    assert len(rows) == 2 and rows[0]['starts_at'] != rows[1]['starts_at']
    with pytest.raises(ValueError, match='conflicting_event_occurrence'):
        s.collect(source(), fetch_rows([one, occurrence(id=33, title='Different')]), now=NOW)


def test_image_publisher_identity_and_guarded_preview(monkeypatch):
    good = 'https://capitolavillage.com/wp-content/uploads/2026/11/DJ-Ryan.jpg'
    assert s.photo_url(s.CAPITOLA_VILLAGE, good) == good
    for invalid in [good + '?resize=150', good.replace('capitolavillage.com', 'attacker.example'),
                    good.replace('DJ-Ryan.jpg', 'logo.jpg')]:
        assert s.photo_url(s.CAPITOLA_VILLAGE, invalid) is None
    monkeypatch.setattr(preview_worker, 'fetch_publisher',
                        lambda url, accept, **kw: fetch_rows([occurrence()])(url, accept))
    result = preview_worker.preview_source(source())
    assert result['p_future_count'] == 1 and len(result['p_events']) == 1
    assert result['p_error'] is None
