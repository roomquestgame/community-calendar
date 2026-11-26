from roomquest.calendar_profile_signals import annotate_unsupported

def test_native_unsupported_retry_retains_installed_provider_without_approval():
    from roomquest.registration_auto_defer import auto_defer_nonactionable, MONTH_SECONDS
    for plugin, provider in [('event-discovery', 'event_discovery'), ('tickera', 'tickera')]:
        html = '<script src="/wp-content/plugins/' + plugin + '/events.js"></script>'
        reason = provider + '_adapter_needed'
        annotated = annotate_unsupported({'p_outcome': 'review', 'p_reason': 'no_reusable_calendar'}, html)
        assert annotated['p_type'] == provider
        deferred = auto_defer_nonactionable(dict(annotated, p_endpoint='https://example.org/',
                                                p_profile={'unverified': True}, source_id=999))
        assert deferred == {'p_outcome': 'retry', 'p_reason': reason,
                            'p_retry_seconds': MONTH_SECONDS, 'p_type': provider}


def test_unsupported_native_metadata_does_not_promote_weak_or_mismatched_evidence():
    from roomquest.registration_auto_defer import auto_defer_nonactionable, MONTH_SECONDS
    base = {'p_outcome': 'review', 'p_reason': 'no_reusable_calendar'}
    weak = annotate_unsupported(base, '<p>Event Discovery and Tickera</p>')
    assert weak == base
    for reason, wrong in [('event_discovery_adapter_needed', 'html'),
                          ('event_discovery_adapter_needed', 'tickera'),
                          ('tickera_adapter_needed', 'event_discovery'),
                          ('wordpress_calendar_adapter_needed', 'wordpress')]:
        assert auto_defer_nonactionable({'p_outcome': 'review', 'p_reason': reason,
                                        'p_type': wrong}) == {
            'p_outcome': 'retry', 'p_reason': reason, 'p_retry_seconds': MONTH_SECONDS}


def test_native_plugin_annotation_keeps_access_and_valid_collection_outcomes():
    for outcome, reason in [('disabled', 'robots_denied'),
                            ('retry', 'source_network_error'),
                            ('review', 'venue_location_unresolved'),
                            ('verified', None)]:
        result = {'p_outcome': outcome, 'p_reason': reason, 'p_type': 'ical'}
        assert annotate_unsupported(result, '<script src="/wp-content/plugins/event-discovery/events.js"></script>') == result

def test_original_registration_receipt_retains_unsupported_native_identity():
    from unittest.mock import patch
    from roomquest import feed_registration
    for provider, plugin in [('event_discovery', 'event-discovery'), ('tickera', 'tickera')]:
        receipts = []
        def rpc(method, args, **kwargs):
            if method.endswith('claim_registration'):
                return {'url': 'https://publisher.example/'}
            if method.endswith('feed_profile'):
                return {}
            receipts.append(args)
            return True
        # Strong plugin asset, but no supported calendar contract/date snapshot.
        page = '<html><script src="/wp-content/plugins/' + plugin + '/events.js"></script></html>'
        with patch.object(feed_registration, 'supabase_rpc', rpc), \
             patch.object(feed_registration, 'fetch_publisher', return_value=page):
            assert feed_registration.register('ticket') == {'outcome': 'retry'}
        assert receipts[-1]['p_type'] == provider
        assert receipts[-1]['p_reason'] == provider + '_adapter_needed'
        assert receipts[-1]['p_outcome'] == 'retry'
        assert 'p_endpoint' not in receipts[-1]
        assert 'p_profile' not in receipts[-1]
