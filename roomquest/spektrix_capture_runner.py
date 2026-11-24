"""Feedzilla Spektrix capture runner (inactive until the paired DB contract).

The caller supplies lease-fenced read/write, a robots-aware GET, the existing
stage-record conversion, and an ATOMIC stage+CAS operation. No network or
database credentials, category claim, publication, or registration here.
A stage acknowledgement is not a publication receipt.
"""
from datetime import datetime, timedelta, timezone
import json
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from roomquest import feedzilla_capture_store as store
from roomquest import spektrix_capture_plan as planner
from roomquest import spektrix_v3 as api

HOST = 'system.spektrix.com'
MAX_STEPS = 8
MAX_BATCH_BYTES = 140_000
# The existing common DB preview contract is capped at 500 for this family.
# Refuse an oversized manifest rather than silently dropping performances.
MAX_SEALED_MEMBERS = 500


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


def _write_receipt(receipt, revision, *, count=None):
    if (not isinstance(receipt, dict)
            or receipt.get('checkpoint_saved') is not True
            or type(receipt.get('revision')) is not int
            or receipt['revision'] != revision + 1
            or count is not None and (
                type(receipt.get('staged_count')) is not int
                or receipt['staged_count'] != count)):
        _fail('write_receipt_invalid')
    return receipt['revision']


def _manifest(source, profile, envelope, at):
    """Re-derive exact URLs from the persisted publisher evidence BEFORE GET.

    A valid checksum or matching host alone cannot authorize a request to
    another client, an arbitrary API resource, or a forged plan ID.
    """
    state = store.decode(source, envelope, at=at)
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
        if p['tasks'] != base or state['phase'] != 'fetch':
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
        if state['phase'] == 'fetch' and p['cursor'] == len(p['tasks']):
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


def _batch(state):
    rows = []
    for row in state['records'][state['stage_cursor']:
                                state['stage_cursor'] + store.MAX_STAGE_BATCH]:
        candidate = rows + [row]
        if len(json.dumps(candidate, ensure_ascii=True).encode('utf-8')) > MAX_BATCH_BYTES:
            break
        rows = candidate
    if not rows:
        _fail('stage_batch_limit')
    return rows


def run_slice(source, profile, *, read, write, fetch, convert, seal, stage_and_save,
              can_continue, clock=_clock, max_steps=MAX_STEPS):
    """Advance a source-bound 60-day capture through bounded work.

    read() -> {revision, checkpoint}; write(revision, envelope) -> CAS receipt.
    fetch(url, 'application/json') must enforce existing publisher policies.
    convert(source, complete_snapshot) uses the existing stage-row contract.
    seal(revision, previous, next, fetch_receipts, members) atomically saves
    the complete explicit member manifest and returns its sealed_count.
    stage_and_save(revision, previous_envelope, next_envelope, rows) MUST
    atomically validate the current lease/generation, stage exactly those rows
    idempotently, and CAS-save the acknowledgement. It returns a write receipt
    with staged_count. No separate, unverified cursor advances are accepted.
    The DB must also independently certify complete staged membership before
    the existing publication worker may publish. This runner does not do so.
    """
    if (not isinstance(source, dict) or source.get('kind') != 'json'
            or not isinstance(profile, dict)
            or profile.get('ready_for_registration') is not True
            or type(max_steps) is not int or not 1 <= max_steps <= MAX_STEPS):
        _fail('context_invalid')
    at = clock()
    # Validate exact client/feed scope before any callback.
    start = at.astimezone(ZoneInfo(profile['timezone'])).date()
    end = start + timedelta(days=api.MAX_DAYS - 1)
    base = planner.base_tasks(source, profile, start, end)
    revision, envelope = _read_receipt(read())
    if envelope is None:
        envelope = store.new(source, base, allowed_hosts=[HOST],
                             start=start, end=end, at=at)
        revision = _write_receipt(write(revision, envelope), revision)

    staged = 0
    for _ in range(max_steps):
        at = clock()
        state, base_count = _manifest(source, profile, envelope, at)
        phase = state['phase']
        if phase == 'done' or not can_continue():
            break
        if phase == 'fetch':
            p = state['progress']
            url = p['tasks'][p['cursor']]
            body = fetch(url, 'application/json')
            _validate_page(url, body)
            at = clock()
            # Base phase must never be marked terminal until its real instance
            # records determine whether a second phase is necessary.
            last_base = p['cursor'] + 1 == base_count
            terminal = not last_base and p['cursor'] + 1 == len(p['tasks'])
            updated = store.acknowledge_page(source, envelope, url, body,
                                              terminal=terminal, at=at)
            if last_base:
                plans = planner.plan_tasks(source, profile, updated, at=at)
                if plans:
                    updated = store.add_verified_requests(
                        source, updated, plans, scope_verified=True, at=at)
                else:
                    # A genuinely empty/off-sale calendar has no plan pages.
                    # Re-acknowledge this same validated final base page with
                    # terminal proof; do not invent a sentinel HTTP request.
                    updated = store.acknowledge_page(
                        source, envelope, url, body, terminal=True, at=at)
            _manifest(source, profile, updated, at)
            revision = _write_receipt(write(revision, updated), revision)
            envelope = updated
        elif phase == 'project':
            snapshot = planner.project(source, profile, envelope, at=at)
            rows = convert(source, snapshot)
            if not isinstance(rows, list) or len(rows) > MAX_SEALED_MEMBERS:
                _fail('sealed_membership_limit')
            updated = store.prepare_staging(source, envelope, rows, at=clock())
            members = [{key: row[key] for key in ('id', 'starts_at', 'event_url')}
                       for row in rows]
            receipt = seal(revision, envelope, updated,
                           state['progress']['receipts'], members)
            if (not isinstance(receipt, dict)
                    or type(receipt.get('sealed_count')) is not int
                    or receipt['sealed_count'] != len(members)):
                _fail('seal_receipt_invalid')
            revision = _write_receipt(receipt, revision)
            envelope = updated
        elif phase == 'stage':
            rows = _batch(state)
            updated = store.acknowledge_stage(source, envelope, len(rows), at=clock())
            receipt = stage_and_save(revision, envelope, updated, rows)
            revision = _write_receipt(receipt, revision, count=len(rows))
            staged += len(rows)
            envelope = updated
        else:
            _fail('phase_invalid')

    state, _ = _manifest(source, profile, envelope, clock())
    done = store.ready_to_publish(source, envelope, at=clock())
    return {'status': 'staged' if done else 'pending',
            'phase': state['phase'], 'revision': revision,
            'checkpoint_sha256': envelope['sha256'],
            'staged_this_slice': staged, 'staged_count': state['stage_cursor'],
            'record_count': len(state['records'])}
