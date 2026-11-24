"""Source-bound compressed multi-run evidence has no partial publication path."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from roomquest import feedzilla_capture_store as store

STAMP=datetime(2026,11,24,12,0,tzinfo=timezone.utc)
API='https://system.spektrix.com/thealbany/api/v3/events'
TWO='https://system.spektrix.com/thealbany/api/v3/instances'
THREE='https://system.spektrix.com/thealbany/api/v3/venues'
SOURCE={'source_key':'municipal_001','feed_url':API,'platform_adapter':'spektrix'}
BODY='[{"id":"one","name":"A real event"}]'
RECORD={'id':'spektrix:one','starts_at':'2026-12-02T20:00:00+00:00',
        'event_url':'https://www.thealbany.org.uk/events/a-real-event'}


def new():
    return store.new(SOURCE,[API,TWO],
        allowed_hosts=['system.spektrix.com'],start='2026-11-24',
        end='2027-01-22',at=STAMP)


def test_one_request_cannot_publish_partial_calendar():
    initial=new()
    assert not store.ready_to_publish(SOURCE,initial,at=STAMP)
    one=store.acknowledge_page(SOURCE,initial,API,BODY,at=STAMP)
    assert store.decode(SOURCE,one,at=STAMP)['progress']['cursor']==1
    assert not store.ready_to_publish(SOURCE,one,at=STAMP)
    with pytest.raises(ValueError,match='feedzilla_capture_stage_not_ready'):
        store.prepare_staging(SOURCE,one,[RECORD],at=STAMP)


def test_two_resumable_pages_then_stage_ack_permit_completion():
    first=new()
    one=store.acknowledge_page(SOURCE,first,API,BODY,at=STAMP)
    two=store.acknowledge_page(SOURCE,one,TWO,'[]',terminal=True,at=STAMP)
    state=store.decode(SOURCE,two,at=STAMP)
    assert state['phase']=='project'
    assert state['pages'][0]=={'url':API,'body':BODY}
    assert state['progress']['terminal_verified'] is True
    staged=store.prepare_staging(SOURCE,two,[RECORD],at=STAMP)
    assert not store.ready_to_publish(SOURCE,staged,at=STAMP)
    complete=store.acknowledge_stage(SOURCE,staged,1,at=STAMP)
    assert store.ready_to_publish(SOURCE,complete,at=STAMP)
    assert store.decode(SOURCE,complete,at=STAMP)['stage_cursor']==1


def test_acknowledged_records_must_be_contiguous_and_bounded():
    one=store.acknowledge_page(SOURCE,new(),API,BODY,at=STAMP)
    two=store.acknowledge_page(SOURCE,one,TWO,'[]',terminal=True,at=STAMP)
    stage=store.prepare_staging(SOURCE,two,[RECORD]*21,at=STAMP)
    with pytest.raises(ValueError,match='feedzilla_capture_stage_receipt_invalid'):
        store.acknowledge_stage(SOURCE,stage,21,at=STAMP)
    with pytest.raises(ValueError,match='feedzilla_capture_stage_receipt_invalid'):
        store.acknowledge_stage(SOURCE,stage,0,at=STAMP)
    advanced=store.acknowledge_stage(SOURCE,stage,20,at=STAMP)
    assert not store.ready_to_publish(SOURCE,advanced,at=STAMP)
    finished=store.acknowledge_stage(SOURCE,advanced,1,at=STAMP)
    assert store.ready_to_publish(SOURCE,finished,at=STAMP)


def test_empty_verified_calendar_can_complete_but_not_before_last_page():
    one=store.acknowledge_page(SOURCE,new(),API,'[]',at=STAMP)
    two=store.acknowledge_page(SOURCE,one,TWO,'[]',terminal=True,at=STAMP)
    complete=store.prepare_staging(SOURCE,two,[],at=STAMP)
    assert store.ready_to_publish(SOURCE,complete,at=STAMP)


def test_published_next_link_requires_explicit_scope_proof():
    nxt='https://system.spektrix.com/thealbany/api/v3/instances?page=2'
    with pytest.raises(ValueError):
        store.acknowledge_page(SOURCE,new(),API,BODY,
                               next_link=nxt,at=STAMP)
    one=store.acknowledge_page(SOURCE,new(),API,BODY,
                              next_link=nxt,next_link_scope_verified=True,at=STAMP)
    two=store.acknowledge_page(SOURCE,one,TWO,'[]',at=STAMP)
    last=store.acknowledge_page(SOURCE,two,nxt,'[]',terminal=True,at=STAMP)
    assert store.decode(SOURCE,last,at=STAMP)['phase']=='project'


def test_tampering_or_source_substitution_is_detected():
    initial=new()
    wrong=dict(SOURCE, source_key='municipal_other')
    with pytest.raises(ValueError,match='feedzilla_capture_invalid'):
        store.decode(wrong,initial,at=STAMP)
    wrong=dict(SOURCE, platform_adapter='wordpress')
    with pytest.raises(ValueError,match='feedzilla_capture_invalid'):
        store.decode(wrong,initial,at=STAMP)
    forged=dict(initial,payload=initial['payload'][:-1]+'!')
    with pytest.raises(ValueError,match='feedzilla_capture_invalid'):
        store.decode(SOURCE,forged,at=STAMP)
    forged=dict(initial,sha256='f'*64)
    with pytest.raises(ValueError,match='feedzilla_capture_checksum'):
        store.decode(SOURCE,forged,at=STAMP)


def test_fetched_content_hash_must_match_a_bounded_original_page():
    first=new()
    one=store.acknowledge_page(SOURCE,first,API,BODY,at=STAMP)
    state=store.decode(SOURCE,one,at=STAMP)
    forged=deepcopy(state)
    forged['pages'][0]['body']='[]'
    with pytest.raises(ValueError,match='feedzilla_capture_receipt_invalid'):
        store.encode(SOURCE,forged,at=STAMP)


def test_expired_checkpoint_is_rejected_without_replay():
    old=new()
    with pytest.raises(ValueError):
        store.decode(SOURCE,old,at=STAMP+timedelta(hours=4,seconds=1))


def test_claim_cannot_ack_wrong_endpoint_or_premature_terminal():
    with pytest.raises(ValueError):
        store.acknowledge_page(SOURCE,new(),TWO,BODY,at=STAMP)
    with pytest.raises(ValueError):
        store.acknowledge_page(SOURCE,new(),API,BODY,terminal=True,at=STAMP)


def test_missing_stage_evidence_refused():
    one=store.acknowledge_page(SOURCE,new(),API,BODY,at=STAMP)
    two=store.acknowledge_page(SOURCE,one,TWO,'[]',terminal=True,at=STAMP)
    with pytest.raises(ValueError,match='feedzilla_capture_records_invalid'):
        store.prepare_staging(SOURCE,two,[{'id':'x'}],at=STAMP)
