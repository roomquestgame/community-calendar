import json
from unittest.mock import patch
import pytest
from roomquest.jsonld_adapter import parse
from roomquest.feed_registration import classify

BASE = 'https://www.punchlinecomedyclub.com/'

def event(**changes):
    return {'@type': 'Event', 'name': 'Public performance',
            'startDate': '2026-12-12T19:00:00',
            'url': 'https://tickets.example/event/one',
            'location': {'@type': 'Place', 'name': 'Punch Line', 'address': {
                'streetAddress': '444 Battery Street', 'addressLocality': 'San Francisco',
                'addressRegion': 'CA', 'postalCode': '94111'}}, **changes}


def read(items, base=BASE):
    with patch('roomquest.preview_worker.LOOKAHEAD_DAYS', 500):
        return parse(json.dumps(items), base)


def test_timed_records_survive_date_only_placeholders_and_unknown_end():
    items = [event(startDate='2026-12-12T19:00:00-08:00',endDate='2026-12-12'),
             event(name='Untimed',startDate='2026-12-13',url='https://tickets.example/event/two')]
    rows = read(items)
    assert len(rows) == 1
    assert rows[0]['starts_at'] == '2026-12-13T03:00:00+00:00'
    assert rows[0]['ends_at'] is None
    assert rows[0]['timezone'] == 'America/Los_Angeles'


def test_reviewed_venue_zone_honors_dst_and_calendar_scope():
    for wall, utc in [('2026-12-12T19:00:00','2026-12-13T03:00:00+00:00'),
                      ('2027-06-12T19:00:00','2027-06-13T02:00:00+00:00')]:
        assert read([event(startDate=wall)])[0]['starts_at'] == utc
    with pytest.raises(ValueError,match='timezone_unresolved'):
        read([event()], 'https://other.example/')
    offsite = event();offsite['location']['address']['addressLocality'] = 'Los Angeles'
    with pytest.raises(ValueError,match='timezone_unresolved'):
        read([offsite])


def test_invalid_and_conflicting_times_still_fail_closed():
    for changes, reason in [({'endDate':'2026-12-11'},'invalid_event_end'),
                            ({'endDate':'2026-12-12T18:00:00'},'invalid_event_end'),
                            ({'startDate':'2026-12-12T19:00:00-05:00'},'publisher_schedule_conflict')]:
        with pytest.raises(ValueError,match=reason):read([event(**changes)])


def test_registration_recognizes_reusable_calendar_with_date_only_end():
    events=[event(startDate='2026-12-12T19:00:00-08:00',endDate='2026-12-12'),
            event(startDate='2026-12-13T19:00:00-08:00',endDate='2026-12-13',url='https://tickets.example/event/two')]
    body='<script type="application/ld+json">'+json.dumps(events)+'</script>'
    assert classify(BASE,body)['p_outcome']=='verified'
