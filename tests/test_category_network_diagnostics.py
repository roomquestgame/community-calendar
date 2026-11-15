"""Network failure classification must never weaken fetch or logging guards."""
import errno
import json
import socket
import ssl
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

from roomquest import category_worker as worker
from roomquest import preview_worker as preview
from roomquest.preview_worker import PreviewError


SECRET = 'private-token https://private.invalid/event?secret=private-body'


def wrapped(reason):
    error = PreviewError('robots_unavailable')
    error.__cause__ = URLError(reason)
    return error


def certificate_error(code):
    reason = ssl.SSLCertVerificationError(1, SECRET)
    reason.verify_code = code
    reason.verify_message = SECRET
    return reason


def records(caplog):
    return [json.loads(entry.getMessage()) for entry in caplog.records
            if entry.name == 'roomquest.category_worker']


@pytest.mark.parametrize('reason,expected', [
    (certificate_error(20), {'url_reason_type': 'SSLCertVerificationError', 'tls_verify_code': 20}),
    (ssl.SSLEOFError(8, SECRET), {'url_reason_type': 'SSLEOFError'}),
    (ssl.SSLError(1, SECRET), {'url_reason_type': 'SSLError'}),
    (socket.gaierror(socket.EAI_AGAIN, SECRET), {'url_reason_type': 'gaierror', 'dns_errno': socket.EAI_AGAIN}),
    (socket.gaierror(socket.EAI_NONAME, SECRET), {'url_reason_type': 'gaierror', 'dns_errno': socket.EAI_NONAME}),
    (TimeoutError(errno.ETIMEDOUT, SECRET), {'url_reason_type': 'TimeoutError', 'network_errno': errno.ETIMEDOUT}),
    (ConnectionRefusedError(errno.ECONNREFUSED, SECRET), {'url_reason_type': 'ConnectionRefusedError', 'network_errno': errno.ECONNREFUSED}),
    (ConnectionResetError(errno.ECONNRESET, SECRET), {'url_reason_type': 'ConnectionResetError', 'network_errno': errno.ECONNRESET}),
    (ConnectionAbortedError(errno.ECONNABORTED, SECRET), {'url_reason_type': 'ConnectionAbortedError', 'network_errno': errno.ECONNABORTED}),
    (BrokenPipeError(errno.EPIPE, SECRET), {'url_reason_type': 'BrokenPipeError', 'network_errno': errno.EPIPE}),
    (ConnectionError(SECRET), {'url_reason_type': 'ConnectionError'}),
    (PermissionError(errno.EACCES, SECRET), {'url_reason_type': 'PermissionError', 'network_errno': errno.EACCES}),
    (OSError(errno.ENETUNREACH, SECRET), {'url_reason_type': 'OSError', 'network_errno': errno.ENETUNREACH}),
    (SECRET, {'url_reason_type': 'string'}),
    (None, {'url_reason_type': 'unknown'}),
    ((20, SECRET), {'url_reason_type': 'unknown'}),
])
def test_nested_reason_emits_only_closed_labels_and_codes(caplog, reason, expected):
    error = wrapped(reason)
    original_args, original_cause = error.args, error.__cause__
    diagnostic = worker._Diagnostics('html')
    diagnostic.source({'source_id': 5610})
    diagnostic.observe('fetch', error=error)
    record, = records(caplog)
    assert {key: record[key] for key in expected} == expected
    assert record['error_code'] == 'robots_unavailable'
    assert record['cause_type'] == 'URLError'
    assert record['error_kind'] == 'transient'
    assert record['source_id'] == 5610
    assert error.args is original_args and error.__cause__ is original_cause
    assert original_cause.reason is reason
    assert 'private' not in caplog.text and 'https://' not in caplog.text
    assert all(entry.exc_info is None for entry in caplog.records)


@pytest.mark.parametrize('value', [-1, 0, 999999, True, '20', None])
def test_unrecognized_tls_codes_are_omitted(value):
    assert worker._url_error_details(wrapped(certificate_error(value))) == {
        'url_reason_type': 'SSLCertVerificationError'}


@pytest.mark.parametrize('family,expected', [(OSError, 'OSError'), (socket.gaierror, 'gaierror')])
@pytest.mark.parametrize('value', [-999999, 999999, True, '110', None])
def test_unknown_or_noninteger_errno_is_omitted(family, expected, value):
    reason = family(SECRET)
    reason.errno = value
    assert worker._url_error_details(wrapped(reason)) == {'url_reason_type': expected}


