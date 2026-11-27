from copy import deepcopy
from datetime import datetime, timedelta, timezone
from html import escape
import json
from unittest.mock import Mock, patch

import pytest

from roomquest import new_york_performance_expansion as ny
from roomquest.preview_worker import PreviewError
from tests.test_new_york_arts import fake_record

NOW = datetime(2026, 11, 15, 1, 30, tzinfo=timezone.utc)
UUID1 = '11111111-1111-4111-8111-111111111111'
UUID2 = '22222222-2222-4222-8222-222222222222'


@pytest.fixture(autouse=True)
def normalized_without_wall_clock():
    with patch.object(ny, 'record', side_effect=fake_record):
        yield


def source(key):
    return dict(source_key=key, feed_url=ny.SOURCES[key][0], kind='html', platform_adapter='html', timezone=ny.ZONE)


def course(identity=1, slug='test_concert', name='Community Concert', body='<p>A complete concert description.</p>'):
    url='https://www.viewcy.com/event/'+slug
    return dict(id=identity,uuid=slug,object='course',name=name,description=body,url=url,
                category_id=360,timezone=ny.ZONE,events=[dict(object='event',uuid=UUID1,name=name,
                starts_at='2026-11-18T00:30:00.000Z',ends_at='2026-11-18T02:30:00.000Z',book_url=url)])


def jalopy_manifest(*courses, **overrides):
    return json.dumps(dict(object='list',data=list(courses),has_more=False,total_count=len(courses),url='',**overrides))


def native_event(c):
    first=c['events'][0]
    return dict(id=c['uuid'],numericId=c['id'],name=c['name'].strip(),description='$55',
        owner=dict(id=ny.JALOPY_OWNER,username='jalopytheatre'),url='/event/'+c['uuid'],
        published=True,status='published',canceled=False,visibility='listed',accessMode='open',
        hideAddressUntilPurchase=False,locationSetting='physical',attendanceModes=['in-person'],
        timezone=ny.ZONE,categoryName='Concerts',futureEventCount=len(c['events']),
        nextEvent=dict(id=first['uuid'],startsAt=first['starts_at'],endsAt=first['ends_at']),
        location=dict(name='Jalopy Theatre',address='315 Columbia St',city='Brooklyn',
                      state='New York',country='US',zipcode='11231',latitude=40.68136,longitude=-74.00432))


def jalopy_detail(c, *, native=None, body=None, text_size=None):
    native=deepcopy(native or native_event(c))
    body=c['description'] if body is None else body
    count=len(body.encode()) if text_size is None else text_size
    stream=(':HL["/styles.css","style"]\n'
            '54:I[123,[],"PublicEvent"]\n'
            + '55:T'+format(count,'x')+','+body
            + '52:'+json.dumps(['$','$L54',c['uuid'],{'event':native}])+'\n')
    return '<script>self.__next_f.push('+json.dumps([1,stream])+')</script>'


def jalopy_fetch(courses, details=None):
    lookup={c['url']:jalopy_detail(c) for c in courses}
    lookup.update(details or {})
    def fetch(url,accept):
        if url==ny.SOURCES[ny.JALOPY][0]:
            assert accept=='application/json'
            return jalopy_manifest(*courses)
        assert accept=='text/html'
        return lookup[url]
    return fetch


def art_event(identity='2000000000001', title='A Local Performance', **updates):
    result=dict(id=identity,name=title,url='https://www.eventbrite.com/e/local-show-tickets-'+identity,
        primary_organizer_id=ny.ART_ORGANIZER,timezone=ny.ZONE,start_date='2026-11-18',start_time='19:00:00',
        additionalSessionsCount=0,is_online_event=False,is_cancelled=False,is_protected_event=False,
        hide_start_date=False,hide_end_date=False,ticket_availability=dict(is_sold_out=False))
    result.update(updates)
    return result


def art_page(events,total=None,number=1):
    total=len(events) if total is None else total
    more=number*12<total
    if number==1:
        page=dict(organizer=dict(id=ny.ART_ORGANIZER,name='Brooklyn Art Haus',profilePageUrl=ny.SOURCES[ny.ART_HAUS][0]),
                  upcomingEvents=events,upcomingEventsTotal=total,upcomingEventsFailed=False,hasMoreUpcoming=more)
        return '<script id="__NEXT_DATA__" type="application/json">'+json.dumps({'props':{'pageProps':page}})+'</script>'
    return json.dumps(dict(events=events,total=total,hasMore=more))


