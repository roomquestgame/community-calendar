"""Bounded event-photo discovery/verification with durable future-refresh reuse."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import os
import re
import struct
from time import monotonic
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup
import requests

from roomquest.preview_worker import event_image, public_source_url, validate_public_dns, supabase_rpc, PreviewError
from roomquest.preview_worker import robots_allowed, _robots_request_path, pace_publisher, fetch_publisher
from roomquest.publisher_pacing import capture_publisher_pacing
from roomquest.venue_resolver import fetch_page, json_nodes, words

MIMES = {'image/jpeg', 'image/png', 'image/webp', 'image/gif', 'image/avif'}
MAX_IMAGE = 10_000_000
PROBE_SECONDS = 8
DETAIL_PAGE_SECONDS = 10
DETAIL_IMAGE_CAPABILITY = 'event_detail_image_version'
DETAIL_IMAGE_VERSION = 1


class MediaDeferred(PreviewError):
    """A temporary inability to check an image is not evidence of no image."""

    def __init__(self, reason, *, host=None, retry_after_seconds=30, attempted=False):
        super().__init__(reason)
        self.reason = reason
        self.host = canonical_host(host) if host else None
        self.retry_after_seconds = max(1, min(3600, int(retry_after_seconds)))
        self.attempted = bool(attempted)


class MediaPageUnavailable(PreviewError):
    """A denied/unavailable page does not prove the event has no photograph."""


def detail_image_claim(claim):
    """Accept only the backend's exact, separately negotiated detail-page work."""
    return (type(claim.get(DETAIL_IMAGE_CAPABILITY)) is int
            and claim[DETAIL_IMAGE_CAPABILITY] == DETAIL_IMAGE_VERSION
            and claim.get('candidate_only') is False
            and 'candidate_url' in claim and claim['candidate_url'] is None
            and isinstance(claim.get('source_key'), str) and bool(claim['source_key'])
            and isinstance(claim.get('title'), str) and bool(claim['title'].strip())
            and public_source_url(claim.get('event_url'))
            and claim.get('extraction_url') == claim['event_url'])


def canonical_host(host: str) -> str:
    """Match the backend's publisher-host key without changing request URLs."""
    return (host or '').lower().rstrip('.').removeprefix('www.')


def retry_after_seconds(value, *, default=60):
    """Honor a bounded Retry-After delay without waiting inside the invocation."""
    try:
        if str(value).strip().isdigit():
            seconds = int(str(value).strip())
        else:
            when = parsedate_to_datetime(str(value))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            seconds = math.ceil((when - datetime.now(timezone.utc)).total_seconds())
        return max(1, min(3600, seconds))
    except (TypeError, ValueError, OverflowError):
        return default


def _same_detail_url(value, url):
    """Compare declared event identity without authorizing another request."""
    if not isinstance(value, str) or not value.strip():
        return False
    expected, actual = urlparse(url), urlparse(urljoin(url, value))
    return (actual.scheme == expected.scheme
            and canonical_host(actual.hostname) == canonical_host(expected.hostname)
            and actual.port == expected.port
            and (actual.path.rstrip('/') or '/') == (expected.path.rstrip('/') or '/')
            and actual.query == expected.query)


def _specific_title_prefix(expected, actual):
    shortened = words(actual)
    return (len(shortened) >= 12 and len(set(shortened.split())) >= 3
            and expected.startswith(shortened + ' '))


def _page_image_candidate(value, url):
    from roomquest.registered_native_content import image_candidate

    candidate = image_candidate(value, url)
    if candidate and re.search(r'(?:^|[-_.])(?:logo|favicon|avatar|icon|map)(?:[-_.]|$)',
                               unquote(urlparse(candidate).path).rsplit('/', 1)[-1], re.I):
        return None
    if candidate and re.search(
            r'/(?:og[-_]?(?:image|default)|site[-_]logo|default(?:[-_]image)?|default[-_]event[-_]image|placeholder|'
            r'social[-_](?:image|thumbnail|share))(?:[-_](?:default|image|\d+(?:x\d+)?|v\d+))*\.[a-z0-9]{2,5}$',
            unquote(urlparse(candidate).path), re.I):
        return None
    return candidate


