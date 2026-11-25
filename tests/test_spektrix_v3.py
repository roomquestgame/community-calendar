"""Offline read-only Spektrix v3 public collection and tenant discovery tests."""
from datetime import date, timedelta
from threading import Lock
from time import sleep

import pytest

from roomquest import spektrix_discovery as discovery
from roomquest import spektrix_v3 as api

START = '2026-12-05'
STOP = '2026-12-08'
EVENT = '347737AVNHRBKMRLMQKLLCMGLMCVVMMVC'
INSTANCE = '1928802AGPJVJCHJVPHSNVRRBPHQBSJJQ'
PLAN = '1801APGQPRKNVLCHGSKJBCTJKDRMGPLNL'
VENUE = '201AGBHDRLQHNHPHKKMPKLGPMDRDTDMVL'


def profile(**overrides):
    return {
        'client': 'thealbany',
        'publisher_url': 'https://www.thealbany.org.uk/events',
        'country': 'GB',
        'timezone': 'Europe/London',
        'home_city': 'London',
        **overrides,
    }


def event(**overrides):
    return {'id': EVENT, 'name': 'Christmas: The Gingerbread Man', 'description': 'Family fun',
            'webUrl': 'https://www.thealbany.org.uk/events/gingerbread-man/',
            'imageUrl': '', 'duration': 55, **overrides}


def instance(**overrides):
    return {'id': INSTANCE, 'event': {'id': EVENT}, 'planId': PLAN,
            'start': '2026-12-05T14:00:00', 'startUtc': '2026-12-05T14:00:00Z',
            'isOnSale': True, 'cancelled': False, **overrides}


def plan(**overrides):
    return {'id': PLAN, 'name': 'Main Stage',
            'venue': {'id': VENUE}, **overrides}


def venue(**overrides):
    return {'id': VENUE, 'name': 'The Albany',
            'address': 'Douglas Way, London, SE8 4AG', **overrides}


def test_date_window_exactly_60_days_and_readonly_fixed_urls():
    start = date(2026, 11, 24)
    end = start + timedelta(days=59)
    chunks = api.windows(start, end)
    assert len(chunks) == 1
    assert chunks[0] == (start, end)
    assert chunks[-1][1] == end
    assert sum((b - a).days + 1 for a, b in chunks) == 60
    assert api.api_url('thealbany', 'events', start=START, end=STOP).endswith(
        '/events?instanceStart_from=2026-12-05&instanceStart_to=2026-12-08')
    assert api.api_url('thealbany', 'instances', start=START, end=STOP).endswith(
        '/instances?startFrom=2026-12-05&startTo=2026-12-08')
    assert api.api_url('thealbany', 'plans', identity=PLAN).endswith('/plans/' + PLAN)
    assert api.api_url('thealbany', 'venues').endswith('/venues')
    with pytest.raises(ValueError, match='spektrix_window_invalid'):
        api.windows(start, start + timedelta(days=60))
    for client in ('../other', 'thealbany/api/v3/venues', 'THEALBANY', ''):
        with pytest.raises(ValueError, match='spektrix_client_invalid'):
            api.api_url(client, 'venues')
    with pytest.raises(ValueError, match='spektrix_route_invalid'):
        api.api_url('thealbany', 'customers')


def test_instance_plan_venue_link_has_stable_performance_identity():
    result = api.project(profile(), [event()], [instance()], [plan()], [venue()],
                         START, STOP)
    assert result['complete'] is True
    assert result['instance_total'] == 1
    assert result['held_unsale_or_cancelled'] == 0
    [row] = result['events']
    assert row['id'] == 'thealbany:' + INSTANCE
    assert row['source_event_id'] == EVENT
    assert row['source_venue_id'] == VENUE
    assert row['starts_at'] == '2026-12-05T14:00:00+00:00'
    assert row['ends_at'] == '2026-12-05T14:55:00+00:00'
    assert row['venue_name'] == 'The Albany'
    assert row['venue_city'] == 'London'
    assert row['event_url'].startswith('https://www.thealbany.org.uk/events/')


