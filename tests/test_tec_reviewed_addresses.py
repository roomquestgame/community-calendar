from copy import deepcopy
from hashlib import md5
from roomquest.reviewed_venue_addresses import complete_tec_venues, TEC_VENUES


def source(url):
    return {'feed_url': url, 'source_key': 'municipal_' + md5(('feed_registration:' + url).encode()).hexdigest()[:24]}


def test_reviewed_calendar_address_without_coordinates_and_preserved_input():
    for url, venue in TEC_VENUES.items():
        description = 'Where? The Super Rad Arcade Bar 58 9th St., Lynchburg, Virginia 24504'
        event = {'venue': [], 'url': url.split('/wp-json')[0] + '/event/concert/', 'description': description}
        payload = {'events': [event]}
        before = deepcopy(payload)
        result = complete_tec_venues(payload, source(url))
        assert payload == before
        assert result['events'][0]['venue']['venue'] == venue[0]
        assert result['events'][0]['venue']['zip'] == venue[-1]
        assert 'geo_lat' not in result['events'][0]['venue']


def test_preserve_explicit_venues_and_reject_offsite_scope():
    for url in TEC_VENUES:
        base = {'venue': [], 'url': url.split('/wp-json')[0] + '/event/test/',
                'description': 'Where? The Super Rad Arcade Bar 58 9th St., Lynchburg, Virginia 24504'}
        for event in [dict(base, venue={'venue': 'Other Hall'}), dict(base, description='Off-campus event'),
                      dict(base, url='https://other.example/event/test/')]:
            payload = {'events': [event]}
            assert complete_tec_venues(payload, source(url)) == payload
        payload = {'events': [base]}
        assert complete_tec_venues(payload, {**source(url), 'source_key': 'other'}) == payload
        assert complete_tec_venues(payload, source(url + '?venue=7')) == payload


def test_super_rad_requires_event_address_evidence():
    url = next(iter(TEC_VENUES))
    payload = {'events': [{'venue': [], 'url': url.split('/wp-json')[0] + '/event/test/', 'description': 'A concert'}]}
    assert complete_tec_venues(payload, source(url)) == payload


def test_recurring_collector_and_registration_share_completion():
    import json
    from datetime import datetime, timedelta, timezone
    from unittest.mock import patch
    from roomquest.wordpress_adapter import collect
    from roomquest.registration_formats import probe
    url = 'https://www.lucasoilstadium.com/wp-json/tribe/events/v1/events'
    start = datetime.now(timezone.utc) + timedelta(days=2)
    event = {'id': 1, 'title': 'Football', 'status': 'publish', 'venue': [],
             'url': 'https://www.lucasoilstadium.com/event/football/',
             'utc_start_date': start.isoformat(), 'utc_end_date': (start + timedelta(hours=3)).isoformat(),
             'timezone': 'America/Indiana/Indianapolis', 'description': 'Stadium football game.'}
    body = json.dumps({'events': [event], 'total_pages': 1})
    rows = collect(source(url), lambda *_: body)
    assert len(rows) == 1
    assert rows[0]['venue_address'] == '500 S. Capitol Avenue, Indianapolis, IN, 46225'
    assert rows[0]['lat'] is None
    with patch('roomquest.mapsee_adapter.parse_tribe', return_value=rows) as parser:
        assert probe(url, body, 'wordpress')
        assert parser.call_args.args[0]['events'][0]['venue']['city'] == 'Indianapolis'
