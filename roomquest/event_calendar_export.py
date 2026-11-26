"""Read event-bound facts from a publisher's calendar export link, without visiting Google."""
from datetime import datetime, timezone
import html
import re
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bs4 import BeautifulSoup


def evidence(page, url, identity):
    if not isinstance(identity, dict) or identity.get('adapter') != 'event_discovery':
        return None
    if url != identity.get('event_url'):
        return None
    soup = BeautifulSoup(page, 'html.parser')
    canonical = soup.select('link[rel="canonical"][href]')
    og_url = soup.select('meta[property="og:url"][content]')
    if canonical:
        if len(canonical) != 1 or canonical[0]['href'] != url:
            return None
    elif len(og_url) != 1 or og_url[0]['content'] != url:
        return None
    title = html.unescape(str(identity.get('event_title') or '')).strip()
    if not title:
        return None
    try:
        expected = datetime.fromisoformat(identity['starts_at'].replace('Z', '+00:00'))
        if expected.utcoffset() is None:
            return None
    except (ValueError, TypeError, KeyError):
        return None
    answers = {}
    for anchor in soup.select('a[href]'):
        try:
            link = urlsplit(anchor['href'])
            if (link.scheme != 'https' or link.hostname not in ('www.google.com', 'calendar.google.com')
                    or link.path not in ('/calendar/event', '/calendar/render')):
                continue
            query = parse_qs(link.query, keep_blank_values=True)
            if any(len(query.get(key, [])) != 1 for key in ('action', 'text', 'dates', 'ctz', 'location')):
                continue
            if query['action'][0] != 'TEMPLATE' or html.unescape(query['text'][0]).strip() != title:
                continue
            dates = query['dates'][0].split('/')
            if len(dates) != 2 or not all(re.fullmatch(r'\d{8}T\d{6}', d) for d in dates):
                continue
            zone = ZoneInfo(query['ctz'][0])
            start = datetime.strptime(dates[0], '%Y%m%dT%H%M%S').replace(tzinfo=zone)
            if (start.utcoffset() != start.replace(fold=1).utcoffset()
                    or start.astimezone(timezone.utc).astimezone(zone) != start
                    or start.astimezone(timezone.utc) != expected.astimezone(timezone.utc)):
                continue
            parts = [p.strip() for p in query['location'][0].split(',')]
            if (len(parts) != 4 or parts[3].upper() not in ('US', 'USA', 'UNITED STATES')
                    or not re.fullmatch(r'[A-Z]{2}', parts[2])
                    or not re.fullmatch(r'\d{1,6}[A-Za-z]?\s+[A-Za-z][A-Za-z0-9 .\x27-]{1,120}', parts[0])
                    or not re.fullmatch(r'[A-Za-z][A-Za-z .\x27-]{1,60}', parts[1])):
                continue
            address = ', '.join(parts[:3])
            answer = {'address': address, 'evidence_url': url,
                      'evidence_name': identity.get('original_venue_name') or address,
                      'method': 'event_calendar_export', 'calendar_start': start.astimezone(timezone.utc).isoformat()}
            answers[(address, answer['calendar_start'])] = answer
        except (ValueError, TypeError, ZoneInfoNotFoundError):
            continue
    return next(iter(answers.values())) if len(answers) == 1 else None