def _primary_artwork_element(tag, expected):
    for parent in [tag, *tag.parents]:
        if parent.name in ('nav', 'aside', 'footer') or parent.get('role') in ('navigation', 'complementary', 'contentinfo'):
            return False
        labels = (' '.join(parent.get('class') or []) + ' ' + (parent.get('id') or '')
                  + ' ' + (parent.get('aria-label') or ''))
        if re.search(r'(?:^|[-_\s])(sidebar|related|recommended|sponsor|advertisement)(?:[-_\s]|$)', labels, re.I):
            return False
    article = tag.find_parent('article')
    if article is not None:
        headings = article.select('h1,h2,h3,h4,h5,h6')[:5]
        if headings and not any(words(heading.get_text(' ', strip=True)) == expected
                                or words(heading.get_text(' ', strip=True)).startswith(expected + ' ')
                                or _specific_title_prefix(expected, heading.get_text(' ', strip=True))
                                for heading in headings):
            return False
    labels = ' '.join(tag.get('class') or []) + ' ' + (tag.get('alt') or '') + ' ' + (tag.get('aria-label') or '')
    return not re.search(r'\b(?:logo|map|icon|avatar|tracking)\b', labels, re.I)


def _heading_hero_photo(soup, url, expected):
    headings = [tag for tag in soup.select('h1')[:5]
                if words(tag.get_text(' ', strip=True)) == expected
                or words(tag.get_text(' ', strip=True)).startswith(expected + ' ')
                or _specific_title_prefix(expected, tag.get_text(' ', strip=True))]
    if len(headings) != 1:
        return None, False
    # A bounded ancestor of the event heading can own a hero/banner picture.
    # Never search stylesheets or page-wide backgrounds, cards or sidebars.
    for parent in list(headings[0].parents)[:4]:
        if parent.name in ('main', 'article', 'body', 'html'):
            break
        labels = ' '.join(parent.get('class') or [])
        if not re.search(r'(?:^|[-_\s])(?:hero|banner)(?:[-_\s]|$)', labels, re.I):
            continue
        if len(parent.select('h1')) != 1:
            return None, True
        candidates = set()
        for tag in [parent, *parent.select('img,[style]')][:20]:
            if not _primary_artwork_element(tag, expected):
                continue
            values = [tag.get(name) for name in ('data-src', 'data-lazy-src', 'src')] if tag.name == 'img' else []
            style = tag.get('style', '')
            if re.search(r'(?:^|;)\s*background(?:-image)?\s*:', style, re.I):
                values += [quoted or plain for quoted, plain in re.findall(
                    r'url\(\s*(?:[\"\']([^\"\']+)[\"\']|([^\s)]+))\s*\)', style, re.I)]
            for value in values:
                if candidate := _page_image_candidate(value, url):
                    candidates.add(candidate)
                    if tag.name == 'img':
                        break
        if len(candidates) == 1:
            return candidates.pop(), False
        if candidates:
            return None, True
    return None, False


def extract_photo(html: str, url: str, title: str, *, allow_heading_prefix=False) -> str | None:
    soup = BeautifulSoup(html, 'html.parser')
    expected = words(title)
    for script in soup.select('script[type="application/ld+json"]')[:30]:
        try:
            for item in json_nodes(json.loads(script.string or script.get_text())):
                types = item.get('@type', [])
                types = types if isinstance(types, list) else [types]
                if any(str(t).split('/')[-1].endswith('Event') for t in types):
                    identity = item.get('url') or item.get('@id')
                    if identity is not None and not _same_detail_url(identity, url):
                        continue
                    if not (words(item.get('name')) == expected
                            or allow_heading_prefix and identity is not None
                            and _specific_title_prefix(expected, item.get('name'))):
                        continue
                    if image := _page_image_candidate(item.get('image'), url):
                        return image
        except (ValueError, TypeError, RecursionError):
            continue
    headings = [tag.get('content') or tag.get_text(' ', strip=True)
                for tag in soup.select('title,h1,meta[property="og:title"]')[:15]]
    full_title = any(words(h) == expected or words(h).startswith(expected + ' ') for h in headings)
    # A trusted exact event URL may have a shorter publisher heading than an
    # accepted display title. In that case require a specific primary heading
    # and semantic event/featured artwork; never fall back to generic OG art.
    short_heading = (allow_heading_prefix and any(
        _specific_title_prefix(expected, tag.get_text(' ', strip=True)) for tag in soup.select('h1')[:5]))
    if len(expected) < 4 or not (full_title or short_heading):
        return None
    if allow_heading_prefix:
        image, ambiguous = _heading_hero_photo(soup, url, expected)
        if ambiguous:
            return None
        if image:
            return image
    # A page's explicit event/featured artwork is stronger evidence than the
    # publisher-wide Open Graph default. Keep the existing semantic selectors;
    # do not scan arbitrary page images, backgrounds or related-event links.
    for selector in ('.tribe-events-event-image img', 'img.wp-post-image', '[itemprop="image"][src]'):
        candidates = set()
        for tag in soup.select(selector)[:5]:
            if not _primary_artwork_element(tag, expected):
                continue
            for attribute in ('data-src', 'data-lazy-src', 'src'):
                dimensions = {key: tag[key] for key in ('width', 'height') if tag.has_attr(key)}
                if image := _page_image_candidate({'url': tag.get(attribute), **dimensions}, url):
                    candidates.add(image)
                    break
        if len(candidates) == 1:
            return candidates.pop()
        if len(candidates) > 1:
            return None
    if not full_title:
        return None
    for tag in soup.select('meta[property="og:image"],meta[name="twitter:image"],meta[property="twitter:image"]')[:5]:
        width = soup.select_one('meta[property="og:image:width"]')
        height = soup.select_one('meta[property="og:image:height"]')
        try:
            if width and int(width.get('content', 0)) < 160 or height and int(height.get('content', 0)) < 90:
                continue
        except ValueError:
            continue
        if image := _page_image_candidate(tag.get('content'), url):
            return image
    return None


