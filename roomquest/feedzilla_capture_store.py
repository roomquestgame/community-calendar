"""Compressed source-bound capture state for multi-run Feedzilla collectors.

This is the Python persistence envelope, NOT a database-backed worker or an
approval to publish. The database must separately enforce source ownership,
leases, CAS revision, publisher pacing, stage acknowledgements and rights.

An incomplete fetch prefix can be resumed, but only a verified terminal page
can enter projection. Publication is not permitted until every projected
record has a server-acknowledged stage receipt.
"""
import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import zlib

from roomquest import feedzilla_pagination_checkpoint as progress

VERSION = 1
MAX_ENVELOPE = 850_000
MAX_EXPANDED = 12_000_000
MAX_PAGE_BYTES = 3_000_000
MAX_RECORDS = 4500
MAX_STAGE_BATCH = 20
_ALLOWED_PHASES = {'fetch', 'project', 'stage', 'done'}


def _fail(reason='invalid'):
    raise ValueError('feedzilla_capture_' + reason)


def _raw(obj):
    try:
        return json.dumps(obj, sort_keys=True, ensure_ascii=True,
                          separators=(',', ':')).encode('utf-8')
    except (TypeError, ValueError, RecursionError):
        _fail()


def _validate_state(state, *, source_key=None, feed_url=None, adapter=None, at=None):
    if not isinstance(state, dict) or set(state) != {
            'progress', 'pages', 'phase', 'records', 'stage_cursor'}:
        _fail()
    cursor = state['progress']
    progress.validate(cursor, source_key=source_key, feed_url=feed_url,
                      adapter=adapter, at=at)
    pages, phase, records, stage = (state[key] for key in (
        'pages', 'phase', 'records', 'stage_cursor'))
    if (phase not in _ALLOWED_PHASES or not isinstance(pages, list)
            or len(pages) != cursor['cursor']
            or not isinstance(records, list) or len(records) > MAX_RECORDS
            or type(stage) is not int or not 0 <= stage <= len(records)):
        _fail()
    for i, page in enumerate(pages):
        if (not isinstance(page, dict) or set(page) != {'url', 'body'}
                or page['url'] != cursor['tasks'][i]
                or not isinstance(page['body'], str)
                or len(page['body'].encode('utf-8')) > MAX_PAGE_BYTES
                or hashlib.sha256(page['body'].encode('utf-8')).hexdigest()
                   != cursor['receipts'][i]['sha256']):
            _fail('receipt_invalid')
    if (phase == 'fetch' and (cursor['terminal_verified'] or records or stage)
            or phase == 'project' and (not progress.complete(cursor, at=at)
                                       or records or stage)
            or phase in ('stage', 'done') and not progress.complete(cursor, at=at)
            or phase == 'done' and stage != len(records)):
        _fail('phase_invalid')
    if any(not isinstance(row, dict) or not row.get('id')
           or not row.get('starts_at') or not row.get('event_url')
           for row in records):
        _fail('records_invalid')
    if len(_raw(state)) > MAX_EXPANDED:
        _fail('size_limit')
    return state


def new(source, tasks, *, allowed_hosts, start, end, at=None):
    """A new 60-day-or-shorter scoped fetch plan with no certified records."""
    if not isinstance(source, dict):
        _fail('source_invalid')
    cursor = progress.new(source['source_key'], source['feed_url'],
                          source['platform_adapter'], tasks,
                          allowed_hosts=allowed_hosts,start=start,end=end,at=at)
    state={'progress':cursor,'pages':[],'phase':'fetch','records':[],
           'stage_cursor':0}
    _validate_state(state, source_key=source['source_key'],
                    feed_url=source['feed_url'], adapter=source['platform_adapter'],at=at)
    return encode(source,state,at=at)


def encode(source, state, *, at=None):
    """Bounded immutable checkpoint envelope; DB still owns the CAS revision."""
    if not isinstance(source,dict):
        _fail('source_invalid')
    _validate_state(state,source_key=source.get('source_key'),
                    feed_url=source.get('feed_url'),adapter=source.get('platform_adapter'),at=at)
    raw = _raw(state)
    compressed = zlib.compress(raw, 9)
    envelope = {
        'version': VERSION,
        'source_key': source['source_key'], 'feed_url': source['feed_url'],
        'adapter': source['platform_adapter'],
        'started_at': state['progress']['started_at'],
        'encoding': 'zlib+base64',
        'uncompressed_bytes': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(),
        'payload': base64.b64encode(compressed).decode('ascii')
    }
    if len(_raw(envelope)) > MAX_ENVELOPE:
        _fail('size_limit')
    return envelope


