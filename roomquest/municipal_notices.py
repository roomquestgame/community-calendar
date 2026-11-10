"""Dated official Clarksville notices through the existing guarded collector.

This is the town's published news first page, not a general news-to-events
converter. Only an explicit dated service notice or timed council meeting is
eligible. Publication dates never supply event dates. No household route,
meeting venue, emergency alert, or missing year is inferred.
"""
from datetime import datetime, time, timedelta, timezone
import logging
import re
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record, timestamp

KEY = 'clarksville_municipal_notices_va'
URL = 'https://clarksvilleva.org/news/'
HOSTS = ('clarksvilleva.org',)
ZONE = 'America/New_York'
SOURCES = {KEY: URL}
MAX_ARTICLES = 30
MAX_DETAILS = 6
LOOKAHEAD_DAYS = 60
_LOG = logging.getLogger(__name__)
_MONTH = r'(?:January|February|March|April|May|June|July|August|September|October|November|December)'
_WEEKDAY = r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)'
_DATE = re.compile(rf'(?:(?P<weekday>{_WEEKDAY})\s*,?\s*)?(?P<month>{_MONTH})\s+'
                   r'(?P<day>\d{1,2})(?:\s*(?:st|nd|rd|th))?(?:\s*,?\s+(?P<year>20\d{2}))?', re.I)
_TIME = re.compile(r'\b(\d{1,2}):(\d{2})\s*([ap])\.?m\.?\b', re.I)


def source_payload():
    return {'source_key': KEY, 'feed_url': URL, 'kind': 'html',
            'platform_adapter': 'html', 'timezone': ZONE,
            'civic_contract_version': 1, 'civic_jurisdiction_id': 'us-va-clarksville'}


def validate(source):
    if (type(source.get('civic_contract_version')) is not int
            or any(source.get(key) != value for key, value in source_payload().items())):
        raise ValueError('unregistered_municipal_notice_source')
    return {'url': URL, 'hosts': HOSTS, 'scope': 'publisher_news_first_page'}


def _now(value=None):
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError('timezone_unresolved')
    return value.astimezone(timezone.utc)


def _check_deadline(deadline):
    if deadline is not None and monotonic() >= deadline:
        raise ValueError('collection_deadline')


def _url(value):
    if not isinstance(value, str):
        raise ValueError('municipal_notice_link_missing')
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or parsed.netloc != HOSTS[0] or parsed.query or parsed.fragment
            or not re.fullmatch(r'/[a-z0-9-]+/', parsed.path)
            or parsed.path in {'/news/', '/feed/', '/wp-admin/', '/wp-json/'}):
        raise ValueError('municipal_notice_link_mismatch')
    return value


def _dates(value, *, year=None, after=None):
    found = []
    for match in _DATE.finditer(value):
        selected_year = int(match['year']) if match['year'] else year
        if selected_year is None:
            raise ValueError('municipal_notice_year_missing')
        day = datetime.strptime(f"{match['month']} {match['day']} {selected_year}", '%B %d %Y').date()
        if after is not None and day < after and not match['year'] and after.month == 12 and day.month == 1:
            day = day.replace(year=day.year + 1)
        if match['weekday'] and match['weekday'].casefold() != day.strftime('%A').casefold():
            raise ValueError('municipal_notice_weekday_conflict')
        found.append(day)
    return found


def _notice_type(title):
    if re.search(r'\b(?:town hall|office)\b.*\bclosed\b', title, re.I):
        return 'closure'
    # "Leaf collection begins week of ..." does not publish an end or a
    # household collection date. General service news stays informational.
    if re.search(r'\btown council\b.*\bmeeting\b', title, re.I):
        return 'meeting'
    return None


def candidates(payload, *, now=None):
    current = _now(now).astimezone(ZoneInfo(ZONE)).date()
    if not isinstance(payload, str) or len(payload) > 3_000_000:
        raise ValueError('invalid_municipal_notice_payload')
    soup = BeautifulSoup(payload, 'html.parser')
    articles = soup.select('article.elementor-post')
    if not articles or len(articles) > MAX_ARTICLES:
        raise ValueError('municipal_notice_listing_shape_changed')
    selected, seen, held = [], set(), 0
    for article in articles:
        heading = article.select_one('.elementor-post__title a[href]')
        if heading is None:
            raise ValueError('municipal_notice_listing_shape_changed')
        title = heading.get_text(' ', strip=True)
        kind = _notice_type(title)
        if kind is None:
            continue
        ids = [part.removeprefix('post-') for part in article.get('class', []) if re.fullmatch(r'post-[1-9]\d*', part)]
        if len(ids) != 1 or ids[0] in seen:
            raise ValueError('municipal_notice_identity_conflict')
        seen.add(ids[0])
        try:
            dates = _dates(title)
            if len(dates) != 1:
                raise ValueError('municipal_notice_explicit_date_required')
            day = dates[0]
            end = day + timedelta(days=1)
            if end <= current or day > current + timedelta(days=LOOKAHEAD_DAYS):
                continue
            selected.append({'id': ids[0], 'title': title, 'day': day, 'kind': kind,
                             'url': _url(heading['href'])})
        except (ValueError, TypeError) as exc:
            held += 1
            _hold(ids[0], exc)
    if len(selected) > MAX_DETAILS:
        raise ValueError('municipal_notice_detail_limit')
    if held and not selected:
        raise ValueError('municipal_notice_evidence_unavailable')
    return selected


def _hold(identity, error):
    reason = str(error)
    if not re.fullmatch(r'[a-z_]{3,100}', reason):
        reason = 'invalid_municipal_notice_record'
    _LOG.warning('municipal_notice_held source=%s id=%s reason=%s', KEY, identity, reason)


