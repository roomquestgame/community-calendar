import copy
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
import pytest
from roomquest.squarespace import collect, parse_registered
from roomquest.preview_worker import preview_source, PreviewError

BASE = 'https://venue.example.org/events'

def payload():
    start = datetime.now(timezone.utc) + timedelta(days=2)
    return {'upcoming': [{'id': 'stable-id', 'title': 'Actual concert', 'workflowState': 1,
        'startDate': start.timestamp()*1000, 'endDate': (start+timedelta(hours=2)).timestamp()*1000,
        'fullUrl': '/events/concert', 'categories': ['Music'],
        'location': {'addressTitle': 'Actual Hall', 'addressLine1': '12 Main St',
                     'addressLine2': 'Raleigh, NC', 'markerLat': 35.8, 'markerLng': -78.6}}], 'past': []}

def test_ashland_museum_uses_the_reviewed_offsite_address():
    from roomquest.squarespace import ASHLAND_MUSEUM

    data = payload()
    data['upcoming'][0]['location'] = {
        'addressTitle': 'Truist Theater in Brock Commons',
        'addressLine1': 'Randolph-Macon College, Henry Street',
        'addressLine2': 'Ashland, VA 23005',
        'mapLat': 40.720882, 'mapLng': -74.000988,
    }
    rows = parse_registered(data, ASHLAND_MUSEUM)
    assert rows[0]['venue_address'] == '304 Henry Street, Ashland, VA 23005'
    assert rows[0]['lat'] == pytest.approx(37.76146)

def test_confirmed_archive_cursor_is_not_fetched_or_treated_as_truncation():
    data = payload(); data['past'] = [{'publishOn': 1000, 'endDate': 2000}]
    data['pagination'] = {'nextPage': 'https://evil.example.org/', 'nextPageOffset': 1000}
    calls = []
    rows = collect({'feed_url': BASE+'?category=Music&format=json'}, lambda url, _: calls.append(url) or json.dumps(data))
    assert len(calls) == 1 and urlsplit(calls[0]).hostname == 'venue.example.org'
    assert parse_qs(urlsplit(calls[0]).query) == {'category': ['Music'], 'format': ['json']}
    assert rows[0]['id'] == 'stable-id' and rows[0]['lat'] == 35.8

@pytest.mark.parametrize('cursor', [True, 3000, '1000', float('inf')])
def test_unproven_cursor_fails_instead_of_partial_success(cursor):
    data=payload();data['pagination']={'nextPage':True,'nextPageOffset':cursor}
    data['past']=[{'publishOn':1000,'endDate':2000}]
    with pytest.raises(ValueError, match='pagination_requires_review'):parse_registered(data,BASE)

def test_items_pagination_is_not_mistaken_for_separate_past_archive():
    data=payload();data['items']=data.pop('upcoming');data['pagination']={'nextPage':True,'nextPageOffset':1000}
    data['past']=[{'publishOn':1000,'endDate':2000}]
    with pytest.raises(ValueError,match='pagination_requires_review'):parse_registered(data,BASE)

def test_mapsee_legacy_fields_keep_identical_factual_identity():
    data=payload();v=data['upcoming'][0]['location'];v['mapLat']=v.pop('markerLat');v['mapLng']=v.pop('markerLng')
    from roomquest.mapsee_adapter import record
    e=data['upcoming'][0]
    before=record(e['title'],e['startDate'],e['endDate'],v['addressTitle'],'12 Main St, Raleigh, NC','',BASE+'/concert',e['id'],'Music',35.8,-78.6)
    assert parse_registered(data,BASE)==[{**before, 'description': ''}]

def test_conflicting_geo_is_held_without_discarding_address():
    data=payload();data['upcoming'][0]['location'].update(mapLat=40.0,mapLng=-74.0)
    [row]=parse_registered(data,BASE)
    assert row['lat'] is row['lng'] is None and row['venue_address']=='12 Main St, Raleigh, NC'
    data=payload();data['upcoming'][0]['location'].update(mapLat='35.800',mapLng='-78.600')
    assert parse_registered(data,BASE)[0]['lat']==35.8

def test_empty_unpublished_cancelled_all_day_and_missing_end():
    assert parse_registered({'upcoming':[]},BASE)==[]
    with pytest.raises(ValueError,match='unsupported_squarespace_payload'):
        parse_registered({'upcoming':None,'items':[]},BASE)
    data=payload();e=data['upcoming'][0]
    for change in [{'cancelled':True},{'workflowState':0},{'allDay':True}]:
        assert parse_registered({'upcoming':[{**e,**change}]},BASE)==[]
    e.pop('endDate');[row]=parse_registered(data,BASE)
    assert row['ends_at'] is None

def test_source_limits_bad_dates_and_conflicting_occurrences():
    data=payload();data['upcoming']*=501
    with pytest.raises(ValueError,match='source_record_limit'):parse_registered(data,BASE)
    data=payload();data['upcoming'][0]['endDate']=1000
    with pytest.raises(ValueError,match='invalid_event_end'):parse_registered(data,BASE)
    data=payload();data['upcoming'].append({**data['upcoming'][0],'title':'Different title'})
    with pytest.raises(ValueError,match='conflicting_event_occurrence'):parse_registered(data,BASE)

def test_missing_geometry_keeps_exact_venue_signature_for_cache():
    data=payload();data['upcoming'][0]['location'].pop('markerLat');data['upcoming'][0]['location'].pop('markerLng')
    [row]=parse_registered(data,BASE)
    assert row['venue_name']=='Actual Hall' and row['venue_address']=='12 Main St, Raleigh, NC' and row['lat'] is None

def test_registered_family_dispatch_and_protected_transport():
    source={'source_key':'municipal_mapsee_fixture','platform_adapter':'squarespace','kind':'json','feed_url':BASE}
    with patch('roomquest.mapsee_adapter.profiles',return_value={source['source_key']:{'url':BASE,'type':'squarespace'}}),patch('roomquest.preview_worker.fetch_publisher',return_value=json.dumps(payload())) as fetch:
        result=preview_source(source)
        assert result['p_source_key']==source['source_key'] and len(result['p_events'])==1
        assert fetch.call_args.kwargs['respect_robots'] is True
    with patch('roomquest.mapsee_adapter.profiles',return_value={}),patch('roomquest.preview_worker.fetch_publisher') as fetch:
        with pytest.raises(PreviewError,match='unregistered_mapsee_source'):preview_source(source)
        fetch.assert_not_called()


def test_reviewed_aquarian_venue_does_not_replace_explicit_location():
    from roomquest.squarespace import AQUARIAN

    data = payload()
    entry = data['upcoming'][0]
    entry['id'] = '6ae20b8f4691e86544fdc6ef'
    assert parse_registered(data, AQUARIAN)[0]['venue_name'] == 'Actual Hall'
    entry['location'] = {'mapLat': 40.72, 'mapLng': -74.0}
    [row] = parse_registered(data, AQUARIAN)
    assert row['venue_address'] == '12 S Thompson St, Richmond, VA 23221'
    assert row['lat'] == pytest.approx(37.55704)
    entry['id'] = 'unreviewed'
    assert parse_registered(data, AQUARIAN) == []
