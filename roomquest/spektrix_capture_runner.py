"""Fetch-only Spektrix adapter for the existing incremental collector.

No staging, completion, publication, or separate event ledger. The adapter
returns the ordinary preview_source result only after a terminal, scoped
fetch manifest has been acknowledged by the shared checkpoint writer.
Production admission remains disabled.
"""
from datetime import datetime, timedelta, timezone
import json
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from roomquest import feedzilla_capture_store as store
from roomquest import spektrix_capture_plan as planner
from roomquest import spektrix_v3 as api
from roomquest.incremental_snapshot import MAX_EVENTS, Snapshot, fingerprint, utc_start

HOST = 'system.spektrix.com'
MAX_STEPS = 8
MAX_PREVIEWS = 10
MAX_SAMPLE_BYTES = 18_000


def _fail(reason):
    raise ValueError('spektrix_runner_' + reason)


def _clock():
    return datetime.now(timezone.utc)


def _read_receipt(receipt):
    if (not isinstance(receipt, dict) or set(receipt) != {'revision', 'checkpoint'}
            or type(receipt['revision']) is not int or receipt['revision'] < 0
            or (receipt['checkpoint'] is None) != (receipt['revision'] == 0)
            or receipt['checkpoint'] is not None
            and not isinstance(receipt['checkpoint'], dict)):
        _fail('read_receipt_invalid')
    return receipt['revision'], receipt['checkpoint']


def _write_receipt(receipt, revision):
    if (not isinstance(receipt, dict)
            or receipt.get('checkpoint_saved') is not True
            or type(receipt.get('revision')) is not int
            or receipt['revision'] != revision + 1):
        _fail('write_receipt_invalid')
    return receipt['revision']


def _manifest(source, profile, envelope, context_hash, at):
    """Re-derive exact URLs from the persisted publisher evidence BEFORE GET.

    A valid checksum or matching host alone cannot authorize a request to
    another client, an arbitrary API resource, or a forged plan ID.
    """
    state = store.decode(source, envelope, context_hash=context_hash, at=at)
    p = state['progress']
    born = datetime.fromisoformat(p['started_at'])
    start = born.astimezone(ZoneInfo(profile['timezone'])).date()
    end = start + timedelta(days=api.MAX_DAYS - 1)
    if (p['allowed_hosts'] != [HOST]
            or p['window_start'] != start.isoformat()
            or p['window_end'] != end.isoformat()):
        _fail('window_scope_invalid')
    base = planner.base_tasks(source, profile, start, end)
    if p['tasks'][:len(base)] != base:
        _fail('manifest_invalid')
    if len(state['pages']) < len(base):
        if p['tasks'] != base or p['terminal_verified']:
            _fail('manifest_invalid')
    else:
        _, instances, _, _ = planner._read_base(source, profile, state)
        active = {row['planId'] for row in instances.values()
                  if row.get('cancelled') is False and row.get('isOnSale') is True}
        if len(active) >= api.MAX_PLANS:
            _fail('plan_limit')
        plans = [api.api_url(profile['client'], 'plans', identity=pid)
                 for pid in sorted(active)]
        if p['tasks'] != base + plans:
            _fail('manifest_invalid')
        if not p['terminal_verified'] and p['cursor'] == len(p['tasks']):
            # The runner saves the expanded plan (or terminal empty proof)
            # atomically with the final base page, never an unsealed prefix.
            _fail('manifest_unsealed')
    return state, len(base)


def _validate_page(url, body):
    if not isinstance(body, str):
        _fail('page_invalid')
    parts = urlsplit(url).path.split('/')
    if parts[-2] == 'plans':
        page = api._payload(body)
        if not isinstance(page, dict) or page.get('id') != parts[-1]:
            _fail('plan_identity_invalid')
    else:
        resource = parts[-1]
        limits = {'events': api.MAX_EVENTS, 'instances': api.MAX_INSTANCES,
                  'venues': api.MAX_VENUES}
        if resource not in limits:
            _fail('manifest_invalid')
        rows = api._items(body, limits[resource], resource)
        api._merge({}, rows, resource, limits[resource])


def capture_context(snapshot, profile):
    """Bind the in-flight capture to the existing processing/policy context."""
    if not isinstance(snapshot, Snapshot):
        _fail('incremental_context_required')
    return fingerprint({
        'adapter': store.ADAPTER, 'processing_context': snapshot.context_hash,
        'policy_context': snapshot.policy_context, 'profile': profile,
    })


