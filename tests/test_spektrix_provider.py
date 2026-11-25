"""Unregistered Spektrix URLs cannot bypass stored provider profiles."""
from datetime import date

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


def test_short_live_probe_calls_bounded_api_with_injected_transport(monkeypatch):
    called=[]
    def fake_collect(value,start,end,fetch,deadline_at=None):
        called.append((value,start,end,deadline_at))
        return {'complete':True,'events':[]}
    monkeypatch.setattr(spektrix_v3,'collect',fake_collect)
    got=spektrix_provider.probe(source(),profile(),lambda url,accept: '{}',
        today=date(2026,11,24),deadline_at=12)
    assert got==[]
    assert len(called)==1
    assert (called[0][2]-called[0][1]).days==spektrix_provider.MAX_PROBE_DAYS-1


def test_public_feed_does_not_require_a_stored_profile():
    assert provider_registration.collect(
        URL, 'spektrix', lambda url, accept: '[]', deadline=100,
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
        URL, 'spektrix', lambda url, accept: '[]', deadline=100,
        profile=None) == []
