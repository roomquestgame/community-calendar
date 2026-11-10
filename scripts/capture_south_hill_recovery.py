#!/usr/bin/env python3
"""Read-only transport preflight for the unfinished South Hill source cohort.

Registered adapters use preview_source. Candidate websites use the exact same
publisher transport with robots, DNS, host, size and deadline guards unchanged.
Fetching an unparsed page never marks it ready. This script has no database
credentials, demand, source activation, staging, image probes or publication.

The output contains bounded receipts only, not publisher page bodies. It keeps
prior source holds separate from the outcome of this one observation.
"""

from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from time import monotonic
from urllib.error import HTTPError
from urllib.parse import urlsplit


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SOURCES = {
    'discover_halifax_va': {
        'url': 'https://gohalifaxva.com/events/',
        'kind': 'html', 'adapter': 'html', 'chunks': True,
        'prior_hold': 'seven_day_window_excluded_later_occurrences',
    },
    'shady_shack_bracey_va': {
        'url': 'https://shadyshackgrill.com/bracey-shady-shack-bar-and-grill-events',
        'kind': 'html', 'adapter': 'html',
        'prior_hold': 'owner_year_rule_and_collector_transport_require_validation',
    },
    'south_hill_chamber_va': {
        'url': 'https://members.southhillchamber.com/calendar',
        'kind': 'html', 'adapter': 'html', 'prior_hold': 'publisher_http_403',
    },
    'coopers_landing_clarksville_va': {
        'url': 'https://cooperslandinginn.net/?page_id=119',
        'kind': 'html', 'adapter': 'html', 'prior_hold': 'robots_denied',
    },
    'mecklenburg_va_libraries': {
        'url': 'https://calendar.google.com/calendar/ical/mecklib.org%40gmail.com/public/basic.ics',
        'kind': 'ical', 'adapter': 'ical', 'prior_hold': 'robots_denied',
    },
    'municipal_chambermaster_halifax_va': {
        'url': 'https://www.halifaxchamber.net/api/events',
        'kind': 'xml', 'adapter': 'growthzone', 'prior_hold': 'source_refresh_requires_validation',
    },
    'colonial_center': {
        'url': 'https://colonialcenterva.org/upcoming-shows/',
        'prior_hold': 'collector_access_unverified',
    },
    'colonial_center_ludus': {
        'url': 'https://colonialcenter.ludus.com/index.php?sections=events',
        'prior_hold': 'publisher_http_403',
    },
    'pine_knot_farms': {
        'url': 'https://www.pineknotfarms.com/events/',
        'prior_hold': 'collector_and_policy_unverified',
    },
    'shineforth_eventbrite': {
        'url': 'https://www.eventbrite.com/e/south-hill-community-open-house-tickets-2003457708939',
        'prior_hold': 'publisher_rate_limited',
    },
    'svcc_campus_events': {
        'url': 'https://southside.edu/campus-events',
        'prior_hold': 'public_local_occurrences_unverified',
    },
}

PER_SOURCE_SECONDS = 40
HALIFAX_SECONDS = 240
OVERALL_SECONDS = 540
MAX_HALIFAX_CHUNKS = 40
MAX_RECORDS = 500


def _bounded_error(error, preview_worker):
    value = error.args[0] if isinstance(error, (preview_worker.PreviewError, ValueError)) and len(error.args) == 1 else ''
    return value if isinstance(value, str) and re.fullmatch(r'[a-z_0-9]{3,100}', value) else 'source_preflight_failed'


def _http_status(error):
    seen = set()
    for _ in range(6):
        if error is None or id(error) in seen:
            break
        seen.add(id(error))
        if isinstance(error, HTTPError) and 100 <= error.code <= 599:
            return error.code
        response = getattr(error, 'response', None)
        status = getattr(response, 'status_code', None)
        if type(status) is int and 100 <= status <= 599:
            return status
        error = error.__cause__
    return None


def _source(key, definition):
    return {'source_key': key, 'feed_url': definition['url'],
            'kind': definition['kind'], 'platform_adapter': definition['adapter'],
            'timezone': 'America/New_York'}