def fetch_detail_page(claim, *, deadline, clock, host_limiter=None):
    """Fetch the claimed page through the existing publisher policy/transport."""
    if not detail_image_claim(claim):
        raise MediaPageUnavailable('page_unavailable')
    url = claim['event_url']
    host = urlparse(url).hostname or ''
    canonical = canonical_host(host)
    # A www canonical redirect remains the same publisher. Other origins need
    # their own accepted event URL; this task never discovers or follows links.
    hosts = tuple(dict.fromkeys((host, canonical, 'www.' + canonical)))
    permit = host_limiter.request(host) if host_limiter is not None else nullcontext()
    with permit, capture_publisher_pacing() as pacing:
        try:
            return fetch_publisher(url, 'text/html', respect_robots=True,
                                   deadline_at=min(deadline, clock() + DETAIL_PAGE_SECONDS),
                                   allowed_hosts=hosts)
        except PreviewError as error:
            code = error.args[0] if error.args else None
            wait = max(pacing['crawl_delay_seconds'], pacing['retry_after_seconds'])
            if (code in ('robots_denied', 'publisher_wait_requires_review')
                    or pacing['wait_unbounded'] or wait > 3600
                    or code in ('publisher_http_400', 'publisher_http_401', 'publisher_http_403',
                                'publisher_http_404', 'publisher_http_410', 'redirect_host_not_approved',
                                'invalid_redirect_url', 'non_public_dns', 'source_too_large',
                                'source_unavailable_or_oversized')):
                raise MediaPageUnavailable('page_unavailable') from error
            reason = {'source_fetch_deadline': 'deadline',
                      'publisher_pacing_deferred': 'host_busy',
                      'publisher_rate_limited': 'transient_http',
                      'publisher_http_429': 'transient_http',
                      'publisher_http_408': 'transient_http',
                      'publisher_http_425': 'transient_http'}.get(code, 'network_error')
            if isinstance(code, str) and code.startswith('publisher_http_5'):
                reason = 'transient_http'
            raise MediaDeferred(reason, host=host, retry_after_seconds=max(30, wait),
                                attempted=reason != 'host_busy') from error
        except (requests.RequestException, OSError) as error:
            raise MediaDeferred('network_error', host=host, attempted=True) from error


def image_signature(data: bytes, mime: str) -> bool:
    if mime == 'image/jpeg':
        return data.startswith(b'\xff\xd8\xff')
    if mime == 'image/png' and data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) >= 24:
        width, height = struct.unpack('>II', data[16:24])
        return 160 <= width <= 30000 and 90 <= height <= 30000
    if mime == 'image/gif' and data[:6] in (b'GIF87a', b'GIF89a') and len(data) >= 10:
        width, height = struct.unpack('<HH', data[6:10])
        return width >= 160 and height >= 90
    if mime == 'image/webp':
        return data[:4] == b'RIFF' and data[8:12] == b'WEBP'
    return mime == 'image/avif' and data[4:8] == b'ftyp' and b'avif' in data[8:32]


def _native_image_access(url, host, deadline, *, attempted):
    """Check this image path under the existing permit and total probe budget."""
    with capture_publisher_pacing() as pacing:
        try:
            if not robots_allowed(host, _robots_request_path(url), deadline_at=deadline):
                return False
            pace_publisher(host, deadline)
        except PreviewError as error:
            code = error.args[0] if error.args else None
            wait = max(pacing['crawl_delay_seconds'], pacing['retry_after_seconds'])
            # Media backoffs are bounded at one hour. Never shorten a published
            # longer wait or treat a policy denial as permission to try a page.
            if code in ('robots_denied', 'publisher_wait_requires_review') or pacing['wait_unbounded'] or wait > 3600:
                return False
            reason = {'source_fetch_deadline': 'deadline',
                      'publisher_pacing_deferred': 'host_busy',
                      'publisher_rate_limited': 'transient_http'}.get(code, 'network_error')
            raise MediaDeferred(reason, host=host, retry_after_seconds=max(30, wait),
                                attempted=attempted) from error
    return True


