"""New calendars retain normal staging, certification and bounded public transport."""
from copy import deepcopy
import importlib
from unittest.mock import ANY, MagicMock, Mock, patch

import pytest

from roomquest import preview_worker as worker
from roomquest.publisher_evidence import attach, family, image_url
from roomquest.event_media import resolve_photo

PANTRY = 'good_shepherd_food_pantry_south_hill_va'
RENDER = 'https://goodshepherdsouthhill.org/wp-admin/admin-ajax.php'
NONCE, ARGS = '0123456789', 'a' * 40
SOURCES = [
    ('coopers_landing_clarksville_va', 'coopers_landing',
     'https://cooperslandinginn.net/?page_id=119', 'cooperslandinginn.net'),
    ('clarksville_tourism_va', 'clarksville_tourism',
     'https://tourism.visitclarksvilleva.com/calendar/', 'tourism.visitclarksvilleva.com'),
    (PANTRY, 'good_shepherd', 'https://goodshepherdsouthhill.org/welcome/calendar/',
     'goodshepherdsouthhill.org'),
]
TOURISM_EVENT = ('https://tourism.visitclarksvilleva.com/connections/76407-historic-downtown-clarksville/'
                 'events/2026/12/5/667469/historic-downtown-clarksvilles-1st-annual-cookie-cocoa-crawl/')


@pytest.mark.parametrize('spec', SOURCES)
@pytest.mark.parametrize('status', ['scheduled', 'cancelled', 'postponed'])
def test_normal_worker_stages_evidence_and_status_before_v3_certification(spec, status):
    key, module_name, feed, host = spec
    source = dict(source_key=key, kind='html', platform_adapter='html',
                  feed_url=feed, timezone='America/New_York')
    event = attach(dict(id='stable-record', event_url=TOURISM_EVENT if module_name=='clarksville_tourism' else feed,
                        title='Public event', description='Publisher narrative',
                        starts_at='2026-12-07T23:30:00+00:00', ends_at=None,
                        lat=None, lng=None, publisher_status=status), key)
    calls = []
    def collect(src, fetch, *, deadline_at, **extra):
        assert src == source and deadline_at is not None
        fetch(feed, 'text/html')
        if key == PANTRY:
            assert set(extra) == {'render_calendar'}
            assert extra['render_calendar'](nonce=NONCE, args=ARGS) == 'rendered calendar'
        else:
            assert extra == {}
        return [deepcopy(event)]
    module = importlib.import_module('roomquest.'+module_name)
    with patch.object(module, 'collect', side_effect=collect), \
         patch.object(worker, 'fetch_publisher', return_value='discovery') as fetch, \
         patch.object(worker, 'render_good_shepherd_calendar', return_value='rendered calendar') as render, \
         patch.object(worker, 'supabase_rpc', side_effect=lambda name,payload:calls.append((name,deepcopy(payload))) or len(payload.get('p_events',[]))):
        result = worker._process_claimed_source(source)
    assert result['complete'] == 1 and result['staged'] == 1
    assert [name for name,_ in calls] == ['community_collector_record_staged_events',
                                       'community_collector_record_preview_v3']
    assert calls[0][1]['p_events'] == [event]
    assert calls[1][1]['p_parser_capability'] == 'publisher_event_candidates_v1'
    assert fetch.call_args.kwargs['respect_robots'] is True
    assert fetch.call_args.kwargs['allowed_hosts'] == (host,)
    if key == PANTRY:
        assert render.call_args.kwargs['deadline_at'] == fetch.call_args.kwargs['deadline_at']
    else:
        render.assert_not_called()


