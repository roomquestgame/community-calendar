"""Fetch-only evidence for bounded multipage collection.

Uses the existing compressed checkpoint codec. The shared incremental
snapshot owns event hashes, staging acknowledgements, withdrawals and
publication. There are deliberately no event rows or staging cursors here.
No production claim admits this new envelope format yet.
"""
from copy import deepcopy
import hashlib
import json
import re
import zlib

from roomquest import feedzilla_pagination_checkpoint as progress
from roomquest import national_feed_checkpoint as codec

VERSION = 2
ADAPTER = 'feedzilla_fetch_v2'
MAX_ENVELOPE = codec.MAX_BYTES
MAX_PAGE_BYTES = 3_000_000
_HASH = re.compile(r'[a-f0-9]{64}\Z')


def _fail(reason='invalid'):
    raise ValueError('feedzilla_capture_' + reason)


def _validate_state(source, state, context_hash, *, at=None):
    if (not isinstance(source, dict) or not isinstance(state, dict)
            or set(state) != {'progress', 'pages', 'context_hash'}
            or not isinstance(context_hash, str) or not _HASH.fullmatch(context_hash)
            or state['context_hash'] != context_hash):
        _fail('context_invalid')
    cursor = state['progress']
    progress.validate(cursor, source_key=source['source_key'],
                      feed_url=source['feed_url'],
                      adapter=source['platform_adapter'], at=at)
    pages = state['pages']
    if not isinstance(pages, list) or len(pages) != cursor['cursor']:
        _fail()
    for i, page in enumerate(pages):
        if (not isinstance(page, dict) or set(page) != {'url', 'body'}
                or page['url'] != cursor['tasks'][i]
                or not isinstance(page['body'], str)
                or len(page['body'].encode('utf-8')) > MAX_PAGE_BYTES
                or hashlib.sha256(page['body'].encode('utf-8')).hexdigest()
                   != cursor['receipts'][i]['sha256']):
            _fail('receipt_invalid')
    return state


def new(source, tasks, *, allowed_hosts, start, end, context_hash, at=None):
    cursor = progress.new(source['source_key'], source['feed_url'],
                          source['platform_adapter'], tasks,
                          allowed_hosts=allowed_hosts, start=start, end=end, at=at)
    return encode(source, {'progress': cursor, 'pages': [],
                           'context_hash': context_hash},
                  context_hash=context_hash, at=at)


def encode(source, state, *, context_hash, at=None):
    _validate_state(source, state, context_hash, at=at)
    cursor = state['progress']
    result = {
        'version': VERSION, 'adapter': ADAPTER,
        'source_key': source['source_key'], 'feed_url': source['feed_url'],
        'context_hash': context_hash, 'started_at': cursor['started_at'],
        'window_start': cursor['window_start'], 'window_end': cursor['window_end'],
        'cursor': cursor['cursor'], 'manifest_count': len(cursor['tasks']),
        'terminal_verified': cursor['terminal_verified'],
        'manifest_hash': cursor['plan_sha256'],
        **codec.encode_payload(state),
    }
    if len(json.dumps(result).encode()) > MAX_ENVELOPE:
        _fail('size_limit')
    return result


def decode(source, envelope, *, context_hash, at=None):
    if (not isinstance(source, dict) or not isinstance(envelope, dict)
            or set(envelope) != {'version', 'adapter', 'source_key', 'feed_url',
                'context_hash', 'started_at', 'window_start', 'window_end',
                'cursor', 'manifest_count', 'terminal_verified', 'manifest_hash',
                'encoding', 'uncompressed_bytes', 'sha256', 'payload'}
            or type(envelope['version']) is not int or envelope['version'] != VERSION
            or envelope['adapter'] != ADAPTER
            or envelope['source_key'] != source.get('source_key')
            or envelope['feed_url'] != source.get('feed_url')
            or envelope['context_hash'] != context_hash
            or type(envelope['cursor']) is not int
            or type(envelope['manifest_count']) is not int
            or type(envelope['terminal_verified']) is not bool):
        _fail('context_invalid')
    try:
        state = codec.decode_payload(envelope)
    except (ValueError, TypeError, KeyError, UnicodeError, zlib.error, RecursionError) as exc:
        _fail('checksum' if str(exc) == 'national_feed_checkpoint_checksum' else 'invalid')
    _validate_state(source, state, context_hash, at=at)
    cursor = state['progress']
    if (any(envelope[key] != cursor[key] for key in
            ('started_at', 'window_start', 'window_end', 'cursor', 'terminal_verified'))
            or envelope['manifest_count'] != len(cursor['tasks'])
            or envelope['manifest_hash'] != cursor['plan_sha256']):
        _fail('identity_changed')
    return state


def add_verified_requests(source, envelope, urls, *, context_hash,
                          scope_verified=False, at=None):
    state = decode(source, envelope, context_hash=context_hash, at=at)
    result = deepcopy(state)
    result['progress'] = progress.extend_verified_tasks(
        state['progress'], urls, scope_verified=scope_verified, at=at)
    return encode(source, result, context_hash=context_hash, at=at)


def acknowledge_page(source, envelope, url, body, *, context_hash, next_link=None,
                     next_link_scope_verified=False, terminal=False, at=None):
    state = decode(source, envelope, context_hash=context_hash, at=at)
    if (not isinstance(body, str) or len(body.encode('utf-8')) > MAX_PAGE_BYTES):
        _fail('page_invalid')
    cursor = progress.advance(
        state['progress'], url, hashlib.sha256(body.encode('utf-8')).hexdigest(),
        next_link=next_link, next_link_scope_verified=next_link_scope_verified,
        terminal=terminal, at=at)
    result = deepcopy(state)
    result['progress'] = cursor
    result['pages'].append({'url': url, 'body': body})
    return encode(source, result, context_hash=context_hash, at=at)


def ready_to_project(source, envelope, *, context_hash, at=None):
    """Only fetch completeness, never event or publication acceptance."""
    state = decode(source, envelope, context_hash=context_hash, at=at)
    return progress.complete(state['progress'], at=at)