def art_detail(event,body='Full native performance details.', *, parent=False, widgets=None):
    basic=dict(id=event['id'],name=event['name'],url=event['url'],organizationId=ny.ART_ORGANIZATION,
        organizer=dict(id=ny.ART_ORGANIZER),status='live',isOnline=False,isProtected=False,isListed=True,
        isParentEvent=parent,summary='Publisher overview.',hideStartDate=False,hideEndDate=False,
        startDate=dict(local='2026-11-18T19:00:00',utc='2026-11-19T00:00:00Z',timezone=ny.ZONE),
        endDate=dict(local='2026-11-18T21:00:00',utc='2026-11-19T02:00:00Z',timezone=ny.ZONE),
        venue=dict(name='Brooklyn Art Haus',address=dict(country='US',city='Brooklyn',region='NY',
            localizedMultiLineAddressDisplay=['24 Marcy Ave','Brooklyn, NY 11211'],latitude='40.7134273',longitude='-73.9549377')))
    if parent:
        basic['startDate']=dict(local='2025-01-18T19:00:00',utc='2025-01-19T00:00:00Z',timezone=ny.ZONE)
    context=dict(basicInfo=basic,structuredContent=dict(modules=[dict(type='text',text='<p>'+escape(body)+'</p>')],
        widgets=widgets or dict(faqs=[],nativeVideo=None,parking=None,agenda=None,lineup=None)),taxonomies=dict(category='Performing Arts'))
    return '<script id="__NEXT_DATA__" type="application/json">'+json.dumps({'props':{'pageProps':dict(context=context,error=None,canonicalUrl=event['url'])}})+'</script>'


def art_fetch(events, detail=None):
    def fetch(url,accept):
        if url==ny.SOURCES[ny.ART_HAUS][0]:return art_page(events[:12],len(events))
        if '/organizer-profile/api/' in url:
            page=int(url.split('page=')[1].split('&')[0]);assert accept=='application/json'
            return art_page(events[(page-1)*12:page*12],len(events),page)
        event=next(e for e in events if e['url']==url)
        return detail(event) if detail else art_detail(event)
    return fetch


def finish(key,fetch,max_details=2):
    state=None;claims=[]
    for _ in range(100):
        result=ny.collect_chunk(source(key),fetch,checkpoint=state,now=NOW,max_details=max_details)
        state=result['checkpoint'];ny._checkpoint(key,state,NOW);claims.append(result)
        if result['complete']:return result,claims
        assert result['events']==[]
    raise AssertionError('Complete snapshot not reached')


def test_jalopy_full_utf8_text_frames_and_occurrence_ids_survive_complete_checkpoint():
    body='<p>'+'Musique — complete narrative. '*110+'Final access requirement.</p>'
    c=course(body=body);second=deepcopy(c['events'][0]);second.update(uuid=UUID2,starts_at='2026-11-25T00:30:00.000Z',ends_at='2026-11-25T02:30:00.000Z');c['events'].append(second)
    result,claims=finish(ny.JALOPY,jalopy_fetch([c]))
    assert len(result['events'])==2 and {r['id'] for r in result['events']}=={UUID1,UUID2}
    assert all(r['description']==ny._body(body) and len(r['description'])>2000 for r in result['events'])
    assert all(r['venue_address']=='315 Columbia Street, Brooklyn, NY 11231' for r in result['events'])
    assert claims[0]['events']==[] and claims[-2]['checkpoint']['phase']=='verify'
    assert len(result['checkpoint']['row_hashes'])==2