def test_api_facts_are_collectable_without_a_manual_location_profile():
    value = {
        'client': 'foxtucsontheatre',
        'api_base': 'https://tickets.foxtucson.com/foxtucsontheatre/api/v3',
        'publisher_url': 'https://tickets.foxtucson.com/foxtucsontheatre/website/',
    }
    fox_event = event(id=EVENT, webUrl='', webEventId='gingerbread-man')
    fox_instance = instance(start='2026-12-05T07:00:00',
                            startUtc='2026-12-05T14:00:00Z')
    fox_venue = venue(name='Fox Tucson Theatre',
                      address='17 West Congress Street, Tucson, AZ 85701')
    [row] = api.project(value, [fox_event], [fox_instance], [plan()],
                        [fox_venue], START, STOP)['events']
    assert row['venue_city'] == 'Tucson'
    assert row['timezone'] is None
    assert row['event_url'].endswith(
        '/website/EventDetails.aspx?WebEventId=gingerbread-man')

def test_second_venue_is_not_replaced_by_first_venue():
    other = '401ANPJQJQPQMRSBDNMVNLSPGTRBVQVRH'
    new_plan = '9806ASSTKDLDBPRRRVQQRRDHSJMQVBSNQ'
    rows = api.project(profile(),
        [event()], [instance(planId=new_plan)],
        [plan(id=new_plan, venue={'id': other})],
        [venue(), venue(id=other, name='Canada Water Theatre',
                        address='21 Surrey Quays Rd, London SE16 7AR')],
        START, STOP)['events']
    assert len(rows) == 1
    assert rows[0]['source_venue_id'] == other
    assert rows[0]['venue_name'] == 'Canada Water Theatre'


def test_missing_venue_event_link_or_matching_event_fails_whole_snapshot():
    scenarios = [
        ([event()], [instance()], [], [venue()], 'spektrix_plan_venue_unresolved'),
        ([event()], [instance()], [plan()], [], 'spektrix_plan_venue_unresolved'),
        ([event(webUrl='http://evil.example/show')], [instance()], [plan()], [venue()],
         'spektrix_event_link_unverified'),
        ([], [instance()], [plan()], [venue()], 'spektrix_event_manifest_mismatch'),
    ]
    for events, instances, plans, venues, reason in scenarios:
        with pytest.raises(ValueError, match=reason):
            api.project(profile(), events, instances, plans, venues, START, STOP)


def test_cancelled_and_unsold_performances_never_get_published():
    result = api.project(profile(), [event()],
                         [instance(cancelled=True)], [], [], START, STOP)
    assert result['events'] == []
    assert result['held_unsale_or_cancelled'] == 1
    result = api.project(profile(), [event()],
                         [instance(isOnSale=False)], [], [], START, STOP)
    assert result['events'] == []


def test_venue_api_missing_address_requires_verified_override():
    blank = venue(address='')
    with pytest.raises(ValueError, match='spektrix_venue_location_unresolved'):
        api.project(profile(), [event()], [instance()], [plan()], [blank], START, STOP)
    source = profile(verified_venues={
        VENUE: {'address': '35-47 Bethnal Green Road, London E1 6LA',
                'city': 'London', 'timezone': 'Europe/London',
                'evidence_url': 'https://www.thealbany.org.uk/visit-us'}})
    row = api.project(source, [event()], [instance()], [plan()], [blank],
                      START, STOP)['events'][0]
    assert 'Bethnal Green' in row['venue_address']


def test_generic_blank_venue_can_use_narrow_verified_plan_location():
    blank = venue(name='Spitalfields Music', address='')
    source = profile(verified_plans={
        PLAN: {
            'name': 'Tower Hamlets Town Hall',
            'address': '160 Whitechapel Road, London E1 1BJ',
            'city': 'London',
            'timezone': 'Europe/London',
            'evidence_url': 'https://www.thealbany.org.uk/visit-us',
        }
    })
    row = api.project(source, [event()], [instance()], [plan()], [blank],
                      START, STOP)['events'][0]
    assert row['source_plan_id'] == PLAN
    assert row['source_venue_id'] == VENUE
    assert row['venue_name'] == 'Tower Hamlets Town Hall'
    assert row['venue_address'] == '160 Whitechapel Road, London, E1 1BJ'

    # The reviewed address is plan-scoped. A second plan that reuses the same
    # generic blank Venue must not inherit the first plan's location.
    other_plan = '9806ASSTKDLDBPRRRVQQRRDHSJMQVBSNQ'
    with pytest.raises(ValueError, match='spektrix_venue_location_unresolved'):
        api.project(source, [event()], [instance(planId=other_plan)],
                    [plan(id=other_plan)], [blank], START, STOP)


