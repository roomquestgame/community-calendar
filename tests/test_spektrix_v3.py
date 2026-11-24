"""Offline read-only Spektrix v3 public collection and tenant discovery tests."""
from datetime import date, timedelta

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
    assert len(chunks) == 9
    assert chunks[0] == (start, start + timedelta(days=6))
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
        ([event(webUrl='')], [instance()], [plan()], [venue()],
         'spektrix_event_link_missing'),
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
                'evidence_url': 'https://richmix.org.uk/visit-us'}})
    row = api.project(source, [event()], [instance()], [plan()], [blank],
                      START, STOP)['events'][0]
    assert 'Bethnal Green' in row['venue_address']


def test_local_and_utc_clocks_must_match_and_reject_ambiguous_dst():
    with pytest.raises(ValueError, match='spektrix_time_conflict'):
        api.project(profile(), [event()], [instance(startUtc='2026-12-05T15:00:00')],
                    [plan()], [venue()], START, STOP)
    with pytest.raises(ValueError, match='spektrix_time_invalid'):
        api.project(profile(), [event()], [
            instance(start='2026-10-25T01:30:00', startUtc='2026-10-25T00:30:00')],
            [plan()], [venue()], '2026-10-25', '2026-10-25')


def test_one_shot_bounded_probe_never_guesses_urls_or_drops_parts():
    client = 'thealbany'
    responses = {
        api.api_url(client, 'events', start=START, end=STOP): [event()],
        api.api_url(client, 'instances', start=START, end=STOP): [instance()],
        api.api_url(client, 'plans', identity=PLAN): plan(),
        api.api_url(client, 'venues'): [venue()],
    }
    visited = []

    def fetch(url, accept):
        assert accept == 'application/json'
        visited.append(url)
        return responses[url]

    result = api.collect(profile(), START, STOP, fetch)
    assert len(result['events']) == 1
    assert visited == list(responses)
    del responses[api.api_url(client, 'venues')]
    with pytest.raises(KeyError):
        api.collect(profile(), START, STOP, fetch)


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
