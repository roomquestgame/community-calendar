import json
from unittest.mock import patch
import pytest
from roomquest.mapsee_adapter import address, parse_tribe
from roomquest.jsonld_adapter import parse

def event(address_value, start='2026-12-12T10:30:00-07:00'):
    return {'@type':'Event','name':'Public event','startDate':start,
            'url':'https://www.veteranscenter.org/event/public/',
            'location':{'@type':'Place','name':'Actual venue','address':address_value}}

def read(e,base):
    with patch('roomquest.preview_worker.LOOKAHEAD_DAYS',500):
        return parse(json.dumps([e]),base)[0]

def test_nissis_address_is_normalized_without_inventing_location():
    e=event('1455 Coal Creek Dr. Lafayette, Co. 80026')
    row=read(e,'https://nissis.com/shows/')
    assert row['venue_address']=='1455 Coal Creek Dr., Lafayette, CO 80026'
    assert row['venue_city']=='Lafayette'
    assert row['lat'] is None and row['lng'] is None
    assert read(e,'https://other.example/')['venue_address']==e['location']['address']

@pytest.mark.parametrize('city',['Colorado Springs','Pueblo'])
def test_mt_carmel_preserves_venue_timezone_and_utc_instant(city):
    a={'streetAddress':'12 Main St','addressLocality':city,'addressRegion':'CO'}
    row=read(event(a),'https://www.veteranscenter.org/mtcarmel-events/')
    assert row['timezone']=='America/Denver'
    assert row['starts_at']=='2026-12-12T17:30:00+00:00'
    a['addressRegion']='VA'
    assert read(event(a),'https://www.veteranscenter.org/mtcarmel-events/').get('timezone') is None

def test_mt_carmel_conflicting_offset_is_not_silently_corrected():
    a={'streetAddress':'12 Main St','addressLocality':'Pueblo','addressRegion':'CO'}
    with pytest.raises(ValueError,match='publisher_schedule_conflict'):
        read(event(a,'2026-12-12T10:30:00-05:00'),'https://www.veteranscenter.org/mtcarmel-events/')

def test_country_is_preserved_and_existing_us_cache_addresses_unchanged():
    a={'streetAddress':'12 Main St','addressLocality':'Cambridge','postalCode':'CB1 1AA','addressCountry':{'name':'United Kingdom'}}
    assert address(a)=='12 Main St, Cambridge, CB1 1AA, United Kingdom'
    a={'streetAddress':'12 Main St','addressLocality':'Pueblo','addressRegion':'CO','postalCode':'81003'}
    for country in ['US','USA','United States','United States of America']:
        assert address({**a,'addressCountry':country})==address(a)

def test_tec_country_reaches_normalized_feed():
    data={'events':[{'id':1,'title':'Nature walk','url':'https://venue.example/event/walk',
        'start_date':'2026-12-12 10:00:00','end_date':'2026-12-12 12:00:00','timezone':'Europe/London',
        'venue':{'venue':'Nature Reserve','address':"Nature’s Way",'city':'Peterborough',
                 'province':'Cambridgeshire','zip':'PE7 8JG','country':'United Kingdom'}}]}
    with patch('roomquest.preview_worker.LOOKAHEAD_DAYS',500):
        rows=parse_tribe(data)
    assert rows[0]['venue_address'].endswith('PE7 8JG, United Kingdom')