def test_original_facts_ignore_provider_label_and_exclude_reviewed_performance_enrichment():
    renamed={**source(ny.JALOPY),'publisher_name':'Renamed provider label'}
    assert ny._source(renamed)==ny.JALOPY
    c=course();result,_=finish(ny.JALOPY,jalopy_fetch([c]));row,=result['events']
    facts=row['collector_event_content_v1']['facts']
    assert facts['venue_name']=='Jalopy Theatre' and facts['venue_address']=='315 Columbia St'
    assert facts['venue_address']!=row['venue_address']
    assert (facts['source_latitude'],facts['source_longitude'])==(40.68136,-74.00432)
    event=art_event();result,_=finish(ny.ART_HAUS,art_fetch([event]));row,=result['events']
    facts=row['collector_event_content_v1']['facts']
    assert facts['venue_address']=='24 Marcy Ave' and facts['venue_address']!=row['venue_address']
    assert facts['venue_postal_code']=='11211' and facts['publisher_categories']==['Performing Arts']
    assert 'publisher_organizer_id' not in facts


def test_publisher_narrative_change_changes_facts_not_occurrence_id():
    original=course(body='<p>Original complete concert narrative.</p>')
    changed=course(body='<p>Changed complete publisher concert narrative.</p>')
    first=finish(ny.JALOPY,jalopy_fetch([original]))[0]['events'][0]
    second=finish(ny.JALOPY,jalopy_fetch([changed]))[0]['events'][0]
    assert second['id']==first['id']
    assert second['collector_event_content_v1']!=first['collector_event_content_v1']


def test_jalopy_private_indefinite_and_multiweek_ranges_do_not_become_occurrences():
    private=course(1,name='Private Guitar Lessons');private['events'][0].update(starts_at='2022-01-01T00:00:00Z',ends_at='2029-01-01T00:00:00Z')
    multiday=course(2,slug='multiweek_class');multiday['events'][0].update(ends_at='2027-01-18T02:30:00Z')
    queue,total=ny._jalopy_manifest(jalopy_manifest(private,multiday),NOW)
    assert queue==[] and total==2
    result,_=finish(ny.JALOPY,jalopy_fetch([private,multiday]));assert result['events']==[]


@pytest.mark.parametrize('change',['more','total','duplicate','timezone','event_identity'])
def test_jalopy_incomplete_or_changed_catalog_is_rejected(change):
    c=course();data=json.loads(jalopy_manifest(c))
    if change=='more':data['has_more']=True
    if change=='total':data['total_count']=2
    if change=='duplicate':data['data'].append(c);data['total_count']=2
    if change=='timezone':data['data'][0]['timezone']='UTC'
    if change=='event_identity':data['data'][0]['events'][0]['book_url']='https://www.viewcy.com/event/another'
    with pytest.raises(ValueError,match='manifest_incomplete'):
        ny._jalopy_manifest(json.dumps(data),NOW)


@pytest.mark.parametrize('change',['body','owner','count','clock','frame'])
def test_jalopy_changed_native_detail_never_silently_passes(change):
    c=course();n=native_event(c);kwargs={}
    if change=='body':kwargs['body']='<p>Different narrative.</p>'
    if change=='owner':n['owner']['username']='another'
    if change=='count':n['futureEventCount']=5
    if change=='clock':n['nextEvent']['startsAt']='2026-11-18T01:30:00Z'
    if change=='frame':kwargs['text_size']=10
    item=ny._jalopy_manifest(jalopy_manifest(c),NOW)[0][0]
    with pytest.raises(ValueError,match='changed'):
        ny._jalopy_detail(item,jalopy_detail(c,native=n,**kwargs),NOW)


def test_jalopy_explicit_offsite_uses_actual_queens_venue():
    c=course(body='<p>OFFSITE SHOW at Gottscheer Hall.</p>');n=native_event(c)
    n['location']=dict(name='Gottscheer Hall',address='6-57 Fairview Ave',city='Ridgewood',state='New York',country='US',zipcode='11385',latitude=40.706827,longitude=-73.9054957)
    result,_=finish(ny.JALOPY,jalopy_fetch([c],{c['url']:jalopy_detail(c,native=n)}))
    row,=result['events'];assert row['venue_address']=='6-57 Fairview Avenue, Ridgewood, NY 11385'
    assert row['lat']==40.706827 and not row.get('location_is_approximate')