def probe_image(url: str, *, candidate_validator=None, deadline=None, clock=None,
                host_limiter=None, session=None, respect_robots=False) -> tuple[str, str] | None:
    current = url
    clock = clock or monotonic
    deadline = min(deadline, clock() + PROBE_SECONDS) if deadline is not None else clock() + PROBE_SECONDS
    attempted = False
    # A dedicated run supplies one reusable Session per executor thread. Legacy
    # callers retain their short-lived Session; no Session crosses threads.
    with nullcontext(session) if session is not None else requests.Session() as session:
        for _ in range(3):
            remaining = deadline - clock()
            if remaining < 0.25:
                raise MediaDeferred('deadline', attempted=attempted)
            if (not event_image(current)
                    or candidate_validator is not None and not candidate_validator(current)):
                return None
            host = urlparse(current).hostname or ''
            try:
                validate_public_dns(host)
            except PreviewError as error:
                if error.args == ('non_public_dns',):
                    return None
                raise MediaDeferred('network_error', host=host, attempted=attempted) from error
            # Redirect destinations pass URL and DNS checks before acquiring
            # their own host slot. A redirect never bypasses publisher limits.
            permit = host_limiter.request(host) if host_limiter is not None else nullcontext()
            try:
                with permit:
                    if respect_robots and not _native_image_access(current, host, deadline, attempted=attempted):
                        return None
                    remaining = deadline - clock()
                    if remaining < 0.25:
                        raise MediaDeferred('deadline', attempted=attempted)
                    connect_timeout = min(2, remaining / 3)
                    read_timeout = min(5, remaining - connect_timeout)
                    attempted = True
                    with session.get(current, timeout=(connect_timeout, read_timeout), stream=True,
                                     allow_redirects=False, headers={'User-Agent': 'RoomQuestCommunityCalendar/0.2',
                                                                     'Range': 'bytes=0-4095', 'Accept': 'image/*'}) as response:
                        if clock() >= deadline:
                            raise MediaDeferred('deadline', attempted=True)
                        if response.status_code in (301,302,303,307,308):
                            current = urljoin(current, response.headers.get('Location', ''))
                            continue
                        if response.status_code in (408, 425, 429) or 500 <= response.status_code <= 599:
                            delay = retry_after_seconds(response.headers.get('Retry-After'),
                                                        default=60 if response.status_code == 429 else 30)
                            if host_limiter is not None:
                                host_limiter.backoff(host, delay)
                            raise MediaDeferred('transient_http', host=host,
                                                retry_after_seconds=delay, attempted=True)
                        if response.status_code not in (200,206):
                            return None
                        mime = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
                        # Some publisher CDNs still advertise progressive JPEG's legacy MIME.
                        # Normalize the header; the JPEG signature check below stays mandatory.
                        if mime == 'image/pjpeg':
                            mime = 'image/jpeg'
                        total = response.headers.get('Content-Range', '').rsplit('/', 1)[-1]
                        if (mime not in MIMES or int(response.headers.get('Content-Length') or 0) > MAX_IMAGE
                                or total.isdigit() and int(total) > MAX_IMAGE):
                            return None
                        # Read only a prefix; never download/copy full publisher files.
                        data = next(response.iter_content(4096), b'')
                        if clock() >= deadline:
                            raise MediaDeferred('deadline', attempted=True)
                        return (current, mime) if image_signature(data, mime) else None
            except MediaDeferred as error:
                error.attempted = error.attempted or attempted
                raise
            except (requests.RequestException, OSError) as error:
                raise MediaDeferred('network_error', host=host, attempted=attempted) from error
    return None


