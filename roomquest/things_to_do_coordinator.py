"""One scheduled tick: requested pages first, then bounded discovery planning."""
import os
from time import monotonic

from roomquest.preview_worker import supabase_rpc
from roomquest.things_to_do_search import run_search
from roomquest.things_to_do_worker import run_batch


def discovery_rpc(action, payload):
    return supabase_rpc('community_collector_activity_discovery',
                        {'p_action': action, 'p_payload': payload}, timeout=4)


def run_tick(*, database=None, page_worker=None, search=None, clock=None, key=None):
    if database is None and os.environ.get('VERCEL_ENV') != 'production':
        return {'status': 'disabled_environment'}
    clock = clock or monotonic
    started = clock()
    result = (page_worker or run_batch)()
    # The last known good route remains authoritative while the additive backend
    # is unavailable, disabled, under pressure, or servicing requested evidence.
    if result.get('status') not in ('idle', 'expired', 'disabled') or clock()-started > 3:
        return result
    database = database or discovery_rpc
    try:
        plan = database('plan', {})
        if plan.get('status') in ('paused_load', 'paused_telemetry', 'busy', 'backpressure'):
            return result
        benchmark_only = plan.get('status') in ('disabled', 'expired')
        admission = {'status': 'disabled'} if benchmark_only else database('admit', {})
        if admission.get('status') == 'admitted':
            return (page_worker or run_batch)()  # admission already committed; fetch now
        if clock()-started > 8:
            return {'status': 'planning_deadline'}
        job = database('next_search', {'planner': 'benchmark'} if benchmark_only else {})
        if job.get('status') != 'ready':
            if benchmark_only:
                return result
            return {'status': 'planned', 'search': job.get('status', 'unavailable')}
        return (search or run_search)(key=key if key is not None else os.environ.get('TAVILY_API_KEY', ''),
                                      job=job, database=database)
    except Exception:
        return {'status': 'discovery_unavailable'}
