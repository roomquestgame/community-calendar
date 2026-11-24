"""Evidence-only signatures for publisher calendars without a supported feed.

These signals improve registration diagnostics; they do not authorize requests,
register endpoints, or turn a publisher widget into a complete event snapshot.
An actual supported feed always wins via the existing registration classifier.
"""
import re

MAX_SIGNAL_CHARS = 500_000


def unsupported_calendar_profile(html):
    """Return a precise unsupported family, never a collector/approval decision.

    Capture both ends of a large HTML response because embed scripts commonly
    live in the document footer. The existing fetcher owns payload limits.
    """
    if not isinstance(html, str) or not html.lstrip('\ufeff \t\r\n').startswith('<'):
        return None
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
    return None