@pytest.mark.parametrize('spec', SOURCES)
def test_empty_and_failed_sources_use_certified_path_without_partial_staging(spec):
    key, module_name, feed, _ = spec
    module = importlib.import_module('roomquest.'+module_name)
    source = dict(source_key=key, kind='html', platform_adapter='html', feed_url=feed, timezone='America/New_York')
    for error in [None, worker.PreviewError('robots_denied')]:
        calls=[]
        with patch.object(module,'collect',return_value=[],side_effect=error), \
             patch.object(worker,'supabase_rpc',side_effect=lambda n,p:calls.append((n,deepcopy(p))) or 0):
            result=worker._process_claimed_source(source)
        assert result['complete'] == (error is None)
        assert result['failed'] == (error is not None)
        assert calls[-1][0]=='community_collector_record_preview_v3'
        if error:
            assert len(calls)==1 and calls[0][1]['p_error']=='robots_denied'
        else:
            assert calls[-1][1]['p_parser_capability']=='publisher_event_candidates_v1'


def fake_transport(monkeypatch, *, body=b'<div>calendar</div>', status=200, headers=None):
    reply=MagicMock(status_code=status, headers=headers or {'Content-Type':'text/html; charset=UTF-8'},encoding='utf-8')
    reply.iter_content.return_value=[body]
    session=MagicMock()
    session.__enter__.return_value=session
    session.post.return_value=reply
    monkeypatch.setattr(worker.requests,'Session',lambda:session)
    dns=Mock();robots=Mock(return_value=True);pacing=Mock()
    monkeypatch.setattr(worker,'validate_public_dns',dns)
    monkeypatch.setattr(worker,'robots_allowed',robots)
    monkeypatch.setattr(worker,'pace_publisher',pacing)
    monkeypatch.setattr(worker,'_observe_retry_after',Mock())
    return session,reply,dns,robots,pacing


def test_only_observed_display_action_is_posted_under_existing_guards(monkeypatch):
    session,reply,dns,robots,pacing=fake_transport(monkeypatch)
    assert worker.render_good_shepherd_calendar(nonce=NONCE,args=ARGS)=='<div>calendar</div>'
    session.get.assert_not_called()
    session.post.assert_called_once()
    args,kw=session.post.call_args
    assert args==(RENDER,)
    assert kw['data']=={'action':'r34ics_ajax','r34ics_nonce':NONCE,'subaction':'display_calendar',
                        'args':ARGS,'js_args[debug]':'false'}
    assert kw['allow_redirects'] is False and kw['stream'] is True
    assert kw['headers']['User-Agent'].startswith('RoomQuestCommunityCalendar/')
    assert kw['headers']['Referer']=='https://goodshepherdsouthhill.org/welcome/calendar/'
    dns.assert_called_once_with('goodshepherdsouthhill.org')
    robots.assert_called_once_with('goodshepherdsouthhill.org','/wp-admin/admin-ajax.php', deadline_at=ANY)
    pacing.assert_called_once()
    reply.close.assert_called_once()


@pytest.mark.parametrize('nonce,args', [(None,ARGS),(1234567890,ARGS),(NONCE,None),
    ('x'*10,ARGS),(NONCE,'f'*41),(NONCE,'https://private.example'),(NONCE,ARGS+'&action=delete')])
def test_malformed_public_markup_cannot_control_a_request(monkeypatch,nonce,args):
    session,*_=fake_transport(monkeypatch)
    with pytest.raises(worker.PreviewError,match='^invalid_calendar_render_parameters$'):
        worker.render_good_shepherd_calendar(nonce=nonce,args=args)
    session.post.assert_not_called()


@pytest.mark.parametrize('change', [{'action':'delete_user'},{'subaction':'subscribe'},
    {'extra':'anything'},{'r34ics_nonce':1234567890}])
def test_internal_boundary_rejects_other_actions_and_form_fields(monkeypatch,change):
    session,*_=fake_transport(monkeypatch)
    form={'action':'r34ics_ajax','r34ics_nonce':NONCE,'subaction':'display_calendar','args':ARGS,'js_args[debug]':'false'}
    form.update(change)
    with pytest.raises(worker.PreviewError,match='^invalid_calendar_render_parameters$'):
        worker._fetch_publisher_request(RENDER,'text/html',respect_robots=True,
                                        allowed_hosts=('goodshepherdsouthhill.org',),calendar_form=form)
    session.post.assert_not_called()


