"""Independent demand lanes. Credentials and one-use tickets stay server-side."""
import errno
import json
import logging
import re
import socket
import ssl
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
import requests
from roomquest.collector_errors import failure_details
from roomquest.linked_event_descriptions import PROFILES as LINKED_DESCRIPTION_PROFILES
from roomquest.atlantic_city_library_chamber import CHECKPOINT_KEYS as ATLANTIC_LIBRARY_CHECKPOINT_KEYS
from roomquest.atlantic_city_nightlife_more import CHECKPOINT_KEYS as ATLANTIC_NIGHTLIFE_CHECKPOINT_KEYS
from roomquest.atlantic_city_studio import CHECKPOINT_KEYS as ATLANTIC_STUDIO_CHECKPOINT_KEYS
from roomquest.atlantic_city_cardboard_arena import CHECKPOINT_KEYS as ATLANTIC_CARDBOARD_CHECKPOINT_KEYS
from roomquest.atlantic_city_local_venues import CHECKPOINT_KEYS as ATLANTIC_LOCAL_VENUE_CHECKPOINT_KEYS
from roomquest.preview_worker import PreviewError, supabase_rpc, _process_claimed_source
from roomquest import national_feed_worker

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
                         'community_collector_openactive_state',
                         'community_collector_record_staged_events',
                         'community_collector_stage_incremental',
                         'community_collector_complete_incremental',
                         'community_collector_record_preview',
                         'community_collector_record_preview_v2',
                         'community_collector_record_preview_v3',
                         'community_collector_publish_category',
                         'community_collector_finish_category'))
# This is an explicit diagnostic vocabulary, not a shape-only exception-message
# filter: even a secret that happens to look like a code must not reach logs.
_ERROR_CODES = frozenset(('database_unavailable', 'staging_deadline', 'incremental_receipt_invalid',
    'registered_native_source_invalid', 'registered_native_capability_required',
    'registered_native_event_identity_invalid', 'registered_native_description_too_long',
    'registered_native_evidence_invalid',
    'atlantic_fair_clock_changed',
    'atlantic_fair_date_changed',
    'atlantic_fair_description_incomplete',
    'atlantic_fair_description_shape_changed',
    'atlantic_fair_detail_identity',
    'atlantic_fair_detail_missing',
    'atlantic_fair_detail_schedule_changed',
    'atlantic_fair_event_identity',
    'atlantic_fair_manifest_changed',
    'atlantic_fair_manifest_incomplete',
    'atlantic_fair_page_identity',
    'atlantic_fair_payload_changed',
    'atlantic_fair_record_limit',
    'atlantic_fair_timezone_required',
    'atlantic_fair_venue_changed',
    'balic_clock_missing',
    'balic_description_limit',
    'balic_description_missing',
    'balic_invalid_image',
    'balic_manifest_changed',
    'balic_page_changed',
    'balic_page_identity',
    'balic_performer_clock_changed',
    'balic_performer_clock_conflict',
    'balic_performer_description_conflict',
    'balic_performer_eligibility_changed',
    'balic_performer_identity_changed',
    'balic_performer_json_changed',
    'balic_performer_occurrence_missing',
    'balic_performer_year_changed',
    'balic_poster_edition_changed',
    'balic_program_eligibility_changed',
    'balic_source_identity',
    'balic_timezone_required',
    'balic_venue_changed',
    'inland_calendar_edition_unreviewed',
    'inland_clock_invalid',
    'inland_description_limit',
    'inland_listing_identity_changed',
    'inland_program_description_changed',
    'inland_program_manifest_changed',
    'inland_record_incomplete',
    'inland_registration_changed',
    'inland_venue_context_changed',
    'unregistered_atlantic_remaining_fair_source',
    'unregistered_atlantic_remaining_inland_source',
    'atlantic_local_community_description_invalid',
    'atlantic_local_community_identity_changed',
    'atlantic_local_community_time_changed',
    'atlantic_local_recreation_clock_conflict',
    'atlantic_local_recreation_duplicate_identity',
    'atlantic_local_recreation_record_limit',
    'brigantine_document_shape_changed',
    'brigantine_drop_in_manifest_changed',
    'brigantine_drop_in_policy_changed',
    'brigantine_edition_unreviewed',
    'brigantine_native_text_missing',
    'brigantine_program_clock_changed',
    'brigantine_program_clock_conflict',
    'brigantine_program_description_changed',
    'brigantine_program_term_changed',
    'brigantine_program_weekday_missing',
    'invalid_atlantic_local_recreation_html',
    'invalid_brigantine_pdf',
    'local_markets_clock_invalid',
    'local_markets_clock_review_changed',
    'local_markets_detail_limit',
    'local_markets_duplicate_occurrence',
    'local_markets_event_identity',
    'local_markets_full_description_mismatch',
    'local_markets_incomplete_parse',
    'local_markets_incomplete_snapshot',
    'local_markets_schedule_conflict',
    'local_markets_snapshot_changed',
    'local_markets_street_missing',
    'local_markets_timezone_changed',
    'local_markets_venue_changed',
    'local_markets_venue_point_invalid',
    'local_markets_wix_calendar_changed',
    'local_markets_wix_clock_changed',
    'local_markets_wix_description_container_changed',
    'local_markets_wix_description_shape_changed',
    'local_markets_wix_incomplete_manifest',
    'local_markets_wix_recurrence_unreviewed',
    'local_venue_calendar_date_conflict',
    'local_venue_checkpoint_invalid',
    'local_venue_checkpoint_size_limit',
    'local_venue_clock_conflict',
    'local_venue_clock_invalid',
    'local_venue_clock_missing',
    'local_venue_date_invalid',
    'local_venue_date_missing_or_ambiguous',
    'local_venue_description_container_changed',
    'local_venue_description_date_conflict',
    'local_venue_description_limit',
    'local_venue_description_incomplete',
    'local_venue_description_missing',
    'local_venue_detail_identity',
    'local_venue_duplicate_identity',
    'local_venue_event_identity',
    'local_venue_location_changed',
    'local_venue_manifest_incomplete',
    'local_venue_manifest_invalid',
    'local_venue_nonpublic_or_cancelled',
    'local_venue_nonpublic_or_sold_out',
    'local_venue_participation_changed',
    'local_venue_schedule_conflict',
    'local_venue_schedule_unverified',
    'local_venue_ticket_identity_unverified',
    'local_venue_undated_edition_requires_review',
    'local_venue_weekday_conflict',
    'newday_calendar_edition_unreviewed',
    'newday_calendar_identity_changed',
    'newday_description_changed',
    'newday_listing_changed',
    'njshorerun_context_year_unresolved',
    'njshorerun_dated_run_changed',
    'njshorerun_description_or_date_changed',
    'njshorerun_meeting_place_unreviewed',
    'njshorerun_page_identity_changed',
    'njshorerun_save_the_date_changed',
    'njshorerun_unreviewed_meetup_manifest',
    'njshorerun_weekday_conflict',
    'njshorerun_weekly_manifest_changed',
    'ocean_library_clock_mismatch',
    'ocean_library_closure_metadata_changed',
    'ocean_library_duplicate_identity',
    'ocean_library_event_identity_changed',
    'ocean_library_manifest_changed',
    'ocean_library_manifest_incomplete',
    'ocean_library_payload_changed',
    'ocean_library_venue_changed',
    'unregistered_atlantic_city_local_venue',
    'unregistered_atlantic_local_community_source',
    'unregistered_atlantic_local_markets_source',
    'unregistered_atlantic_local_recreation_source',
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
    'invalid_calendar_render_parameters', 'invalid_visit_raleigh_request', 'calendar_render_redirect_blocked',
    'invalid_calendar_render_content_type',
    'adapter_requires_configuration', 'source_timezone_required', 'park_code_missing',
    'park_catalog_incomplete', 'unverified_park_calendar_identifier',
    'unregistered_html_calendar'))


