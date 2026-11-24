"""Unregistered Spektrix URLs cannot bypass stored provider profiles."""
from datetime import date

import pytest

from roomquest import provider_registration, spektrix_provider, spektrix_v3
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


def test_exact_source_url_and_publisher_profile_are_required():
    assert spektrix_provider.validate(source(),profile())==profile()
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


def test_provider_registration_bridge_rejects_missing_profile():
    with pytest.raises(ValueError,match='spektrix_provider_profile_required'):
        provider_registration.collect(URL,'spektrix',lambda url,accept:'[]',
                                      deadline=100,profile=None)

def test_staged_spektrix_profile_cannot_register_or_collect():
    with pytest.raises(ValueError, match='spektrix_provider_not_enabled'):
        provider_registration.collect(
            URL,'spektrix',lambda url,accept:'[]',deadline=100,
            profile={**profile(),'ready_for_registration':False},registration_probe=True)
    with pytest.raises(ValueError,match='spektrix_provider_checkpoint_required'):
        provider_registration.collect(
            URL,'spektrix',lambda url,accept:'[]',deadline=100,
            profile={**profile(),'ready_for_registration':True})