@pytest.mark.parametrize('change',['unknown_venue','hidden','private','cancelled','oversize'])
def test_jalopy_unreviewed_private_and_oversize_details_are_individually_held(change):
    c=course();n=native_event(c)
    if change=='unknown_venue':n['location']['address']='999 Other Street'
    if change=='hidden':n['hideAddressUntilPurchase']=True
    if change=='private':n['accessMode']='private'
    if change=='cancelled':n['canceled']=True
    if change=='oversize':c['description']='<p>'+'x'*12001+'</p>'
    result,_=finish(ny.JALOPY,jalopy_fetch([c],{c['url']:jalopy_detail(c,native=n)}))
    assert result['events']==[] and result['checkpoint']['diagnostics'][0]['disposition']=='held'


def test_art_haus_full_pagination_is_private_until_all_pages_and_details_revalidated():
    events=[art_event(str(2000000000001+i)) for i in range(30)]
    fetch=Mock(side_effect=art_fetch(events))
    result,claims=finish(ny.ART_HAUS,fetch)
    assert len(result['events'])==30 and len(result['checkpoint']['queue'])==30
    assert [c['checkpoint']['manifest_count'] for c in claims[:3]]==[12,24,30]
    assert all(c['events']==[] for c in claims[:-1])
    for page in (1,2,3):assert sum(c.args[0]==ny._art_page_url(page) for c in fetch.call_args_list)==2


@pytest.mark.parametrize('mutation',['wrong_total','duplicate','wrong_organizer','truncated','has_more'])
def test_art_haus_incomplete_native_pages_are_rejected(mutation):
    events=[art_event(str(2000000000001+i)) for i in range(12)]
    data=json.loads(art_page(events,30,2))
    if mutation=='wrong_total':data['total']=True
    if mutation=='duplicate':data['events'][1]=data['events'][0]
    if mutation=='wrong_organizer':data['events'][0]['primary_organizer_id']='other'
    if mutation=='truncated':data['events'].pop()
    if mutation=='has_more':data['hasMore']=False
    with pytest.raises(ValueError,match='manifest_incomplete'):ny._art_page(json.dumps(data),2)


def test_art_haus_full_body_and_native_parking_preserved_with_actual_street():
    event=art_event();body='Full performance narrative. '*110+'Final instruction.'
    widgets=dict(faqs=[],nativeVideo=None,parking={'availability':'free'},agenda=None,lineup=None)
    result,_=finish(ny.ART_HAUS,art_fetch([event],lambda e:art_detail(e,body,widgets=widgets)))
    row,=result['events'];assert body in row['description'] and row['description'].endswith('Parking: free.')
    assert row['venue_address']=='24 Marcy Avenue, Brooklyn, NY 11211' and len(row['description'])>2000


def test_art_haus_unverified_parent_range_is_held_not_published_as_year_long_event():
    event=art_event(additionalSessionsCount=3)
    result,_=finish(ny.ART_HAUS,art_fetch([event],lambda e:art_detail(e,parent=True)))
    assert result['events']==[]
    assert result['checkpoint']['diagnostics'][0]['reason']=='recurring_occurrences_unresolved'


def test_unknown_art_haus_prose_widget_is_held_without_silent_omission():
    event=art_event()
    result,_=finish(ny.ART_HAUS,art_fetch([event],lambda e:art_detail(e,widgets={'faqs':[{'question':'Extra','answer':'Required instructions'}]})))
    assert result['events']==[] and result['checkpoint']['diagnostics'][0]['reason']=='description_shape_changed'


@pytest.mark.parametrize('mutation',['body','row_hash','source','cursor','venue','clock','phase'])
def test_checkpoint_rejects_tampering_even_when_outer_seal_is_recomputed(mutation):
    c=course();result,_=finish(ny.JALOPY,jalopy_fetch([c]));state=deepcopy(result['checkpoint'])
    if mutation=='body':state['events'][0]['description']='Shortened.'
    if mutation=='row_hash':state['row_hashes']={}
    if mutation=='source':state['source_key']=ny.ART_HAUS
    if mutation=='cursor':state['cursor']=True
    if mutation=='venue':state['events'][0]['venue_address']='999 Other Street, Brooklyn, NY 11231'
    if mutation=='clock':state['events'][0]['starts_at']='2026-11-18T01:30:00Z'
    if mutation=='phase':state['phase']='details'
    ny._seal(state)
    with pytest.raises(ValueError,match='checkpoint_invalid'):
        ny.collect_chunk(source(ny.JALOPY),Mock(),checkpoint=state,now=NOW)