def _error_code(error):
    if not isinstance(error, PreviewError):
        return 'unexpected_error'
    value = error.args[0] if len(error.args) == 1 else None
    from roomquest import new_york_sources, boston_sources, raleigh_direct_sources
    if type(value) is str and (value in _ERROR_CODES
            or value in new_york_sources.diagnostic_codes()
            or value in boston_sources.diagnostic_codes()
            or value in raleigh_direct_sources.diagnostic_codes()
            or re.fullmatch(r'publisher_http_[1-5][0-9]{2}', value)):
        return value
    return 'unclassified_preview_error'


def _error_type(error):
    # Never emit a custom exception class/module name or call str/repr(error).
    for family, label in ((PreviewError, 'PreviewError'), (HTTPError, 'HTTPError'),
            (URLError, 'URLError'),
            (requests.exceptions.ConnectTimeout, 'RequestsConnectTimeout'),
            (requests.exceptions.ReadTimeout, 'RequestsReadTimeout'),
            (requests.exceptions.Timeout, 'RequestsTimeout'),
            (requests.exceptions.SSLError, 'RequestsSSLError'),
            (requests.exceptions.ConnectionError, 'RequestsConnectionError'),
            (requests.exceptions.RequestException, 'RequestsRequestException'),
            (TimeoutError, 'TimeoutError'),
            (ConnectionError, 'ConnectionError'), (PermissionError, 'PermissionError'),
            (OSError, 'OSError'), (json.JSONDecodeError, 'JSONDecodeError'),
            (TypeError, 'TypeError'), (ValueError, 'ValueError'), (KeyError, 'KeyError'),
            (IndexError, 'IndexError'), (RuntimeError, 'RuntimeError')):
        if isinstance(error, family):
            return label
    return 'Exception'