def resolve_photo(claim: dict, *, fetcher=None, probe=None, clock=None, deadline=None,
                  host_limiter=None, session=None, strict_deadline=False):
    clock = clock or monotonic
    deadline = deadline if deadline is not None else clock() + 20
    candidate_validator = None
    native_content = False
    detail_content = False
    from roomquest.registered_native_content import CAPABILITY, media_claim, image_candidate
    if DETAIL_IMAGE_CAPABILITY in claim:
        if not detail_image_claim(claim):
            return None
        detail_content = native_content = True
        candidate_validator = image_candidate
    elif CAPABILITY in claim:
        if not media_claim(claim):
            return None
        candidate_validator = image_candidate
        native_content = True
    elif claim.get('candidate_only') is True:
        from roomquest.publisher_evidence import family, image_url
        source_key = claim.get('source_key') or ''
        if source_key and (publisher := family(source_key, claim['event_url'])):
            candidate_validator = lambda url, *_: image_url(url, publisher)
        elif source_key.startswith('virginia_state_parks_'):
            from roomquest.virginia_state_parks import event_photo_url
            candidate_validator = event_photo_url
        else:
            # The backend releases candidate-only work only after registration
            # records explicit publisher-photo permission. Keep platform-specific
            # validators when available, otherwise apply the generic URL, DNS,
            # redirect, MIME, byte-signature, and size checks below.
            candidate_validator = event_image
    raw_candidate = claim.get('candidate_url')
    if isinstance(raw_candidate, str):
        raw_candidate = raw_candidate.strip() or None
    candidate = (candidate_validator or event_image)(raw_candidate, claim['event_url'])
    if not candidate:
        # HTML candidates were selected from the source's already-fetched
        # event page. A missing/rejected candidate is not permission to crawl
        # that page again or substitute its generic Open Graph artwork.
        if claim.get('candidate_only') is True:
            return None
        required = DETAIL_PAGE_SECONDS + PROBE_SECONDS if detail_content else 9
        if clock() + required >= deadline:
            if strict_deadline:
                raise MediaDeferred('deadline')
            return None
        if detail_content:
            html = (fetcher(claim['event_url']) if fetcher is not None else fetch_detail_page(
                claim, deadline=deadline - PROBE_SECONDS, clock=clock, host_limiter=host_limiter))
        else:
            html = (fetcher or fetch_page)(claim['event_url'])
        candidate = extract_photo(html, claim['event_url'], claim['title'],
                                  allow_heading_prefix=detail_content)
    if not candidate or clock() + 8 >= deadline:
        if candidate and strict_deadline:
            raise MediaDeferred('deadline')
        return None
    verified = probe(candidate) if probe is not None else probe_image(
        candidate, candidate_validator=candidate_validator,
        deadline=deadline if strict_deadline else None,
        clock=clock if strict_deadline else None, host_limiter=host_limiter, session=session,
        respect_robots=native_content)
    if verified and candidate_validator is not None and not candidate_validator(verified[0]):
        return None
    return {'image_url': verified[0], 'mime_type': verified[1],
            'evidence_url': claim.get('extraction_url') or claim['event_url']} if verified else None


def rpc(action: str, payload=None):
    return supabase_rpc('community_collector_media', {'p_action': action, 'p_payload': payload or {}})


def dedicated_media_ready():
    """Deploy safely before activation; an older backend keeps the old path."""
    if os.environ.get('VERCEL_ENV') != 'production' or os.environ.get('FORWARD_GEOCODER_ENABLED') != 'true':
        return False
    try:
        capability = rpc('capabilities')
        return isinstance(capability, dict) and capability.get('dedicated_ready') is True
    except (PreviewError, requests.RequestException, ValueError, OSError):
        return False


def run_batch(*, database=None, resolver=None, clock=None, deadline_seconds=38):
    stats = {'claimed': 0, 'ready': 0, 'unavailable': 0, 'errors': 0}
    if os.environ.get('VERCEL_ENV') != 'production' or os.environ.get('FORWARD_GEOCODER_ENABLED') != 'true':
        return stats
    database, resolver, clock = database or rpc, resolver or resolve_photo, clock or monotonic
    deadline = clock() + min(38, max(1, deadline_seconds))
    # The backend releases candidate-only VA work only to a deployed worker
    # that supports it; old workers retain their existing legacy claim path.
    claims = database('claim', {'limit': 3, 'candidate_only_version': 'publisher_event_html_v2',
                                'registered_native_content_version': 1}) or []
    def process(claim):
        try:
            return claim, resolver(claim, deadline=deadline), None
        except (PreviewError, requests.RequestException, ValueError, OSError):
            return claim, None, 'page_unavailable'
    with ThreadPoolExecutor(max_workers=3) as pool:
        for claim, result, error in pool.map(process, claims[:3]):
            stats['claimed'] += 1
            identity = {k: claim[k] for k in ('media_key','lease_id')}
            if result:
                database('submit', {**identity, **result});stats['ready'] += 1
            else:
                database('fail', {**identity, 'reason': error or 'no_event_image'})
                stats['errors' if error else 'unavailable'] += 1
    return stats

