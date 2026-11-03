"""Independent demand lanes. Credentials and one-use tickets stay server-side."""
from time import monotonic
from roomquest.preview_worker import PreviewError, supabase_rpc, _process_claimed_source

CATEGORIES = frozenset(('ical', 'wordpress', 'jsonld', 'squarespace', 'library',
                        'rss', 'localist', 'socrata', 'chambermaster', 'chambermate', 'parks', 'html'))


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
    try:
        if source['action'] == 'collect':
            result.update(_process_claimed_source(source, deadline_at=started + 39))
            if result['failed']:
                return result
        # A source-bound ten-row publication call, with a shared database cap.
        # Remaining rows retain their checkpoint and dispatch a continuation.
        published = supabase_rpc('community_collector_publish_category', args, timeout=12)
        result['publication'] = published
        outcome = 'busy' if published.get('outcome') in ('busy', 'idle') else 'complete'
        return result
    finally:
        supabase_rpc('community_collector_finish_category', {**args, 'p_outcome': outcome}, timeout=5)
