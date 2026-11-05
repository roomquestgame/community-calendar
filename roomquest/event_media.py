"""Bounded event-photo discovery/verification with durable future-refresh reuse."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import os
import struct
from time import monotonic
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import requests

from roomquest.preview_worker import event_image, public_source_url, validate_public_dns, supabase_rpc, PreviewError
from roomquest.venue_resolver import fetch_page, json_nodes, words

MIMES = {'image/jpeg', 'image/png', 'image/webp', 'image/gif', 'image/avif'}
MAX_IMAGE = 10_000_000
PROBE_SECONDS = 8


class MediaDeferred(PreviewError):
    """A temporary inability to check an image is not evidence of no image."""

    def __init__(self, reason, *, host=None, retry_after_seconds=30, attempted=False):
        super().__init__(reason)
        self.reason = reason
        self.host = canonical_host(host) if host else None
        self.retry_after_seconds = max(1, min(3600, int(retry_after_seconds)))
        self.attempted = bool(attempted)


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


def extract_photo(html: str, url: str, title: str) -> str | None:
    soup = BeautifulSoup(html, 'html.parser')
    for script in soup.select('script[type="application/ld+json"]')[:30]:
        try:
            for item in json_nodes(json.loads(script.string or script.get_text())):
                types = item.get('@type', [])
                types = types if isinstance(types, list) else [types]
                if any(str(t).split('/')[-1].endswith('Event') for t in types) and words(item.get('name')) == words(title):
                    if image := event_image(item.get('image'), url):
                        return image
        except (ValueError, TypeError, RecursionError):
            continue
    headings = [tag.get('content') or tag.get_text(' ', strip=True)
                for tag in soup.select('title,h1,meta[property="og:title"]')[:15]]
    expected = words(title)
    if len(expected) < 4 or not any(words(h) == expected or words(h).startswith(expected + ' ') for h in headings):
        return None
    for tag in soup.select('meta[property="og:image"],meta[name="twitter:image"],meta[property="twitter:image"]')[:5]:
        width = soup.select_one('meta[property="og:image:width"]')
        height = soup.select_one('meta[property="og:image:height"]')
        try:
            if width and int(width.get('content', 0)) < 160 or height and int(height.get('content', 0)) < 90:
                continue
        except ValueError:
            continue
        if image := event_image(tag.get('content'), url):
            return image
    for tag in soup.select('.tribe-events-event-image img[src], img.wp-post-image[src], [itemprop="image"][src]')[:5]:
        if image := event_image(tag.get('src'), url):
            return image
    return None


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


def probe_image(url: str, *, candidate_validator=None, deadline=None, clock=None,
                host_limiter=None, session=None) -> tuple[str, str] | None:
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
                        mime = response.headers.get('Content-Type', '').split(';')[0].lower()
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
    fetcher, clock = fetcher or fetch_page, clock or monotonic
    deadline = deadline if deadline is not None else clock() + 20
    candidate_validator = None
    if claim.get('candidate_only') is True:
        from roomquest.virginia_state_parks import event_photo_url
        candidate_validator = event_photo_url
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
        if clock() + 9 >= deadline:
            if strict_deadline:
                raise MediaDeferred('deadline')
            return None
        candidate = extract_photo(fetcher(claim['event_url']), claim['event_url'], claim['title'])
    if not candidate or clock() + 8 >= deadline:
        if candidate and strict_deadline:
            raise MediaDeferred('deadline')
        return None
    verified = probe(candidate) if probe is not None else probe_image(
        candidate, candidate_validator=candidate_validator,
        deadline=deadline if strict_deadline else None,
        clock=clock if strict_deadline else None, host_limiter=host_limiter, session=session)
    if verified and candidate_validator is not None and not candidate_validator(verified[0]):
        return None
    return {'image_url': verified[0], 'mime_type': verified[1], 'evidence_url': claim['event_url']} if verified else None


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
    claims = database('claim', {'limit': 3, 'candidate_only_version': 'publisher_event_html_v2'}) or []
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

