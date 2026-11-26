"""Discover Tockify's public publisher-wide iCalendar subscription."""
import re
from urllib.parse import quote


EMBED = 'public.tockify.com/browser/embed.js'
CALENDAR = re.compile(r'\bdata-tockify-calendar\s*=\s*(["\'])([A-Za-z0-9._-]{1,100})\1', re.I)


def subscription(page):
    """Return one exact advertised Tockify calendar as its public ICS feed."""
    if not isinstance(page, str) or EMBED not in page.casefold():
        return None
    identifiers = {match[2] for match in CALENDAR.finditer(page)}
    if len(identifiers) != 1:
        return None
    identifier = next(iter(identifiers))
    return 'https://tockify.com/api/feeds/ics/' + quote(identifier, safe='._-')
