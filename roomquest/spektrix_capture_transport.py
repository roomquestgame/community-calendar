"""Future admission bridge to the EXISTING shared fetch checkpoint RPCs.

No live claim advertises the required fetch-only v2 capability. The eventual
ordinary dispatcher must pass its existing current Snapshot and use the
standard preview/stage/complete/finish pipeline. No Feedzilla-only RPCs.
"""
from hashlib import md5
from time import monotonic
from roomquest import spektrix_capture_runner as runner
from roomquest.incremental_snapshot import Snapshot, current_snapshot
from roomquest.publisher_pacing import pacing_rpc_fields

READ = 'community_collector_read_fetch_checkpoint'
WRITE = 'community_collector_write_fetch_checkpoint'


def preview(source, profile, *, collection_context, rpc, fetch_publisher,
            convert, pacing, deadline_at, clock=None,
            monotonic_clock=monotonic, max_steps=runner.MAX_STEPS):
    snapshot = current_snapshot()
    if (not isinstance(source, dict) or source.get('action') != 'collect'
            or type(source.get('fetch_checkpoint_version')) is not int
            or source['fetch_checkpoint_version'] != 2
            or source.get('kind') != 'json'
            or source.get('platform_adapter') != 'spektrix'
            or not isinstance(source.get('feed_url'), str)
            or source.get('source_key') != 'municipal_' + md5(
                ('feed_registration:' + source['feed_url']).encode()).hexdigest()[:24]
            or not isinstance(collection_context, dict)
            or collection_context.get('p_category') != 'jsonld'
            or not isinstance(collection_context.get('p_ticket'), str)
            or not collection_context['p_ticket']
            or not isinstance(snapshot, Snapshot)
            or snapshot.source_key != source['source_key']
            or snapshot.collection_context != collection_context):
        raise ValueError('spektrix_runner_shared_claim_required')
    if deadline_at is None or monotonic_clock() >= deadline_at - 12:
        raise ValueError('spektrix_runner_deadline')
    scope = {**collection_context, 'p_source_key': source['source_key']}

    def read():
        return rpc(READ, scope.copy(), timeout=8)

    def write(revision, envelope):
        if pacing['wait_unbounded']:
            raise ValueError('publisher_wait_requires_review')
        return rpc(WRITE, {**scope, 'p_expected_revision': revision,
                           'p_checkpoint': envelope, **pacing_rpc_fields(pacing)}, timeout=8)

    def fetch(url, accept):
        return fetch_publisher(url, accept, respect_robots=True,
                               allowed_hosts=(runner.HOST,), follow_redirects=False,
                               deadline_at=deadline_at - 12)

    kwargs = {'clock': clock} if clock is not None else {}
    # Reserve existing completion time. The common worker owns staging and
    # its ordinary retry/failure recording; no separate lease release.
    return runner.run_slice(
        source, profile, snapshot=snapshot, read=read, write=write, fetch=fetch,
        convert=convert, can_continue=lambda: (
            not pacing['wait_unbounded'] and monotonic_clock() < deadline_at - 12),
        max_steps=max_steps, **kwargs)
