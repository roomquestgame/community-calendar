"""Synthetic shapes reviewed against Norfolk, Richmond and Nebraska payloads."""
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch

import pytest
from roomquest.event_description import description
from roomquest import biblioevents, nebraska_final, richmond_public_calendars
from roomquest.ics_adapter import parse
from roomquest.preview_worker import _process_claimed_source


def test_narrative_excludes_scripts_and_neighbor_navigation():
    assert description('<p>Cut fabric &amp; prepare kits.</p><nav>Next concert</nav>'
                       '<div class="post-navigation">Another event</div>'
                       '<script>bad()</script><p>Bring scissors.</p>') == 'Cut fabric & prepare kits.\nBring scissors.'
    assert description(None) == ''
    assert description('<p></p>') == ''
    assert len(description('x' * 2100)) == 2000
    with pytest.raises(ValueError):
        description({'unexpected': 'body'})


@pytest.mark.parametrize('key', ['municipal_8939728dcbdf1480d118c65d',
                                 'pamunkey_mechanicsville_libcal_va', 'ashland_public_library_ical_ne'])
def test_ics_narrative_preserves_occurrence_and_legacy_image(key):
    start=(datetime.now(timezone.utc)+timedelta(days=2)).strftime('%Y%m%dT%H%M%SZ')
    raw='\r\n'.join(['BEGIN:VCALENDAR','VERSION:2.0','BEGIN:VEVENT','UID:shared-program',
        'SUMMARY:Tabletop Gaming','DTSTART:'+start,'LOCATION:Library',
        'URL:https://example.org/event/1','GEO:37.5;-77.4','CATEGORIES:Games,Adults',
        'IMAGE:https://example.org/program.jpg',
        'DESCRIPTION:Play board games\\, meet neighbors.\\nBring friends.',
        'END:VEVENT','END:VCALENDAR',''])
    row,=parse(raw,{'source_key':key,'url':'https://example.org/calendar.ics'},legacy=True)
    assert row['description']=='Play board games, meet neighbors.\nBring friends.'
    assert row['publisher_categories']==['Games','Adults']
    assert row['image_url']=='https://example.org/program.jpg'
    assert row['id']=='shared-program' and row['venue_address']==''


def test_biblioevents_retains_prose_and_event_types_not_audiences():
    now=datetime.now(timezone.utc)
    page={'events':{'items':['event1']},'entities':{
        'events':{'event1':{'indexStart':(now+timedelta(days=1)).isoformat(),'definition':{
            'title':'Designers Den','branchLocationId':'branch','description':'<p>Make a paper collage.</p>',
            'typeIds':['craft'],'audienceIds':['adult']}}},
        'locations':{'branch':{'name':'Benson Branch'}},
        'eventTypes':{'craft':{'name':'Arts & Crafts'}},
        'eventAudiences':{'adult':{'name':'Adults'}}}}
    pages=iter([json.dumps(page),' {"events":{"items":[]}}'])
    source={'source_key':'omaha_public_library_biblioevents_ne','feed_url':'https://omaha.bibliocommons.com/v2/events',
            'kind':'html','platform_adapter':'html','timezone':'America/Chicago'}
    row,=biblioevents.collect(source,lambda *_:next(pages),now=now)
    assert row['description']=='Make a paper collage.'
    assert row['publisher_categories']==['Arts & Crafts']
    assert row['id']=='event1' and row['venue_address']=='6015 Binney St, Omaha, NE 68104'


def test_localhop_reads_event_narrative_not_instance_query_text():
    now=datetime.now(timezone.utc)
    start=(now+timedelta(days=1)).isoformat()
    event={'objectId':'event1','name':'Senior Coffee','status':'publish',
           'description':'<p>Enjoy coffee and conversation.</p>',
           'address':{'place':'Library','address1':'123 Main St','city':'Lincoln','state':'NE','postalCode':'68508'}}
    row={'objectId':'instance1','event':event,'actualStartDate':{'iso':start},'status':'publish',
         'organization':{'objectId':nebraska_final.GROUPS[nebraska_final.LINCOLN][0]},'query':'unrelated index text'}
    rows=nebraska_final.localhop(nebraska_final.LINCOLN,
        lambda *_:'window.AppConfig.ParseAppId = "abcdefghijklmnopqrst"',
        lambda *_:json.dumps({'results':[row]}),now)
    assert rows[0]['description']=='Enjoy coffee and conversation.'
    assert rows[0]['id']=='instance1'


def test_richmond_volunteer_description_survives_address_extraction():
    start=datetime.now(timezone.utc)+timedelta(days=1)
    shift={'locationType':'Address','locationState':'VA','timezone':'America/New_York',
        'opportunityType':'Project','volunteersStillNeeded':5,'opportunityLink':'https://www.cfengage.org/opportunity/a01234567890123',
        'description':'<p>Help prepare food boxes at 123 Main Street, Richmond.</p>',
        'locationCity':'Richmond','locationZipCode':'23220','organizationServedName':'Community Center',
        'startDateTimeISO':start.isoformat(),'endDateTimeISO':(start+timedelta(hours=2)).isoformat(),
        'opportunityName':'Packing Shift','occurrenceId':'shift1'}
    row,=richmond_public_calendars.volunteer_shifts(json.dumps({'items':[{'occurrences':[shift]}]}))
    assert row['description']=='Help prepare food boxes at 123 Main Street, Richmond.'
    assert row['venue_address']=='123 Main Street, Richmond, VA 23220'
    assert row['id']=='shift1'


def test_worker_sends_description_to_staging_without_new_fetches():
    source={'source_key':'omaha_public_library_biblioevents_ne','kind':'html','platform_adapter':'html'}
    event={'id':'event1','description':'Make a paper collage.','publisher_categories':['Arts & Crafts']}
    calls=[]
    def rpc(name,payload,**kwargs):
        calls.append((name,payload))
        return 1 if name=='community_collector_record_staged_events' else None
    with patch('roomquest.preview_worker.preview_source',return_value={
            'p_source_key':source['source_key'],'p_events':[event], 'p_samples':[event],
            'p_future_count':1,'p_venue_count':1,'p_error':None}),\
         patch('roomquest.preview_worker.supabase_rpc',side_effect=rpc):
        result=_process_claimed_source(source)
    assert result['staged']==1 and result['complete']==1
    assert next(p for n,p in calls if n=='community_collector_record_staged_events')['p_events']==[event]
