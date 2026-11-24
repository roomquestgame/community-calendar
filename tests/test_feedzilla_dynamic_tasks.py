"""Dynamic later-phase Spektrix plan pages must remain publisher verified."""
from datetime import datetime, timezone
import pytest
from roomquest import feedzilla_capture_store as capture
from roomquest import feedzilla_pagination_checkpoint as pagination

STAMP=datetime(2026,11,24,12,0,tzinfo=timezone.utc)
API='https://system.spektrix.com/thealbany/api/v3/events'
INSTANCES='https://system.spektrix.com/thealbany/api/v3/instances'
PLAN='https://system.spektrix.com/thealbany/api/v3/plans/13006AMVKCPJNKCQLHCRCQLLGRLHHPSLL'
SOURCE={'source_key':'municipal_001','feed_url':API,'platform_adapter':'spektrix'}


def start():
    return capture.new(SOURCE,[API,INSTANCES],allowed_hosts=['system.spektrix.com'],
      start='2026-11-24',end='2027-01-22',at=STAMP)


def after_two_pages():
    first=capture.acknowledge_page(SOURCE,start(),API,'[]',at=STAMP)
    return capture.acknowledge_page(SOURCE,first,INSTANCES,'[]',at=STAMP)


def test_verified_plan_pages_can_extend_a_complete_fetch_prefix():
    pending=after_two_pages()
    state=capture.decode(SOURCE,pending,at=STAMP)
    assert state['progress']['cursor']==2
    assert state['progress']['terminal_verified'] is False
    old_plan=state['progress']['plan_sha256']
    extended=capture.add_verified_requests(SOURCE,pending,[PLAN],
                                          scope_verified=True,at=STAMP)
    state=capture.decode(SOURCE,extended,at=STAMP)
    assert state['progress']['cursor']==2
    assert state['progress']['tasks'][-1]==PLAN
    assert state['progress']['plan_sha256']!=old_plan
    assert len(state['pages'])==2
    ended=capture.acknowledge_page(SOURCE,extended,PLAN,'{}',terminal=True,at=STAMP)
    assert capture.decode(SOURCE,ended,at=STAMP)['phase']=='project'


@pytest.mark.parametrize('url',[API,INSTANCES,'https://wrong.example.org/page'])
def test_duplicate_and_foreign_plan_requests_fail_closed(url):
    with pytest.raises(ValueError,match='feedzilla_checkpoint_invalid'):
        capture.add_verified_requests(SOURCE,after_two_pages(),[url],
                                      scope_verified=True,at=STAMP)


def test_cannot_append_without_provider_evidence_or_before_base_completed():
    with pytest.raises(ValueError,match='feedzilla_checkpoint_invalid'):
        capture.add_verified_requests(SOURCE,after_two_pages(),[PLAN],
                                      scope_verified=False,at=STAMP)
    with pytest.raises(ValueError,match='feedzilla_checkpoint_invalid'):
        capture.add_verified_requests(SOURCE,start(),[PLAN],
                                      scope_verified=True,at=STAMP)


def test_multiple_verified_request_ids_reject_duplicates():
    with pytest.raises(ValueError,match='feedzilla_checkpoint_invalid'):
        capture.add_verified_requests(SOURCE,after_two_pages(),[PLAN,PLAN],
                                      scope_verified=True,at=STAMP)
