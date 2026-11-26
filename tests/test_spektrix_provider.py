"""Unregistered Spektrix URLs cannot bypass stored provider profiles."""
from datetime import date
from urllib.parse import urlsplit
from time import monotonic

import pytest

from roomquest import provider_registration, spektrix_discovery, spektrix_provider, spektrix_v3
from roomquest.registration_formats import source_key

CLIENT='thealbany'
URL='https://system.spektrix.com/thealbany/api/v3/events'
PUBLISHER='https://www.thealbany.org.uk/events'
EVENT='347737AVNHRBKMRLMQKLLCMGLMCVVMMVC'
VENUE='201AGBHDRLQHNHPHKKMPKLGPMDRDTDMVL'


def source():
    return {'source_key':source_key(URL),'feed_url':URL,
            'platform_adapter':'spektrix','kind':'json'}


def profile():
    return {
        'client':CLIENT,'publisher_url':PUBLISHER,
        'country':'GB','home_city':'London','timezone':'Europe/London',
        'event_urls':{EVENT:'https://www.thealbany.org.uk/events/gingerbread-man/'},
        'verified_plans':{},
        'verified_venues':{VENUE:{
            'address':'9 Giffin Street, London SE8 4RJ','city':'London',
            'evidence_url':'https://www.thealbany.org.uk/venues/deptford-lounge'}}
    }


def test_only_canonical_source_api_is_detected():
    assert provider_registration.family(URL)=='spektrix'
    for endpoint in (
        'https://system.spektrix.com/thealbany/api/v3/instances',
        URL+'?instanceStart_from=2026-11-24',
        'https://example.net/thealbany/api/v3/events',
        'https://system.spektrix.com/not/a/venue',
    ):
        assert not spektrix_provider.family(endpoint)


def test_direct_client_website_is_deterministic_registration_evidence():
    fox = 'https://tickets.foxtucson.com/foxtucsontheatre/website/'
    assert spektrix_discovery.submitted_website(fox) == {
        'client': 'foxtucsontheatre',
        'evidence_url': fox,
        'evidence_type': 'branded_client_website',
        'api_base': 'https://tickets.foxtucson.com/foxtucsontheatre/api/v3',
        'api_verified': False,
    }
    assert spektrix_discovery.submitted_website(
        'https://system.spektrix.com/thealbany/website')['client'] == 'thealbany'
    for invalid in (
        'https://example.org/foxtucsontheatre/website/',
        'https://tickets.foxtucson.com/foxtucsontheatre/website/?venue=other',
        'https://tickets.foxtucson.com/foxtucsontheatre/website/EventList.aspx',
    ):
        assert spektrix_discovery.submitted_website(invalid) is None


def test_same_organization_branded_api_is_exactly_bound():
    branded = ('https://tickets.beaconartscentre.co.uk/beaconartscentre/'
               'api/v3/events')
    branded_source = {
        'source_key': source_key(branded), 'feed_url': branded,
        'platform_adapter': 'spektrix', 'kind': 'json',
    }
    branded_profile = {
        **profile(),
        'client': 'beaconartscentre',
        'publisher_url': 'https://www.beaconartscentre.co.uk/whats-on/',
        'api_base': ('https://tickets.beaconartscentre.co.uk/'
                     'beaconartscentre/api/v3'),
        'event_urls': {}, 'verified_venues': {},
    }
    assert spektrix_provider.family(branded)
    assert spektrix_provider.validate(branded_source, branded_profile) == branded_profile
    with pytest.raises(ValueError, match='spektrix_provider_source_invalid'):
        spektrix_provider.validate(
            branded_source,
            dict(branded_profile,
                 api_base='https://tickets.attacker.org.uk/beaconartscentre/api/v3'))