def test_local_and_utc_clocks_must_match_and_reject_ambiguous_dst():
    with pytest.raises(ValueError, match='spektrix_time_conflict'):
        api.project(profile(), [event()], [instance(startUtc='2026-12-05T15:00:00')],
                    [plan()], [venue()], START, STOP)
    with pytest.raises(ValueError, match='spektrix_time_invalid'):
        api.project(profile(), [event()], [
            instance(start='2026-10-25T01:30:00', startUtc='2026-10-25T00:30:00')],
            [plan()], [venue()], '2026-10-25', '2026-10-25')


def test_one_shot_collection_uses_single_venue_without_plan_downloads():
    client = 'thealbany'
    responses = {
        api.api_url(client, 'events', start=START, end=STOP): [event()],
        api.api_url(client, 'instances', start=START, end=STOP): [instance()],
        api.api_url(client, 'venues'): [venue()],
    }
    visited = []

    def fetch(url, accept):
        assert accept == 'application/json'
        visited.append(url)
        return responses[url]

    result = api.collect(profile(), START, STOP, fetch)
    assert len(result['events']) == 1
    assert set(visited) == set(responses)
    assert len(visited) == len(responses)
    assert not any('/plans/' in url for url in visited)
    del responses[api.api_url(client, 'venues')]
    with pytest.raises(KeyError):
        api.collect(profile(), START, STOP, fetch)


def test_multi_venue_collection_resolves_each_plan():
    client = 'thealbany'
    other = '401ANPJQJQPQMRSBDNMVNLSPGTRBVQVRH'
    responses = {
        api.api_url(client, 'events', start=START, end=STOP): [event()],
        api.api_url(client, 'instances', start=START, end=STOP): [instance()],
        api.api_url(client, 'venues'): [venue(), venue(id=other, name='Other')],
        api.api_url(client, 'plans', identity=PLAN): plan(),
    }
    visited = []
    result = api.collect(
        profile(), START, STOP,
        lambda url, accept: (visited.append(url), responses[url])[1])
    assert len(result['events']) == 1
    assert visited[-1].endswith('/plans/' + PLAN)


def test_multi_venue_plan_fetches_are_concurrent_but_bounded():
    client = 'thealbany'
    other_venue = '401ANPJQJQPQMRSBDNMVNLSPGTRBVQVRH'
    plan_ids = [PLAN] + [f'plan-{index:010d}' for index in range(1, 7)]
    instances = [instance(
        id=f'instance-{index:010d}', planId=plan_id,
        start=f'2026-12-{5 + index:02d}T14:00:00',
        startUtc=f'2026-12-{5 + index:02d}T14:00:00Z')
        for index, plan_id in enumerate(plan_ids)]
    responses = {
        api.api_url(client, 'events', start=START, end=STOP): [event()],
        api.api_url(client, 'instances', start=START, end=STOP): instances[:4],
        api.api_url(client, 'venues'): [venue(), venue(id=other_venue, name='Other')],
    }
    for plan_id in plan_ids[:4]:
        responses[api.api_url(client, 'plans', identity=plan_id)] = plan(id=plan_id)
    active = peak = 0
    lock = Lock()

    def fetch(url, accept):
        nonlocal active, peak
        assert accept == 'application/json'
        if '/plans/' not in url:
            return responses[url]
        with lock:
            active += 1
            peak = max(peak, active)
        sleep(0.03)
        with lock:
            active -= 1
        return responses[url]

    result = api.collect(profile(), START, STOP, fetch)
    assert len(result['events']) == 4
    assert 1 < peak <= api.MAX_CONCURRENT_PLAN_REQUESTS


def test_first_party_booking_link_yields_candidate_not_auto_admission():
    html = ('<html><iframe src="https://tickets.richmix.org.uk/richmix/website/'
            'ChooseSeats.aspx?EventInstanceId=1930202"></iframe></html>')
    got = discovery.discover('https://richmix.org.uk/music-and-events/', html)
    assert got['status'] == 'unverified'
    assert got['candidates'][0]['client'] == 'richmix'
    assert got['candidates'][0]['api_verified'] is False
    assert got['candidates'][0]['evidence_type'] == 'first_party_booking'
    got = discovery.discover(
        'https://www.cornex.co.uk/events',
        '<html><iframe src="https://tickets.cornex.co.uk/cambridgelive/'
        'website/KeepAlive.aspx"></iframe></html>')
    assert got['candidates'][0]['client'] == 'cambridgelive'