def _halifax_preview(source, preview_worker, deadline, row):
    """Exercise the new complete-only path without a ticket or database write.

    A checkpoint lives only in this audit's memory. Every chunk uses ordinary
    guarded publisher access and validates the listing again. Partial events
    never become a parsed/healthy source, even after some chunks succeeded.
    """
    from roomquest import discover_halifax

    checkpoint = None
    row.update(snapshot_complete=False, chunk_count=0, accounted_count=0)
    for number in range(1, MAX_HALIFAX_CHUNKS + 1):
        if monotonic() + discover_halifax.MIN_DETAIL_SECONDS >= deadline:
            raise preview_worker.PreviewError('collection_deadline')
        chunk_deadline = min(deadline, monotonic() + 36)
        result = discover_halifax.collect_chunk(
            source,
            lambda url, accept: preview_worker.fetch_publisher(
                url, accept, respect_robots=True, allowed_hosts=('gohalifaxva.com',),
                deadline_at=chunk_deadline),
            checkpoint=checkpoint, deadline_at=chunk_deadline,
        )
        if monotonic() >= deadline:
            raise preview_worker.PreviewError('collection_deadline')
        if (not isinstance(result, dict) or type(result.get('complete')) is not bool
                or not isinstance(result.get('events'), list)
                or not isinstance(result.get('checkpoint'), dict)):
            raise preview_worker.PreviewError('snapshot_shape_missing')
        next_state = result['checkpoint']
        cursor, count = next_state.get('cursor'), next_state.get('manifest_count')
        if (type(cursor) is not int or type(count) is not int
                or not 0 <= cursor <= count <= discover_halifax.MAX_CARDS):
            raise preview_worker.PreviewError('snapshot_checkpoint_invalid')
        row.update(chunk_count=number, accounted_count=cursor, manifest_count=count,
                   manifest_hash=next_state.get('manifest_hash'),
                   window_start=next_state.get('window_start'))
        print(json.dumps({'source_key': source['source_key'], 'chunk': number,
                          'accounted_count': cursor, 'manifest_count': count,
                          'snapshot_complete': result['complete']}), flush=True)
        if result['complete']:
            if cursor != count:
                raise preview_worker.PreviewError('snapshot_completion_mismatch')
            decisions = next_state.get('diagnostics', [])
            if not isinstance(decisions, list) or len(decisions) > discover_halifax.MAX_CARDS * 2:
                raise preview_worker.PreviewError('snapshot_checkpoint_invalid')
            row.update(snapshot_complete=True, decisions=decisions,
                       held_count=sum(item.get('disposition') == 'held' for item in decisions),
                       excluded_count=sum(item.get('disposition') == 'excluded' for item in decisions),
                       warning_count=sum(item.get('disposition') == 'warning' for item in decisions))
            return {'p_error': None, 'p_events': result['events'],
                    'p_parser_capability': 'publisher_event_candidates_v1'}
        if result['events']:
            raise preview_worker.PreviewError('snapshot_partial_events_exposed')
        if checkpoint and next_state == checkpoint:
            raise preview_worker.PreviewError('snapshot_no_progress')
        checkpoint = next_state
    raise preview_worker.PreviewError('snapshot_chunk_limit')


def _candidate_receipt(event):
    # Public normalized occurrence facts, not publisher page bodies or database
    # payloads. Full event prose and all transport headers remain out of output.
    fields = ('id', 'title', 'starts_at', 'ends_at', 'timezone', 'venue_name',
              'venue_address', 'venue_city', 'event_url', 'image_url',
              'publisher_status', 'publisher_details', 'location_provenance')
    return {key: event[key] for key in fields if key in event}