def test_exact_source_url_and_publisher_profile_are_required():
    validated = spektrix_provider.validate(source(), profile())
    assert validated['client'] == CLIENT
    assert validated['api_base'] == 'https://system.spektrix.com/thealbany/api/v3'
    assert validated['publisher_url'] == PUBLISHER
    for modified in (
        dict(source(),source_key='municipal_wrong'),
        dict(source(),feed_url='https://system.spektrix.com/richmix/api/v3/events'),
        dict(source(),kind='html'),
    ):
        with pytest.raises(ValueError,match='spektrix_provider_source_invalid'):
            spektrix_provider.validate(modified,profile())
    invalid=dict(profile(),event_urls={EVENT:'https://other.example.org/show'})
    with pytest.raises(ValueError,match='spektrix_provider_event_links_invalid'):
        spektrix_provider.validate(source(),invalid)


def test_registration_probe_matches_recurring_window_with_injected_transport(monkeypatch):
    called=[]
    def fake_collect(value,start,end,fetch,deadline_at=None):
        called.append((value,start,end,deadline_at))
        return {'complete':True,'events':[]}
    monkeypatch.setattr(spektrix_v3,'collect',fake_collect)
    got=spektrix_provider.probe(source(),profile(),lambda url,accept: '{}',
        today=date(2026,11,24),deadline_at=12)
    assert got==[]
    assert len(called)==1
    assert (called[0][2]-called[0][1]).days==spektrix_v3.MAX_DAYS-1


def test_public_feed_does_not_require_a_stored_profile():
    assert provider_registration.collect(
        URL, 'spektrix', lambda url, accept: '[]', deadline=monotonic()+10,
        profile=None, registration_probe=True) == []


def test_verified_plan_profiles_are_bounded():
    value = profile()
    value['verified_plans'] = {
        '1801APGQPRKNVLCHGSKJBCTJKDRMGPLNL': {
            'address': '160 Whitechapel Road, London E1 1BJ'}}
    assert spektrix_provider.validate(source(), value)['verified_plans'] == value['verified_plans']
    value['verified_plans'] = []
    with pytest.raises(ValueError, match='spektrix_provider_plans_invalid'):
        spektrix_provider.validate(source(), value)
    value['verified_plans'] = {'bad': {}}
    with pytest.raises(ValueError, match='spektrix_provider_plans_invalid'):
        spektrix_provider.validate(source(), value)


def test_public_feed_uses_the_same_dispatch_for_recurring_collection():
    assert provider_registration.collect(
        URL, 'spektrix', lambda url, accept: '[]', deadline=monotonic()+10,
        profile=None) == []


def test_later_performance_registers_and_collects_with_identical_native_identity():
    """Atlantic canary: no first-fortnight rows, real performance on day 17."""
    import json
    from urllib.parse import parse_qs, urlsplit
    from datetime import datetime, timezone, timedelta
    today = datetime.now(timezone.utc).date()
    performance = today + timedelta(days=16)
    event_id = '6801ABTVLJRVPSSSGRNRDNBVDKGKTRLVM'
    instance_id = '55001AMSBLSDPDNMRVSMJKRHLNGCNQBMH'
    plan_id = '1001ADGKSHLJDTDBJQTBMGLLJRLBJCMNN'
    venue_id = '401ANPJQJQPQMRSBDNMVNLSPGTRBVQVRH'
    url = 'https://tickets.example.org/atlantic/api/v3/events'
    calls = []
    def fetch(target, accept):
        calls.append(target)
        parts = urlsplit(target)
        query = parse_qs(parts.query)
        if parts.path.endswith('/venues'):
            return json.dumps([{'id': venue_id, 'name': 'Theater',
                                'address': '336 W 20th Street, New York, NY 10011'}])
        last = query.get('instanceStart_to', query.get('startTo'))[0]
        if performance.isoformat() > last:
            return '[]'
        if parts.path.endswith('/events'):
            return json.dumps([{'id': event_id, 'name': 'FINN', 'duration': 0,
                                'webUrl': '', 'webEventId': 'AFKFINN'}])
        return json.dumps([{'id': instance_id, 'event': {'id': event_id},
                            'planId': plan_id, 'isOnSale': True, 'cancelled': False,
                            'start': str(performance)+'T16:00:00',
                            'startUtc': str(performance)+'T21:00:00'}])
    kwargs = dict(deadline=monotonic()+20, profile=None)
    initial = provider_registration.collect(url, 'spektrix', fetch,
                                             registration_probe=True, **kwargs)
    refresh = provider_registration.collect(url, 'spektrix', fetch, **kwargs)
    assert len(initial) == 1
    assert initial == refresh
    assert len(calls) == 6  # Same three bounded resources, no fallback probe.
    assert all(str(today+timedelta(days=59)) in target
               for target in calls if not target.endswith('/venues'))
    assert 'AFKFINN' in initial[0]['event_url']