def test_first_party_branded_web_components_yields_exact_api_base():
    html = ('<html><link rel="import" href="https://tickets.beaconartscentre.co.uk/'
            'beaconartscentre/api/v3/webcomponents/html"></html>')
    got = discovery.discover('https://www.beaconartscentre.co.uk/whats-on/', html)
    assert got == {
        'status': 'unverified',
        'candidates': [{
            'client': 'beaconartscentre',
            'evidence_url': ('https://tickets.beaconartscentre.co.uk/'
                             'beaconartscentre/api/v3/webcomponents/html'),
            'evidence_type': 'first_party_api',
            'api_verified': False,
            'api_base': ('https://tickets.beaconartscentre.co.uk/'
                         'beaconartscentre/api/v3'),
        }],
    }
    assert api.api_url('beaconartscentre', 'venues',
                       base=got['candidates'][0]['api_base']) == (
        'https://tickets.beaconartscentre.co.uk/beaconartscentre/api/v3/venues')
    with pytest.raises(ValueError, match='spektrix_api_base_invalid'):
        api.api_url('beaconartscentre', 'venues',
                    base='https://tickets.beaconartscentre.co.uk/other/api/v3')


def test_static_web_component_attributes_yield_same_branded_api_without_js():
    html = ('<html><spektrix-donate client-name="beaconartscentre" '
            'custom-domain="tickets.beaconartscentre.co.uk"></spektrix-donate></html>')
    got = discovery.discover('https://www.beaconartscentre.co.uk/whats-on/', html)
    assert got['status'] == 'unverified'
    assert got['candidates'][0] == {
        'client': 'beaconartscentre',
        'evidence_url': ('https://tickets.beaconartscentre.co.uk/'
                         'beaconartscentre/api/v3/webcomponents/html'),
        'evidence_type': 'first_party_api',
        'api_verified': False,
        'api_base': ('https://tickets.beaconartscentre.co.uk/'
                     'beaconartscentre/api/v3'),
    }
    foreign = html.replace('tickets.beaconartscentre.co.uk', 'tickets.attacker.org.uk')
    assert discovery.discover(
        'https://www.beaconartscentre.co.uk/whats-on/', foreign)['status'] == 'none'
    central = html.replace('tickets.beaconartscentre.co.uk', 'system.spektrix.com')
    assert discovery.discover(
        'https://www.beaconartscentre.co.uk/whats-on/', central)['status'] == 'none'


def test_large_publisher_page_bounds_only_spektrix_candidates():
    navigation = ''.join(
        '<a href="/ordinary-page-%d">Page %d</a>' % (index, index)
        for index in range(discovery.MAX_LINKS + 12))
    evidence = ('<link rel="import" href="https://tickets.beaconartscentre.co.uk/'
                'beaconartscentre/api/v3/webcomponents/html">')
    component = ('<spektrix-donate client-name="beaconartscentre" '
                 'custom-domain="tickets.beaconartscentre.co.uk"></spektrix-donate>')
    got = discovery.discover(
        'https://www.beaconartscentre.co.uk/whats-on/',
        '<html>' + navigation + evidence + component + '</html>')
    assert got['status'] == 'unverified'
    assert got['candidates'][0]['client'] == 'beaconartscentre'


def test_candidate_limit_still_fails_closed():
    evidence = ''.join(
        '<a href="https://system.spektrix.com/client%d/website/EventList.aspx">x</a>'
        % index for index in range(discovery.MAX_LINKS + 1))
    assert discovery.discover('https://publisher.example.org/events',
                              '<html>' + evidence + '</html>')['status'] == 'invalid_page'


def test_foreign_branded_api_is_not_discovered():
    html = ('<html><link rel="import" href="https://tickets.attacker.org.uk/'
            'beaconartscentre/api/v3/webcomponents/html"></html>')
    assert discovery.discover(
        'https://www.beaconartscentre.co.uk/whats-on/', html)['status'] == 'none'


