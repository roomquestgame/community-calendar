"""Guard publisher identity, real in-person venue, narratives and NYC fake pin."""
from datetime import datetime, timezone
from copy import deepcopy
import json
from roomquest import santa_cruz_square_venues as sc

NOW=datetime(2026,11,18,20,0,tzinfo=timezone.utc)
def source():
    url,kind,adapter=sc.SOURCES[sc.DIVERSITY]
    return {'source_key':sc.DIVERSITY,'feed_url':url,'kind':kind,
            'platform_adapter':adapter,'timezone':sc.ZONE}
def event():
    return {'id':'test-publisher-event-1','workflowState':1,'title':'Guided Mindfulness',
            'fullUrl':'/upcoming-events/2026/11/23/guided-mindfulness',
            'startDate':1795460400000,'endDate':1795464000000,
            'body':'<p>Guided meditation practice with experienced instructors and a discussion of mindful breathing and stress management for community participants.</p>',
            'location':{'addressTitle':'The Diversity Center',
              'addressLine1':'1117 Soquel Avenue',
              'addressLine2':'Santa Cruz, California, 95062',
              'markerLat':40.7207559,'markerLng':-74.0007613},
            'assetUrl':'https://images.squarespace-cdn.com/content/v1/52449106e4b098f57c7a9472/test/photo.jpg?format=750w',
            'categories':['Wellness']}
def collect(item):
    payload={'website':{'timeZone':sc.ZONE},'upcoming':[item],'pagination':{}}
    return sc.collect(source(),lambda *_:json.dumps(payload),now=NOW)
def test_exact_publisher_venue_and_no_inherited_nyc_coordinates():
    rows=collect(event())
    assert len(rows)==1
    row=rows[0]
    assert row['venue_address']=='1117 Soquel Avenue, Santa Cruz, CA 95062'
    assert row.get('lat') is None and row.get('lng') is None
    assert 'mindful breathing' in row['description']
    assert row['publisher_categories']==['Wellness']
def test_virtual_offsite_and_wrong_streets_are_held():
    for name,street,local in (
        ('Zoom','',''),('London Nelson Community Center','301 Center Street','Santa Cruz, California, 95060'),
        ('The Diversity Center','1217 Soquel Avenue','Santa Cruz, California, 95062')):
        x=deepcopy(event())
        x['location'].update(addressTitle=name,addressLine1=street,addressLine2=local)
        assert not collect(x)
def test_wrong_event_identity_missing_body_or_cancellation_held():
    for change in (
        {'fullUrl':'https://attacker.test/upcoming-events/2026/11/23/guided-mindfulness'},
        {'fullUrl':'/upcoming-events/2026/11/23/../../fake'},
        {'body':'<p></p>'},
        {'title':'Canceled Guided Mindfulness'}):
        x=event()
        x.update(change)
        assert not collect(x)
def test_feed_url_and_adapter_are_locked():
    x=source()
    x['feed_url']='https://www.diversitycenter.org/other?format=json'
    try:sc.collect(x,lambda *_:'{}',now=NOW)
    except ValueError as exc:assert str(exc)=='unregistered_santa_cruz_square_source'
    else:raise AssertionError('source substitution was accepted')
