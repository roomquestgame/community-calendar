"""Evidence-only calendar platform signatures.

The registration checker already owns access, supported feed validation and
publication. This module only reports unsupported calendar families when no
existing family or publisher-linked feed has been verified.
"""
import re

MAX_SIGNAL_CHARS = 500_000


def unsupported_calendar_profile(html):
    """A descriptive technical hold, never an authorized collector endpoint."""
    if not isinstance(html, str) or not html.lstrip('\ufeff \t\r\n').startswith('<'):
        return None

    # Embed scripts may be near the bottom of a long document.
    fragment = (html[:MAX_SIGNAL_CHARS] + '\n' + html[-MAX_SIGNAL_CHARS:]).casefold()
    if ('elfsight-app-' in fragment and
            ('elfsightcdn.com/platform.js' in fragment or
             'apps.elfsight.com/p/platform.js' in fragment)):
        return 'elfsight_adapter_needed'
    if ('system.spektrix.com/' in fragment and
            re.search(r'/api/v[23]/(?:events|instances)\b', fragment)):
        return 'spektrix_adapter_needed'
    if (re.search(r'\b(?:new\s+)?fullcalendar\.calendar\s*\(', fragment) and
            re.search(r'\bevents\s*:', fragment)):
        return 'fullcalendar_adapter_needed'
    if ('data-tockify-calendar=' in fragment and
            'public.tockify.com/browser/embed.js' in fragment):
        return 'tockify_adapter_needed'
    if ('venuepilot.com' in fragment
            and (re.search(r'venuepilot\.com/[^"\']*(?:widget|event)', fragment)
                 or '#/events' in fragment)):
        return 'venuepilot_adapter_needed'
    if re.search(r'https://[a-z0-9.-]+\.myvscloud\.com/webtrac/web/search\.html(?:[?&"\']|$)',
                 fragment):
        return 'webtrac_adapter_needed'
    # Multiple publisher-rendered TicketWeb event links identify a linked
    # ticketing inventory, not merely a footer or one-off purchase button.
    if len(set(re.findall(
            r'https://(?:www\.)?ticketweb\.com/event/[a-z0-9_%./?=&-]+', fragment))) >= 2:
        return 'ticketweb_linked_events_adapter_needed'
    # A Wix application shell is its own platform signal.  Test it before
    # WordPress plugin names because Wix warmup JSON can contain arbitrary
    # publisher-authored text and bundled asset names.  Native Wix Events and
    # custom/static Wix calendars require different completeness contracts.
    if ('id="wix-warmup-data"' in fragment or "id='wix-warmup-data'" in fragment):
        from roomquest.wix_public_events import WIX_EVENTS
        if WIX_EVENTS in fragment:
            return 'wix_events_adapter_needed'
        return 'wix_custom_page_adapter_needed'
    # WordPress event publishers may advertise legacy plugin fingerprints
    # even without a readable events API. Report a *technical hold*, not a
    # feed. Specific plugin families are more useful than a CMS generator.
    from roomquest.wordpress_capabilities import wordpress_fingerprints
    matches = wordpress_fingerprints(html)
    family_reasons = {
        'the-events-calendar': 'the_events_calendar_adapter_needed',
        'events-manager': 'events_manager_adapter_needed',
        'event-organiser': 'event_organiser_adapter_needed',
        'modern-events-calendar': 'mec_adapter_needed',
        'eventon': 'eventon_adapter_needed',
        'wp-event-manager': 'wp_event_manager_adapter_needed',
        'all-in-one-event-calendar': 'ai1ec_adapter_needed',
        'tickera': 'tickera_adapter_needed',
        'event-discovery': 'event_discovery_adapter_needed',
        'legacy-json-api': 'wordpress_legacy_json_adapter_needed',
    }
    if len(matches) == 1 and matches[0] in family_reasons:
        return family_reasons[matches[0]]
    if (matches or re.search(r'/wp-content/(?:plugins|themes)/|'
                             r'<meta[^>]{0,250}generator[^>]{0,250}wordpress', fragment)
            or ('<link' in fragment and 'https://api.w.org/' in fragment)):
        return 'wordpress_calendar_adapter_needed'
    return None


def annotate_unsupported(result, html):
    """Add a platform-specific reason to an existing technical review only.

    Call after the normal native feed and HTML collection recovery. Preserve
    source scope, access denials, and all other outcome/hold categories.
    """
    if (not isinstance(result, dict) or result.get('p_outcome') != 'review'
            or result.get('p_reason') not in ('html_adapter_needed', 'no_reusable_calendar')):
        return result
    reason = unsupported_calendar_profile(html)
    if not reason:
        return result
    return dict(result, p_reason=reason, p_type='html')
