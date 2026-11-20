"""Extract physical US addresses from the LOCATION text of a registered calendar."""

import re
from collections import defaultdict

from scripts.combine_ics import US_STATES

_STATE_NAMES = (
    'Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|'
    'Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|'
    'Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|'
    'New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|'
    'Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|'
    'West Virginia|Wisconsin|Wyoming|District of Columbia'
)
_STATE_CODES = dict(zip(_STATE_NAMES.lower().split('|'), US_STATES.split('|'), strict=True))
_STATES = set(_STATE_CODES.values())
_SUFFIX = r'(?:street|st|avenue|ave|road|rd|drive|dr|boulevard|blvd|lane|ln|court|ct|circle|cir|highway|hwy|parkway|pkwy|place|pl|way|terrace|ter|loop|trail|trl)'
_CITY = r"[A-Za-z][A-Za-z .'’\-]{0,55}?"
_ZIP = r'\d{5}(?:-\d{4})?'
_SEPARATOR = r'(?:\s*,\s*|\s+)'
_UNIT = r'(?:suite|ste\.?|unit|apt\.?|\#)\s*[\w-]+'
_STREET = r"\d{1,7}[A-Za-z]?\s+[\w .'’\-]{1,72}?"
_ADDRESS = re.compile(
    rf'(?P<street>{_STREET}(?:\s*,\s*{_UNIT})?)\s*,\s*'
    rf'(?P<city>{_CITY}){_SEPARATOR}(?P<state>[A-Za-z]{{2}})?\s*,?\s*(?P<zip>{_ZIP})?$',
    re.I)
_JOINED = re.compile(
    rf'(?P<street>{_STREET}\b{_SUFFIX}\.?(?:\s+(?:NE|NW|SE|SW|N|S|E|W))?'
    rf'(?:{_SEPARATOR}{_UNIT})?){_SEPARATOR}(?P<city>{_CITY})'
    rf'{_SEPARATOR}(?P<state>[A-Za-z]{{2}})?\s*,?\s*(?P<zip>{_ZIP})?$', re.I)
_STATE_NAME_END = re.compile(r'\b(?:' + '|'.join(sorted(_STATE_CODES, key=len, reverse=True))
                             + rf')(?=,?\s*(?:{_ZIP})?$)', re.I)
_UNUSABLE = re.compile(r'[<>;|@]|https?://|\b(?:online|virtual|zoom|webinar|P\.?\s*O\.?\s+box)\b', re.I)
_NUMBER = re.compile(r"(?<![\w-])\d{1,7}[A-Za-z]?\s+(?=[A-Za-z])")
_REPEAT_LOCALITY = re.compile(rf'\b(?P<local>{_CITY}\s+(?:{US_STATES})\s+{_ZIP})\s+(?P=local)$', re.I)


def _parts(raw):
    # Raw LOCATION is retained in venue_name, including non-address information.
    if not raw or len(raw) >= 160 or _UNUSABLE.search(raw):
        return None
    text = re.sub(r'\s+', ' ', raw.replace('\n', ', ')).strip(' ,-')
    text = re.sub(r',\s*(?:USA|US|United States(?: of America)?)$', '', text, flags=re.I)
    text = _STATE_NAME_END.sub(lambda m: _STATE_CODES[m.group().lower()], text)
    text = _REPEAT_LOCALITY.sub(r'\g<local>', text)
    number = _NUMBER.search(text)
    if not number:
        return None
    venue = text[:number.start()].strip(' ,-')
    body = text[number.start():]
    # An explicit comma after the street takes precedence over a street
    # suffix embedded in a name such as "West End Ave". A lone "SD 57501"
    # after a comma is state/ZIP, not a full city and state.
    explicit = _ADDRESS.fullmatch(body)
    match = explicit if explicit and explicit['state'] else _JOINED.fullmatch(body) or explicit
    if not match:
        return None
    street, city, state, postal = match.group('street', 'city', 'state', 'zip')
    state = (state or '').upper()
    return venue, street.strip(), city.strip(), state, postal or ''


def extract_venue_addresses(rows):
    """A damaged state needs a unique complete match within this same snapshot."""
    parsed = {}
    states = defaultdict(set)
    for row in rows:
        raw = row.get('venue_name') or ''
        if row.get('venue_address') not in (None, '', raw) or raw in parsed:
            continue
        parts = _parts(raw)
        if not parts:
            parsed[raw] = None
            continue
        venue, street, city, state, postal = parts
        identity = (venue.casefold(), street.casefold(), city.casefold(), postal)
        parsed[raw] = (street, city, state, postal, identity)
        if state in _STATES:
            states[identity].add(state)

    for row in rows:
        raw = row.get('venue_name') or ''
        if not parsed.get(raw) or row.get('venue_address') not in (None, '', raw):
            continue
        street, city, state, postal, identity = parsed[raw]
        if state not in _STATES:
            alternatives = states[identity]
            if not (postal and identity[0] and len(alternatives) == 1):
                continue
            state = next(iter(alternatives))
        row['venue_address'] = f'{street}, {city}, {state}' + (f' {postal}' if postal else '')
        row['venue_city'] = row.get('venue_city') or city
