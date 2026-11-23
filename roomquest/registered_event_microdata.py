"""Conservative publisher-declared HTML Event microdata fallback.

Only a single Event microdata item with ISO-offset time and a complete Place/
PostalAddress is eligible. This deliberately does not mine dates from prose,
infer local zones, or combine unrelated page metadata.
"""
from datetime import datetime
from roomquest.mapsee_adapter import record
from roomquest.registered_native_content import attach


def parse_event_microdata(source, soup, url):
    roots = []
    for node in soup.select('[itemscope][itemtype]'):
        itemtype = str(node.get('itemtype', ''))
        if itemtype.startswith(('https://schema.org/', 'http://schema.org/')):
            name = itemtype.rsplit('/', 1)[-1]
            if name.endswith('Event'):
                roots.append(node)
    if len(roots) != 1:
        raise ValueError('html_calendar_event_jsonld_missing')
    root = roots[0]

    def property_node(parent, key):
        matching = [node for node in parent.select('[itemprop]')
                    if key in node.get('itemprop', '').split()
                    and node.find_parent(attrs={'itemscope': True}) is parent]
        if len(matching) != 1:
            raise ValueError('html_calendar_event_microdata_ambiguous')
        return matching[0]

    def prop(parent, key):
        node = property_node(parent, key)
        return (node.get('content') or node.get('datetime') or
                node.get_text(' ', strip=True)).strip()

    name = prop(root, 'name')
    start = prop(root, 'startDate')
    begins = datetime.fromisoformat(start.replace('Z', '+00:00'))
    if not name or len(name) > 250 or begins.tzinfo is None or begins.utcoffset() is None:
        raise ValueError('html_calendar_event_microdata_ambiguous')
    end = None
    if root.select('[itemprop="endDate"]'):
        end = prop(root, 'endDate')
        finishes = datetime.fromisoformat(end.replace('Z', '+00:00'))
        if finishes.tzinfo is None or finishes.utcoffset() is None or finishes < begins:
            raise ValueError('html_calendar_event_microdata_ambiguous')

    place = property_node(root, 'location')
    if not place.has_attr('itemscope') or not str(place.get('itemtype', '')).endswith('/Place'):
        raise ValueError('html_calendar_event_microdata_ambiguous')
    address = property_node(place, 'address')
    if not address.has_attr('itemscope') or not str(address.get('itemtype', '')).endswith('/PostalAddress'):
        raise ValueError('html_calendar_event_microdata_ambiguous')
    street, city, region, postcode = (prop(address, field) for field in (
        'streetAddress', 'addressLocality', 'addressRegion', 'postalCode'))
    if not all((street, city, region, postcode)):
        raise ValueError('html_calendar_event_microdata_ambiguous')
    venue = prop(place, 'name')
    row = record(name, start, end, venue,
                 ', '.join((street, city, region + ' ' + postcode)), city,
                 url, url + '#microdata-event')
    if row is None:
        return []
    description = None
    if root.select('[itemprop="description"]'):
        description = prop(root, 'description')
    attach(row, source, description_value=description, evidence_url=url)
    return [row]