def test_direct_urlerror_is_classified_but_http_error_is_not(caplog):
    error = URLError(ConnectionResetError(errno.ECONNRESET, SECRET))
    worker._Diagnostics('html').report(error)
    record, = records(caplog)
    assert record['url_reason_type'] == 'ConnectionResetError'
    assert record['network_errno'] == errno.ECONNRESET
    assert record['error_type'] == 'URLError'
    http = HTTPError('https://private.invalid/', 403, SECRET, {'X-Private': SECRET}, None)
    assert worker._url_error_details(http) == {}
    outer = PreviewError('robots_denied')
    outer.__cause__ = http
    assert worker._url_error_details(outer) == {}


def test_custom_reason_names_messages_and_properties_are_not_logged(caplog):
    class PrivateExceptionName(Exception):
        def __str__(self):
            raise AssertionError('Must not stringify private exception')

        def __repr__(self):
            raise AssertionError('Must not repr private exception')

        @property
        def errno(self):
            raise AssertionError('Unknown reason attributes must not be inspected')

    worker._Diagnostics('html').report(wrapped(PrivateExceptionName(SECRET)))
    record, = records(caplog)
    assert record['url_reason_type'] == 'unknown'
    assert 'PrivateExceptionName' not in caplog.text and 'private' not in caplog.text


def test_malformed_native_subclass_attribute_preserves_base_record(caplog):
    class CustomCertificateError(ssl.SSLCertVerificationError):
        @property
        def verify_code(self):
            raise RuntimeError(SECRET)

    worker._Diagnostics('html').report(wrapped(CustomCertificateError(SECRET)))
    record, = records(caplog)
    assert record['error_code'] == 'robots_unavailable'
    assert record['cause_type'] == 'URLError'
    assert 'url_reason_type' not in record and 'private' not in caplog.text


def test_diagnostics_keep_existing_three_record_and_identity_limits(caplog):
    diagnostic = worker._Diagnostics('html')
    errors = [wrapped(TimeoutError(SECRET)) for _ in range(4)]
    diagnostic.report(errors[0])
    diagnostic.report(errors[0])
    for error in errors[1:]:
        diagnostic.report(error)
    assert len(records(caplog)) == 3
    assert len(diagnostic.reported) == 3


def test_source_failure_keeps_one_attempt_recording_finish_and_no_publication(caplog):
    calls = []
    error = wrapped(certificate_error(20))

    def rpc(path, data, **kwargs):
        calls.append((path, data))
        if path == 'community_collector_claim_category':
            return {'action': 'collect', 'source_key': 'fixture', 'source_id': 5610,
                    'kind': 'html', 'platform_adapter': 'html'}
        return True

    with patch.object(worker, 'supabase_rpc', side_effect=rpc), \
            patch.object(preview, 'supabase_rpc', side_effect=rpc), \
            patch.object(preview, 'preview_source', side_effect=error) as fetch:
        result = worker.collect_category('html', 'private-ticket')
    assert result == {'category': 'html', 'claimed': 1, 'complete': 0, 'failed': 1,
                      'staged': 0, 'failure_scope': 'source', 'error_kind': 'transient',
                      'error_code': 'robots_unavailable'}
    fetch.assert_called_once()
    assert [path for path, _ in calls] == ['community_collector_claim_category',
        'community_collector_record_preview_v2', 'community_collector_finish_category']
    assert calls[-1][1]['p_outcome'] == 'source_error'
    record, = records(caplog)
    assert record['phase'] == 'fetch' and record['tls_verify_code'] == 20
    assert 'private' not in caplog.text


def test_logging_failure_preserves_source_failure_and_finish():
    error = wrapped(socket.gaierror(socket.EAI_AGAIN, SECRET))
    with patch.object(worker, 'supabase_rpc', side_effect=[{'action': 'publish'}, error, True]) as rpc, \
            patch.object(worker._LOGGER, 'warning', side_effect=RuntimeError(SECRET)):
        with pytest.raises(PreviewError) as caught:
            worker.collect_category('html', 'private-ticket')
    assert caught.value is error
    assert rpc.call_args_list[-1].args == ('community_collector_finish_category',
        {'p_category': 'html', 'p_ticket': 'private-ticket', 'p_outcome': 'failed'})
