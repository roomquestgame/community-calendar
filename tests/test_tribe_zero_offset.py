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