def test_checkpoint_rejects_rehashed_fact_tampering_and_finishes_legacy_prefix():
    first=course();second=course(2,slug='second_concert',name='Second Concert')
    second['events'][0]['uuid']=UUID2
    fetch=jalopy_fetch([first,second])
    state=ny.collect_chunk(source(ny.JALOPY),fetch,now=NOW,max_details=1)['checkpoint']
    partial=ny.collect_chunk(source(ny.JALOPY),fetch,checkpoint=state,now=NOW,max_details=1)['checkpoint']
    tampered=deepcopy(partial)
    tampered['events'][0]['collector_event_content_v1']['facts']['description']='Tampered facts.'
    tampered['row_hashes'][ny._row_key(tampered['events'][0])]=ny._digest(tampered['events'][0])
    ny._seal(tampered)
    with pytest.raises(ValueError,match='checkpoint_invalid'):
        ny.collect_chunk(source(ny.JALOPY),fetch,checkpoint=tampered,now=NOW,max_details=1)
    legacy=deepcopy(partial)
    legacy['events'][0].pop('collector_event_content_v1')
    legacy['row_hashes'][ny._row_key(legacy['events'][0])]=ny._digest(legacy['events'][0])
    ny._seal(legacy)
    for _ in range(10):
        result=ny.collect_chunk(source(ny.JALOPY),fetch,checkpoint=legacy,now=NOW,max_details=1)
        legacy=result['checkpoint']
        if result['complete']:break
    assert result['complete']
    assert all('collector_event_content_v1' not in row for row in result['events'])


def test_manifest_change_discards_private_snapshot_and_restarts():
    c=course();fetch=jalopy_fetch([c]);state=None
    for _ in range(2):state=ny.collect_chunk(source(ny.JALOPY),fetch,checkpoint=state,now=NOW)['checkpoint']
    assert state['phase']=='verify' and state['events']
    changed=deepcopy(c);changed['description']='<p>Changed complete narrative.</p>'
    result=ny.collect_chunk(source(ny.JALOPY),jalopy_fetch([changed]),checkpoint=state,now=NOW)
    assert not result['complete'] and result['events']==[]
    assert result['checkpoint']['phase']=='manifest' and result['checkpoint']['events']==[]


def test_normal_permission_failure_does_not_create_success_or_retry():
    c=course();state=ny.collect_chunk(source(ny.JALOPY),jalopy_fetch([c]),now=NOW)['checkpoint']
    error=PreviewError('robots_denied');fetch=Mock(side_effect=error)
    with pytest.raises(PreviewError) as caught:ny.collect_chunk(source(ny.JALOPY),fetch,checkpoint=state,now=NOW)
    assert caught.value is error and fetch.call_count==1 and state['cursor']==0


def test_pacing_pause_is_durable_private_and_expiration_restarts():
    c=course();state=ny.collect_chunk(source(ny.JALOPY),jalopy_fetch([c]),now=NOW)['checkpoint']
    result=ny.collect_chunk(source(ny.JALOPY),Mock(side_effect=PreviewError('publisher_pacing_deferred')),checkpoint=state,now=NOW)
    assert not result['complete'] and result['checkpoint']['cursor']==0
    result=ny.collect_chunk(source(ny.JALOPY),jalopy_fetch([c]),checkpoint=state,now=NOW+timedelta(hours=5))
    assert result['checkpoint']['started_at']==(NOW+timedelta(hours=5)).isoformat()


@pytest.mark.parametrize('field,value',[('feed_url','https://other.invalid/'),('kind','json'),('platform_adapter','viewcy'),('timezone','UTC')])
def test_source_contract_is_exact(field,value):
    invalid=source(ny.JALOPY);invalid[field]=value;fetch=Mock()
    with pytest.raises(ValueError,match='source_unregistered'):ny.collect_chunk(invalid,fetch,now=NOW)
    fetch.assert_not_called()


def test_jalopy_missing_flight_body_reference_has_bounded_source_error():
    c=course();native=native_event(c);native['description']='$ffff'
    item=ny._jalopy_manifest(jalopy_manifest(c),NOW)[0][0]
    with pytest.raises(ValueError,match='^nyc_performance_detail_changed$'):
        ny._jalopy_detail(item,jalopy_detail(c,native=native),NOW)


