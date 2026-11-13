"""WordPress "UTC+0" event zones repeat local wall time in utc_* fields."""
from datetime import datetime, timedelta, timezone

import pytest

from roomquest.mapsee_adapter import parse_tribe

DAY = (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat()


def _event(**patch):
    # Captured shape: macdillfss.com "Baby Time at the Library", November 2026.
    item = {
        'id': 1, 'status': 'publish', 'title': 'Baby Time at the Library',
        'url': 'https://macdillfss.com/event/baby-time-at-the-library/',
        'start_date': DAY + ' 09:30:00', 'end_date': DAY + ' 10:00:00',
        'utc_start_date': DAY + ' 09:30:00', 'utc_end_date': DAY + ' 10:00:00',
        'timezone': 'UTC+0', 'timezone_abbr': 'UTC+0', 'all_day': False,
        'venue': {'venue': 'Library', 'address': '8102 Condor St', 'city': 'MacDill AFB',
                  'state': 'FL', 'zip': '33621'},
    }
    item.update(patch)
    return item


@pytest.mark.parametrize('zone', ['UTC+0', 'UTC', 'utc-0', 'UTC+00:00', 'Etc/UTC', 'GMT'])
def test_zero_offset_publisher_zone_is_held(zone):
    assert parse_tribe({'events': [_event(timezone=zone, timezone_abbr=zone)]}) == []


def test_real_publisher_zones_keep_utc_dates():
    eastern = _event(timezone='America/New_York', timezone_abbr='EST',
                     utc_start_date=DAY + ' 14:30:00', utc_end_date=DAY + ' 15:00:00')
    fixed = _event(id=2, timezone='UTC-5', timezone_abbr='UTC-5',
                   utc_start_date=DAY + ' 14:30:00', utc_end_date=DAY + ' 15:00:00')
    rows = parse_tribe({'events': [eastern, fixed]})
    assert [row['starts_at'] for row in rows] == [DAY + 'T14:30:00+00:00'] * 2


def _dated(day, start, end, **patch):
    return _event(start_date=f'{day} {start}', end_date=f'{day} {end}',
                  utc_start_date=f'{day} {start}', utc_end_date=f'{day} {end}', **patch)


def test_reviewed_source_zone_reinterprets_utc_default_wall_clock():
    # Captured Baby Time shape: 9:30 AM Eastern (EST in winter) is 14:30Z, not 09:30Z.
    rows = parse_tribe({'events': [_dated('2027-01-06', '09:30:00', '10:00:00')]},
                       utc_default_zone='America/New_York')
    assert [(r['starts_at'], r['ends_at']) for r in rows] == [
        ('2027-01-06T14:30:00+00:00', '2027-01-06T15:00:00+00:00')]
    # Central-time reviewed source (BUILD, Chicago): 4:00 PM CST is 22:00Z.
    rows = parse_tribe({'events': [_dated('2027-01-06', '16:00:00', '17:00:00')]},
                       utc_default_zone='America/Chicago')
    assert rows[0]['starts_at'] == '2027-01-06T22:00:00+00:00'


def test_reviewed_zone_never_touches_real_publisher_zones():
    eastern = _event(timezone='America/New_York', utc_start_date=DAY + ' 14:30:00',
                     utc_end_date=DAY + ' 15:00:00')
    rows = parse_tribe({'events': [eastern]}, utc_default_zone='America/Chicago')
    assert rows[0]['starts_at'] == DAY + 'T14:30:00+00:00'


def test_reviewed_zone_rejects_nonexistent_dst_wall_clock():
    gap = _dated('2027-03-14', '02:30:00', '03:30:00')
    with pytest.raises(ValueError, match='timezone_nonexistent'):
        parse_tribe({'events': [gap]}, utc_default_zone='America/New_York')


def test_reviewed_zone_table_covers_only_audited_sources():
    from roomquest.mapsee_adapter import TRIBE_UTC_DEFAULT_ZONES, profiles
    known = profiles()
    assert len(TRIBE_UTC_DEFAULT_ZONES) == 7
    for key, zone in TRIBE_UTC_DEFAULT_ZONES.items():
        assert known[key]['type'] == 'tribe' and known[key]['platform_adapter'] == 'wordpress'
        assert zone in ('America/New_York', 'America/Chicago')
    assert TRIBE_UTC_DEFAULT_ZONES['municipal_mapsee_6b6a983c5d1ea8a1fe3fede2'] == 'America/Chicago'


def test_wordpress_collect_passes_reviewed_zone(monkeypatch):
    import roomquest.mapsee_adapter as adapter
    import roomquest.wordpress_adapter as wp
    seen = {}
    real = adapter.parse_tribe
    def spy(payload, **kw):
        seen['zone'] = kw.get('utc_default_zone')
        return real(payload, **kw)
    monkeypatch.setattr(adapter, 'parse_tribe', spy)
    import json
    key, zone = next(iter(adapter.TRIBE_UTC_DEFAULT_ZONES.items()))
    wp.collect({'source_key': key, 'feed_url': 'https://example.org'},
               lambda *_: json.dumps({'events': [], 'total_pages': 1}))
    assert seen['zone'] == zone
