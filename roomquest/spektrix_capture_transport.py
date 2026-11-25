"""Inactive adapter from a negotiated claim to the dedicated Feedzilla RPCs.

No dispatcher invokes this module yet. The backend must independently issue
the capability only after category routing, pacing, and final membership
gates exist. Neither this adapter nor the runner can finish/publish a claim.
"""
from hashlib import md5
from time import monotonic
from roomquest import spektrix_capture_runner as runner

READ = 'community_collector_feedzilla_capture_read'
WRITE = 'community_collector_feedzilla_capture_write'
STAGE = 'community_collector_feedzilla_capture_stage'


def run_claimed_capture(source, profile, *, collection_context, rpc, fetch_publisher,
                        convert, deadline_at, clock=None, monotonic_clock=monotonic,
                        max_steps=runner.MAX_STEPS):
    """Connect the pure runner to the exact, lease-fenced RPC contract.

    The passed rpc/fetch functions are the normal guarded preview_worker
    transports. A dedicated backend claim must negotiate version 1; nothing
    here supplies/activates a provider profile or alters publisher pacing.
    """
    if (not isinstance(source, dict) or source.get('action') != 'collect'
            or type(source.get('feedzilla_capture_version')) is not int
            or source['feedzilla_capture_version'] != 1
            or not isinstance(source.get('feed_url'), str)
            or source.get('source_key') != 'municipal_' + md5(
                ('feed_registration:' + source['feed_url']).encode()).hexdigest()[:24]
            or not isinstance(collection_context, dict)
            or collection_context.get('p_category') not in ('html', 'jsonld')
            or not isinstance(collection_context.get('p_ticket'), str)
            or not collection_context['p_ticket']):
        raise ValueError('spektrix_runner_claim_required')
    if deadline_at is None or monotonic_clock() >= deadline_at - 12:
        raise ValueError('spektrix_runner_deadline')
    scope = {'p_category': collection_context['p_category'],
             'p_ticket': collection_context['p_ticket'],
             'p_source_key': source['source_key']}

    def read():
        return rpc(READ, scope.copy(), timeout=8)

    def write(revision, envelope):
        return rpc(WRITE, {**scope, 'p_expected_revision': revision,
                          'p_checkpoint': envelope}, timeout=8)

    def stage(revision, previous, updated, rows):
        return rpc(STAGE, {**scope, 'p_expected_revision': revision,
                          'p_previous_sha256': previous['sha256'],
                          'p_checkpoint': updated, 'p_events': rows}, timeout=8)

    def fetch(url, accept):
        return fetch_publisher(url, accept, respect_robots=True,
                               allowed_hosts=(runner.host(profile),), follow_redirects=False,
                               deadline_at=deadline_at - 10)

    kwargs = {'clock': clock} if clock is not None else {}
    return runner.run_slice(source, profile, read=read, write=write, fetch=fetch,
                            convert=convert, stage_and_save=stage,
                            can_continue=lambda: monotonic_clock() < deadline_at - 12,
                            max_steps=max_steps, **kwargs)
