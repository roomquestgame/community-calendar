"""Read dated workshops from Red Door 104's public studio catalogue."""
from datetime import datetime
import json
import re
from time import monotonic
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import record, timestamp
from roomquest.publisher_evidence import attach

SOURCE_KEY = 'red_door_104_va'
SOURCE_URL = 'https://www.reddoor104.com/workshops-special-events'
TIMEZONE = 'America/New_York'
ADDRESS = '104 North Main Street, Farmville, VA 23901'
EVENT_URL = re.escape(SOURCE_URL) + r'/[a-z0-9]+(?:-[a-z0-9]+)*'
PHOTO_URL = (r'https://images[.]squarespace-cdn[.]com/content/v1/5505f653e4b072c28ec4ab8b/'
             r'[a-f0-9-]{36}/[A-Za-z0-9_.-]+\.(?:jpe?g|png|webp)')
_TIME = r'(\d{1,2}(?::\d{2})?\s*[ap]m)'
_DATE = re.compile(r'(\w+)\s*,?\s+([A-Za-z]+) (\d{1,2})(?:st|nd|rd|th)?, (20\d{2})', re.I)


def _local(day, text):
    text = re.sub(r'\s+', '', text).upper()
    clock = datetime.strptime(text, '%I:%M%p' if ':' in text else '%I%p').time()
    return timestamp(datetime.combine(day, clock), TIMEZONE)


def _workshop(payload, url, title, identity, image):
    page = BeautifulSoup(payload, 'html.parser')
    canonical = page.select_one('link[rel="canonical"]')
    name = page.select_one('h1.product-title')
    excerpt = page.select_one('.product-excerpt')
    if not canonical or canonical.get('href') != url or not name or not excerpt:
        raise ValueError('red_door_workshop_detail_missing')
    if ' '.join(name.stripped_strings).split() != title.split():
        raise ValueError('red_door_workshop_identity_mismatch')
    if page.select_one('.product.sold-out, .sqs-add-to-cart-button.sold-out'):
        return None
    description = excerpt.get_text(' ', strip=True)
    if re.search(r'\b(?:cancell?ed|postponed|off[- ]site|virtual|online only)\b', description, re.I):
        return None
    fields = {}
    for tag in excerpt.select('h2, h3, h4, p'):
        label, sep, value = tag.get_text(' ', strip=True).partition(':')
        label = label.strip().casefold()
        if sep and label in ('date', 'time', 'location'):
            fields.setdefault(label, set()).add(value.strip())
    if any(len(fields.get(k, ())) != 1 for k in ('date', 'time')):
        return None
    date_match = _DATE.fullmatch(next(iter(fields['date'])))
    time_match = re.fullmatch(_TIME + r'\s*[-–—]\s*' + _TIME, next(iter(fields['time'])), re.I)
    if not date_match or not time_match:
        return None
    venue = fields.get('location', set())
    if venue and {v.casefold() for v in venue} - {'red door 104', 'red door 104 studio'}:
        return None
    # The shop's own LocalBusiness address anchors the studio catalogue.
    addresses = set()
    for tag in page.select('script[type="application/ld+json"]'):
        data = json.loads(tag.get_text())
        if isinstance(data, dict) and data.get('@type') == 'LocalBusiness' and data.get('name') == 'Red Door 104':
            addresses.add(' '.join(str(data.get('address', '')).split()))
    if addresses != {'104 N Main St Farmville, VA, 23901 United States'}:
        raise ValueError('red_door_studio_address_unverified')
    weekday, month, date, year = date_match.groups()
    day = datetime.strptime(f'{month} {date} {year}', '%B %d %Y').date()
    start, end = (_local(day, clock) for clock in time_match.groups())
    if day.strftime('%A').casefold() != weekday.casefold() or end <= start:
        return None
    result = record(title, start, end, 'Red Door 104', ADDRESS, 'Farmville', url, identity, 'Arts & Crafts')
    if result:
        result.update(description=description[:3000], attendance_mode='in_person')
        # Use the listing image only when the detail page corroborates it.
        if image not in {tag.get('data-image') for tag in page.select('img[data-image]')}:
            image = None
        attach(result, SOURCE_KEY, candidate=image)
    return result


def collect(source, fetch, *, deadline_at=None):
    if (source.get('source_key'), source.get('feed_url'), source.get('timezone'),
        source.get('kind'), source.get('platform_adapter')) != (
            SOURCE_KEY, SOURCE_URL, TIMEZONE, 'html', 'html'):
        raise ValueError('unregistered_red_door_calendar')
    page = BeautifulSoup(fetch(SOURCE_URL, 'text/html'), 'html.parser')
    if page.select_one('[rel="next"], .pagination, .load-more'):
        raise ValueError('pagination_requires_review')
    cards = page.select('.sqs-pinterest-products-wrapper a.product[data-item-id]')
    if not 1 <= len(cards) <= 16:
        raise ValueError('red_door_catalogue_count_unverified')
    rows, seen = [], set()
    for card in cards:
        if 'sold-out' in card.get('class', ()):
            continue
        url = urljoin(SOURCE_URL, card.get('href', ''))
        name = card.select_one('.product-title')
        identity = card['data-item-id']
        if not name or not re.fullmatch(EVENT_URL, url) or not re.fullmatch(r'[a-f0-9]{24}', identity) or identity in seen:
            raise ValueError('red_door_workshop_identity_unverified')
        seen.add(identity)
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError('collection_deadline')
        image = card.select_one('img[data-image]')
        if row := _workshop(fetch(url, 'text/html'), url, name.get_text(' ', strip=True),
                            identity, image.get('data-image') if image else None):
            rows.append(row)
    return rows
