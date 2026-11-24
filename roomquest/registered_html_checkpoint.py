"""Fetch-only continuation over the existing private checkpoint contract.

The same registered HTML parser handles intake and refresh. No network,
credentials, source writes, stage receipts or publication are owned here.
"""
from datetime import timedelta
from hashlib import sha256
from time import monotonic
from urllib.parse import urlsplit

from roomquest import feedzilla_pagination_checkpoint as progress
from roomquest import national_feed_checkpoint as codec
from roomquest.registered_html_calendar import resume_capture, _registered_url
from roomquest.registered_native_content import validate_record
from roomquest.publisher_pacing import pacing_rpc_fields

CAPABILITY = 'registered_html_checkpoint_version'
PENDING = 'html_calendar_capture_continue'
MAX_REQUESTS = 8
CONTEXT_VERSION = 1


def enabled(source):
    return type(source.get(CAPABILITY)) is int and source[CAPABILITY] == 1


def context_hash(source):
    from roomquest.incremental_snapshot import fingerprint, parser_context
    return fingerprint({'version': CONTEXT_VERSION,
                        'parser': parser_context(source),
                        'source_key': source['source_key'],
                        'feed_url': source['feed_url'],
                        'adapter': 'html'})


# BEGIN EVE159_PREDECESSOR_CONTEXT
def _dispatch_predecessor_context(source):
    """Recognize captures from the immediately preceding dispatcher-only release.

    This is NOT a hash bypass. Reconstruct the previous package fingerprint
    using only these two reviewed, reversible control-flow edits. Every other
    deployed source/config file and dependency version must still match the
    captured fingerprint. Old response bytes are replayed by the current
    complete traversal and ordinary native record validator.
    """
    from hashlib import sha1
    from importlib.metadata import PackageNotFoundError, version
    from pathlib import Path
    from roomquest.incremental_snapshot import fingerprint

    def strip_block(data, name, replacement=b''):
        # Markers are full lines, not arbitrary substrings in code or text.
        lines = data.splitlines(keepends=True)
        start = [i for i, line in enumerate(lines)
                 if line.strip() == ('# BEGIN ' + name).encode()]
        end = [i for i, line in enumerate(lines)
               if line.strip() == ('# END ' + name).encode()]
        if len(start) != 1 or len(end) != 1 or start[0] >= end[0]:
            raise ValueError('invalid_dispatch_compatibility')
        return b''.join(lines[:start[0]]) + replacement + b''.join(lines[end[0]+1:])

    def git_blob(data):
        return sha1(('blob %d\0' % len(data)).encode() + data).hexdigest()

    try:
        package = Path(__file__).resolve().parent
        root = package.parent
        paths = [p for p in package.rglob('*')
                 if p.is_file() and p.suffix in ('.py', '.json')
                 and 'catalogs' not in p.relative_to(package).parts]
        paths.extend(p for p in (root / 'scripts/combine_ics.py',
                                 root / 'scrapers/growthzone.py',
                                 root / 'scrapers/lib/jsonld.py',
                                 root / 'scrapers/lib/base.py',
                                 root / 'scrapers/lib/utils.py',
                                 root / 'scrapers/lib/tribe_events.py',
                                 root / 'source_priority.json',
                                 root / 'requirements.txt') if p.is_file())
        digest = sha256()
        restored = set()
        for path in sorted(paths):
            name = path.relative_to(root).as_posix()
            data = path.read_bytes()
            if name == 'roomquest/category_worker.py':
                data = strip_block(data, 'EVE159_DISPATCH_CONTEXT')
                if git_blob(data) != '14f449eb0e9a4d5de30fd53c7ba6f1bc7f392300':
                    return None
                restored.add(name)
            elif name == 'roomquest/registered_html_checkpoint.py':
                data = strip_block(data, 'EVE159_PREDECESSOR_CONTEXT')
                data = strip_block(data, 'EVE159_PREDECESSOR_DECODE',
                                   b'        state = _decode(source, checkpoint, context, at=at)\n')
                if git_blob(data) != 'e2be0a2b358916d6633643920858b637f373b268':
                    return None
                restored.add(name)
            digest.update(name.encode('utf-8') + b'\0')
            digest.update(data)
            digest.update(b'\0')
        if len(restored) != 2:
            return None
        for dependency in ('icalendar', 'recurring-ical-events', 'python-dateutil',
                           'beautifulsoup4', 'feedparser', 'lxml', 'tzdata', 'x-wr-timezone'):
            try:
                installed = version(dependency)
            except PackageNotFoundError:
                installed = 'absent'
            digest.update((dependency + '=' + installed + '\0').encode('utf-8'))
        return fingerprint({'version': CONTEXT_VERSION, 'parser': digest.hexdigest(),
                            'source_key': source['source_key'],
                            'feed_url': source['feed_url'], 'adapter': 'html'})
    except (OSError, ValueError, KeyError, TypeError):
        return None


