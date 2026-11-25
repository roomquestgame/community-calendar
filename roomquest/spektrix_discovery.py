"""Find *candidate* Spektrix client names in an official publisher web page.

Discovery supplies evidence, never a source approval or authorization to use
an API. Venue ownership, public GET access, real Event/Instance facts and
matching publisher event links must be verified downstream.
"""
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit

MAX_SCAN = 256_000
MAX_LINKS = 200
CLIENT = re.compile(r'^[a-z][a-z0-9_-]{1,59}$')
WEBSITE = re.compile(
    r'^/([a-z][a-z0-9_-]{1,59})/website/'
    r'(?:ChooseSeats|EventList|EventDetails|KeepAlive|Booking|ViewEvent)\.aspx$', re.I)
API = re.compile(r'^/([a-z][a-z0-9_-]{1,59})/api/v3/(?:events|instances|venues)(?:/|$)', re.I)
WEB_COMPONENTS = re.compile(
    r'^/([a-z][a-z0-9_-]{1,59})/api/v3/webcomponents/html/?$', re.I)
THIRD_PARTY = {'system.spektrix.com', 'api.system.spektrix.com'}


def _organization_domain(host):
    if not host:
        return ''
    parts = host.casefold().split('.')
    if (len(parts) >= 3 and parts[-1] in ('uk', 'au', 'nz')
            and parts[-2] in ('co', 'org', 'ac', 'net', 'gov')):
        return '.'.join(parts[-3:])
    return '.'.join(parts[-2:]) if len(parts) >= 2 else host.casefold()


class _Links(HTMLParser):
    def __init__(self, page):
        super().__init__(convert_charrefs=True)
        self.page = page
        self.urls = []

    def handle_starttag(self, tag, attrs):
        # Spektrix's public web-component loader derives its branded API import
        # at runtime from these publisher-authored attributes.  Capture that
        # static proof without executing JavaScript.  The ordinary URL loop
        # below still enforces HTTPS, exact client syntax, same-organization
        # ownership, ambiguity and the central-host boundary.
        if tag.startswith('spektrix-'):
            attributes = dict(attrs)
            client = attributes.get('client-name')
            domain = attributes.get('custom-domain')
            if (isinstance(client, str) and CLIENT.fullmatch(client.casefold())
                    and isinstance(domain, str) and 3 <= len(domain) <= 253
                    and '/' not in domain and '@' not in domain and ':' not in domain):
                branded = urlsplit('https://' + domain.casefold())
                if branded.hostname == domain.casefold():
                    self.urls.append(
                        'https://' + branded.hostname + '/' + client.casefold()
                        + '/api/v3/webcomponents/html')
                    if len(self.urls) > MAX_LINKS:
                        raise ValueError('spektrix_discovery_link_limit')
        if tag not in ('a', 'iframe', 'script', 'link'):
            return
        attributes = dict(attrs)
        raw = attributes.get('href') if tag in ('a', 'link') else attributes.get('src')
        if not isinstance(raw, str) or not raw.strip() or len(raw) > 1500:
            return
        self.urls.append(urljoin(self.page, raw.strip()))
        if len(self.urls) > MAX_LINKS:
            raise ValueError('spektrix_discovery_link_limit')


def discover(publisher_url, html):
    """Publisher-linked clients, with evidence URL and ambiguity preserved."""
    try:
        page = urlsplit(publisher_url)
        if (page.scheme != 'https' or not page.hostname or page.username or page.password
                or not isinstance(html, str) or not html.lstrip().startswith('<')
                or len(html) > 2_500_000):
            raise ValueError
        reader = _Links(publisher_url)
        reader.feed(html[:MAX_SCAN] + html[-MAX_SCAN:] if len(html) > MAX_SCAN else html)
    except (ValueError, AssertionError):
        return {'status': 'invalid_page', 'candidates': []}
    clients = {}
    for link in reader.urls:
        try:
            uri = urlsplit(link)
            if uri.scheme != 'https' or not uri.hostname or uri.username or uri.password:
                continue
            platform = uri.hostname in THIRD_PARTY
            if not platform and _organization_domain(uri.hostname) != _organization_domain(page.hostname):
                continue
            branded_api = (API.match(uri.path) or WEB_COMPONENTS.match(uri.path)) \
                if not platform else None
            match = ((WEBSITE.match(uri.path) or API.match(uri.path)) if platform
                     else (WEBSITE.match(uri.path) or branded_api))
            if match is None:
                continue
            client = match[1].casefold()
            if not CLIENT.fullmatch(client):
                continue
            # The public publisher page can establish a client-name candidate
            # but cannot prove that the API belongs to the same live venue.
            record = {
                'client': client, 'evidence_url': link,
                'evidence_type': ('spektrix_host' if platform else
                                  'first_party_api' if branded_api else
                                  'first_party_booking'),
                'api_verified': False,
            }
            if branded_api:
                record['api_base'] = (
                    'https://' + uri.hostname.casefold() + '/' + client + '/api/v3')
            clients.setdefault(client, []).append(record)
        except ValueError:
            continue
    records = [items[0] for items in clients.values()]
    return {'status': ('unverified' if len(records) == 1
                       else 'ambiguous' if len(records) > 1 else 'none'),
            'candidates': sorted(records, key=lambda row: row['client'])}