def test_jalopy_theatre_or_tavern_open_mic_is_visibly_approximate_and_body_bound():
    body=('Signups at 6pm, begins at 6:30pm Names are drawn out of a hat at 6:30pm '
          'and the performer is allowed one song or the total allotted time of four minutes. '
          'If there is a conflicting performance in the theatre, the open mic will be held in the tavern.')
    c=course(slug='jalopy_open_mic_eith',body=body)
    result,_=finish(ny.JALOPY,jalopy_fetch([c]));row,=result['events']
    assert row['location_is_approximate'] is True
    assert row['venue_name']=='Jalopy Theatre / Tavern (approximate meeting point)'
    assert row['venue_address']=='315 Columbia Street, Brooklyn, NY 11231'
    assert row['description']==body
    changed=deepcopy(c);changed['description']=body+' Venue changed.'
    held,_=finish(ny.JALOPY,jalopy_fetch([changed]))
    assert held['events']==[] and held['checkpoint']['diagnostics'][0]['reason']=='venue_unreviewed'


def test_jalopy_named_theatre_estimate_is_exact_body_bound_and_never_other_venue():
    # Frozen public native narrative; its digest is the reviewed evidence bound.
    body='Doors 7:30pm, Show 8pm\n$20 adv / $25 dos\nJay Bragg Presents: Christmas in New Vaudeville\n(From Nashville via The North Pole)\nVaudeville impresario Jay Bragg brings the sixth annual “Christmas in New Vaudeville,” The Merriest Show On Earth, back to New York for its third year in the city, this time at the Jalopy Theater in Brooklyn on Monday, December 7.\nA third-generation entertainer, Bragg has spent 25 years onstage developing his own modern take on one of America’s great entertainment traditions. His New Vaudeville productions revive the spirit of the classic variety show, with live music, theatrical storytelling and old-school showmanship.\nEvery December, Bragg becomes King Kazoo, bandleader from the North Pole. Dressed in his signature bright red frock coat and top hat, brass kazoo in hand, he leads The Reindeer Band through a night of holiday favorites and original Christmas songs, built for the whole family. The show is part vaudeville throwback and part Christmas spectacle, and it has the warmth of a holiday party where the whole room gets pulled in.\nKing Kazoo is less a costume than the truest version of Bragg: an entertainer who believes the audience’s joy is the whole point. He learned that performing for audiences in nursing homes and as a hospice volunteer, and it’s the spirit behind every New Vaudeville show.\nFor Bragg, New York is where it all started. His grandparents, Ernie and Ursula, met performing together in New York vaudeville in the early 1930s, and music from their original act still turns up in his productions today. Nearly a century later, their grandson brings the family tradition back to the city where it began.\nIf you want to feel like a kid at Christmas again, this show’s for you.\n“\nA life without whimsy is a life lived too grimly"\nwww.jaybragg.com\nwww.newvaudeville.com\nwww.acousticsingingtelegram.com'
    c=course(slug='jay_braggs_christma',body=body);native=native_event(c);native['location']=None
    result,_=finish(ny.JALOPY,jalopy_fetch([c],{c['url']:jalopy_detail(c,native=native)}))
    row,=result['events']
    assert row['location_is_approximate'] is True
    assert row['venue_name']=='Jalopy Theatre (approximate venue address)'
    assert row['venue_address']=='315 Columbia Street, Brooklyn, NY 11231'
    assert row['description']==body
    for change in ('body','slug','location'):
        altered=deepcopy(c);venue=deepcopy(native)
        if change=='body':altered['description']=body.replace('Jalopy Theater in Brooklyn','another theater in Manhattan')
        if change=='slug':altered['uuid']='another_show';altered['url']='https://www.viewcy.com/event/another_show';altered['events'][0]['book_url']=altered['url'];venue['id']=altered['uuid'];venue['url']='/event/'+altered['uuid']
        if change=='location':venue['location']=dict(name='Another Theatre',address='999 Other Street')
        held,_=finish(ny.JALOPY,jalopy_fetch([altered],{altered['url']:jalopy_detail(altered,native=venue)}))
        assert held['events']==[] and held['checkpoint']['diagnostics'][0]['reason']=='venue_unreviewed'