# END EVE159_PREDECESSOR_CONTEXT
def _source(source):
    if not enabled(source):
        raise ValueError('html_calendar_capture_not_admitted')
    url = _registered_url(source)
    from roomquest import forestry_england
    if forestry_england.owns_url(url):
        raise ValueError('html_calendar_capture_unsupported')
    return url


def _decode(source, checkpoint, context, *, at=None):
    state = codec.decode(source, checkpoint, at=at)
    if (set(state) != {'started_at', 'events', 'context', 'progress', 'pages'}
            or state['events'] != [] or state['context'] != context):
        raise ValueError('html_calendar_capture_context_changed')
    plan = progress.validate(state['progress'], source_key=source['source_key'],
                             feed_url=source['feed_url'], adapter='html', at=at)
    if (state['started_at'] != plan['started_at']
            or plan['allowed_hosts'] != [urlsplit(source['feed_url']).hostname]
            or type(state['pages']) is not list
            or len(state['pages']) != plan['cursor']
            or checkpoint['cursor'] != plan['cursor']
            or checkpoint['manifest_count'] != len(plan['tasks'])
            or checkpoint['record_count'] != 0 or checkpoint['stage_cursor'] != 0
            or (checkpoint['phase'] == 'stage') != plan['terminal_verified']):
        raise ValueError('html_calendar_capture_invalid')
    for page, receipt in zip(state['pages'], plan['receipts']):
        if (not isinstance(page, dict) or set(page) != {'url', 'body'}
                or not isinstance(page['body'], str)
                or page['url'] != receipt['url']
                or sha256(page['body'].encode()).hexdigest() != receipt['sha256']):
            raise ValueError('html_calendar_capture_invalid')
    return state


