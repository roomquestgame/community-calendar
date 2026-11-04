"""Independent demand lanes. Credentials and one-use tickets stay server-side."""
from time import monotonic, sleep
from roomquest.preview_worker import PreviewError, supabase_rpc, _process_claimed_source

CATEGORIES = frozenset(('ical', 'wordpress', 'jsonld', 'squarespace', 'library',
                        'rss', 'localist', 'socrata', 'chambermaster', 'chambermate', 'parks', 'html'))

MAX_HANDOFF_WAIT_SECONDS = 2
FINISH_TIMEOUT_SECONDS = 5
# api/html_demand.py and api/category_demand.py both have maxDuration=60.
# Preserve additional time for response handling and invocation overhead.
INVOCATION_BUDGET_SECONDS = 60
FINISH_MARGIN_SECONDS = 3


def _wait_for_html_handoff(handoff, started):
    ready_at = handoff.get('ready_at')
    if ready_at is None:
        return
    remaining = ready_at - monotonic()
    if (0 < remaining <= MAX_HANDOFF_WAIT_SECONDS
            and ready_at + FINISH_TIMEOUT_SECONDS + FINISH_MARGIN_SECONDS
            <= started + INVOCATION_BUDGET_SECONDS):
        # Keep the existing host lease for a short wait outside any database
        # transaction. Longer waits still use the normal recovery mechanism.
        sleep(remaining)


def collect_category(category, ticket):
    if category not in CATEGORIES:
        raise PreviewError('unsupported_category')
    args = {'p_category': category, 'p_ticket': ticket}
    started = monotonic()
    source = supabase_rpc('community_collector_claim_category', args, timeout=8)
    if not source:
        supabase_rpc('community_collector_finish_category', {**args, 'p_outcome': 'idle'}, timeout=5)
        return {'outcome': 'idle'}
    outcome = 'failed'
    result = {'category': category, 'claimed': 1}
    publisher_handoff = {}
    try:
        if source['action'] == 'collect':
            process_args = {'deadline_at': started + 39}
            if category == 'html':
                process_args['publisher_handoff'] = publisher_handoff
            result.update(_process_claimed_source(source, **process_args))
            if result['failed']:
                if category == 'html' and result.get('failure_scope') == 'source':
                    # The recorded source hold/retry owns its next attempt.
                    # Release this HTML slot without cooling other publishers.
                    outcome = 'source_error'
                return result
        # A source-bound ten-row publication call, with a shared database cap.
        # Remaining rows retain their checkpoint and dispatch a continuation.
        published = supabase_rpc('community_collector_publish_category', args, timeout=12)
        result['publication'] = published
        outcome = 'busy' if published.get('outcome') in ('busy', 'idle') else 'complete'
        return result
    finally:
        try:
            if category == 'html' and outcome in ('complete', 'source_error'):
                _wait_for_html_handoff(publisher_handoff, started)
        finally:
            # Finish exactly once even if the local wait is interrupted.
            supabase_rpc('community_collector_finish_category',
                         {**args, 'p_outcome': outcome}, timeout=FINISH_TIMEOUT_SECONDS)