def _metadata(url, current, valid_until, *, kind, topic, precision):
    return {'version': 1, 'kind': kind, 'topic': topic,
            'jurisdiction_id': 'us-va-clarksville', 'jurisdiction_name': 'Clarksville, Virginia',
            'applicability': 'jurisdiction', 'source_url': url,
            'verified_at': current.isoformat(),
            'valid_until': valid_until.astimezone(timezone.utc).isoformat(),
            'time_precision': precision, 'timezone': ZONE}


def parse_notice(payload, candidate, *, now=None):
    current = _now(now)
    url = _url(candidate['url'])
    if not isinstance(payload, str) or len(payload) > 3_000_000:
        raise ValueError('invalid_municipal_notice_payload')
    soup = BeautifulSoup(payload, 'html.parser')
    canonical = soup.select('link[rel="canonical"]')
    heading = soup.select_one('h1.elementor-heading-title')
    body = soup.select_one('.elementor-widget-theme-post-content .elementor-widget-container')
    if (len(canonical) != 1 or canonical[0].get('href') != url or heading is None or body is None
            or plain(heading.get_text(' ', strip=True)) != plain(candidate['title'])):
        raise ValueError('municipal_notice_detail_identity_mismatch')
    for node in body.select('script,style,form,nav'):
        node.decompose()
    description = plain(body.get_text(' ', strip=True))
    if not description:
        raise ValueError('municipal_notice_body_missing')
    announced_status = re.search(r'\b(cancelled|canceled|postponed)\b', candidate['title'], re.I)
    if announced_status:
        status = 'postponed' if announced_status[1].casefold() == 'postponed' else 'cancelled'
    elif re.search(r'\b(?:cancelled|canceled|postponed)\b', description, re.I):
        # A prose reference could concern another occurrence. Hold it rather
        # than leave an apparently scheduled record or infer cancellation.
        raise ValueError('municipal_notice_status_requires_review')
    else:
        status = 'scheduled'
    day, kind = candidate['day'], candidate['kind']
    identity = 'municipal:clarksville:' + candidate['id']
    if kind == 'meeting':
        times = list(_TIME.finditer(candidate['title']))
        if len(times) != 1 or not 1 <= int(times[0][1]) <= 12 or int(times[0][2]) > 59:
            raise ValueError('municipal_meeting_time_unresolved')
        hour = int(times[0][1]) % 12 + (12 if times[0][3].lower() == 'p' else 0)
        begins = timestamp(datetime.combine(day, time(hour, int(times[0][2]))).isoformat(), ZONE)
        row = record(candidate['title'], begins.isoformat(), None, '', '', '', url, identity,
                     'Civic & Public Services', tz=ZONE, retain_until_end=True)
        if row is None:
            return None
        # Existing app visibility fallback only, never a claimed meeting end.
        row['civic'] = _metadata(url, current, begins + timedelta(hours=3),
                                 kind='meeting', topic='government', precision='timed')
    elif kind == 'closure':
        closed = re.search(r'\b(?:town hall(?: office)?|office)\s+(?:will be|is)\s+closed\b([^.!?]{0,220})', description, re.I)
        if not closed or _dates(closed[1], year=day.year) != [day]:
            raise ValueError('municipal_closure_date_conflict')
        reopened = re.search(r'\b(?:office\s+)?will\s+re[- ]?open\b([^.!?]{0,180})', description, re.I)
        end = day + timedelta(days=1)
        if reopened:
            reopening_dates = _dates(reopened[1], year=day.year, after=day)
            if len(reopening_dates) != 1 or not day < reopening_dates[0] <= day + timedelta(days=14):
                raise ValueError('municipal_reopening_date_conflict')
            end = reopening_dates[0]
        if end <= current.astimezone(ZoneInfo(ZONE)).date():
            return None
        begins = datetime.combine(day, time(), ZoneInfo(ZONE))
        finishes = datetime.combine(end, time(), ZoneInfo(ZONE))
        row = {'id': identity, 'title': candidate['title'][:180],
               'starts_at': begins.astimezone(timezone.utc).isoformat(),
               'ends_at': finishes.astimezone(timezone.utc).isoformat(),
               'starts_on': day.isoformat(), 'ends_on': end.isoformat(),
               'venue_name': '', 'venue_address': '', 'venue_city': '',
               'lat': None, 'lng': None, 'event_url': url, 'category': 'Civic & Public Services',
               'reason': 'missing_verified_venue_geo',
               'civic': _metadata(url, current, finishes, kind='service',
                                  topic='public_services', precision='date')}
    else:
        raise ValueError('unsupported_municipal_notice_kind')
    row.update(description=description[:2000], timezone=ZONE,
               publisher_categories=['Civic & Public Services'], publisher_status=status)
    return row


def collect(source, fetch, *, deadline_at=None, now=None):
    validate(source)
    _check_deadline(deadline_at)
    current = _now(now)
    selected = candidates(fetch(URL, 'text/html'), now=current)
    rows, held = [], 0
    for item in selected:
        _check_deadline(deadline_at)
        # Required fetch failures fail the snapshot rather than swallowing a
        # transport error and calling an incomplete collection healthy.
        payload = fetch(item['url'], 'text/html')
        try:
            row = parse_notice(payload, item, now=current)
            if row is not None:
                rows.append(row)
        except (ValueError, TypeError, OverflowError) as exc:
            held += 1
            _hold(item['id'], exc)
    _check_deadline(deadline_at)
    if held and not rows:
        raise ValueError('municipal_notice_evidence_unavailable')
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))
