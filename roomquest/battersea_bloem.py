"""The reviewed Battersea Bloem workshop page and its linked public Square store.

Square's published page lists the exact featured event product IDs. Its shipped
read-only loader returns their complete dates, times and venue addresses. This
adapter reads only that one store and those IDs, without executing JavaScript,
using an account, or visiting checkout. Other JSON and transport rules remain
unchanged. Every request uses the caller's robots/pacing/deadline protections.
"""
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import json
import re
from time import monotonic
from urllib.parse import urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record
from roomquest.registration_formats import source_key

URL = 'https://www.batterseabloem.com/workshop'
STORE = 'https://battersea-bloem.square.site/'
USER_ID = '139773107'
SITE_ID = '282506720780254463'
MERCHANT_ID = 'ML3YRNCESREJB'
API = STORE + 'app/store/api/v28/editor/users/' + USER_ID + '/sites/' + SITE_ID + '/products'
ZONE = 'Europe/London'
VENUE = 'Battersea Bloem'
ADDRESS = '10 Hamilton Road, Cambridge CB4 1BP, United Kingdom'
MAX_BODY = 3_000_000
MAX_EVENTS = 20
PRODUCT_ID = re.compile(r'(?:[1-9]\d{0,9}|[A-Z0-9]{20,32})')


def _fail(reason):
    raise ValueError('battersea_' + reason)


def _deadline(deadline_at):
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError('collection_deadline')


def _bounded(payload):
    if not isinstance(payload, str) or len(payload.encode('utf-8')) > MAX_BODY:
        _fail('response_unverified')
    return payload.lstrip('\ufeff \t\r\n')


def _json(payload):
    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                _fail('json_unverified')
            value[key] = item
        return value
    try:
        return json.loads(_bounded(payload), object_pairs_hook=unique_object)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError('battersea_json_unverified') from exc


def _publisher_page(payload):
    """Unwrap only the observed Duda representation of this exact page."""
    body = _bounded(payload)
    if body.startswith(('{', '[')):
        envelope = _json(body)
        if (not isinstance(envelope, dict) or envelope.get('alias') != 'workshop'
                or envelope.get('page_title') != 'Workshops'
                or envelope.get('isHomePage') is not False
                or not isinstance(envelope.get('parameters'), dict)
                or envelope['parameters'].get('InitialPageAlias') != 'workshop'
                or not isinstance(envelope.get('css'), str)
                or '#dm' not in envelope['css']
                or not isinstance(envelope.get('content'), str)
                or not isinstance(envelope.get('headsection'), str)):
            _fail('page_envelope_unverified')
        body = envelope['headsection'] + envelope['content']
    if not body.startswith('<'):
        _fail('page_unverified')
    soup = BeautifulSoup(body, 'html.parser')
    headings = [plain(node.get_text(' ', strip=True)) for node in soup.select('h1')]
    canonical = {node.get('content') for node in soup.select('meta[property="og:url"]')}
    declared = {node.get('href') for node in soup.select('link[rel="canonical"]')}
    if (canonical != {URL} or (declared and declared != {URL})
            or headings != ['Botanical Workshops'] or not soup.select_one('.dmBody')):
        _fail('page_identity_unverified')
    # The official page really links to this public booking store. Do not
    # substitute an unlinked merchant, product route, or a guessed platform URL.
    if not any(urljoin(URL, anchor['href']) == STORE for anchor in soup.select('a[href]')):
        _fail('booking_link_unverified')
    return STORE


