"""Independent demand lanes. Credentials and one-use tickets stay server-side."""
import json
import logging
import re
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from roomquest.collector_errors import failure_details
from roomquest.preview_worker import PreviewError, supabase_rpc, _process_claimed_source

CATEGORIES = frozenset(('ical', 'wordpress', 'jsonld', 'squarespace', 'library',
                        'rss', 'localist', 'socrata', 'chambermaster', 'chambermate', 'parks', 'html', 'revize'))

MAX_HANDOFF_WAIT_SECONDS = 2
FINISH_TIMEOUT_SECONDS = 5
# api/html_demand.py and api/category_demand.py both have maxDuration=60.
# Preserve additional time for response handling and invocation overhead.
INVOCATION_BUDGET_SECONDS = 60
FINISH_MARGIN_SECONDS = 3


def _wait_for_html_handoff(handoff, started):
    ready_at = handoff.get('ready_at')
    if ready_at is None:
        return
    remaining = ready_at - monotonic()
    if (0 < remaining <= MAX_HANDOFF_WAIT_SECONDS
            and ready_at + FINISH_TIMEOUT_SECONDS + FINISH_MARGIN_SECONDS
            <= started + INVOCATION_BUDGET_SECONDS):
        # Keep the existing host lease for a short wait outside any database
        # transaction. Longer waits still use the normal recovery mechanism.
        sleep(remaining)


_LOGGER = logging.getLogger(__name__)
_REPORTED = object()
_PHASES = frozenset(('dispatch', 'claim', 'fetch', 'stage', 'record', 'publish', 'finish'))
_OPERATIONS = frozenset(('community_collector_claim_category',
                         'community_collector_read_fetch_checkpoint',
                         'community_collector_write_fetch_checkpoint',
                         'community_collector_record_staged_events',
                         'community_collector_record_preview',
                         'community_collector_record_preview_v2',
                         'community_collector_record_preview_v3',
                         'community_collector_publish_category',
                         'community_collector_finish_category'))
# This is an explicit diagnostic vocabulary, not a shape-only exception-message
# filter: even a secret that happens to look like a code must not reach logs.
_ERROR_CODES = frozenset(('database_unavailable', 'staging_deadline',
    'fetch_checkpoint_context_missing', 'fetch_checkpoint_invalid_response',
    'halifax_checkpoint_invalid', 'halifax_checkpoint_size_limit',
    'halifax_directory_incomplete', 'halifax_directory_event_identity',
    'halifax_directory_detail_identity', 'halifax_directory_detail_conflict',
    'unregistered_discover_halifax', 'invalid_html_event_payload',
    'collector_not_configured', 'unsupported_collector_rpc', 'unsupported_category',
    'source_parse_error', 'invalid_calendar_payload', 'event_schedule_missing',
    'dns_unavailable', 'robots_unavailable', 'source_network_error',
    'source_fetch_deadline', 'collection_deadline', 'publisher_rate_limited',
    'publisher_pacing_deferred',
    'robots_denied', 'invalid_source_url', 'invalid_redirect_url', 'non_public_dns',
    'redirect_blocked', 'redirect_host_not_approved', 'redirect_missing_location',
    'too_many_redirects', 'publisher_wait_requires_review',
    'invalid_calendar_render_parameters', 'calendar_render_redirect_blocked',
    'invalid_calendar_render_content_type',
    'adapter_requires_configuration', 'source_timezone_required', 'park_code_missing',
    'park_catalog_incomplete', 'unverified_park_calendar_identifier',
    'unregistered_html_calendar'))


def _error_code(error):
    if not isinstance(error, PreviewError):
        return 'unexpected_error'
    value = error.args[0] if len(error.args) == 1 else None
    if type(value) is str and (value in _ERROR_CODES
            or re.fullmatch(r'publisher_http_[1-5][0-9]{2}', value)):
        return value
    return 'unclassified_preview_error'


def _error_type(error):
    # Never emit a custom exception class/module name or call str/repr(error).
    for family, label in ((PreviewError, 'PreviewError'), (HTTPError, 'HTTPError'),
            (URLError, 'URLError'), (TimeoutError, 'TimeoutError'),
            (ConnectionError, 'ConnectionError'), (PermissionError, 'PermissionError'),
            (OSError, 'OSError'), (json.JSONDecodeError, 'JSONDecodeError'),
            (TypeError, 'TypeError'), (ValueError, 'ValueError'), (KeyError, 'KeyError'),
            (IndexError, 'IndexError'), (RuntimeError, 'RuntimeError')):
        if isinstance(error, family):
            return label
    return 'Exception'


