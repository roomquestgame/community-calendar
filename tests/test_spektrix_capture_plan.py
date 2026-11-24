"""Plan URLs must be derived from an exact staged Spektrix instance manifest."""
from datetime import datetime,timezone
import json
import pytest
from roomquest import feedzilla_capture_store as capture
from roomquest import spektrix_capture_plan as planner

CONTEXT='a'*64
STAMP=datetime(2026,11,24,12,0,tzinfo=timezone.utc)
CLIENT='thealbany'
EVENT='347737AVNHRBKMRLMQKLLCMGLMCVVMMVC'
INSTANCE='1928802AGPJVJCHJVPHSNVRRBPHQBSJJQ'
PLAN='1801APGQPRKNVLCHGSKJBCTJKDRMGPLNL'
VENUE='201AGBHDRLQHNHPHKKMPKLGPMDRDTDMVL'
SOURCE={'source_key':'municipal_001','feed_url':'https://system.spektrix.com/thealbany/api/v3/events','platform_adapter':'spektrix'}
PROFILE={'client':CLIENT,'publisher_url':'https://www.thealbany.org.uk/events','country':'GB',
         'home_city':'London','timezone':'Europe/London'}
EVENTS=[{'id':EVENT,'name':'Real Gig','webUrl':'https://www.thealbany.org.uk/events/real-gig/',
         'duration':90,'description':'Music','imageUrl':''}]
INSTANCES=[{'id':INSTANCE,'event':{'id':EVENT},'planId':PLAN,
            'cancelled':False,'isOnSale':True,'start':'2026-12-05T19:00:00',
            'startUtc':'2026-12-05T19:00:00Z'}]
VENUES=[{'id':VENUE,'name':'The Albany','address':'Douglas Way, London SE8 4AG'}]
PLAN_PAGE={'id':PLAN,'venue':{'id':VENUE},'name':'Main Hall'}
START='2026-12-05';END='2026-12-08'


def base_capture(events=EVENTS,instances=INSTANCES,venues=VENUES):
    urls=planner.base_tasks(SOURCE,PROFILE,START,END)
    data=[events,instances,venues]
    cp=capture.new(SOURCE,urls,allowed_hosts=['system.spektrix.com'],
                   start=START,end=END,context_hash=CONTEXT,at=STAMP)
    for url,body in zip(urls,data):
        cp=capture.acknowledge_page(SOURCE,cp,url,json.dumps(body),context_hash=CONTEXT,at=STAMP)
    return cp


def test_complete_instance_ids_generate_exact_followup_plan_requests():
    base=base_capture()
    plans=planner.plan_tasks(SOURCE,PROFILE,base,context_hash=CONTEXT,at=STAMP)
    assert plans==['https://system.spektrix.com/thealbany/api/v3/plans/'+PLAN]
    cp=capture.add_verified_requests(SOURCE,base,plans,scope_verified=True,context_hash=CONTEXT,at=STAMP)
    cp=capture.acknowledge_page(SOURCE,cp,plans[0],json.dumps(PLAN_PAGE),terminal=True,context_hash=CONTEXT,at=STAMP)
    result=planner.project(SOURCE,PROFILE,cp,context_hash=CONTEXT,at=STAMP)
    assert result['complete'] is True
    assert len(result['events'])==1
    assert result['events'][0]['source_instance_id']==INSTANCE
    assert result['events'][0]['venue_name']=='The Albany'
    assert capture.ready_to_project(SOURCE,cp,context_hash=CONTEXT,at=STAMP)
    assert 'records' not in capture.decode(SOURCE,cp,context_hash=CONTEXT,at=STAMP)


def test_missing_plan_does_not_turn_into_complete_snapshot():
    base=base_capture()
    with pytest.raises(ValueError,match='spektrix_capture_not_complete'):
        planner.project(SOURCE,PROFILE,base,context_hash=CONTEXT,at=STAMP)


def test_cross_client_and_missing_event_id_cannot_generate_plan_urls():
    wrong=dict(SOURCE,feed_url='https://system.spektrix.com/richmix/api/v3/events')
    with pytest.raises(ValueError):
        planner.plan_tasks(wrong,PROFILE,base_capture(),context_hash=CONTEXT,at=STAMP)
    malformed=[dict(INSTANCES[0],event={'id':'nonexistent'})]
    with pytest.raises(ValueError,match='spektrix_capture_instance_identity_invalid'):
        planner.plan_tasks(SOURCE,PROFILE,base_capture(instances=malformed),context_hash=CONTEXT,at=STAMP)


def test_nonexistent_plan_id_cannot_be_substituted():
    base=base_capture()
    plans=planner.plan_tasks(SOURCE,PROFILE,base,context_hash=CONTEXT,at=STAMP)
    cp=capture.add_verified_requests(SOURCE,base,plans,scope_verified=True,context_hash=CONTEXT,at=STAMP)
    wrong=dict(PLAN_PAGE,id='not-the-publisher-plan-id')
    cp=capture.acknowledge_page(SOURCE,cp,plans[0],json.dumps(wrong),terminal=True,context_hash=CONTEXT,at=STAMP)
    with pytest.raises(ValueError,match='spektrix_capture_plan_identity_invalid'):
        planner.project(SOURCE,PROFILE,cp,context_hash=CONTEXT,at=STAMP)


def test_date_window_never_exceeds_sixty_days():
    with pytest.raises(ValueError,match='spektrix_window_invalid'):
        planner.base_tasks(SOURCE,PROFILE,'2026-11-24','2027-01-23')