def _featured_ids(payload):
    soup = BeautifulSoup(_bounded(payload), 'html.parser')
    scripts = [tag.string or tag.get_text() for tag in soup.find_all('script')
               if re.search(r'\bwindow\.__BOOTSTRAP_STATE__\s*=', tag.string or tag.get_text())]
    if len(scripts) != 1:
        _fail('square_bootstrap_unverified')
    match = re.fullmatch(r'\s*window\.__BOOTSTRAP_STATE__\s*=\s*(\{.*\})\s*;?\s*', scripts[0], re.S)
    if not match:
        _fail('square_bootstrap_unverified')
    state = _json(match[1])
    try:
        site = state['siteData']['site']['properties']
        page = state['siteData']['page']['properties']
        area = page['contentAreas']['userContent']
        cells = area['content']['cells']
        if (state['cmsContentDraftId'] is not None
                or str(state['siteData']['user']['id']) != USER_ID
                or site['classicSiteID'] != SITE_ID or site['catalogSiteId'] != SITE_ID
                or site['squareMerchantId'] != MERCHANT_ID
                or site['domain']['subdomain'] != urlsplit(STORE).hostname
                or str(site['domain']['site_id']) != SITE_ID
                or state['siteData']['snapshot']['properties']['title'] != VENUE
                or state['storeInfo']['merchant_id'] != MERCHANT_ID
                or state['storeInfo']['currency'] != 'GBP'
                or page['route'] != 'home' or page['hidden'] is not False
                or area['hidden'] is not False
                or not isinstance(cells, list) or len(cells) > 100):
            _fail('square_store_unverified')
        blocks = [cell for cell in cells
                  if isinstance(cell, dict) and isinstance(cell.get('content'), dict)
                  and cell['content'].get('purpose') == 'featured-events@^1.0.0']
        if len(blocks) != 1 or ('hidden' in blocks[0] and blocks[0]['hidden'] is not False):
            _fail('square_calendar_unverified')
        block = blocks[0]['content']
        if (block.get('layout') != 'featured-events-grid'
                or ('hidden' in block and block['hidden'] is not False)
                or not isinstance(block.get('properties'), dict)
                or ('hidden' in block['properties'] and block['properties']['hidden'] is not False)):
            _fail('square_calendar_unverified')
        ids = block['properties']['featuredEventIds']
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('battersea_square_bootstrap_unverified') from exc
    if (not isinstance(ids, list) or not 1 <= len(ids) <= MAX_EVENTS
            or any(not isinstance(value, str) or not PRODUCT_ID.fullmatch(value) for value in ids)
            or len(set(ids)) != len(ids)):
        _fail('square_featured_ids_unverified')
    return ids


def products_url(ids):
    # The public storefront's observed GET loader, constrained to one merchant
    # and exactly the active featured IDs. No catalog-wide query or pagination.
    target = API + '?' + urlencode([('page', 1), ('per_page', len(ids)), ('product_type', 'event')]
                                   + [('ids[]', identity) for identity in ids])
    if len(target) > 1000:
        _fail('square_featured_ids_limit')
    return target


def _schedule(details):
    if (not isinstance(details, dict) or details.get('timezone') != ZONE
            or not isinstance(details.get('timezone_info'), dict)
            or details['timezone_info'].get('name') != ZONE
            or details.get('has_no_end_time') not in ('0', '1')):
        _fail('square_schedule_unverified')

    def wall(day, clock):
        if (not isinstance(day, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day)
                or not isinstance(clock, str)
                or not re.fullmatch(r'(?:[1-9]|1[0-2]):[0-5]\d [AP]M', clock)):
            _fail('square_schedule_unverified')
        try:
            return datetime.combine(datetime.strptime(day, '%Y-%m-%d').date(),
                                    datetime.strptime(clock, '%I:%M %p').time())
        except ValueError as exc:
            raise ValueError('battersea_square_schedule_unverified') from exc

    start = wall(details.get('start_date'), details.get('start_time'))
    end = None if details['has_no_end_time'] == '1' else wall(details.get('end_date'), details.get('end_time'))
    if end is not None and not timedelta(0) < end - start <= timedelta(days=1):
        _fail('square_schedule_unverified')
    # timezone_info.utc_offset_* is an editor-time cache, not an occurrence
    # offset. The shared normalizer uses the actual date and Europe/London IANA
    # rules, including its existing ambiguous/nonexistent-wall-time rejection.
    return start, end


def _venue(details):
    address = details.get('address')
    if (details.get('location_types') != ['IN_PERSON']
            or details.get('join_event_online_link') not in ('', None)
            or plain(details.get('location_name')).casefold() not in ('', VENUE.casefold())
            or not isinstance(address, dict) or address.get('country_code') != 'GB'
            or address.get('country_code_cca2') != 'GB'
            or address.get('country_code_full_name') != 'United Kingdom'
            or address.get('region_code') != 'ENG' or address.get('region_code_cca2') != 'ENG'
            or plain(address.get('city')).casefold() != 'cambridge'
            or plain(address.get('postal_code')).upper() != 'CB4 1BP'):
        _fail('square_venue_unverified')
    lines = (plain(address.get('street')).casefold(), plain(address.get('street2')).casefold())
    if lines not in {('10', 'hamilton road'), ('cb4 1bp', '10 hamilton road')}:
        _fail('square_venue_unverified')
    return ADDRESS


def _price(product):
    price = product.get('price')
    if not isinstance(price, dict):
        _fail('square_price_unverified')
    try:
        low, high = (Decimal(str(price[key])) for key in ('low', 'high'))
        if (not low.is_finite() or not high.is_finite() or low < 0 or high < low
                or high > 100000 or low * 100 != price.get('low_subunits')
                or high * 100 != price.get('high_subunits')):
            _fail('square_price_unverified')
    except (KeyError, TypeError, InvalidOperation) as exc:
        raise ValueError('battersea_square_price_unverified') from exc
    return 'Price: £' + format(low, '.2f') + (('–£' + format(high, '.2f')) if high != low else '') + '.'


