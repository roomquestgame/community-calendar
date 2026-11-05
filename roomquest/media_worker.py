"""Ticketed, bounded image verification independent of the geocoder runtime.

The database owns eligibility, freshness, leases and continuation. This worker
only probes already selected publisher images; it never fetches event HTML or
copies image files into storage.
"""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
import json
import os
import threading
from time import monotonic

import requests

from roomquest.event_media import (
    MediaDeferred, PROBE_SECONDS, canonical_host, resolve_photo,
)
from roomquest.preview_worker import PreviewError, supabase_rpc

RPC = 'community_collector_media_demand'
WORKER_VERSION = 'media_demand_v1'
CANDIDATE_VERSION = 'publisher_event_html_v2'
MAX_CONCURRENCY = 10
MAX_PER_HOST = 3
RUN_SECONDS = 40
CLAIM_TIMEOUT = 3
RESULT_TIMEOUT = 3
FINISH_TIMEOUT = 5
# A fresh claim must have time for its entire bounded probe and result RPC.
ADMISSION_HEADROOM = CLAIM_TIMEOUT + PROBE_SECONDS + RESULT_TIMEOUT + 1


def rpc(action, payload, *, timeout=4):
    return supabase_rpc(RPC, {'p_action': action, 'p_payload': payload}, timeout=timeout)


def _bounded_int(value, default, minimum, maximum):
    return max(minimum, min(maximum, value)) if type(value) is int else default


class HostLimiter:
    """One shared limiter for all requests, including validated redirect hosts.

    The database admits only one drain invocation at a time. It also limits
    initial candidate-host item leases independently of these HTTP permits.
    """

    def __init__(self, limit, *, backoffs=None, clock=None):
        self.limit = _bounded_int(limit, MAX_PER_HOST, 1, MAX_PER_HOST)
        self.clock = clock or monotonic
        self._lock = threading.Lock()
        self._active = {}
        self._until = {}
        if isinstance(backoffs, dict):
            for host, seconds in backoffs.items():
                if isinstance(host, str) and type(seconds) in (int, float) and seconds > 0:
                    self.backoff(host, min(3600, seconds))

    def backoff(self, host, seconds):
        host = canonical_host(host)
        if not host:
            return
        with self._lock:
            self._until[host] = max(self._until.get(host, 0), self.clock() + max(1, min(3600, seconds)))

    def excluded_hosts(self):
        now = self.clock()
        with self._lock:
            self._until = {host: until for host, until in self._until.items() if until > now}
            hosts = set(self._until)
            hosts.update(host for host, count in self._active.items() if count >= self.limit)
            return sorted(hosts)[:128]

    @contextmanager
    def request(self, host):
        host = canonical_host(host)
        with self._lock:
            delay = self._until.get(host, 0) - self.clock()
            if delay > 0:
                raise MediaDeferred('host_busy', host=host, retry_after_seconds=int(delay) + 1)
            if self._active.get(host, 0) >= self.limit:
                # Do not spend a claimed item's lease waiting in a local queue.
                raise MediaDeferred('host_busy', host=host, retry_after_seconds=2)
            self._active[host] = self._active.get(host, 0) + 1
        try:
            yield
        finally:
            with self._lock:
                count = self._active[host] - 1
                if count:
                    self._active[host] = count
                else:
                    self._active.pop(host, None)


class _ThreadSessions:
    """Connection reuse without sharing a mutable requests.Session across threads."""

    def __init__(self):
        self._local = threading.local()
        self._sessions = []
        self._lock = threading.Lock()

    def get(self):
        if not hasattr(self._local, 'session'):
            self._local.session = requests.Session()
            with self._lock:
                self._sessions.append(self._local.session)
        return self._local.session

    def close(self):
        for session in self._sessions:
            session.close()


def _record(database, action, payload):
    result = database(action, payload, timeout=RESULT_TIMEOUT)
    return isinstance(result, dict) and result.get('recorded') is True


def _process(claim, *, common, database, resolver, clock, deadline, limiter, sessions):
    identity = {**common, 'media_key': claim['media_key'], 'lease_id': claim['lease_id']}
    temporary = None
    result = None
    unexpected = False
    try:
        if claim.get('candidate_only') is not True:
            # This lane has no permission to crawl a missing candidate's page.
            unexpected = True
            raise MediaDeferred('network_error')
        if clock() + PROBE_SECONDS + RESULT_TIMEOUT + 1 >= deadline:
            raise MediaDeferred('deadline')
        result = resolver(claim, clock=clock, deadline=deadline - RESULT_TIMEOUT - 1,
                          strict_deadline=True, host_limiter=limiter, session=sessions.get())
        if result is not None and (not isinstance(result, dict)
                or not all(isinstance(result.get(key), str) and result[key]
                           for key in ('image_url', 'mime_type', 'evidence_url'))):
            unexpected = True
            raise MediaDeferred('network_error', attempted=True)
    except MediaDeferred as error:
        temporary = error
    except (PreviewError, requests.RequestException, ValueError, OSError):
        temporary = MediaDeferred('network_error', attempted=True)
    except Exception:
        # Preserve the lease for recovery and stop new admission on code errors.
        # Do not expose exception messages, request URLs, tokens or tickets.
        unexpected = True
        temporary = MediaDeferred('network_error', attempted=True)

    if temporary is not None:
        if temporary.host and temporary.reason in ('transient_http', 'network_error'):
            limiter.backoff(temporary.host, temporary.retry_after_seconds)
        action = 'defer'
        payload = {**identity, 'reason': temporary.reason,
                   'retry_after_seconds': temporary.retry_after_seconds,
                   'attempted': temporary.attempted}
        if temporary.host:
            payload['host'] = temporary.host
        metric = 'deferred'
    elif result:
        action, payload, metric = 'submit', {
            **identity, **{key: result[key] for key in ('image_url', 'mime_type', 'evidence_url')}}, 'ready'
    else:
        action, payload, metric = 'fail', {**identity, 'reason': 'no_event_image'}, 'unavailable'

    try:
        recorded = _record(database, action, payload)
    except Exception:
        # The result may have committed even when its acknowledgement was lost.
        # Never replace an uncertain submit with a terminal no-image result.
        return {'errors': 1, 'unrecorded': 1, 'fatal': True}
    if not recorded:
        return {'errors': 1, 'unrecorded': 1, 'fatal': unexpected}
    return {metric: 1, 'errors': int(unexpected), 'fatal': unexpected}