def audit(keys):
    receipt = {
        'schema_version': 2,
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'read_only': True,
        'authoritative_state_unchanged': True,
        'collection_ready': False,
        'limits': {'per_source_seconds': PER_SOURCE_SECONDS,
                   'halifax_seconds': HALIFAX_SECONDS,
                   'overall_seconds': OVERALL_SECONDS, 'max_records': MAX_RECORDS,
                   'max_halifax_chunks': MAX_HALIFAX_CHUNKS},
        'sources': [],
    }
    try:
        from roomquest import preview_worker
    except ModuleNotFoundError as error:
        module = error.name or ''
        receipt.update(
            complete=False,
            environment_error='dependency_unavailable',
            missing_module=module if re.fullmatch(r'[a-zA-Z0-9_.]{1,80}', module) else 'unknown',
        )
        return receipt

    overall = monotonic() + OVERALL_SECONDS
    for key in keys:
        definition = SOURCES[key]
        started = monotonic()
        row = {
            'source_key': key,
            'feed_url': definition['url'],
            'prior_hold': definition['prior_hold'],
            'hold_cleared': False,
            'mode': ('complete_halifax_chunks' if definition.get('chunks') else
                     'preview_source' if 'kind' in definition else 'guarded_unparsed_content'),
            'candidate_only': 'kind' not in definition,
        }
        try:
            if started >= overall:
                raise preview_worker.PreviewError('collection_deadline')
            budget = HALIFAX_SECONDS if definition.get('chunks') else PER_SOURCE_SECONDS
            deadline = min(overall, started + budget)
            if 'kind' in definition:
                source = _source(key, definition)
                result = (_halifax_preview(source, preview_worker, deadline, row)
                          if definition.get('chunks') else
                          preview_worker.preview_source(source, deadline_at=deadline))
                if monotonic() >= deadline:
                    raise preview_worker.PreviewError('collection_deadline')
                if not isinstance(result, dict) or 'p_error' not in result or 'p_events' not in result:
                    raise preview_worker.PreviewError('snapshot_shape_missing')
                if result['p_error'] is not None:
                    raise preview_worker.PreviewError(result['p_error'])
                events = result['p_events']
                if (not isinstance(events, list) or len(events) > MAX_RECORDS
                        or any(not isinstance(event, dict) for event in events)):
                    raise preview_worker.PreviewError('snapshot_records_invalid')
                if ((definition['kind'] == 'html' or definition['adapter'] == 'growthzone')
                        and result.get('p_parser_capability') != 'publisher_event_candidates_v1'):
                    raise preview_worker.PreviewError('snapshot_capability_missing')
                row.update(
                    outcome='parsed',
                    candidate_count=len(events),
                    candidate_image_count=sum(bool(event.get('image_url')) for event in events),
                    parser_capability=result.get('p_parser_capability'),
                    candidates=[_candidate_receipt(event) for event in events],
                )
            else:
                payload = preview_worker.fetch_publisher(
                    definition['url'], 'text/html', respect_robots=True,
                    allowed_hosts=(urlsplit(definition['url']).hostname,),
                    deadline_at=deadline,
                )
                if monotonic() >= deadline:
                    raise preview_worker.PreviewError('collection_deadline')
                encoded = payload.encode('utf-8') if isinstance(payload, str) else payload
                row.update(
                    outcome='fetched_unparsed',
                    body_bytes=len(encoded),
                    body_sha256=hashlib.sha256(encoded).hexdigest(),
                )
        except Exception as error:
            code = ('dependency_unavailable' if isinstance(error, ModuleNotFoundError)
                    else _bounded_error(error, preview_worker))
            row.update(outcome='blocked', error=code)
            row['failure_category'] = (
                'environment_dependency' if code == 'dependency_unavailable' else
                'environment_dns' if code == 'dns_unavailable' else
                'network_guard' if code == 'non_public_dns' else
                'publisher_policy' if code == 'robots_denied' else
                'publisher_rate_limit' if code == 'publisher_rate_limited' else
                'publisher_access' if code.startswith('publisher_http_') else
                'transport_unavailable' if code == 'robots_unavailable' else
                'deadline' if code in ('collection_deadline', 'source_fetch_deadline') else
                'parser_or_runtime'
            )
            if isinstance(error, ModuleNotFoundError):
                module = error.name or ''
                row['missing_module'] = module if re.fullmatch(r'[a-zA-Z0-9_.]{1,80}', module) else 'unknown'
            if code in ('dns_unavailable', 'non_public_dns'):
                row.update(failure_stage='dns', publisher_http_not_attempted=True)
            status = _http_status(error)
            if status is not None:
                row['observed_http_status'] = status
        row['duration_seconds'] = round(monotonic() - started, 3)
        receipt['sources'].append(row)
        print(json.dumps({key: value for key, value in row.items()
                          if key not in ('candidates', 'decisions')}), flush=True)
    receipt['complete'] = all(row['outcome'] in ('parsed', 'fetched_unparsed') for row in receipt['sources'])
    receipt['counts'] = {
        'parsed': sum(row['outcome'] == 'parsed' for row in receipt['sources']),
        'fetched_unparsed': sum(row['outcome'] == 'fetched_unparsed' for row in receipt['sources']),
        'blocked': sum(row['outcome'] == 'blocked' for row in receipt['sources']),
        'environment_dns': sum(row.get('failure_category') == 'environment_dns' for row in receipt['sources']),
        'environment_dependency': sum(row.get('failure_category') == 'environment_dependency' for row in receipt['sources']),
        'parsed_future_candidates': sum(row.get('candidate_count', 0) for row in receipt['sources']),
    }
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', action='append', choices=tuple(SOURCES),
                        help='One or more exact sources; omitted means the bounded cohort.')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(list(dict.fromkeys(args.source or SOURCES)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: result.get(key) for key in (
        'schema_version', 'checked_at', 'read_only', 'authoritative_state_unchanged',
        'complete', 'collection_ready', 'counts', 'environment_error', 'missing_module',
    )}), flush=True)
    return 0 if result['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
