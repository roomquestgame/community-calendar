"""Inactive version-2 binding to the sealed, lease-fenced Feedzilla contract.

No production claim negotiates this capability yet. The backend must finish
native staging and publication integration before enabling it. A successful
verification proves staged membership, not a completed preview or public event.
"""
from hashlib import md5
from time import monotonic
from roomquest import spektrix_capture_runner as runner
from roomquest.publisher_pacing import pacing_rpc_fields

READ = 'community_collector_feedzilla_capture_read'
WRITE = 'community_collector_feedzilla_capture_write'
SEAL = 'community_collector_feedzilla_capture_seal'
STAGE = 'community_collector_feedzilla_capture_stage'
NOTE_WAIT = 'community_collector_feedzilla_capture_note_wait'
YIELD = 'community_collector_feedzilla_capture_yield'
VERIFY = 'community_collector_feedzilla_capture_verify'


def _error(reason):
    raise ValueError('spektrix_runner_' + reason)


def run_claimed_capture(source, profile, *, collection_context, rpc, fetch_publisher,
                        convert, pacing, deadline_at, clock=None,
                        monotonic_clock=monotonic, max_steps=runner.MAX_STEPS):
    """Resume an exact, negotiated claim; yield or independently verify.

    The caller supplies the existing robots-aware publisher transport, scoped
    RPC function, and current capture_publisher_pacing state. Never claim
    source approval, preview completion or publication from this function.
    """
    if (not isinstance(source, dict) or source.get('action') != 'collect'
            or type(source.get('feedzilla_capture_version')) is not int
            or source['feedzilla_capture_version'] != 2
            or not isinstance(source.get('feed_url'), str)
            or source.get('source_key') != 'municipal_' + md5(
                ('feed_registration:' + source['feed_url']).encode()).hexdigest()[:24]
            or not isinstance(collection_context, dict)
            or collection_context.get('p_category') not in ('html', 'jsonld')
            or not isinstance(collection_context.get('p_ticket'), str)
            or not collection_context['p_ticket']
            or not isinstance(pacing, dict)
            or set(pacing) != {'crawl_delay_seconds', 'retry_after_seconds', 'wait_unbounded'}
            or any(type(pacing[k]) is not int or not 0 <= pacing[k] <= 86400
                   for k in ('crawl_delay_seconds', 'retry_after_seconds'))
            or type(pacing['wait_unbounded']) is not bool):
        _error('claim_required')
    if deadline_at is None or monotonic_clock() >= deadline_at - 12:
        _error('deadline')
    scope = {'p_category': collection_context['p_category'],
             'p_ticket': collection_context['p_ticket'],
             'p_source_key': source['source_key']}
    unsaved_fetch = False

    def wait_fields():
        return pacing_rpc_fields(pacing)

    def read():
        return rpc(READ, scope.copy(), timeout=8)

    def write(revision, envelope):
        nonlocal unsaved_fetch
        result = rpc(WRITE, {**scope, 'p_expected_revision': revision,
                            'p_checkpoint': envelope, **wait_fields()}, timeout=8)
        if (isinstance(result, dict) and result.get('checkpoint_saved') is True
                and type(result.get('revision')) is int
                and result['revision'] == revision + 1):
            unsaved_fetch = False
        return result

    def seal(revision, previous, updated, receipts, members):
        return rpc(SEAL, {**scope, 'p_expected_revision': revision,
                          'p_previous_sha256': previous['sha256'],
                          'p_checkpoint': updated, 'p_fetch_receipts': receipts,
                          'p_members': members}, timeout=8)

    def stage(revision, previous, updated, rows):
        return rpc(STAGE, {**scope, 'p_expected_revision': revision,
                           'p_previous_sha256': previous['sha256'],
                           'p_checkpoint': updated, 'p_events': rows}, timeout=8)

    def fetch(url, accept):
        nonlocal unsaved_fetch
        unsaved_fetch = True
        return fetch_publisher(url, accept, respect_robots=True,
                               allowed_hosts=(runner.HOST,), follow_redirects=False,
                               deadline_at=deadline_at - 10)

    kwargs = {'clock': clock} if clock is not None else {}
    try:
        result = runner.run_slice(
            source, profile, read=read, write=write, fetch=fetch,
            convert=convert, seal=seal, stage_and_save=stage,
            can_continue=lambda: (not pacing['wait_unbounded']
                                  and monotonic_clock() < deadline_at - 12),
            max_steps=max_steps, **kwargs)
    except Exception:
        if unsaved_fetch:
            receipt = rpc(NOTE_WAIT, {**scope, **wait_fields()}, timeout=5)
            if not isinstance(receipt, dict) or receipt.get('pacing_saved') is not True:
                _error('pacing_receipt_invalid')
        raise

    current = {**scope, 'p_expected_revision': result['revision'],
               'p_checkpoint_sha256': result['checkpoint_sha256']}
    if result['status'] == 'pending':
        receipt = rpc(YIELD, {**current, **wait_fields()}, timeout=5)
        if (not isinstance(receipt, dict) or receipt.get('released') is not True
                or receipt.get('status') not in ('pending', 'review')
                or type(receipt.get('revision')) is not int
                or receipt['revision'] != result['revision']):
            _error('yield_receipt_invalid')
        return {**result, 'status': receipt['status'], 'lease_released': True}
    receipt = rpc(VERIFY, current, timeout=8)
    if (not isinstance(receipt, dict) or receipt.get('verified') is not True
            or any(type(receipt.get(k)) is not int for k in
                   ('revision', 'expected_count', 'staged_count', 'venue_count'))
            or receipt['revision'] != result['revision']
            or receipt['expected_count'] != result['record_count']
            or receipt['staged_count'] != result['record_count']
            or not 0 <= receipt['venue_count'] <= result['record_count']):
        _error('verification_receipt_invalid')
    return {**result, 'status': 'verified', 'lease_released': False,
            'venue_count': receipt['venue_count']}
