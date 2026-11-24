"""Checkpoint-only tests; no publisher network access or source admission."""
from datetime import datetime, timedelta, timezone
import hashlib

import pytest

from roomquest import feedzilla_pagination_checkpoint as cp

URL = 'https://www.thealbany.org.uk/events'
API = 'https://system.spektrix.com/thealbany/api/v3'
PAGES = [
    API + '/events?instanceStart_from=2026-11-24&instanceStart_to=2026-11-30',
    API + '/instances?startFrom=2026-11-24&startTo=2026-11-30',
]
STAMP = datetime(2026, 11, 24, 8, 0, tzinfo=timezone.utc)
HASH = hashlib.sha256(b'a verified publisher response').hexdigest()


def start(adapter='spektrix'):
    return cp.new('municipal_001', URL, adapter, PAGES,
                  allowed_hosts=['www.thealbany.org.uk', 'system.spektrix.com'],
                  start='2026-11-24', end='2027-01-22', at=STAMP)


def test_incomplete_page_prefix_never_certifies_an_event_snapshot():
    state = start()
    assert cp.next_request(state, at=STAMP) == PAGES[0]
    assert not cp.complete(state, at=STAMP)
    one = cp.advance(state, PAGES[0], HASH, at=STAMP)
    assert one['cursor'] == 1
    assert cp.next_request(one, at=STAMP) == PAGES[1]
    assert not cp.complete(one, at=STAMP)
    assert state['cursor'] == 0  # immutable snapshot update
    two = cp.advance(one, PAGES[1], HASH, terminal=True, at=STAMP)
    assert cp.next_request(two, at=STAMP) is None
    assert cp.complete(two, at=STAMP)
    assert two['receipts'] == [
        {'url': PAGES[0], 'sha256': HASH},
        {'url': PAGES[1], 'sha256': HASH},
    ]


def test_publisher_verified_next_link_can_extend_without_guessing():
    s = start('html')
    next_url = 'https://www.thealbany.org.uk/events?page=2'
    a = cp.advance(s, PAGES[0], HASH, next_link=next_url,
                   next_link_scope_verified=True, at=STAMP)
    assert a['tasks'][-1] == next_url
    assert not cp.complete(a, at=STAMP)
    b = cp.advance(a, PAGES[1], HASH, at=STAMP)
    c = cp.advance(b, next_url, HASH, terminal=True, at=STAMP)
    assert cp.complete(c, at=STAMP)


@pytest.mark.parametrize('data', [
    {'request_url': PAGES[1], 'payload_hash': HASH},
    {'request_url': PAGES[0], 'payload_hash': 'not-sha'},
    {'request_url': PAGES[0], 'payload_hash': HASH, 'terminal': True},
    {'request_url': PAGES[0], 'payload_hash': HASH,
     'next_link': 'https://attacker.org/next', 'next_link_scope_verified': True},
    {'request_url': PAGES[0], 'payload_hash': HASH,
     'next_link': 'https://www.thealbany.org.uk/events?page=2',
     'next_link_scope_verified': False},
    {'request_url': PAGES[0], 'payload_hash': HASH,
     'next_link': PAGES[0], 'next_link_scope_verified': True},
])
def test_wrong_cursor_or_provenance_cannot_move_forward(data):
    with pytest.raises(ValueError, match='feedzilla_checkpoint_invalid'):
        cp.advance(start(), at=STAMP, **data)


def test_resume_rejects_other_source_other_adapter_and_modified_plan():
    s = start()
    assert cp.validate(s, source_key='municipal_001',
                       feed_url=URL, adapter='spektrix', at=STAMP) is s
    for key in ('source_key', 'feed_url', 'adapter', 'plan_sha256', 'window_end'):
        modified = dict(s, **{key: 'bad'})
        with pytest.raises(ValueError, match='feedzilla_checkpoint_invalid'):
            cp.validate(modified, at=STAMP)
    with pytest.raises(ValueError, match='feedzilla_checkpoint_invalid'):
        cp.validate(s, source_key='municipal_002', at=STAMP)


def test_expired_progress_cannot_be_revived_or_published():
    s = start()
    later = STAMP + timedelta(hours=4, seconds=1)
    with pytest.raises(ValueError, match='feedzilla_checkpoint_invalid'):
        cp.validate(s, at=later)
    with pytest.raises(ValueError, match='feedzilla_checkpoint_invalid'):
        cp.advance(s, PAGES[0], HASH, at=later)


def test_reorder_repeat_and_external_endpoints_fail_creation():
    for tasks in ([PAGES[0], PAGES[0]], ['https://attacker.org/events'], []):
        with pytest.raises(ValueError, match='feedzilla_checkpoint_invalid'):
            cp.new('municipal_001', URL, 'wix', tasks,
                   allowed_hosts=['www.thealbany.org.uk', 'system.spektrix.com'],
                   start='2026-11-24', end='2027-01-22', at=STAMP)
    with pytest.raises(ValueError, match='feedzilla_checkpoint_invalid'):
        cp.new('municipal_001', URL, 'wix', PAGES,
               allowed_hosts=['www.thealbany.org.uk', 'system.spektrix.com'],
               start='2026-11-24', end='2027-01-23', at=STAMP)


def test_mutating_receipt_or_adding_an_unacknowledged_prefix_is_detected():
    s = start()
    one = cp.advance(s, PAGES[0], HASH, at=STAMP)
    damaged = dict(one, receipts=[{'url': PAGES[1], 'sha256': HASH}])
    with pytest.raises(ValueError, match='feedzilla_checkpoint_invalid'):
        cp.validate(damaged, at=STAMP)
    damaged = dict(one, terminal_verified=True)
    with pytest.raises(ValueError, match='feedzilla_checkpoint_invalid'):
        cp.validate(damaged, at=STAMP)
