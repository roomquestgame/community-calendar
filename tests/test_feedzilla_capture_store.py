"""Fetch-only capture evidence; downstream staging is never in this store."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pytest
from roomquest import feedzilla_capture_store as store
from roomquest import national_feed_checkpoint as codec

STAMP=datetime(2026,11,24,12,0,tzinfo=timezone.utc)
CONTEXT='a'*64
API='https://system.spektrix.com/thealbany/api/v3/events'
TWO='https://system.spektrix.com/thealbany/api/v3/instances'
SOURCE={'source_key':'municipal_001','feed_url':API,'platform_adapter':'spektrix'}
BODY='[{"id":"one","name":"A real event"}]'


def new():
    return store.new(SOURCE,[API,TWO],allowed_hosts=['system.spektrix.com'],
        start='2026-11-24',end='2027-01-22',context_hash=CONTEXT,at=STAMP)


def page(cp,url,body='[]',**kw):
    return store.acknowledge_page(SOURCE,cp,url,body,context_hash=CONTEXT,at=STAMP,**kw)


def decode(cp):
    return store.decode(SOURCE,cp,context_hash=CONTEXT,at=STAMP)


def ready(cp):
    return store.ready_to_project(SOURCE,cp,context_hash=CONTEXT,at=STAMP)


def test_partial_prefix_never_projects_and_terminal_has_no_stage_state():
    initial=new()
    assert not ready(initial)
    one=page(initial,API,BODY)
    assert decode(one)['progress']['cursor']==1
    assert not ready(one)
    two=page(one,TWO,terminal=True)
    assert ready(two)
    assert decode(two)['pages'][0]=={'url':API,'body':BODY}
    assert set(decode(two))=={'context_hash','progress','pages'}
    assert two['cursor']==two['manifest_count']==2
    assert not any(hasattr(store,name) for name in ('prepare_staging','acknowledge_stage','ready_to_publish'))


def test_empty_verified_calendar_is_not_partial():
    one=page(new(),API)
    assert not ready(one)
    assert ready(page(one,TWO,terminal=True))


def test_published_next_link_requires_scope_proof():
    nxt=TWO+'?page=2'
    with pytest.raises(ValueError):
        page(new(),API,BODY,next_link=nxt)
    one=page(new(),API,BODY,next_link=nxt,next_link_scope_verified=True)
    two=page(one,TWO)
    assert ready(page(two,nxt,terminal=True))


def test_tampering_or_source_and_context_substitution():
    initial=new()
    for wrong in (dict(SOURCE,source_key='municipal_other'),dict(SOURCE,platform_adapter='wordpress')):
        with pytest.raises(ValueError):
            store.decode(wrong,initial,context_hash=CONTEXT,at=STAMP)
    with pytest.raises(ValueError):
        store.decode(SOURCE,initial,context_hash='b'*64,at=STAMP)
    with pytest.raises(ValueError):
        decode(dict(initial,payload=initial['payload'][:-1]+'!'))
    with pytest.raises(ValueError,match='checksum'):
        decode(dict(initial,sha256='f'*64))
    with pytest.raises(ValueError,match='identity_changed'):
        decode(dict(initial,cursor=1))


def test_page_receipt_must_match_actual_bounded_body():
    state=decode(page(new(),API,BODY))
    state['pages'][0]['body']='[]'
    with pytest.raises(ValueError,match='receipt_invalid'):
        store.encode(SOURCE,state,context_hash=CONTEXT,at=STAMP)


def test_expired_checkpoint_is_rejected():
    with pytest.raises(ValueError):
        store.decode(SOURCE,new(),context_hash=CONTEXT,at=STAMP+timedelta(hours=4,seconds=1))


def test_wrong_endpoint_and_premature_terminal_rejected():
    with pytest.raises(ValueError):
        page(new(),TWO)
    with pytest.raises(ValueError):
        page(new(),API,terminal=True)


def test_old_stage_payload_not_accepted():
    state=decode(new())
    state['records']=[]
    with pytest.raises(ValueError):
        store.encode(SOURCE,state,context_hash=CONTEXT,at=STAMP)
