"""Batch-two Santa Cruz publisher identities and collector quality regression tests."""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
import json
import pytest

from roomquest import santa_cruz_sources as tec
from roomquest import santa_cruz_rio as rio
from roomquest import santa_cruz_game_night as game
from roomquest import preview_worker
from roomquest.preview_worker import PreviewError

NOW=datetime(2026,11,18,15,0,tzinfo=timezone.utc)

@pytest.fixture(autouse=True)
def fixed_preview(monkeypatch):
    monkeypatch.setattr(preview_worker,'_future_datetime',
                        lambda value:value.astimezone(timezone.utc))

def source(k,profiles,zone):
    url,kind,adapter=profiles[k]
    return {'source_key':k,'feed_url':url,'kind':kind,'platform_adapter':adapter,'timezone':zone}

def valid_tec_item(k):
    local=datetime(2026,11,21,10,0,tzinfo=ZoneInfo(tec.ZONE))
    host='santacruzmuseum.org' if k==tec.NATURAL_HISTORY else 'www.santacruz.org'
    link=('https://santacruzmuseum.org/event/saturdays-in-the-soil-5/'
          if k==tec.NATURAL_HISTORY else
          'https://www.santacruz.org/upcoming-event/guided-redwoods-walk/2026-11-21/')
    return {'id':111,'status':'publish','title':'Redwoods Guided Walk',
            'start_date':local.strftime('%Y-%m-%d %H:%M:%S'),
            'utc_start_date':local.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            'end_date':(local+timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S'),
            'utc_end_date':(local+timedelta(hours=2)).astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            'timezone':tec.ZONE,'all_day':False,
            'description':'<p>A guided public walk through the forest to learn about the redwoods.</p>',
            'url':link,'venue':{'venue':'Santa Cruz Museum of Natural History',
                'address':'1305 East Cliff Drive','city':'Santa Cruz','state':'CA',
                'zip':'95062'},'categories':[{'name':'Nature Walk'}],
            'image':{'url':'https://'+host+'/wp-content/uploads/2026/11/walk.jpg','width':900}}

def test_new_tec_hosts_event_routes_and_categorization_evidence():
    for key in (tec.NATURAL_HISTORY,tec.VISIT_SANTA_CRUZ):
        profile=source(key,tec.SOURCES,tec.ZONE)
        item=valid_tec_item(key)
        rows=tec.collect(profile,lambda url,accept:json.dumps(
            {'events':[item],'total_pages':1}),now=NOW)
        assert len(rows)==1
        assert rows[0]['venue_address']=='1305 East Cliff Drive, Santa Cruz, CA 95062'
        assert rows[0]['publisher_categories']==['Nature Walk']
        assert rows[0]['description'].startswith('A guided public walk')
        assert rows[0]['image_url'].endswith('/walk.jpg')

def test_new_tec_never_accepts_unknown_event_link_or_wrong_timezone():
    museum=source(tec.NATURAL_HISTORY,tec.SOURCES,tec.ZONE)
    with pytest.raises(ValueError,match='unregistered_santa_cruz_source'):
        tec.collect(dict(museum,timezone='America/New_York'),lambda *_:'{}',now=NOW)
    item=valid_tec_item(tec.NATURAL_HISTORY)
    item['url']='https://example.com/event/a/'
    assert tec.collect(museum,lambda *_:json.dumps({'events':[item],'total_pages':1}),now=NOW)==[]

def rio_item(**kw):
    start=datetime(2026,11,21,19,0,tzinfo=ZoneInfo(rio.ZONE))
    item={'id':'squarespace-event-123','title':'Song & Choir Concert','workflowState':1,
          'startDate':int(start.timestamp()*1000),'endDate':int((start+timedelta(hours=2)).timestamp()*1000),
          'body':'<p>Community singers join the annual concert with original compositions.</p>',
          'fullUrl':'/events-2/2026/11/21/song-choir-concert',
          'assetUrl':'https://images.squarespace-cdn.com/content/v1/550c8816e4b07f1da6705ffa/1793212187742-VDQSBZJWP1SA7IOY4OBD/choir.jpg?format=750w',
          'location':{'addressTitle':'Rio Theatre for the Performing',
                      'addressLine1':'1205 Soquel Ave','addressLine2':'Santa Cruz, CA, 95062',
                      'markerLat':36.9800418,'markerLng':-122.010492}}
    item.update(kw);return item

def test_rio_full_narrative_verified_venue_and_image_candidate():
    profile=source(rio.KEY,rio.SOURCES,rio.ZONE)
    data={'upcoming':[rio_item()],'website':{'timeZone':rio.ZONE},'pagination':{'nextPage':False}}
    rows=rio.collect(profile,lambda u,a:json.dumps(data),now=NOW)
    assert len(rows)==1
    assert rows[0]['venue_address']=='1205 Soquel Ave, Santa Cruz, CA 95062'
    assert rows[0]['lat'] is not None
    assert rows[0]['image_url'].endswith('/choir.jpg')
    assert rows[0]['description'].startswith('Community singers join')

def test_rio_offsite_and_cancelled_are_held():
    profile=source(rio.KEY,rio.SOURCES,rio.ZONE)
    item=rio_item(location=dict(rio_item()['location'],addressLine1='2500 Wharf Road'))
    cancelled=rio_item(id='cancel',title='Cancelled Choir',fullUrl='/events-2/2026/11/21/cancelled-choir')
    data={'upcoming':[item,cancelled],'website':{'timeZone':rio.ZONE}}
    assert rio.collect(profile,lambda u,a:json.dumps(data),now=NOW)==[]

def game_feed():
    from icalendar import Calendar, Event
    c=Calendar();c.add('prodid','-//Game Night Collective//');c.add('version','2.0')
    for uid,loc,url in [
       ('valid-123','The Cruz Room, The Cruz Room, 1520 Mission St, Santa Cruz, CA 95060, USA','https://luma.com/lgoshoas'),
       ('wrong-address','The Cruz Room, 1001 Center St, Santa Cruz, CA','https://luma.com/lgoshoas'),
       ('unknown-library','Capitola Branch Library, 2500 Wharf Road, Capitola, CA','https://luma.com/lgoshoas'),
       ('generic-meetup','Gilman Brewing, 817 Soquel Ave, Santa Cruz, CA','https://www.meetup.com/example/events/')]:
        e=Event();e.add('uid',uid+'@gamenightcollective.com')
        e.add('summary','Hosted Board Game Night')
        e.add('dtstart',NOW+timedelta(days=5))
        e.add('dtend',NOW+timedelta(days=5,hours=3))
        e.add('description','Hosted tabletop event with original board games and community play.')
        e.add('location',loc);e.add('url',url);c.add_component(e)
    return c.to_ical()

def test_game_feed_holds_address_conflicts_and_non_event_links():
    profile=source(game.KEY,game.SOURCES,game.ZONE)
    rows=game.collect(profile,lambda url,accept:game_feed(),now=NOW)
    assert len(rows)==1
    assert rows[0]['venue_name']=='The Cruz Room'
    assert rows[0]['venue_address']=='1520 Mission St, Santa Cruz, CA 95060'
    assert rows[0]['event_url']=='https://luma.com/lgoshoas'
    assert rows[0]['description'] and rows[0]['timezone']==game.ZONE

def test_game_preview_never_bypasses_approved_host(monkeypatch):
    calls=[]
    def fetch(url,accept,**kw):
        calls.append((url,accept,kw.get('allowed_hosts'),kw.get('respect_robots')))
        return game_feed().decode()
    monkeypatch.setattr(preview_worker,'fetch_publisher',fetch)
    result=preview_worker.preview_source(source(game.KEY,game.SOURCES,game.ZONE))
    assert result['p_future_count']==1
    assert calls==[(game.FEED,'text/calendar',('vpvkznkdczmtsmizxkbl.supabase.co',),True)]