@pytest.mark.parametrize('url,link', [
    ('https://tickets.z-arts.org/zarts/api/v3/events', 'https://www.z-arts.org/events/the-library-of-enchantment/'),
    ('https://tickets.planosymphony.org/planosymphony/api/v3/events', 'https://planosymphony.org/guildfestiveeve/'),
    ('https://boxoffice.example.co.uk/client/api/v3/events', 'https://www.example.co.uk/events/show/'),
])
def test_native_api_main_publisher_weburl(url, link):
    config = spektrix_provider.profile(url)
    assert spektrix_v3._event_url({'id': EVENT, 'webUrl': link}, config) == link
    assert config['api_base'] + '/events' == url
    assert urlsplit(config['publisher_url']).hostname == urlsplit(url).hostname

@pytest.mark.parametrize('link', [
    'https://evil.example/events/show/',
    'https://www.z-arts.org.evil.example/events/show/',
    'https://other.z-arts.org/events/show/',
    'http://www.z-arts.org/events/show/',
    'https://www.z-arts.org/events/show/#fragment',
])
def test_main_publisher_link_does_not_admit_other_hosts_or_invalid_urls(link):
    with pytest.raises(ValueError, match='spektrix_event_link_unverified'):
        spektrix_v3._event_url({'id': EVENT, 'webUrl': link},
            spektrix_provider.profile('https://tickets.z-arts.org/zarts/api/v3/events'))

def test_central_api_has_no_inferred_publisher_link_hosts():
    assert not spektrix_provider.profile(URL).get('verified_event_hosts')
    assert not spektrix_provider.profile('https://tickets.spektrix.com/client/api/v3/events').get('verified_event_hosts')

@pytest.mark.parametrize('url,link', [
    ('https://tickets.z-arts.org/zarts/api/v3/events', 'https://www.z-arts.org/events/the-library-of-enchantment/'),
    ('https://tickets.planosymphony.org/planosymphony/api/v3/events', 'https://planosymphony.org/guildfestiveeve/'),
])
def test_main_publisher_weburl_survives_native_staging_evidence(url, link):
    from roomquest import registered_native_content as native
    config = spektrix_provider.profile(url)
    claim = {'source_key': source_key(url), 'feed_url': url, 'kind': 'json',
             'platform_adapter': 'spektrix', 'registered_native_content_version': 1}
    event_url = spektrix_v3._event_url({'id': EVENT, 'webUrl': link}, config)
    rows = spektrix_provider.stageable(claim, {'complete': True, 'events': [{
        'id': config['client'] + ':1234567890', 'title': 'Publisher event',
        'starts_at': '2026-12-12T18:00:00+00:00', 'event_url': event_url,
        'venue_name': 'Venue', 'venue_address': '',
        'source_event_id': EVENT, 'source_instance_id': '1234567890',
        'source_plan_id': '2234567890', 'source_venue_id': VENUE,
    }]})
    native.attach(rows[0], claim, description_value='Native publisher text')
    assert rows[0]['registered_native_content']['event_url'] == link
    assert rows[0]['registered_native_content']['feed_url'] == url
    assert rows[0]['spektrix_location']['source_venue_id'] == VENUE
    assert not native.event_url_matches(claim, 'https://other.example/event')
