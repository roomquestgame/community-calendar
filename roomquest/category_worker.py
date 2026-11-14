"""Independent demand lanes. Credentials and one-use tickets stay server-side."""
import json
import logging
import re
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from roomquest.collector_errors import failure_details
from roomquest.linked_event_descriptions import PROFILES as LINKED_DESCRIPTION_PROFILES
from roomquest.atlantic_city_library_chamber import CHECKPOINT_KEYS as ATLANTIC_LIBRARY_CHECKPOINT_KEYS
from roomquest.atlantic_city_nightlife_more import CHECKPOINT_KEYS as ATLANTIC_NIGHTLIFE_CHECKPOINT_KEYS
from roomquest.atlantic_city_studio import CHECKPOINT_KEYS as ATLANTIC_STUDIO_CHECKPOINT_KEYS
from roomquest.atlantic_city_cardboard_arena import CHECKPOINT_KEYS as ATLANTIC_CARDBOARD_CHECKPOINT_KEYS
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
    'atlantic_studio_checkpoint_invalid',
    'atlantic_studio_checkpoint_size_limit',
    'atlantic_studio_clock_conflict',
    'atlantic_studio_detail_identity',
    'atlantic_studio_detail_invalid',
    'atlantic_studio_duplicate_session',
    'atlantic_studio_eligibility_invalid',
    'atlantic_studio_html_invalid',
    'atlantic_studio_instructions_invalid',
    'atlantic_studio_location_changed',
    'atlantic_studio_manifest_invalid',
    'atlantic_studio_session_identity',
    'cardboard_calendar_shape_changed',
    'cardboard_checkpoint_invalid',
    'cardboard_checkpoint_size_limit',
    'cardboard_description_limit',
    'cardboard_description_missing',
    'cardboard_detail_changed',
    'cardboard_event_identity_changed',
    'cardboard_manifest_incomplete',
    'cardboard_public_calendar_identity_changed',
    'cardboard_public_renderer_required',
    'cardboard_schedule_changed',
    'collection_deadline',
    'invalid_cardboard_calendar_parameters',
    'invalid_publisher_image',
    'invalid_publisher_image_content_type',
    'publisher_checkpoint_required',
    'publisher_description_limit',
    'publisher_description_missing',
    'reviewed_poster_description_limit',
    'reviewed_poster_description_missing',
    'reviewed_poster_duplicate_identity',
    'reviewed_poster_edition_changed',
    'reviewed_poster_freshness_expired',
    'reviewed_poster_gallery_changed',
    'reviewed_poster_gallery_incomplete',
    'reviewed_poster_invalid_image',
    'reviewed_poster_manifest_changed',
    'reviewed_poster_page_changed',
    'reviewed_poster_page_identity',
    'reviewed_poster_record_limit',
    'reviewed_poster_script_changed',
    'reviewed_poster_source_identity',
    'reviewed_poster_timezone_required',
    'reviewed_poster_venue_changed',
    'source_record_limit',
    'unregistered_atlantic_studio_source',
    'unregistered_cardboard_arena_source',
    'fetch_checkpoint_context_missing', 'fetch_checkpoint_invalid_response',
    'halifax_checkpoint_invalid', 'halifax_checkpoint_size_limit',
    'halifax_directory_incomplete', 'halifax_directory_event_identity',
    'halifax_directory_detail_identity', 'halifax_directory_detail_conflict',
    'unregistered_linked_description_source', 'linked_description_checkpoint_invalid',
    'linked_description_manifest_invalid', 'linked_description_checkpoint_size_limit',
    'rockhouse_detail_identity_mismatch', 'rockhouse_detail_structure_missing',
    'invalid_downtown_norfolk_detail_identity', 'invalid_downtown_norfolk_detail_content',
    'invalid_sandler_detail_identity', 'invalid_sandler_detail_content',
    'unregistered_visit_atlantic_city', 'visit_atlantic_checkpoint_invalid',
    'visit_atlantic_checkpoint_required', 'visit_atlantic_checkpoint_size_limit',
    'visit_atlantic_description_limit', 'visit_atlantic_detail_dates',
    'visit_atlantic_detail_identity', 'visit_atlantic_detail_structure',
    'visit_atlantic_duplicate_occurrence', 'visit_atlantic_event_limit',
    'visit_atlantic_manifest_limit', 'visit_atlantic_sitemap_invalid',
    'noyes_checkpoint_invalid', 'noyes_checkpoint_size_limit',
    'publisher_detail_limit', 'publisher_next_event_cycle',
    'publisher_calendar_identity_changed', 'publisher_calendar_date_missing',
    'publisher_event_detail_changed', 'publisher_calendar_link_changed',
    'publisher_event_time_changed', 'invalid_event_end',
    'publisher_next_event_changed', 'publisher_event_identity_changed',
    'publisher_description_limit', 'unregistered_atlantic_city_community_source',
    'municipal_calendar_limit', 'municipal_calendar_identity_changed',
    'municipal_event_identity_changed', 'municipal_event_schedule_changed',
    'municipal_checkpoint_invalid', 'municipal_checkpoint_size_limit',
    'publisher_checkpoint_required',
    'unregistered_greatday_source', 'greatday_pagination_invalid',
    'greatday_upcoming_collection_changed', 'greatday_card_identity_changed',
    'greatday_event_identity', 'greatday_card_date_invalid',
    'greatday_duplicate_identity', 'greatday_record_limit', 'greatday_detail_date_invalid',
    'greatday_detail_identity_changed', 'greatday_detail_schedule_changed',
    'greatday_detail_location_changed', 'greatday_checkpoint_invalid',
    'greatday_checkpoint_size_limit', 'atlantic_city_description_limit',
    'unregistered_atlantic_city_stockton_source', 'stockton_event_time_changed',
    'stockton_event_year_unresolved', 'stockton_calendar_result_limit',
    'stockton_calendar_duplicate_conflict', 'stockton_calendar_program_ambiguous',
    'stockton_calendar_shape_changed', 'stockton_event_identity_changed',
    'unregistered_atlantic_pdf_source', 'invalid_atlantic_pdf_document',
    'atlantic_pdf_page_limit', 'atlantic_pdf_text_unavailable',
    'atlantic_pdf_edition_unreviewed', 'atlantic_pdf_schedule_changed',
    'invalid_atlantic_pdf_listing', 'atlantic_pdf_document_conflict',
    'atlantic_pdf_venue_changed', 'atlantic_pdf_conditions_changed',
    'atlantic_pdf_description_changed',
    'atlantic_cape_conflicting_occurrence',
    'atlantic_cape_filters_changed',
    'atlantic_cape_identity_changed',
    'atlantic_cape_location_changed',
    'atlantic_cape_occurrence_changed',
    'atlantic_cape_occurrence_time_conflict',
    'atlantic_cape_occurrence_time_unresolved',
    'atlantic_cape_occurrences_missing',
    'atlantic_cape_pagination_changed',
    'atlantic_cape_pagination_limit',
    'atlantic_cape_payload_changed',
    'atlantic_cape_snapshot_incomplete',
    'atlantic_library_checkpoint_invalid',
    'atlantic_library_checkpoint_size_limit',
    'atlantic_library_checkpoint_source',
    'atlantic_nightlife_checkpoint_invalid',
    'atlantic_nightlife_checkpoint_size_limit',
    'atlantic_nightlife_description_missing',
    'atlantic_nightlife_duplicate_occurrence',
    'atlantic_nightlife_event_identity',
    'atlantic_nightlife_event_limit',
    'chamber_event_identity_changed',
    'chamber_identity_changed',
    'chamber_payload_changed',
    'conflicting_event_occurrence',
    'eht_trot_clock_conflict',
    'eht_trot_clock_unresolved',
    'eht_trot_description_missing',
    'eht_trot_event_identity_changed',
    'eht_trot_manifest_changed',
    'eht_trot_snapshot_incomplete',
    'eht_trot_source_identity_changed',
    'eht_trot_status_changed',
    'eht_trot_venue_changed',
    'federation_event_identity_changed',
    'federation_pagination_duplicate',
    'federation_pagination_identity_changed',
    'federation_pagination_invalid',
    'federation_payload_invalid',
    'federation_timezone_changed',
    'garden_state_calendar_changed',
    'garden_state_calendar_incomplete',
    'garden_state_calendar_time_conflict',
    'garden_state_calendar_venue_changed',
    'hard_rock_calendar_schedule_changed',
    'hard_rock_calendar_venue_changed',
    'hard_rock_detail_identity_changed',
    'hard_rock_detail_schedule_changed',
    'hard_rock_detail_status_changed',
    'jfs_calendar_changed',
    'jfs_description_container_changed',
    'jfs_detail_identity_changed',
    'jfs_detail_schedule_changed',
    'jfs_event_identity_changed',
    'margate_closure_range_invalid',
    'margate_event_date_invalid',
    'margate_feed_changed',
    'source_record_limit',
    'atlantic_city_description_missing',
    'atlantic_city_incomplete_event',
    'atlantic_city_record_limit',
    'atlantic_markets_gaming_calendar_changed',
    'atlantic_markets_gaming_description_limit',
    'atlantic_markets_gaming_description_missing',
    'atlantic_markets_gaming_event_identity',
    'atlantic_markets_gaming_public_widget_changed',
    'atlantic_markets_gaming_recurrence_changed',
    'atlantic_markets_gaming_schedule_changed',
    'atlantic_markets_gaming_shape_changed',
    'atlantic_markets_gaming_venue_changed',
    'atlantic_recreation_clock_conflict',
    'atlantic_recreation_event_identity',
    'atlantic_recreation_timezone_missing',
    'atlantic_social_calendar_changed',
    'atlantic_social_duplicate_occurrence',
    'atlantic_social_event_identity_changed',
    'atlantic_social_record_limit',
    'atlantic_social_schedule_changed',
    'atlantic_social_venue_changed',
    'eht_activity_identity_changed',
    'eht_activity_schedule_changed',
    'eht_activity_schedule_conflict',
    'eht_calendar_date_conflict',
    'eht_calendar_venue_changed',
    'eht_calendar_window_changed',
    'eht_dated_calendar_missing',
    'eht_occurrence_clock_missing',
    'eht_occurrence_conflict',
    'eht_occurrence_schedule_conflict',
    'eht_program_identity_changed',
    'eht_program_notes_changed',
    'independent_venue_calendar_changed',
    'independent_venue_clock_missing',
    'independent_venue_description_container_changed',
    'independent_venue_detail_limit',
    'independent_venue_duplicate_occurrence',
    'independent_venue_event_identity',
    'independent_venue_full_description_unavailable',
    'independent_venue_incomplete_snapshot',
    'independent_venue_location_changed',
    'independent_venue_schedule_conflict',
    'independent_venue_snapshot_changed',
    'independent_venue_timezone_changed',
    'invalid_atlantic_city_payload',
    'invalid_atlantic_recreation_html',
    'invalid_ical_component',
    'invalid_ical_missing_start',
    'invalid_recreation_pdf',
    'invalid_wordpress_description',
    'invalid_wordpress_pagination',
    'oc_class_descriptions_changed',
    'oc_holiday_exceptions_changed',
    'oc_holiday_scope_expired',
    'oc_reservation_policy_changed',
    'oc_schedule_edition_unreviewed',
    'oc_venue_address_changed',
    'oc_water_description_changed',
    'publisher_description_missing',
    'recreation_pdf_page_limit',
    'recreation_pdf_text_unavailable',
    'recurrence_invalid',
    'unregistered_atlantic_independent_venue_source',
    'unregistered_atlantic_markets_gaming_source',
    'unregistered_atlantic_recreation_source',
    'unregistered_atlantic_social_source',
    'unsupported_dense_recurrence',
    'unsupported_wordpress_payload',
    'unregistered_atlantic_cape_source',
    'unregistered_atlantic_library_chamber_source',
    'unregistered_atlantic_nightlife_source',
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
                    if ((source.get('source_key') in ('discover_halifax_va', 'visit_atlantic_city_nj', 'noyes_arts_atlantic_city_nj', 'atlantic_city_municipal_nj', 'greatday_atlantic_city_nj')
                            or source.get('source_key') in LINKED_DESCRIPTION_PROFILES
                            or source.get('source_key') in ATLANTIC_LIBRARY_CHECKPOINT_KEYS
                            or source.get('source_key') in ATLANTIC_NIGHTLIFE_CHECKPOINT_KEYS
                            or source.get('source_key') in ATLANTIC_STUDIO_CHECKPOINT_KEYS
                            or source.get('source_key') in ATLANTIC_CARDBOARD_CHECKPOINT_KEYS)
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
