"""Extract explicit facility facts from retained publisher markdown.

No search-query locality, network calls, generated descriptions or publication.
Unsupported layouts return no records rather than treating snippets as facts.
"""
from hashlib import sha256
import re

from roomquest.things_to_do_search import canonical_url

HEADING = re.compile(r'^#{1,6}\s+(.+)$', re.M)
ACTIVITY = re.compile(r'\b(park|playground|museum|garden|trail|nature center)\b', re.I)
FOOTER = re.compile(r'^#{1,6}\s+(?:Site Footer|Contact Us|Quick Links|Helpful Links)\s*$', re.I | re.M)
ADDRESS = re.compile(r'(?m)^\s*(\d{1,6}\s+[\w .’\'-]+(?:Street|Road|Boulevard|Avenue|Drive|Lane|Court|Way|St\.?|Rd\.?|Blvd\.?|Ave\.?))\s*,?\s*\n?\s*,?\s*([A-Za-z][A-Za-z .\'-]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)\b')


def plain(value):
    value = re.sub(r'!\[[^\]]*\]\([^\n]*\)', '', value)
    value = re.sub(r'\[([^\]]+)\]\([^\n]*?\)', r'\1', value)
    return value.replace('**', '').replace('\u00a0', ' ')


def extract_retained(metadata, url, source_key):
    raw = metadata.get('raw_content')
    if not canonical_url(url) or not isinstance(raw, str) or not raw or len(raw.encode()) > 100_000:
        return []
    # Drop site-wide contact information before looking for a facility address.
    body = FOOTER.split(raw, maxsplit=1)[0]
    headings = [(m.start(), plain(m.group(1)).strip()) for m in HEADING.finditer(body)]
    names = [(pos, title) for pos, title in headings if ACTIVITY.search(title)
             and not re.search(r'\b(about|guide|all|our|hours|directions|features)\b', title, re.I)]
    distinct = {title.casefold() for _, title in names}
    if len(distinct) != 1:
        return []  # directory, missing identity or multiple facilities
    start, title = names[0]
    if len(title) > 300:
        return []
    body = body[start:]
    text = plain(body)
    addresses = list(ADDRESS.finditer(text))
    unique = {tuple(' '.join(x.split()) for x in m.groups()) for m in addresses}
    if len(unique) != 1:
        return []
    street, city, state, postal = unique.pop()
    # The actual publisher address wins, even when the search targeted elsewhere.
    location = f'{street}, {city}, {state} {postal}'
    record = {'source_key': source_key, 'external_id': 'web:sha256:' + sha256(url.encode()).hexdigest(),
              'title': title, 'source_url': url, 'extracted_from_url': url,
              'location_text': location, 'evidence_level': 'detail',
              'location_evidence': {'url': url, 'method': 'retained_publisher_address',
                                    'quote': addresses[0].group(0).strip()},
              'content_evidence': {'provider': 'tavily', 'request_id': metadata.get('request_id'),
                                   'truncated': metadata.get('raw_content_truncated', False)}}
    # Keep complete source paragraphs verbatim. Never mix dated notices or hours
    # from a center, park, parking lot or government office into one schedule.
    paragraphs = []
    for paragraph in re.split(r'\n\s*\n', text):
        paragraph = ' '.join(paragraph.split())
        if (len(paragraph) >= 80 and not paragraph.startswith(('#', '*', '[', '|'))
                and re.search(r'\b(has|features|includes|offers)\b', paragraph, re.I)
                and not re.search(r'\b(permit|prohibited|announcement|closed|will open)\b', paragraph, re.I)
                and re.search(r'[.!?]$', paragraph)):
            paragraphs.append(paragraph)
    if paragraphs:
        record['description'] = '\n\n'.join(paragraphs)[:12000]
    return [record]