class _Diagnostics:
    """At most three safe failure records for one invocation, with no I/O retry."""
    def __init__(self, category):
        self.category = category if category in CATEGORIES else 'unknown'
        self.started = monotonic()
        self.phase, self.operation, self.source_id = 'dispatch', None, None
        self.reported = []

    def source(self, value):
        identity = value.get('source_id') if isinstance(value, dict) else None
        if type(identity) is int and 0 < identity <= 9223372036854775807:
            self.source_id = identity

    def observe(self, phase, *, operation=None, error=None):
        self.phase = phase if phase in _PHASES else 'dispatch'
        self.operation = operation if operation in _OPERATIONS else None
        if error is not None:
            self.report(error)

    def report(self, error):
        if any(error is previous for previous in self.reported) or len(self.reported) >= 3:
            return
        self.reported.append(error)
        try:
            code = _error_code(error)
            details = failure_details(code, expected_source_error=isinstance(error, PreviewError),
                                      phase='collection' if self.phase == 'fetch' else 'staging')
            record = {'event': 'collector_category_failure', 'category': self.category,
                      'phase': self.phase, **details, 'error_type': _error_type(error),
                      'elapsed_ms': min(120000, max(0, int((monotonic() - self.started) * 1000)))}
            if self.source_id is not None:
                record['source_id'] = self.source_id
            if self.operation is not None:
                record['rpc_operation'] = self.operation
            cause = error.__cause__
            if cause is not None:
                record['cause_type'] = _error_type(cause)
            transport = cause if isinstance(cause, HTTPError) else error
            if isinstance(transport, HTTPError) and type(transport.code) is int and 100 <= transport.code <= 599:
                record['upstream_http_status'] = transport.code
            _LOGGER.warning(json.dumps(record, separators=(',', ':'), sort_keys=True))
            # The HTTP fallback avoids repeating a worker record. Exception
            # identity, arguments, traceback and response semantics stay intact.
            setattr(error, '_collector_diagnostic_marker', _REPORTED)
        except Exception:
            # Observability must never replace the source/worker error, change a
            # return value or prevent the existing finally/finish operation.
            pass


def report_category_failure(category, error):
    """Safe fallback for an exception outside collect_category's observation."""
    try:
        if getattr(error, '_collector_diagnostic_marker', None) is not _REPORTED:
            _Diagnostics(category).report(error)
    except Exception:
        pass


def collect_category(category, ticket):
    diagnostics = _Diagnostics(category)
    try:
        if category not in CATEGORIES:
            raise PreviewError('unsupported_category')
        args = {'p_category': category, 'p_ticket': ticket}
        diagnostics.observe('claim', operation='community_collector_claim_category')
        source = supabase_rpc('community_collector_claim_category', args, timeout=8)
        diagnostics.source(source)
        if not source:
            diagnostics.observe('finish', operation='community_collector_finish_category')
            supabase_rpc('community_collector_finish_category', {**args, 'p_outcome': 'idle'}, timeout=5)
            return {'outcome': 'idle'}
        outcome = 'failed'
        result = {'category': category, 'claimed': 1}
        publisher_handoff = {}
        try:
            if source['action'] == 'collect':
                diagnostics.observe('fetch')
                process_args = {'deadline_at': diagnostics.started + 39,
                                'observe_phase': diagnostics.observe}
                if category == 'html':
                    process_args['publisher_handoff'] = publisher_handoff
                    if (source.get('source_key') == 'discover_halifax_va'
                            and type(source.get('fetch_checkpoint_version')) is int
                            and source['fetch_checkpoint_version'] == 1):
                        process_args['collection_context'] = args
                result.update(_process_claimed_source(source, **process_args))
                if result.get('fetch_pending'):
                    # The saved prefix is incomplete. Finishing this claim
                    # dispatches a source-bound fetch continuation, without
                    # staging certification or publishing a partial snapshot.
                    outcome = 'fetch_pending'
                    return result
                if result['failed']:
                    if category == 'html' and result.get('failure_scope') == 'source':
                        # The recorded source hold/retry owns its next attempt.
                        # Release this HTML slot without cooling other publishers.
                        outcome = 'source_error'
                    return result
            # A source-bound ten-row publication call, with a shared database cap.
            # Remaining rows retain their checkpoint and dispatch a continuation.
            diagnostics.observe('publish', operation='community_collector_publish_category')
            published = supabase_rpc('community_collector_publish_category', args, timeout=12)
            result['publication'] = published
            outcome = 'busy' if published.get('outcome') in ('busy', 'idle') else 'complete'
            if (category == 'ical' and source['action'] == 'collect'
                    and result.get('complete') == 1 and result.get('failed') == 0
                    and published.get('outcome') == 'idle'):
                # A recorded snapshot can await venue review without occupying
                # a collector slot. Preserve the publication result and hold;
                # finish still checks the durable successful pacing receipt.
                outcome = 'complete'
            return result
        except Exception as error:
            diagnostics.report(error)  # Preserve the primary phase before finish.
            raise
        finally:
            try:
                if category == 'html' and outcome in ('complete', 'source_error', 'fetch_pending'):
                    # A local handoff interruption is distinct from a failed
                    # finish RPC, so record it before that operation starts.
                    diagnostics.observe('finish')
                    try:
                        _wait_for_html_handoff(publisher_handoff, diagnostics.started)
                    except Exception as error:
                        diagnostics.report(error)
                        raise
            finally:
                # Preserve upstream's finish-once guarantee even when the
                # short publisher handoff wait is interrupted.
                diagnostics.observe('finish', operation='community_collector_finish_category')
                supabase_rpc('community_collector_finish_category',
                             {**args, 'p_outcome': outcome}, timeout=FINISH_TIMEOUT_SECONDS)
    except Exception as error:
        diagnostics.report(error)
        raise