@pytest.mark.parametrize('gate,code', [('dns','non_public_dns'),('robots','robots_denied'),('pacing','publisher_rate_limited')])
def test_post_preserves_access_and_pacing_denials(monkeypatch,gate,code):
    session,_,dns,robots,pacing=fake_transport(monkeypatch)
    if gate=='robots':robots.return_value=False
    elif gate=='dns':dns.side_effect=worker.PreviewError(code)
    else:pacing.side_effect=worker.PreviewError(code)
    with pytest.raises(worker.PreviewError,match='^'+code+'$'):
        worker.render_good_shepherd_calendar(nonce=NONCE,args=ARGS)
    session.post.assert_not_called()


@pytest.mark.parametrize('status',[301,302,303,307,308])
def test_render_never_follows_even_same_host_redirects(monkeypatch,status):
    session,reply,*_=fake_transport(monkeypatch,status=status,headers={'Location':'/welcome/calendar/'})
    with pytest.raises(worker.PreviewError,match='^calendar_render_redirect_blocked$'):
        worker.render_good_shepherd_calendar(nonce=NONCE,args=ARGS)
    assert session.post.call_count==1
    session.get.assert_not_called()
    reply.close.assert_called_once()


@pytest.mark.parametrize('body,status,headers,code', [
    (b'{}',200,{'Content-Type':'application/json'},'invalid_calendar_render_content_type'),
    (b'bad',403,{'Content-Type':'text/html'},'publisher_http_403'),
    (b'wait',429,{'Content-Type':'text/html','Retry-After':'10'},'publisher_http_429'),
    (b'x',200,{'Content-Type':'text/html','Content-Length':str(worker.MAX_BODY+1)},'source_unavailable_or_oversized'),
    (b'x'*(worker.MAX_BODY+1),200,{'Content-Type':'text/html'},'source_too_large'),
    (b'\xff',200,{'Content-Type':'text/html'},'invalid_source_encoding'),
])
def test_render_failures_are_bounded_and_honest(monkeypatch,body,status,headers,code):
    _,reply,*_=fake_transport(monkeypatch,body=body,status=status,headers=headers)
    with pytest.raises(worker.PreviewError,match='^'+code+'$'):
        worker.render_good_shepherd_calendar(nonce=NONCE,args=ARGS)
    reply.close.assert_called_once()


def test_expired_render_deadline_sends_no_post(monkeypatch):
    session,*_=fake_transport(monkeypatch)
    with pytest.raises(worker.PreviewError,match='^source_fetch_deadline$'):
        worker.render_good_shepherd_calendar(nonce=NONCE,args=ARGS,deadline_at=worker.monotonic()-1)
    session.post.assert_not_called()


def test_tourism_candidate_uses_existing_image_probe_without_page_recrawl():
    picture='https://images.locable.com/abcdefghijklmnopqrstuvxyz0123456789=='
    assert family('clarksville_tourism_va',TOURISM_EVENT)=='clarksville_tourism'
    assert image_url(picture,'clarksville_tourism')==picture
    fetch=Mock(side_effect=AssertionError('No page recrawl'))
    claim=dict(source_key='clarksville_tourism_va',event_url=TOURISM_EVENT,title='Cocoa Crawl',
               candidate_only=True,candidate_url=picture)
    assert resolve_photo(claim,fetcher=fetch,probe=lambda _:(picture,'image/jpeg'))['image_url']==picture
    for invalid in [picture+'?x=1',picture+'#x',picture.replace('images.locable.com','images.locable.com.other.example'),
                    picture.replace('https://','https://user@'),picture.replace('.com/','.com:443/'),
                    picture.replace('/abcdef','/../abcdef')]:
        assert image_url(invalid,'clarksville_tourism') is None
    fetch.assert_not_called()