def _preview_output(source, complete_snapshot, convert):
    """Ordinary preview shape; no private staging or publication API."""
    if not isinstance(complete_snapshot, dict) or complete_snapshot.get('complete') is not True:
        _fail('snapshot_incomplete')
    rows = convert(source, complete_snapshot)
    if not isinstance(rows, list) or len(rows) > MAX_EVENTS:
        _fail('shared_incremental_limit')
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get('id'), str)
                or not row['id'].strip() or not isinstance(row.get('event_url'), str)
                or not row['event_url']):
            _fail('event_identity_invalid')
        utc_start(row.get('starts_at'))
    samples = rows[:MAX_PREVIEWS]
    while len(json.dumps(samples, ensure_ascii=False).encode('utf-8')) > MAX_SAMPLE_BYTES:
        samples.pop()
    output = {'p_source_key': source['source_key'], 'p_samples': samples,
              'p_future_count': len(rows),
              'p_venue_count': sum(row.get('lat') is not None for row in rows),
              'p_error': None, 'p_events': rows}
    # Ordinary processing calls Snapshot.plan once on this exact output.
    return output


def run_slice(source, profile, *, snapshot, read, write, fetch, convert,
              can_continue, clock=_clock, max_steps=MAX_STEPS):
    """Fetch under an acknowledged lease/CAS, then return ordinary preview data.

    The caller must retain the ordinary incremental Snapshot for the exact
    active claim and invoke the shared processor in that final lease. If the
    claim expires after partial staging, its old ACKs are not transferable:
    a subsequent claim must re-plan against the current accepted baseline
    and restage its still-changed bodies, never advance a separate cursor.
    """
    if (not isinstance(source, dict) or source.get('kind') != 'json'
            or not isinstance(profile, dict)
            or profile.get('ready_for_registration') is not True
            or not isinstance(snapshot, Snapshot)
            or snapshot.source_key != source.get('source_key')
            or type(max_steps) is not int or not 1 <= max_steps <= MAX_STEPS):
        _fail('context_invalid')
    context_hash = capture_context(snapshot, profile)
    at = clock()
    start = at.astimezone(ZoneInfo(profile['timezone'])).date()
    end = start + timedelta(days=api.MAX_DAYS - 1)
    base = planner.base_tasks(source, profile, start, end)
    revision, envelope = _read_receipt(read())
    if envelope is None:
        envelope = store.new(source, base, allowed_hosts=[HOST],
                             start=start, end=end, context_hash=context_hash, at=at)
        revision = _write_receipt(write(revision, envelope), revision)

    for _ in range(max_steps):
        at = clock()
        state, base_count = _manifest(source, profile, envelope, context_hash, at)
        p = state['progress']
        if p['window_start'] != at.astimezone(ZoneInfo(profile['timezone'])).date().isoformat():
            _fail('window_rolled_over')
        if p['terminal_verified'] or not can_continue():
            break
        url = p['tasks'][p['cursor']]
        body = fetch(url, 'application/json')
        _validate_page(url, body)
        at = clock()
        last_base = p['cursor'] + 1 == base_count
        terminal = not last_base and p['cursor'] + 1 == len(p['tasks'])
        updated = store.acknowledge_page(source, envelope, url, body,
                         context_hash=context_hash, terminal=terminal, at=at)
        if last_base:
            plans = planner.plan_tasks(source, profile, updated,
                                       context_hash=context_hash, at=at)
            if plans:
                updated = store.add_verified_requests(source, updated, plans,
                         context_hash=context_hash, scope_verified=True, at=at)
            else:
                updated = store.acknowledge_page(source, envelope, url, body,
                         context_hash=context_hash, terminal=True, at=at)
        _manifest(source, profile, updated, context_hash, at)
        revision = _write_receipt(write(revision, updated), revision)
        envelope = updated

    at = clock()
    state, _ = _manifest(source, profile, envelope, context_hash, at)
    if state['progress']['window_start'] != at.astimezone(ZoneInfo(profile['timezone'])).date().isoformat():
        _fail('window_rolled_over')
    if not state['progress']['terminal_verified'] or not can_continue():
        return {'fetch_pending': True}
    full = planner.project(source, profile, envelope, context_hash=context_hash, at=at)
    return _preview_output(source, full, convert)