def collect_chunk(source, fetch, *, checkpoint=None, listing=None,
                  deadline_at=None, max_requests=MAX_REQUESTS, at=None):
    url = _source(source)
    if type(max_requests) is not int or not 1 <= max_requests <= MAX_REQUESTS:
        raise ValueError('html_calendar_capture_invalid')
    if listing is not None and checkpoint is not None:
        raise ValueError('html_calendar_capture_invalid')
    context = context_hash(source)
    if checkpoint is not None:
        # BEGIN EVE159_PREDECESSOR_DECODE
        try:
            state = _decode(source, checkpoint, context, at=at)
        except ValueError as exc:
            if str(exc) != 'html_calendar_capture_context_changed':
                raise
            previous = _dispatch_predecessor_context(source)
            if previous is None:
                raise
            state = _decode(source, checkpoint, previous, at=at)
        # END EVE159_PREDECESSOR_DECODE
    else:
        start = codec.now(at).date()
        plan = progress.new(source['source_key'], url, 'html', [url],
                            allowed_hosts=[urlsplit(url).hostname],
                            start=start, end=start + timedelta(days=59), at=at)
        # Codec's record_count is deliberately zero. There is no second event
        # ledger here; ordinary incremental staging owns all normalized rows.
        state = {'started_at': plan['started_at'], 'events': [],
                 'context': context, 'progress': plan, 'pages': []}
    plan = state['progress']
    stream, request, rows = resume_capture(source, state['pages'], deadline_at=deadline_at)
    expected = progress.next_request(plan, at=at)
    if ((request is None) != progress.complete(plan, at=at)
            or (request is not None and request[0] != expected)):
        raise ValueError('html_calendar_capture_invalid')

    requests = 0
    while request is not None and requests < max_requests:
        if deadline_at is not None and monotonic() >= deadline_at - 1:
            if plan['cursor']:
                break
            raise ValueError('collection_deadline')
        target, accept = request
        try:
            if listing is not None:
                body, listing = listing, None
            else:
                body = fetch(target, accept)
        except ValueError as exc:
            # A finite transport pacing/deadline wait is a continuation, not
            # permission to ignore a publisher denial or another error.
            if plan['cursor'] and str(exc) in ('publisher_pacing_deferred',
                                                'source_fetch_deadline',
                                                'publisher_rate_limited'):
                break
            raise
        if not isinstance(body, str):
            raise ValueError('html_calendar_payload_invalid')
        # The ordinary traversal establishes the next exact request before
        # the receipt advances. A failed or truncated response is never saved.
        try:
            next_request = stream.send(body)
        except StopIteration as done:
            next_request, rows = None, done.value
        except ValueError as exc:
            if plan['cursor'] and str(exc) == 'collection_deadline':
                break
            raise
        plan = progress.advance(plan, target, sha256(body.encode()).hexdigest(),
                                next_link=next_request[0] if next_request else None,
                                next_link_scope_verified=next_request is not None,
                                terminal=next_request is None, at=at)
        state['pages'].append({'url': target, 'body': body})
        state['progress'] = plan
        request = next_request
        requests += 1
    complete = progress.complete(plan, at=at)
    if not plan['cursor']:
        raise ValueError('collection_deadline')
    if complete:
        if not isinstance(rows, list):
            raise ValueError('html_calendar_capture_invalid')
        for row in rows:
            validate_record(row, source)
    envelope = codec.encode(source, state, phase='stage' if complete else 'fetch',
                            cursor=plan['cursor'], count=len(plan['tasks']))
    return {'checkpoint': envelope, 'complete': complete,
            'events': rows if complete else None, 'requests': requests}


def read(source, category, ticket, rpc):
    args = {'p_category': category, 'p_ticket': ticket,
            'p_source_key': source['source_key']}
    saved = rpc('community_collector_read_fetch_checkpoint', args, timeout=6)
    if (not isinstance(saved, dict) or type(saved.get('revision')) is not int
            or saved['revision'] < 0 or 'checkpoint' not in saved
            or (saved['checkpoint'] is None) != (saved['revision'] == 0)
            or (saved['checkpoint'] is not None and not isinstance(saved['checkpoint'], dict))):
        raise ValueError('fetch_checkpoint_invalid_response')
    return saved


def collect_and_save(source, fetch, rpc, pacing, *, category, ticket,
                     deadline_at, listing=None, saved=None):
    if category not in ('registration', 'html') or not isinstance(ticket, str) or not ticket:
        raise ValueError('fetch_checkpoint_context_missing')
    _source(source)
    saved = read(source, category, ticket, rpc) if saved is None else saved
    chunk = collect_chunk(source, fetch, checkpoint=saved['checkpoint'],
                          listing=listing, deadline_at=deadline_at)
    if pacing['wait_unbounded']:
        raise ValueError('publisher_wait_requires_review')
    ack = rpc('community_collector_write_fetch_checkpoint', {
        'p_category': category, 'p_ticket': ticket,
        'p_source_key': source['source_key'],
        'p_expected_revision': saved['revision'],
        'p_checkpoint': chunk['checkpoint'], **pacing_rpc_fields(pacing)}, timeout=8)
    if (not isinstance(ack, dict) or ack.get('checkpoint_saved') is not True
            or type(ack.get('revision')) is not int
            or ack['revision'] != saved['revision'] + 1):
        raise ValueError('fetch_checkpoint_invalid_response')
    return chunk