# Only established numeric network/verification codes may enter diagnostics.
# These are not ranges: an arbitrary integer on a custom exception is omitted.
_NETWORK_ERRNOS = frozenset(getattr(errno, name) for name in (
    'EACCES', 'EPERM', 'ECONNABORTED', 'ECONNREFUSED', 'ECONNRESET', 'EHOSTUNREACH',
    'ENETDOWN', 'ENETRESET', 'ENETUNREACH', 'EPIPE', 'ETIMEDOUT'))
_DNS_ERRNOS = frozenset(getattr(socket, name) for name in (
    'EAI_AGAIN', 'EAI_FAIL', 'EAI_NONAME', 'EAI_SYSTEM'))
# OpenSSL X509 verification codes: issuer, validity, trust chain, revocation,
# hostname/IP mismatch and weak key/signature failures. No messages are logged.
_TLS_VERIFY_CODES = frozenset((2, 9, 10, 18, 19, 20, 21, 23, 62, 64, 66, 67, 68))


def _url_error_details(error):
    """Describe one urllib reason using closed labels and allowlisted integers.

    Never stringify a reason, read its message/URL, inspect arbitrary exception
    attributes or follow an unbounded cause chain. This observes the existing
    failure; it does not retry a request or alter any transport/security setting.
    """
    try:
        transport = error.__cause__ if isinstance(error.__cause__, URLError) else error
        if not isinstance(transport, URLError) or isinstance(transport, HTTPError):
            return {}
        reason = transport.reason
        labels = ((ssl.SSLCertVerificationError, 'SSLCertVerificationError'),
                  (ssl.SSLEOFError, 'SSLEOFError'), (ssl.SSLError, 'SSLError'),
                  (socket.gaierror, 'gaierror'), (TimeoutError, 'TimeoutError'),
                  (ConnectionRefusedError, 'ConnectionRefusedError'),
                  (ConnectionResetError, 'ConnectionResetError'),
                  (ConnectionAbortedError, 'ConnectionAbortedError'),
                  (BrokenPipeError, 'BrokenPipeError'), (ConnectionError, 'ConnectionError'),
                  (PermissionError, 'PermissionError'), (OSError, 'OSError'))
        label = next((label for family, label in labels if isinstance(reason, family)),
                     'string' if type(reason) is str else 'unknown')
        result = {'url_reason_type': label}
        if isinstance(reason, ssl.SSLCertVerificationError):
            value = getattr(reason, 'verify_code', None)
            if type(value) is int and value in _TLS_VERIFY_CODES:
                result['tls_verify_code'] = value
        elif isinstance(reason, socket.gaierror):
            value = reason.errno
            if type(value) is int and value in _DNS_ERRNOS:
                result['dns_errno'] = value
        elif isinstance(reason, OSError) and not isinstance(reason, ssl.SSLError):
            value = reason.errno
            if type(value) is int and value in _NETWORK_ERRNOS:
                result['network_errno'] = value
        return result
    except Exception:
        # A malformed diagnostic attribute must not suppress the base record.
        return {}


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
            record.update(_url_error_details(error))
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
    from roomquest import new_york_sources, boston_sources, raleigh_direct_sources
    from roomquest.anchorage_batch20_wasilla import KEY as wasilla_key
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
                if isinstance(source.get('incremental_snapshot'), dict):
                    process_args['collection_context'] = args
                if national_feed_worker.handles(source):
                    process_args['collection_context'] = args
                    process_args['publisher_handoff'] = publisher_handoff
                if category == 'html':
                    process_args['publisher_handoff'] = publisher_handoff
                    # BEGIN EVE159_DISPATCH_CONTEXT
                    from roomquest import registered_html_checkpoint
                    if registered_html_checkpoint.enabled(source):
                        process_args['collection_context'] = args
                    # END EVE159_DISPATCH_CONTEXT
                    if ((source.get('source_key') in ('discover_halifax_va', 'visit_atlantic_city_nj', 'noyes_arts_atlantic_city_nj', 'atlantic_city_municipal_nj', 'greatday_atlantic_city_nj', 'visit_raleigh_nc')
                            or source.get('source_key') == wasilla_key
                            or source.get('source_key') in LINKED_DESCRIPTION_PROFILES
                            or source.get('source_key') in ATLANTIC_LIBRARY_CHECKPOINT_KEYS
                            or source.get('source_key') in ATLANTIC_NIGHTLIFE_CHECKPOINT_KEYS
                            or source.get('source_key') in ATLANTIC_STUDIO_CHECKPOINT_KEYS
                            or source.get('source_key') in ATLANTIC_CARDBOARD_CHECKPOINT_KEYS
                            or source.get('source_key') in ATLANTIC_LOCAL_VENUE_CHECKPOINT_KEYS
                            or source.get('source_key') in new_york_sources.checkpoint_keys()
                            or source.get('source_key') in boston_sources.checkpoint_keys()
                            or source.get('source_key') in raleigh_direct_sources.checkpoint_keys())
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
                if result.get('publication_required') is False:
                    # The lease-fenced completion has already renewed complete
                    # membership. A missing flag keeps the legacy publish call.
                    outcome = 'complete'
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

