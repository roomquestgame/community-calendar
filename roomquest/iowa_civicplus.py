"""Exact enrolled Independence Library detail enrichment on the existing ICS lane."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
import logging

from roomquest.publisher_evidence import optional_description

logger = logging.getLogger(__name__)

KEY = 'independence_ia_library_family'
FEED = 'https://independenceia.gov/common/modules/iCalendar/iCalendar.aspx?catID=26&feed=calendar'


def enrich(records, source, fetch, deadline):
    if source.get('source_key') != KEY or source.get('feed_url') != FEED:
        raise ValueError('unregistered_civicplus_source')
    if len(records) > 20:
        raise ValueError('source_detail_limit')
    result = []
    for record in records:
        html = fetch(record['event_url'], 'text/html', respect_robots=True, deadline_at=deadline)
        soup = BeautifulSoup(html, 'html.parser')
        names = soup.select('[itemprop="name"] h2')
        descriptions = soup.select('div[itemprop="description"]')
        starts = soup.select('[itemprop="startDate"]')
        addresses = soup.select('[itemprop="PostalAddress"], [itemtype="http://schema.org/PostalAddress"]')
        if len(names) != 1 or names[0].get_text(' ', strip=True) != record['title']:
            raise ValueError('publisher_detail_identity_conflict')
        if len(starts) != 1:
            raise ValueError('publisher_detail_schedule_missing')
        value = starts[0].get('content') or starts[0].get_text(strip=True)
        local = datetime.fromisoformat(value).replace(tzinfo=ZoneInfo('America/Chicago'))
        if local.astimezone(timezone.utc) != datetime.fromisoformat(record['starts_at']):
            raise ValueError('publisher_detail_schedule_conflict')
        if len(descriptions) > 1 or len(addresses) != 1:
            raise ValueError('publisher_detail_structure_changed')
        address = addresses[0]
        fields = [address.select_one(f'[itemprop="{key}"]') for key in
                  ('streetAddress', 'addressLocality', 'addressRegion', 'postalCode')]
        if not all(fields):
            raise ValueError('publisher_detail_address_missing')
        street, city, state, zipcode = [f.get_text(' ', strip=True) for f in fields]
        # The detail's actual event address replaces no verified point.
        record['venue_address'] = f'{street}, {city}, {state} {zipcode}'
        record['venue_city'] = city
        # CivicPlus sometimes concatenates its real room label and address in
        # LOCATION. Remove only a suffix whose street matches this event's
        # verified PostalAddress; keep the original room/library wording.
        label = record.get('venue_name', '')
        marker = ' - ' + street
        if marker.casefold() in label.casefold():
            record['venue_name'] = label[:label.casefold().index(marker.casefold())].strip()
        summary = record['description'].replace(record['event_url'], '').strip()
        narrative = ''
        if descriptions:
            for element in descriptions[0].select('script,style,[hidden]'):
                element.decompose()
            narrative = '\n'.join(p.strip() for p in descriptions[0].get_text('\n', strip=True).splitlines() if p.strip())
        narrative = optional_description(KEY, record['id'], narrative)
        record['description'] = (summary + '\n\n' + narrative).strip()[:12000]
        from roomquest.mycountyparks import cancelled
        if cancelled(record['title'], record['description']):
            logger.warning('ics_record_withheld source=%s uid=%s reason=publisher_cancelled',
                           KEY, record['id'])
            continue
        result.append(record)
    return result
