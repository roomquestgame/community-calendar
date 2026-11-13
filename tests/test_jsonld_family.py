from datetime import datetime,timedelta,timezone
import json
from unittest.mock import patch
import pytest
from roomquest.jsonld_adapter import parse
from roomquest.preview_worker import preview_source,PreviewError

BASE='https://venue.example.org/events'
def event():
    at=datetime.now(timezone.utc)+timedelta(days=2)
    return {'@type':'MusicEvent','@id':'stable-event','url':'/event/one','name':'Actual concert',
      'startDate':at.isoformat(),'endDate':(at+timedelta(hours=2)).isoformat(),'keywords':'Music',
      'location':{'@type':'Place','name':'Actual Hall','address':{'streetAddress':'12 Main St','addressLocality':'Raleigh','addressRegion':'NC'},'geo':{'latitude':35.8,'longitude':-78.6}}}
def html(data):return "<SCRIPT TYPE='application/ld+json; charset=utf-8'>"+json.dumps(data)+'</SCRIPT>'


def test_coalition_uses_publisher_occurrence_and_exact_venue():
    from roomquest.jsonld_adapter import COALITION_KEY, COALITION_URL, collect

    item = event()
    item['url'] = 'https://calendar.richmondcultureworks.org/events/matinee/'
    item['location'] = {'@type': 'Place', 'name': 'Coalition Theater', 'address': {
        'streetAddress': '8 W Broad St', 'addressLocality': 'Richmond',
        'addressRegion': 'VA', 'postalCode': '23220'}}
    day = item['startDate'][:10]
    index = ('<section class="ao-assoc-events">'
             f'<a class="ao-event-card" href="{item["url"]}"><time datetime="{day}"></time></a>'
             '</section>')
    source = {'source_key': COALITION_KEY, 'feed_url': COALITION_URL, 'timezone': 'America/New_York'}
    [row] = collect(source, lambda url, _: {COALITION_URL: index, item['url']: html(item)}[url])
    assert row['event_url'] == item['url']
    assert row['venue_address'] == '8 W Broad St, Richmond, VA, 23220'
    assert row['lat'] == pytest.approx(37.54579)

def test_legacy_fields_and_identity_are_unchanged():
    from roomquest.mapsee_adapter import record
    e=event();expected=record(e['name'],e['startDate'],e['endDate'],'Actual Hall','12 Main St, Raleigh, NC','Raleigh', 'https://venue.example.org/event/one','stable-event','Music',35.8,-78.6)
    assert parse(html(e),BASE)==[expected]

@pytest.mark.parametrize('wrapper',[lambda e:e,lambda e:[e],lambda e:{'@graph':[e]},lambda e:{'@type':'ItemList','itemListElement':[{'item':e}]},lambda e:{'event':e}])
def test_common_wrappers_and_raw_json(wrapper):
    assert parse(json.dumps(wrapper(event())),BASE)[0]['id']=='stable-event'

def test_type_arrays_schema_uris_and_local_references():
    e=event();e['@type']=['Thing','https://schema.org/MusicEvent'];v=e['location'];v['@id']='#hall';e['location']={'@id':'#hall'}
    [row]=parse(html({'@graph':[e,v]}),BASE)
    assert row['lat']==35.8 and row['venue_name']=='Actual Hall'

def test_conflicting_reference_and_multiple_physical_venues_fail():
    e=event();v=e['location'];v['@id']='#hall'
    with pytest.raises(ValueError,match='conflicting_jsonld_reference'):parse(html({'@graph':[e,{**v,'name':'Different Hall'}]}),BASE)
    e=event();e['location']=[e['location'],{'@type':'Place','name':'Other Hall'}]
    with pytest.raises(ValueError,match='ambiguous_event_location'):parse(html(e),BASE)

def test_cancelled_and_virtual_skip_but_missing_timezone_fails():
    e=event();e['eventStatus']='https://schema.org/EventCancelled';assert parse(html(e),BASE)==[]
    e=event();e['location']={'@type':'VirtualLocation'};assert parse(html(e),BASE)==[]
    e=event();e['startDate']='2026-11-15T19:00:00'
    with pytest.raises(ValueError,match='timezone_unresolved'):parse(html(e),BASE)

def test_only_explicit_structured_empty_is_healthy():
    assert parse(html({'@type':'ItemList','numberOfItems':0,'itemListElement':[]}),BASE)==[]
    with pytest.raises(ValueError,match='unsupported_jsonld_event_shape'):parse(html({'@type':'Organization','description':'No events found'}),BASE)
    with pytest.raises(ValueError):parse(html(event())+"<script type='application/ld+json'>{bad}</script>",BASE)

def test_missing_geo_retains_source_scoped_venue_facts():
    e=event();e['location'].pop('geo');[row]=parse(html(e),BASE)
    assert row['lat'] is None and row['venue_address']=='12 Main St, Raleigh, NC'

def test_duplicate_conflict_limits_and_date_validation():
    e=event()
    later={**e,'startDate':(datetime.now(timezone.utc)+timedelta(days=4)).isoformat(),'endDate':(datetime.now(timezone.utc)+timedelta(days=4,hours=2)).isoformat()}
    assert len(parse(html([e,later]),BASE))==2
    with pytest.raises(ValueError,match='conflicting_event_occurrence'):parse(html([e,{**e,'name':'Different'}]),BASE)
    with pytest.raises(ValueError,match='source_record_limit'):parse(html([e]*501),BASE)
    e=event();e['endDate']='2001-01-01T00:00:00Z'
    with pytest.raises(ValueError,match='invalid_event_end'):parse(html(e),BASE)

def test_family_dispatch_retains_registry_and_robots_guards():
    source={'source_key':'municipal_mapsee_fixture','platform_adapter':'jsonld','kind':'json','feed_url':BASE}
    with patch('roomquest.mapsee_adapter.profiles',return_value={source['source_key']:{'type':'jsonld','url':BASE}}),patch('roomquest.preview_worker.fetch_publisher',return_value=html(event())) as fetch:
        assert preview_source(source)['p_events'][0]['id']=='stable-event'
        assert fetch.call_args.kwargs['respect_robots'] is True
    with patch('roomquest.mapsee_adapter.profiles',return_value={}),patch('roomquest.preview_worker.fetch_publisher') as fetch:
        with pytest.raises(PreviewError,match='unregistered_mapsee_source'):preview_source(source)
        fetch.assert_not_called()
