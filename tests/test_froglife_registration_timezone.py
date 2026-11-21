import json

from roomquest.mapsee_adapter import TRIBE_UTC_DEFAULT_ZONES, parse_tribe
from roomquest.registration_formats import probe, source_key

URL = 'https://www.froglife.org/wp-json/tribe/events/v1/events/?venue=26896'


def payload(date):
    return {'events': [{'id': 36273, 'title': 'Volunteer day', 'status': 'publish',
        'url': 'https://www.froglife.org/event/volunteer-day/', 'timezone': 'UTC+0',
        'start_date': date + ' 10:00:00', 'end_date': date + ' 12:00:00',
        'utc_start_date': date + ' 10:00:00', 'utc_end_date': date + ' 12:00:00',
        'venue': {'id':26896, 'venue':'Hampton Nature Reserve',
                  'address':"Nature's Way, Hampton", 'city':'Peterborough',
                  'zip':'PE7 8JG', 'country':'United Kingdom'}}]}


def test_registered_venue_scope_is_required_by_probe():
    body = json.dumps(payload('2027-01-16'))
    assert probe(URL, body, 'wordpress')
    assert not probe(URL.split('?')[0], body, 'wordpress')
    assert not probe(URL.replace('26896', '999'), body, 'wordpress')


def test_reviewed_zone_handles_winter_and_summer_wall_clock(monkeypatch):
    # Exercise both DST seasons independently of the production collection window.
    monkeypatch.setattr('roomquest.preview_worker.LOOKAHEAD_DAYS', 500)
    zone = TRIBE_UTC_DEFAULT_ZONES[source_key(URL)]
    winter = parse_tribe(payload('2027-01-16'), strict_public=True, utc_default_zone=zone)
    summer = parse_tribe(payload('2027-07-16'), strict_public=True, utc_default_zone=zone)
    assert winter[0]['starts_at'] == '2027-01-16T10:00:00+00:00'
    assert summer[0]['starts_at'] == '2027-07-16T09:00:00+00:00'
