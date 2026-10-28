"""Bounded event-photo discovery/verification with durable future-refresh reuse."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
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


def probe_image(url: str) -> tuple[str, str] | None:
    current = url
    deadline = monotonic() + 8
    with requests.Session() as session:
        for _ in range(3):
            remaining = deadline - monotonic()
            if remaining < 1 or not event_image(current):
                return None
            validate_public_dns(urlparse(current).hostname or '')
            with session.get(current, timeout=(min(2, remaining), min(5, remaining)), stream=True,
                             allow_redirects=False, headers={'User-Agent': 'RoomQuestCommunityCalendar/0.2',
                                                             'Range': 'bytes=0-4095', 'Accept': 'image/*'}) as response:
                if response.status_code in (301,302,303,307,308):
                    current = urljoin(current, response.headers.get('Location', ''))
                    continue
                if response.status_code not in (200,206):
                    return None
                mime = response.headers.get('Content-Type', '').split(';')[0].lower()
                total = response.headers.get('Content-Range', '').rsplit('/', 1)[-1]
                if (mime not in MIMES or int(response.headers.get('Content-Length') or 0) > MAX_IMAGE
                        or total.isdigit() and int(total) > MAX_IMAGE):
                    return None
                # Read only a prefix; never download/copy full publisher files.
                data = next(response.iter_content(4096), b'')
                return (current, mime) if image_signature(data, mime) else None
    return None


def resolve_photo(claim: dict, *, fetcher=None, probe=None, clock=None, deadline=None):
    fetcher, probe, clock = fetcher or fetch_page, probe or probe_image, clock or monotonic
    deadline = deadline if deadline is not None else clock() + 20
    candidate = event_image(claim.get('candidate_url'), claim['event_url'])
    if not candidate:
        if clock() + 9 >= deadline:
            return None
        candidate = extract_photo(fetcher(claim['event_url']), claim['event_url'], claim['title'])
    if not candidate or clock() + 8 >= deadline:
        return None
    verified = probe(candidate)
    return {'image_url': verified[0], 'mime_type': verified[1], 'evidence_url': claim['event_url']} if verified else None


def rpc(action: str, payload=None):
    return supabase_rpc('community_collector_media', {'p_action': action, 'p_payload': payload or {}})


def run_batch(*, database=None, resolver=None, clock=None, deadline_seconds=38):
    stats = {'claimed': 0, 'ready': 0, 'unavailable': 0, 'errors': 0}
    if os.environ.get('VERCEL_ENV') != 'production' or os.environ.get('FORWARD_GEOCODER_ENABLED') != 'true':
        return stats
    database, resolver, clock = database or rpc, resolver or resolve_photo, clock or monotonic
    deadline = clock() + min(38, max(1, deadline_seconds))
    claims = database('claim', {'limit': 3}) or []
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