def _image(product):
    thumbnail = product.get('thumbnail')
    if thumbnail is None:
        return None
    data = thumbnail.get('data') if isinstance(thumbnail, dict) else None
    if not isinstance(data, dict):
        _fail('square_image_unverified')
    target = data.get('absolute_url')
    if not isinstance(target, str):
        _fail('square_image_unverified')
    parsed = urlsplit(target)
    if (str(data.get('owner_id')) != USER_ID or str(data.get('site_id')) != SITE_ID
            or parsed.scheme != 'https' or parsed.netloc != USER_ID + '.cdn6.editmysite.com'
            or parsed.query or parsed.fragment
            or not re.fullmatch(r'/uploads/1/3/9/7/139773107/[A-Za-z0-9_.-]+\.(?:jpe?g|png|webp)', parsed.path, re.I)
            or type(data.get('width')) is not int or data['width'] < 160
            or type(data.get('height')) is not int or data['height'] < 90):
        _fail('square_image_unverified')
    from roomquest.preview_worker import event_image
    return event_image(target, product['absolute_site_link'])


def _rows(payload, ids):
    data = _json(payload)
    if not isinstance(data, dict) or not isinstance(data.get('data'), list):
        _fail('square_products_unverified')
    products = data['data']
    meta = data.get('meta')
    pagination = meta.get('pagination') if isinstance(meta, dict) else None
    expected = {'total': len(ids), 'count': len(ids), 'per_page': len(ids), 'current_page': 1, 'total_pages': 1}
    if (len(products) != len(ids) or not isinstance(pagination, dict)
            or any(type(pagination.get(key)) is not int or pagination[key] != value for key, value in expected.items())
            or pagination.get('links') != []):
        _fail('square_incomplete_collection')
    result, seen, square_ids = [], set(), set()
    for product in products:
        if not isinstance(product, dict):
            _fail('square_products_unverified')
        identity = product.get('site_product_id')
        square_id = product.get('id')
        if (not isinstance(identity, str) or identity not in ids or identity in seen
                or not isinstance(square_id, str) or not PRODUCT_ID.fullmatch(square_id) or square_id in square_ids
                or product.get('owner_id') != USER_ID or product.get('site_id') != SITE_ID
                or product.get('merchant_id') != MERCHANT_ID
                or product.get('visibility') != 'visible' or product.get('product_type') != 'event'):
            _fail('square_product_identity_unverified')
        seen.add(identity)
        square_ids.add(square_id)
        title, link = product.get('name'), product.get('absolute_site_link')
        relative = product.get('site_link')
        if (not isinstance(title, str) or not 1 <= len(plain(title)) <= 180
                or not isinstance(link, str) or len(link) > 1000):
            _fail('square_product_identity_unverified')
        parsed = urlsplit(link)
        if (parsed.scheme != 'https' or parsed.netloc != urlsplit(STORE).netloc
                or parsed.query or parsed.fragment
                or not re.fullmatch(r'/product/[a-z0-9-]+/' + re.escape(identity), parsed.path)
                or not isinstance(relative, str) or urljoin(STORE, relative) != link):
            _fail('square_product_identity_unverified')
        details = product.get('product_type_details')
        start, end = _schedule(details)
        address = _venue(details)
        narrative = description(product.get('short_description'), limit=2001)
        if len(narrative) > 2000:
            _fail('square_description_too_long')
        badges = product.get('badges')
        if not isinstance(badges, dict) or type(badges.get('out_of_stock')) is not bool:
            _fail('square_availability_unverified')
        parts = [narrative, _price(product)]
        if badges['out_of_stock']:
            parts.append('Tickets sold out.')
        text = '\n\n'.join(part for part in parts if part)
        if len(text) > 2000:
            _fail('square_description_too_long')
        image = _image(product)
        row = record(title, start, end, VENUE, address, 'Cambridge', link,
                     'battersea-square:' + identity, tz=ZONE)
        if row:
            row['timezone'] = ZONE
            row['description'] = text
            if image:
                row['image_url'] = image  # candidate only; existing media gates remain authoritative
            result.append(row)
    if seen != set(ids):
        _fail('square_incomplete_collection')
    return sorted(result, key=lambda row: (row['starts_at'], row['id']))


def collect(source, fetch, *, deadline_at=None, listing=None):
    if source.get('feed_url') != URL or source.get('source_key') != source_key(URL):
        raise ValueError('unregistered_html_source')
    _deadline(deadline_at)
    store = _publisher_page(listing if listing is not None else fetch(URL, 'text/html'))
    _deadline(deadline_at)
    ids = _featured_ids(fetch(store, 'text/html'))
    _deadline(deadline_at)
    rows = _rows(fetch(products_url(ids), 'application/json'), ids)
    _deadline(deadline_at)
    if not rows:
        raise ValueError('no_extractable_events')
    return rows
