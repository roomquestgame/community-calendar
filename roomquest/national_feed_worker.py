"""Leased continuation for regional Wildlife feeds and shared OpenActive state.

Neither path certifies a partial fetch. OpenActive's retained raw item cache is
separate from transient staging and survives the normal 96-hour demand freshness.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import re
from time import monotonic

from roomquest import national_feed_checkpoint as snapshot
from roomquest import openactive, wildlife_trusts
from roomquest.publisher_pacing import pacing_rpc_fields

STATE_RPC = 'community_collector_openactive_state'


def handles(source):
    return bool(openactive.profile(source.get('feed_url'))
                or source.get('feed_url') in wildlife_trusts.URLS
                or source.get('feed_url') in wildlife_trusts.CATALOG_URLS)


def _saved(value):
    if (not isinstance(value, dict) or set(value) != {'revision', 'checkpoint'}
            or type(value['revision']) is not int or value['revision'] < 0
            or value['checkpoint'] is not None and not isinstance(value['checkpoint'], dict)
            or value['checkpoint'] is None and value['revision'] != 0):
        raise ValueError('fetch_checkpoint_invalid_response')
    return value['revision'], value['checkpoint']


def _ack(value, revision):
    if (not isinstance(value, dict) or value.get('checkpoint_saved') is not True
            or type(value.get('revision')) is not int or value['revision'] != revision + 1):
        raise ValueError('fetch_checkpoint_invalid_response')
    return value['revision']


def _samples(rows):
    result = deepcopy(rows[:8])
    while result and len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > 18000:
        result.pop()
    return result


def process(source, pacing, *, collection_context, deadline_at=None,
            publisher_handoff=None, observe_phase=None):
    from roomquest import preview_worker as worker
    from roomquest.collector_errors import failure_details
    from roomquest.registered_native_content import VERSION

    deadline = min(monotonic() + 43, deadline_at or float('inf'))
    is_openactive = bool(openactive.profile(source.get('feed_url')))
    category = 'jsonld' if is_openactive else 'html'
    native = (type(source.get('registered_native_content_version')) is int
              and source['registered_native_content_version'] == 1)
    operation = None
    staged = 0

    def observe(phase, op=None, error=None):
        worker._observe_collection_phase(observe_phase, phase, operation=op, error=error)

    def rpc(op, payload, phase='fetch'):
        nonlocal operation
        operation = op
        observe(phase, op)
        result = worker.supabase_rpc(op, payload)
        operation = None
        return result

    def finish_preview(records=None, checkpoint=None, error=None):
        if checkpoint is not None and is_openactive:
            samples = checkpoint['samples']
            count, venue_count = checkpoint['record_count'], checkpoint['venue_count']
        else:
            records = records or []
            samples, count = _samples(records), len(records)
            venue_count = sum(row.get('lat') is not None for row in records)
        if error:
            samples, count, venue_count = [], 0, 0
        rpc('community_collector_record_preview_v3' if native else 'community_collector_record_preview_v2', {
            'p_source_key': source['source_key'], 'p_samples': samples,
            'p_future_count': count, 'p_venue_count': venue_count, 'p_error': error,
            **({'p_parser_capability': VERSION} if native else {}), **pacing_rpc_fields(pacing)}, 'record')

    def stage(rows):
        nonlocal staged
        for batch in worker._event_batches(rows):
            if monotonic() > deadline - 10:
                # This page has no committed staging cursor yet. Idempotent
                # staging safely replays any acknowledged prefix on next lease.
                return False
            written = rpc('community_collector_record_staged_events', {
                'p_source_key': source['source_key'], 'p_events': batch,
                **({'p_registered_native_content_version': 1} if native else {})}, 'stage')
            if type(written) is not int or written != len(batch):
                raise worker.PreviewError('database_unavailable')
            staged += written
        return True

    try:
        if (not isinstance(collection_context, dict) or collection_context.get('p_category') != category
                or not isinstance(collection_context.get('p_ticket'), str) or not collection_context['p_ticket']):
            raise worker.PreviewError('fetch_checkpoint_context_missing')
        args = {'p_category': category, 'p_ticket': collection_context['p_ticket'],
                'p_source_key': source['source_key']}
        if is_openactive:
            openactive.validate_source(source)
            if not native:
                raise ValueError('registered_native_capability_required')
            revision, checkpoint = _saved(rpc(STATE_RPC, {**args, 'p_action': 'read'}))
            current = datetime.now(timezone.utc)
            if checkpoint is not None:
                try:
                    openactive.validate_checkpoint(source, checkpoint, now=current)
                except ValueError as exc:
                    if str(exc) != 'openactive_checkpoint_expired':
                        raise
                    # An expired first bootstrap resets; an expired delta keeps
                    # its acknowledged tails if still inside tombstone retention.
                    checkpoint = dict(checkpoint, phase='ready')
            reset = False
            if checkpoint is None or checkpoint['phase'] == 'ready':
                checkpoint, reset = openactive.new_checkpoint(source, now=current, previous=checkpoint)

            def save(items=(), *, reset=False):
                nonlocal revision
                if pacing['wait_unbounded']:
                    raise worker.PreviewError('publisher_wait_requires_review')
                openactive.validate_checkpoint(source, checkpoint, now=datetime.now(timezone.utc))
                revision = _ack(rpc(STATE_RPC, {**args, 'p_action': 'apply',
                    'p_expected_revision': revision, 'p_checkpoint': checkpoint,
                    'p_items': list(items), 'p_reset': reset, **pacing_rpc_fields(pacing)}), revision)

            if reset or revision == 0 or checkpoint['phase'] == 'fetch' and all(s['pages'] == 0 for s in checkpoint['streams']):
                save(reset=reset)
            if checkpoint['phase'] == 'fetch':
                for _ in range(4):
                    stream = next((s for s in checkpoint['streams'] if not s['complete']), None)
                    if stream is None:
                        break
                    if monotonic() > deadline - 14:
                        break
                    observe('fetch')
                    requested = stream['next']
                    payload = worker.fetch_publisher(requested, 'application/json', respect_robots=True,
                        deadline_at=deadline - 10, allowed_hosts=openactive.allowed_hosts(source['feed_url']))
                    previous = ((stream['last_modified'], stream['last_id'])
                                if stream['last_modified'] is not None else None)
                    page = openactive.parse_page(payload, requested, stream['url'], previous=previous,
                                                 license_url=stream['license'])
                    # Page items and their next cursor commit atomically. Keep
                    # room for the bounded header and ordinary RPC metadata;
                    # never split a page while advancing past an unsaved suffix.
                    if len(json.dumps(page['items'], ensure_ascii=False).encode()) > 2_850_000:
                        raise ValueError('openactive_page_size_limit')
                    stream.update(next=page['next'], complete=page['tail'], pages=stream['pages'] + 1,
                                  license=page['license'])
                    if page['position']:
                        stream['last_modified'], stream['last_id'] = page['position']
                    if all(s['complete'] for s in checkpoint['streams']):
                        checkpoint['phase'] = 'stage'
                    save(page['items'])
                if checkpoint['phase'] == 'fetch':
                    return {'complete': 0, 'failed': 0, 'staged': 0, 'fetch_pending': True}
            if checkpoint['phase'] == 'stage':
                for _ in range(6):
                    if monotonic() > deadline - 14:
                        return {'complete': 0, 'failed': 0, 'staged': staged, 'fetch_pending': True}
                    result = rpc(STATE_RPC, {**args, 'p_action': 'items', 'p_after': checkpoint['stage_after'], 'p_limit': 20}, 'stage')
                    if (not isinstance(result, dict) or not isinstance(result.get('items'), list)
                            or len(result['items']) > 20 or type(result.get('has_more')) is not bool):
                        raise worker.PreviewError('fetch_checkpoint_invalid_response')
                    items = result['items']
                    for item in items:
                        openactive.validate_item(source, item)
                    keys = [v.get('key') for v in items]
                    if (any(not isinstance(key, str) or not re.fullmatch('[0-9a-f]{64}', key) for key in keys)
                            or keys != sorted(set(keys))
                            or keys and checkpoint['stage_after'] and keys[0] <= checkpoint['stage_after']
                            or not items and result['has_more']):
                        raise worker.PreviewError('fetch_checkpoint_invalid_response')
                    references = sorted({ref for item in items if (ref := openactive.parent_identity(item))})
                    parents = {}
                    if references:
                        found = rpc(STATE_RPC, {**args, 'p_action': 'references', 'p_references': references}, 'stage')
                        if not isinstance(found, dict) or not isinstance(found.get('items'), list):
                            raise worker.PreviewError('fetch_checkpoint_invalid_response')
                        for parent in found['items']:
                            openactive.validate_item(source, parent)
                            if parent.get('identity') not in references or parent['identity'] in parents:
                                raise worker.PreviewError('fetch_checkpoint_invalid_response')
                            parents[parent['identity']] = parent
                    records, held = [], 0
                    for item in items:
                        rows, skips = openactive.project(source, item, parents)
                        for row in rows:
                            openactive.validate_native(row, source)
                        records.extend(rows)
                        held += skips
                    if not stage(records):
                        return {'complete': 0, 'failed': 0, 'staged': staged, 'fetch_pending': True}
                    checkpoint['stage_after'] = keys[-1] if keys else checkpoint['stage_after']
                    checkpoint['record_count'] += len(records)
                    checkpoint['venue_count'] += sum(row.get('lat') is not None for row in records)
                    checkpoint['held_count'] += held
                    checkpoint['samples'] = _samples(checkpoint['samples'] + records)
                    if not result['has_more']:
                        checkpoint['phase'] = 'complete'
                    save()
                    if checkpoint['phase'] == 'complete':
                        break
                if checkpoint['phase'] == 'stage':
                    return {'complete': 0, 'failed': 0, 'staged': staged, 'fetch_pending': True}
            if checkpoint['phase'] != 'complete':
                raise ValueError('openactive_checkpoint_invalid')
            # The backend success receipt atomically marks the retained capture
            # ready and records last_complete_at; errors leave it replayable.
            finish_preview(checkpoint=checkpoint)
        else:
            wildlife_trusts.validate_source(source)
            if type(source.get('fetch_checkpoint_version')) is not int or source['fetch_checkpoint_version'] != 1:
                raise ValueError('publisher_checkpoint_required')
            revision, checkpoint = _saved(rpc('community_collector_read_fetch_checkpoint', args))
            if checkpoint is not None:
                try:
                    snapshot.decode(source, checkpoint)
                except ValueError as exc:
                    if str(exc) != 'national_feed_checkpoint_expired':
                        raise
                    checkpoint = None
            result = wildlife_trusts.collect_chunk(source, lambda url, accept: worker.fetch_publisher(
                url, accept, respect_robots=True, deadline_at=deadline - 10,
                allowed_hosts=wildlife_trusts.allowed_hosts(source['feed_url'])),
                checkpoint=checkpoint, deadline_at=deadline - 10)
            checkpoint = result['checkpoint']

            def save_wildlife():
                nonlocal revision
                if pacing['wait_unbounded']:
                    raise worker.PreviewError('publisher_wait_requires_review')
                revision = _ack(rpc('community_collector_write_fetch_checkpoint', {
                    **args, 'p_expected_revision': revision, 'p_checkpoint': checkpoint,
                    **pacing_rpc_fields(pacing)}), revision)

            save_wildlife()
            if not result['complete']:
                return {'complete': 0, 'failed': 0, 'staged': 0, 'fetch_pending': True}
            records = result['events']
            if native:
                for row in records:
                    wildlife_trusts.validate_native(row, source)
            # Large regional calendars also stage in durable bounded batches.
            for batch in worker._event_batches(records[checkpoint['stage_cursor']:]):
                if not stage(batch):
                    return {'complete': 0, 'failed': 0, 'staged': staged, 'fetch_pending': True}
                checkpoint['stage_cursor'] += len(batch)
                save_wildlife()
            finish_preview(records=records)
        return {'complete': 1, 'failed': 0, 'staged': staged}
    except (ValueError, OSError, worker.PreviewError) as exc:
        if operation is not None or str(exc) in ('database_unavailable', 'fetch_checkpoint_context_missing', 'fetch_checkpoint_invalid_response'):
            raise
        code = str(exc)
        if not re.fullmatch(r'(?:openactive|wildlife|national_feed|national_catalog|registered_native|publisher|source|robots|collection|dns)_[a-z0-9_]{1,100}', code):
            code = 'national_feed_payload_invalid'
        observe('fetch', error=exc)
        finish_preview(error=code)
        return {'complete': 0, 'failed': 1, 'staged': 0,
                **failure_details(code, expected_source_error=True, phase='collection')}
    finally:
        if publisher_handoff is not None and not pacing['wait_unbounded']:
            publisher_handoff['ready_at'] = monotonic() + max(1, pacing['crawl_delay_seconds'], pacing['retry_after_seconds'])
