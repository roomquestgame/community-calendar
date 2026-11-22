"""Bounded, source-bound state for reviewed national HTML feed snapshots.

Only the ordinary private lease/CAS checkpoint RPC persists this envelope. The
payload is compressed to avoid repeating publisher descriptions in transport;
decompression is bounded independently of the claimed header size.
"""
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import zlib

VERSION = 'national_feed_v1'
MAX_BYTES = 850_000
MAX_EXPANDED = 12_000_000
MAX_AGE = timedelta(hours=4)


def now(value=None):
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError('national_feed_checkpoint_invalid')
    return value.astimezone(timezone.utc)


def encode(source, state, *, phase, cursor, count, stage_cursor=0):
    raw = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    if len(raw) > MAX_EXPANDED:
        raise ValueError('national_feed_checkpoint_size_limit')
    result = {
        'version': 1, 'adapter': VERSION, 'source_key': source['source_key'],
        'feed_url': source['feed_url'], 'started_at': state['started_at'],
        'phase': phase, 'cursor': cursor, 'manifest_count': count,
        'record_count': len(state['events']), 'stage_cursor': stage_cursor,
        'encoding': 'zlib+base64', 'uncompressed_bytes': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(),
        'payload': base64.b64encode(zlib.compress(raw, 9)).decode(),
    }
    if len(json.dumps(result).encode()) > MAX_BYTES:
        raise ValueError('national_feed_checkpoint_size_limit')
    return result


def decode(source, checkpoint, *, at=None):
    try:
        if (not isinstance(checkpoint, dict) or set(checkpoint) != {
                'version', 'adapter', 'source_key', 'feed_url', 'started_at',
                'phase', 'cursor', 'manifest_count', 'record_count', 'stage_cursor',
                'encoding', 'uncompressed_bytes', 'sha256', 'payload'}
                or type(checkpoint['version']) is not int or checkpoint['version'] != 1
                or checkpoint['adapter'] != VERSION or checkpoint['encoding'] != 'zlib+base64'
                or checkpoint['source_key'] != source['source_key']
                or checkpoint['feed_url'] != source['feed_url']
                or checkpoint['phase'] not in ('fetch', 'stage')
                or any(type(checkpoint[k]) is not int or checkpoint[k] < 0 for k in (
                    'cursor', 'manifest_count', 'record_count', 'stage_cursor', 'uncompressed_bytes'))
                or checkpoint['cursor'] > checkpoint['manifest_count']
                or checkpoint['stage_cursor'] > checkpoint['record_count']
                or checkpoint['uncompressed_bytes'] > MAX_EXPANDED
                or len(json.dumps(checkpoint).encode()) > MAX_BYTES):
            raise ValueError
        age = now(at) - datetime.fromisoformat(checkpoint['started_at'])
        if not timedelta(seconds=-30) <= age <= MAX_AGE:
            raise ValueError('national_feed_checkpoint_expired')
        compressed = base64.b64decode(checkpoint['payload'], validate=True)
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, MAX_EXPANDED + 1)
        if (len(raw) > MAX_EXPANDED or decoder.unconsumed_tail or decoder.unused_data
                or not decoder.eof or len(raw) != checkpoint['uncompressed_bytes']
                or hashlib.sha256(raw).hexdigest() != checkpoint['sha256']):
            raise ValueError
        state = json.loads(raw)
        if (state['started_at'] != checkpoint['started_at']
                or len(state['events']) != checkpoint['record_count']
                or checkpoint['phase'] == 'stage' and checkpoint['cursor'] != checkpoint['manifest_count']):
            raise ValueError
        return state
    except (ValueError, TypeError, KeyError, UnicodeError, zlib.error) as exc:
        if str(exc) == 'national_feed_checkpoint_expired':
            raise
        raise ValueError('national_feed_checkpoint_invalid') from exc