def test_foreign_publisher_links_and_marketing_mentions_do_not_verify_clients():
    html = ('<html><p>Spektrix client richmix</p>'
            '<a href="https://tickets.attacker.org.uk/falseclient/website/'
            'ChooseSeats.aspx">External</a></html>')
    assert discovery.discover('https://richmix.org.uk/events', html)['status'] == 'none'
    result = discovery.discover('https://richmix.org.uk/events',
        '<html><a href="https://system.spektrix.com/richmix/website/EventList.aspx">One</a>'
        '<a href="https://system.spektrix.com/adctheatre/website/EventList.aspx">Two</a></html>')
    assert result['status'] == 'ambiguous'
    assert {x['client'] for x in result['candidates']} == {'richmix', 'adctheatre'}



def test_weekly_recurrence_ranges_do_not_duplicate_one_event_or_drop_instances():
    first = event(firstInstanceDateTime='2026-12-05T14:00:00',
                  lastInstanceDateTime='2026-12-08T14:00:00',
                  instanceDates='5 December-8 December')
    second = event(firstInstanceDateTime='2026-12-12T14:00:00',
                   lastInstanceDateTime='2026-12-19T14:00:00',
                   instanceDates='12 December-19 December')
    records = {}

    api._merge(records, [first], 'events', api.MAX_EVENTS)
    api._merge(records, [second], 'events', api.MAX_EVENTS)
    assert list(records) == [EVENT]
    with pytest.raises(ValueError, match='spektrix_events_conflict'):
        api._merge(records, [event(name='Entirely different event')], 'events',
                   api.MAX_EVENTS)


def test_payload_at_known_size_limit_is_not_certified_complete():
    with pytest.raises(ValueError, match='spektrix_events_invalid'):
        api._items([{}] * api.MAX_EVENTS, api.MAX_EVENTS, 'events')



def test_public_craft_page_matches_api_event_without_weburl():
    cms = [{
        'url': 'https://www.thealbany.org.uk/events/gingerbread-man/',
        'title': 'Christmas: The Gingerbread Man',
        'instances': ['2026-12-05T14:00:00+00:00'],
    }]
    rows = api.project(profile(), [event(webUrl='')], [instance()], [plan()],
                       [venue()], START, STOP, cms_pages=cms)['events']
    assert len(rows) == 1
    assert rows[0]['event_url'] == cms[0]['url']
    # With no CMS page, the documented Spektrix EventDetails route remains a
    # stable public event link derived from the API event ID.
    fallback = api.project(profile(), [event(webUrl='')], [instance()], [plan()],
                           [venue()], START, STOP)['events'][0]['event_url']
    assert fallback.endswith('/website/EventDetails.aspx?EventId=347737')


def test_cms_page_conflict_with_existing_verified_event_link_is_held():
    cms = [{
        'url': 'https://www.thealbany.org.uk/events/alternate-gingerbread/',
        'title': 'Christmas: The Gingerbread Man',
        'instances': ['2026-12-05T14:00:00Z'],
    }]
    with pytest.raises(ValueError, match='spektrix_event_link_conflict'):
        api.project(profile(event_urls={
            EVENT: 'https://www.thealbany.org.uk/events/gingerbread-man/'}),
            [event(webUrl='')], [instance()], [plan()], [venue()],
            START, STOP, cms_pages=cms)


@pytest.mark.parametrize('address,expected', [
    ('21 Dean St., London, W1D 3NE', 'Europe/London'),
    ('186 Hoe Street, London E17 4QH', 'Europe/London'),
    ('198 Hoe St, London E17 4BF', 'Europe/London'),
    ('17 West Congress Street, Tucson, AZ 85701', None),
    ('21 Dean Street, London W1D', None),
])
def test_native_postcode_timezone_without_profile(address, expected):
    result = api.project(profile(timezone=None), [event()], [instance()],
                         [plan()], [venue(address=address)], START, STOP)
    assert result['events'][0]['timezone'] == expected
    if expected == 'Europe/London':
        assert result['events'][0]['venue_address'].count(',') == 2
    else:
        assert result['events'][0]['venue_address'] == address


def test_native_postcode_timezone_still_checks_publisher_clock():
    with pytest.raises(ValueError, match='spektrix_time_conflict'):
        api.project(profile(timezone=None), [event()],
                    [instance(startUtc='2026-12-05T15:00:00Z')],
                    [plan()], [venue()], START, STOP)