def decode(source, envelope, *, at=None):
    """Reject forged, stale, oversized, cross-source or corrupted checkpoints."""
    if not isinstance(source,dict) or not isinstance(envelope,dict) or set(envelope) != {
            'version','source_key','feed_url','adapter','started_at',
            'encoding','uncompressed_bytes','sha256','payload'}:
        _fail()
    if (type(envelope['version']) is not int or envelope['version'] != VERSION
            or envelope['source_key'] != source.get('source_key')
            or envelope['feed_url'] != source.get('feed_url')
            or envelope['adapter'] != source.get('platform_adapter')
            or envelope['encoding'] != 'zlib+base64'
            or type(envelope['uncompressed_bytes']) is not int
            or not 0 < envelope['uncompressed_bytes'] <= MAX_EXPANDED
            or not isinstance(envelope['payload'],str)
            or len(_raw(envelope)) > MAX_ENVELOPE):
        _fail()
    try:
        binary=base64.b64decode(envelope['payload'],validate=True)
        decompressor=zlib.decompressobj()
        raw=decompressor.decompress(binary,MAX_EXPANDED+1)
        if (len(raw) > MAX_EXPANDED or decompressor.unconsumed_tail
                or decompressor.unused_data or not decompressor.eof
                or len(raw) != envelope['uncompressed_bytes']
                or hashlib.sha256(raw).hexdigest() != envelope['sha256']):
            _fail('checksum')
        state=json.loads(raw)
    except (ValueError, TypeError, zlib.error, UnicodeDecodeError, RecursionError):
        _fail()
    _validate_state(state,source_key=source['source_key'],
                    feed_url=source['feed_url'],adapter=source['platform_adapter'],at=at)
    if envelope['started_at'] != state['progress']['started_at']:
        _fail('identity_changed')
    return state


def acknowledge_page(source, envelope, url, body, *, next_link=None,
                     next_link_scope_verified=False, terminal=False, at=None):
    """Acknowledge precisely one publisher-validated page and its content."""
    state=decode(source,envelope,at=at)
    if (state['phase'] != 'fetch' or not isinstance(body,str)
            or len(body.encode('utf-8')) > MAX_PAGE_BYTES):
        _fail('page_invalid')
    cursor=progress.advance(
        state['progress'],url,hashlib.sha256(body.encode('utf-8')).hexdigest(),
        next_link=next_link,next_link_scope_verified=next_link_scope_verified,
        terminal=terminal,at=at)
    output=deepcopy(state)
    output['progress']=cursor
    output['pages'].append({'url':url,'body':body})
    if progress.complete(cursor,at=at):
        output['phase']='project'
    return encode(source,output,at=at)


def prepare_staging(source, envelope, rows, *, at=None):
    """Only a fully verified manifest may become a stageable record list."""
    state=decode(source,envelope,at=at)
    if (state['phase'] != 'project' or not isinstance(rows,list)
            or len(rows) > MAX_RECORDS):
        _fail('stage_not_ready')
    output=deepcopy(state)
    output['records']=deepcopy(rows)
    output['stage_cursor']=0
    output['phase']='done' if not rows else 'stage'
    return encode(source,output,at=at)


def acknowledge_stage(source, envelope, confirmed_count, *, at=None):
    """Advance *after* matching records were acknowledged by the DB stage RPC."""
    state=decode(source,envelope,at=at)
    if (state['phase'] != 'stage' or type(confirmed_count) is not int
            or not 1 <= confirmed_count <= MAX_STAGE_BATCH
            or state['stage_cursor']+confirmed_count > len(state['records'])):
        _fail('stage_receipt_invalid')
    output=deepcopy(state)
    output['stage_cursor']+=confirmed_count
    if output['stage_cursor'] == len(output['records']):
        output['phase']='done'
    return encode(source,output,at=at)


def ready_to_publish(source, envelope, *, at=None):
    """The *Python* readiness gate; DB must also verify staged acknowledgements."""
    state=decode(source,envelope,at=at)
    return (state['phase']=='done' and
            state['stage_cursor']==len(state['records']) and
            progress.complete(state['progress'],at=at))