def _log(stats):
    # Fixed counters only. Dispatch tickets, image/source URLs and exception
    # arguments are intentionally absent from both logs and response bodies.
    print(json.dumps({'event': 'collector_media_run', **stats}, separators=(',', ':'), sort_keys=True), flush=True)


def collect_media(ticket, *, database=None, resolver=None, clock=None):
    database, resolver, clock = database or rpc, resolver or resolve_photo, clock or monotonic
    started = clock()
    stats = {'claimed': 0, 'ready': 0, 'unavailable': 0, 'deferred': 0,
             'errors': 0, 'unrecorded': 0, 'peak_inflight': 0,
             'stop_reason': 'disabled', 'outcome': 'idle', 'elapsed_ms': 0}
    if os.environ.get('VERCEL_ENV') != 'production':
        return stats

    run = database('start', {'ticket': ticket, 'worker_version': WORKER_VERSION,
                            'candidate_only_version': CANDIDATE_VERSION}, timeout=4)
    if not run:
        stats['stop_reason'] = 'not_admitted'
        return stats
    if not isinstance(run, dict) or not isinstance(run.get('worker_lease_id'), str) or not run['worker_lease_id']:
        raise PreviewError('invalid_media_dispatch')

    common = {'ticket': ticket, 'worker_lease_id': run['worker_lease_id']}
    concurrency = _bounded_int(run.get('concurrency'), 5, 1, MAX_CONCURRENCY)
    seconds = _bounded_int(run.get('budget_seconds'), RUN_SECONDS, 1, RUN_SECONDS)
    deadline = started + seconds
    limiter = HostLimiter(run.get('per_host_concurrency'), backoffs=run.get('host_backoffs'), clock=clock)
    sessions = _ThreadSessions()
    outcome = 'failed'
    stats['stop_reason'] = 'queue_empty'
    futures = set()
    fatal = False
    claims_blocked = False

    try:
        with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix='media') as pool:
            while True:
                can_admit = not fatal and clock() + ADMISSION_HEADROOM < deadline
                if can_admit and not claims_blocked and len(futures) < concurrency:
                    free = concurrency - len(futures)
                    claims = database('claim', {**common, 'limit': free,
                                                'exclude_hosts': limiter.excluded_hosts()}, timeout=CLAIM_TIMEOUT) or []
                    if not isinstance(claims, list) or len(claims) > free:
                        raise PreviewError('invalid_media_claim')
                    claims_blocked = not claims
                    for claim in claims:
                        if (not isinstance(claim, dict) or not claim.get('media_key')
                                or not claim.get('lease_id')):
                            raise PreviewError('invalid_media_claim')
                        futures.add(pool.submit(_process, claim, common=common,
                            database=database, resolver=resolver, clock=clock, deadline=deadline,
                            limiter=limiter, sessions=sessions))
                        stats['claimed'] += 1
                    stats['peak_inflight'] = max(stats['peak_inflight'], len(futures))
                    if not claims and not futures:
                        outcome = 'complete' if stats['claimed'] else 'idle'
                        break

                if not futures:
                    outcome = 'failed' if fatal else 'budget'
                    stats['stop_reason'] = 'worker_error' if fatal else 'budget'
                    break

                # Only free execution slots can claim more work. Completed
                # results are acknowledged inside their own executor thread.
                done, futures = wait(futures, return_when=FIRST_COMPLETED,
                                     timeout=max(0.05, min(1, deadline - clock())))
                for future in done:
                    item = future.result()
                    fatal = fatal or item.pop('fatal', False)
                    for key, value in item.items():
                        stats[key] += value
                if done:
                    claims_blocked = False
                if clock() >= deadline:
                    # Network probes and RPCs have their own tighter deadlines.
                    # Join them before releasing the singleton to its successor.
                    for future in futures:
                        item = future.result()
                        fatal = fatal or item.pop('fatal', False)
                        for key, value in item.items():
                            stats[key] += value
                    futures = set()
                    outcome = 'failed' if fatal else 'budget'
                    stats['stop_reason'] = 'worker_error' if fatal else 'budget'
                    break
    except Exception:
        stats['errors'] += 1
        raise
    finally:
        try:
            sessions.close()
        finally:
            # A fenced finish releases any acknowledgement-uncertain items and
            # lets the database schedule only genuinely eligible continuation.
            try:
                finished = database('finish', {**common, 'outcome': outcome}, timeout=FINISH_TIMEOUT)
                if not isinstance(finished, dict) or finished.get('recorded') is not True:
                    raise PreviewError('media_finish_unconfirmed')
            except Exception:
                stats['errors'] += 1
                outcome = 'failed'
                stats['stop_reason'] = 'finish_error'
                raise
            finally:
                stats['outcome'] = outcome
                stats['elapsed_ms'] = max(0, int((clock() - started) * 1000))
                if outcome == 'failed' and stats['stop_reason'] != 'finish_error':
                    stats['stop_reason'] = 'worker_error'
                _log(stats)
    return stats
