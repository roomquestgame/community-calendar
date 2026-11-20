from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from roomquest.ical_venue_address import extract_venue_addresses
from roomquest.preview_worker import preview_source


def extract(*locations):
    rows = [dict(venue_name=raw, venue_address='') for raw in locations]
    extract_venue_addresses(rows)
    assert [row['venue_name'] for row in rows] == list(locations)
    return [row['venue_address'] for row in rows]


def test_same_building_variants_are_order_independent_and_offsite_is_separate():
    valid = 'Science Center,805 W Sioux Ave Pierre, SD 57501'
    missing = valid.replace('SD ', '')
    malformed = valid.replace('SD ', 'So ')
    park = 'Park,1301 Farm Island Rd Pierre, SD 57501'
    assert extract(missing, malformed, park, valid) == [
        '805 W Sioux Ave, Pierre, SD 57501', '805 W Sioux Ave, Pierre, SD 57501',
        '1301 Farm Island Rd, Pierre, SD 57501', '805 W Sioux Ave, Pierre, SD 57501']
    assert extract(missing)[0] == ''
    assert extract(missing, valid, valid.replace('SD ', 'ND '))[0] == ''
    assert extract(missing, valid.replace('Science Center', 'Other venue'))[0] == ''
    assert extract(missing, valid.replace('57501', '57502'))[0] == ''


@pytest.mark.parametrize(('location', 'expected'), [
    ('Library 1000 E. Church St., Pierre SD  57501 Pierre SD 57501', '1000 E. Church St., Pierre, SD 57501'),
    ('Hall, 11 Main St, Charleston, West Virginia 25301', '11 Main St, Charleston, WV 25301'),
    ('55 Broadway, New York, NY', '55 Broadway, New York, NY'),
    ('Main Hall, 44 Park Ave, Suite 21, Auburn, WA 98001', '44 Park Ave, Suite 21, Auburn, WA 98001'),
    ('Main Hall\n44 Park Ave\nAuburn, WA 98001', '44 Park Ave, Auburn, WA 98001'),
    ('Main Hall, 44 Park Ave, Auburn, WA 98001, USA', '44 Park Ave, Auburn, WA 98001'),
    ('Online at 44 Park Ave, Auburn, WA 98001', ''), ('Pierre SD 57501', ''),
    ('102 Main St / 42 New St, Raleigh, NC', ''), ('Main Hall', ''),
    ('', ''), ('<style>12 Main St, Raleigh, NC', ''),
    ('Hall, 12 Main St, Ottawa, ON', ''), ('P.O. Box 27, Raleigh, NC', ''),
])
def test_location_shapes(location, expected):
    assert extract(location) == [expected]


def test_preserves_specific_adapter_address_and_coordinates():
    row = dict(venue_name='Museum 22 Main St, Raleigh, NC', venue_address='10 Side St, Raleigh, NC',
               venue_city='Raleigh', lat=35.7, lng=-78.6)
    expected = dict(row)
    extract_venue_addresses([row])
    assert row == expected


def test_registered_ical_worker_emits_usable_address_without_changing_identity():
    future = (datetime.now(timezone.utc) + timedelta(days=2)).strftime('%Y%m%dT%H%M%SZ')
    raw = '\r\n'.join(['BEGIN:VCALENDAR','VERSION:2.0','BEGIN:VEVENT','UID:original',
                       'SUMMARY:Class','DTSTART:' + future,
                       'LOCATION:Science Center\\,805 W Sioux Ave Pierre\\, SD 57501',
                       'END:VEVENT','END:VCALENDAR'])
    source = dict(source_key='municipal_6bdd691c0b40e4a6200412d9', kind='ical', platform_adapter='ical',
                  feed_url='https://mms.sd-discovery.org/members/calendar/events_ical.php?org_id=SDDC')
    with patch('roomquest.preview_worker.fetch_publisher', return_value=raw) as fetch:
        first = preview_source(source)
        assert first == preview_source(source)
        assert all(call.kwargs['respect_robots'] for call in fetch.call_args_list)
    assert len(first['p_events']) == 1
    record = first['p_events'][0]
    assert record['id'] == 'original'
    assert record['venue_address'] == '805 W Sioux Ave, Pierre, SD 57501'
    assert record['venue_city'] == 'Pierre'
    assert record['lat'] is None
    assert first['p_samples'] == [record]
