"""Source-bound, monotone *fetch* receipts for bounded calendar pagination.

The database must independently enforce active worker lease, CAS revisions,
rights, pacing and staged-record acknowledgements. This module is only the
reusable Python checkpoint contract, not a persistence/publication shortcut.

An incomplete page prefix can have progress receipts but NEVER a complete
snapshot. Source/adapter/window and the exact requested endpoint list remain
bound to the persisted state across retry invocations.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
from urllib.parse import urlsplit

VERSION = 1
MAX_TASKS = 500
MAX_BYTES = 850_000
MAX_AGE = timedelta(hours=4)
HEX = re.compile(r'^[a-f0-9]{64}$')
KEY = re.compile(r'^[a-z0-9_:-]{3,100})


def _fail():
    raise ValueError('feedzilla_checkpoint_invalid')


def _stamp(at=None):
    at = at or datetime.now(timezone.utc)
    if not isinstance(at, datetime) or at.tzinfo is None:
        _fail()
    return at.astimezone(timezone.utc)


def _digest(tasks):
    return hashlib.sha256(json.dumps(tasks, sort_keys=True, ensure_ascii=True,
                                     separators=(',', ':')).encode()).hexdigest()


def _url(value, hosts):
    try:
        parts = urlsplit(value)
        return (isinstance(value, str) and 10 <= len(value) <= 1200
                and parts.scheme == 'https' and parts.hostname in hosts
                and parts.username is None and parts.password is None
                and not parts.fragment)
    except (ValueError, TypeError):
        return False


def new(source_key, feed_url, adapter, tasks, *, allowed_hosts, start, end, at=None):
    """Create a new, unfinished window with explicit publisher-bound tasks."""
    try:
        start, end = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    except (ValueError, TypeError):
        _fail()
    if (not isinstance(source_key, str) or not KEY.fullmatch(source_key)
            or not isinstance(adapter, str) or not KEY.fullmatch(adapter)
            or end < start or (end - start).days >= 60
            or not isinstance(allowed_hosts, (tuple, list)) or not allowed_hosts
            or any(not isinstance(h, str) or not h for h in allowed_hosts)
            or not isinstance(tasks, list) or not 1 <= len(tasks) <= MAX_TASKS):
        _fail()
    hosts = tuple(allowed_hosts)
    if not _url(feed_url, hosts) or any(not _url(t, hosts) for t in tasks):
        _fail()
    if len(set(tasks)) != len(tasks):
        _fail()
    state = {
        'version': VERSION, 'source_key': source_key, 'feed_url': feed_url,
        'adapter': adapter, 'window_start': start.isoformat(),
        'window_end': end.isoformat(), 'allowed_hosts': list(hosts),
        'started_at': _stamp(at).isoformat(), 'tasks': list(tasks),
        'plan_sha256': _digest(tasks), 'cursor': 0, 'receipts': [],
        'terminal_verified': False,
    }
    validate(state, at=at)
    return state


def validate(state, *, source_key=None, feed_url=None, adapter=None, at=None):
    """Validate a database-resumed envelope before any publisher request."""
    if not isinstance(state, dict) or set(state) != {
            'version', 'source_key', 'feed_url', 'adapter', 'window_start',
            'window_end', 'allowed_hosts', 'started_at', 'tasks',
            'plan_sha256', 'cursor', 'receipts', 'terminal_verified'}:
        _fail()
    if (type(state['version']) is not int or state['version'] != VERSION
            or (source_key is not None and state['source_key'] != source_key)
            or (feed_url is not None and state['feed_url'] != feed_url)
            or (adapter is not None and state['adapter'] != adapter)
            or not isinstance(state['source_key'], str)
            or not KEY.fullmatch(state['source_key'])
            or not isinstance(state['adapter'], str)
            or not KEY.fullmatch(state['adapter'])
            or type(state['cursor']) is not int
            or not isinstance(state['terminal_verified'], bool)
            or not isinstance(state['tasks'], list)
            or not 1 <= len(state['tasks']) <= MAX_TASKS
            or not isinstance(state['receipts'], list)
            or len(state['receipts']) != state['cursor']
            or not 0 <= state['cursor'] <= len(state['tasks'])
            or not isinstance(state['allowed_hosts'], list)
            or not state['allowed_hosts']
            or not isinstance(state['plan_sha256'], str)
            or not HEX.fullmatch(state['plan_sha256'])
            or state['plan_sha256'] != _digest(state['tasks'])
            or any(not _url(t, state['allowed_hosts']) for t in state['tasks'])
            or not _url(state['feed_url'], state['allowed_hosts'])
            or len(set(state['tasks'])) != len(state['tasks'])):
        _fail()
    try:
        start = date.fromisoformat(state['window_start'])
        end = date.fromisoformat(state['window_end'])
        born = datetime.fromisoformat(state['started_at'])
        if (born.tzinfo is None or end < start or (end-start).days >= 60
                or not -timedelta(seconds=30) <= _stamp(at) - born <= MAX_AGE):
            _fail()
    except (ValueError, TypeError, KeyError):
        _fail()
    for i, receipt in enumerate(state['receipts']):
        if (not isinstance(receipt, dict)
                or set(receipt) != {'url', 'sha256'}
                or receipt['url'] != state['tasks'][i]
                or not isinstance(receipt['sha256'], str)
                or not HEX.fullmatch(receipt['sha256'])):
            _fail()
    if state['terminal_verified'] and state['cursor'] != len(state['tasks']):
        _fail()
    if len(json.dumps(state).encode()) > MAX_BYTES:
        _fail()
    return state


def next_request(state):
    validate(state)
    return state['tasks'][state['cursor']] if state['cursor'] < len(state['tasks']) else None


def advance(state, request_url, payload_hash, *, next_link=None,
            next_link_scope_verified=False, terminal=False, at=None):
    """Acknowledge one fully fetched page, optionally appending its proven next.

    The caller must first verify the payload, source, permissions and declared
    pagination semantics. Never invent a page by incrementing a URL counter.
    """
    validate(state, at=at)
    if (state['terminal_verified'] or state['cursor'] == len(state['tasks'])
            or request_url != state['tasks'][state['cursor']]
            or not isinstance(payload_hash, str) or not HEX.fullmatch(payload_hash)
            or terminal and next_link is not None):
        _fail()
    output = dict(state)
    output['tasks'] = list(state['tasks'])
    output['receipts'] = list(state['receipts'])
    if next_link is not None:
        if (not next_link_scope_verified
                or not _url(next_link, state['allowed_hosts'])
                or next_link in output['tasks']
                or len(output['tasks']) >= MAX_TASKS):
            _fail()
        output['tasks'].append(next_link)
        output['plan_sha256'] = _digest(output['tasks'])
    output['receipts'].append({'url': request_url, 'sha256': payload_hash})
    output['cursor'] += 1
    if terminal:
        if output['cursor'] != len(output['tasks']):
            _fail()
        output['terminal_verified'] = True
    validate(output, at=at)
    return output


def complete(state, *, at=None):
    """Only an explicit last-page proof permits downstream snapshot finalize."""
    validate(state, at=at)
    return bool(state['terminal_verified'] and state['cursor'] == len(state['tasks']))
)


def _fail():
    raise ValueError('feedzilla_checkpoint_invalid')


def _stamp(at=None):
    at = at or datetime.now(timezone.utc)
    if not isinstance(at, datetime) or at.tzinfo is None:
        _fail()
    return at.astimezone(timezone.utc)


def _digest(tasks):
    return hashlib.sha256(json.dumps(tasks, sort_keys=True, ensure_ascii=True,
                                     separators=(',', ':')).encode()).hexdigest()


def _url(value, hosts):
    try:
        parts = urlsplit(value)
        return (isinstance(value, str) and 10 <= len(value) <= 1200
                and parts.scheme == 'https' and parts.hostname in hosts
                and parts.username is None and parts.password is None
                and not parts.fragment)
    except (ValueError, TypeError):
        return False


def new(source_key, feed_url, adapter, tasks, *, allowed_hosts, start, end, at=None):
    """Create a new, unfinished window with explicit publisher-bound tasks."""
    try:
        start, end = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    except (ValueError, TypeError):
        _fail()
    if (not isinstance(source_key, str) or not KEY.fullmatch(source_key)
            or not isinstance(adapter, str) or not KEY.fullmatch(adapter)
            or end < start or (end - start).days >= 60
            or not isinstance(allowed_hosts, (tuple, list)) or not allowed_hosts
            or any(not isinstance(h, str) or not h for h in allowed_hosts)
            or not isinstance(tasks, list) or not 1 <= len(tasks) <= MAX_TASKS):
        _fail()
    hosts = tuple(allowed_hosts)
    if not _url(feed_url, hosts) or any(not _url(t, hosts) for t in tasks):
        _fail()
    if len(set(tasks)) != len(tasks):
        _fail()
    state = {
        'version': VERSION, 'source_key': source_key, 'feed_url': feed_url,
        'adapter': adapter, 'window_start': start.isoformat(),
        'window_end': end.isoformat(), 'allowed_hosts': list(hosts),
        'started_at': _stamp(at).isoformat(), 'tasks': list(tasks),
        'plan_sha256': _digest(tasks), 'cursor': 0, 'receipts': [],
        'terminal_verified': False,
    }
    validate(state, at=at)
    return state


def validate(state, *, source_key=None, feed_url=None, adapter=None, at=None):
    """Validate a database-resumed envelope before any publisher request."""
    if not isinstance(state, dict) or set(state) != {
            'version', 'source_key', 'feed_url', 'adapter', 'window_start',
            'window_end', 'allowed_hosts', 'started_at', 'tasks',
            'plan_sha256', 'cursor', 'receipts', 'terminal_verified'}:
        _fail()
    if (type(state['version']) is not int or state['version'] != VERSION
            or (source_key is not None and state['source_key'] != source_key)
            or (feed_url is not None and state['feed_url'] != feed_url)
            or (adapter is not None and state['adapter'] != adapter)
            or not isinstance(state['source_key'], str)
            or not KEY.fullmatch(state['source_key'])
            or not isinstance(state['adapter'], str)
            or not KEY.fullmatch(state['adapter'])
            or type(state['cursor']) is not int
            or not isinstance(state['terminal_verified'], bool)
            or not isinstance(state['tasks'], list)
            or not 1 <= len(state['tasks']) <= MAX_TASKS
            or not isinstance(state['receipts'], list)
            or len(state['receipts']) != state['cursor']
            or not 0 <= state['cursor'] <= len(state['tasks'])
            or not isinstance(state['allowed_hosts'], list)
            or not state['allowed_hosts']
            or not isinstance(state['plan_sha256'], str)
            or not HEX.fullmatch(state['plan_sha256'])
            or state['plan_sha256'] != _digest(state['tasks'])
            or any(not _url(t, state['allowed_hosts']) for t in state['tasks'])
            or not _url(state['feed_url'], state['allowed_hosts'])
            or len(set(state['tasks'])) != len(state['tasks'])):
        _fail()
    try:
        start = date.fromisoformat(state['window_start'])
        end = date.fromisoformat(state['window_end'])
        born = datetime.fromisoformat(state['started_at'])
        if (born.tzinfo is None or end < start or (end-start).days >= 60
                or not -timedelta(seconds=30) <= _stamp(at) - born <= MAX_AGE):
            _fail()
    except (ValueError, TypeError, KeyError):
        _fail()
    for i, receipt in enumerate(state['receipts']):
        if (not isinstance(receipt, dict)
                or set(receipt) != {'url', 'sha256'}
                or receipt['url'] != state['tasks'][i]
                or not isinstance(receipt['sha256'], str)
                or not HEX.fullmatch(receipt['sha256'])):
            _fail()
    if state['terminal_verified'] and state['cursor'] != len(state['tasks']):
        _fail()
    if len(json.dumps(state).encode()) > MAX_BYTES:
        _fail()
    return state


def next_request(state):
    validate(state)
    return state['tasks'][state['cursor']] if state['cursor'] < len(state['tasks']) else None


def advance(state, request_url, payload_hash, *, next_link=None,
            next_link_scope_verified=False, terminal=False, at=None):
    """Acknowledge one fully fetched page, optionally appending its proven next.

    The caller must first verify the payload, source, permissions and declared
    pagination semantics. Never invent a page by incrementing a URL counter.
    """
    validate(state, at=at)
    if (state['terminal_verified'] or state['cursor'] == len(state['tasks'])
            or request_url != state['tasks'][state['cursor']]
            or not isinstance(payload_hash, str) or not HEX.fullmatch(payload_hash)
            or terminal and next_link is not None):
        _fail()
    output = dict(state)
    output['tasks'] = list(state['tasks'])
    output['receipts'] = list(state['receipts'])
    if next_link is not None:
        if (not next_link_scope_verified
                or not _url(next_link, state['allowed_hosts'])
                or next_link in output['tasks']
                or len(output['tasks']) >= MAX_TASKS):
            _fail()
        output['tasks'].append(next_link)
        output['plan_sha256'] = _digest(output['tasks'])
    output['receipts'].append({'url': request_url, 'sha256': payload_hash})
    output['cursor'] += 1
    if terminal:
        if output['cursor'] != len(output['tasks']):
            _fail()
        output['terminal_verified'] = True
    validate(output, at=at)
    return output


def complete(state, *, at=None):
    """Only an explicit last-page proof permits downstream snapshot finalize."""
    validate(state, at=at)
    return bool(state['terminal_verified'] and state['cursor'] == len(state['tasks']))
