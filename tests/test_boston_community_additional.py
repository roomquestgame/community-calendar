"""Native Boston captures: complete prose, actual meeting points and dates."""
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import json

from bs4 import BeautifulSoup
import pytest

from roomquest import boston_community_additional as b, boston_sources

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/boston_additional_community.json').read_text())
NOW = datetime.fromisoformat(FIXTURE['now'])
PAYLOADS = FIXTURE['payloads']


def source(key):
    url, kind, adapter = b.SOURCES[key]
    return dict(source_key=key, feed_url=url, kind=kind, platform_adapter=adapter, timezone=b.ZONE)


def fetch(url, accept):
    return PAYLOADS[url]


def test_arboretum_native_feed_prose_and_exact_gate_intersection():
    rows = b.collect(source(b.ARBORETUM), fetch, now=NOW)
    assert len(rows) == 2
    gate = next(r for r in rows if r['title'] == 'Mushroom Hunt')
    assert gate['venue_address'] == 'Flora Way & Hemlock Hill Road, Boston, MA 02131'
    assert (gate['lat'], gate['lng']) == (42.2964125, -71.1280781)
    assert 'edible and poisonous' in gate['description'] and len(gate['description']) > 600
    assert next(r for r in rows if r['title'].startswith('The Regal Lily'))['venue_address'] == '125 Arborway, Boston, MA 02130'
    boston_sources.validate_records(rows, source(b.ARBORETUM))


def test_arboretum_feed_page_disagreement_never_silently_loses_events():
    def changed(url, accept):
        return fetch(url, accept).replace('URL:https://arboretum.harvard.edu/event/mushroom-hunt-7/',
            'URL:https://arboretum.harvard.edu/event/unrelated/') if '?ical' in url else fetch(url, accept)
    with pytest.raises(ValueError, match='pagination_incomplete'):
        b.collect(source(b.ARBORETUM), changed, now=NOW)


def test_parkour_keeps_details_and_two_actual_meeting_venues():
    rows = b.collect(source(b.PARKOUR), fetch, now=NOW)
    assert len(rows) == 2
    assert {r['venue_address'] for r in rows} == {
        '46 Lincoln Pkwy, Somerville, MA 02143', '15 Properzi Way, Somerville, MA 02143'}
    assert min(len(r['description']) for r in rows) > 550
    boston_sources.validate_records(rows, source(b.PARKOUR))
    card = b._parkour_manifest(fetch(b.SOURCES[b.PARKOUR][0], ''), NOW)[0]
    card['start'] = (datetime.fromisoformat(card['start']) + timedelta(hours=1)).isoformat()
    with pytest.raises(ValueError, match='detail_changed'):
        b._parkour_detail(card, fetch(card['url'], ''), NOW, [])


def test_tracksmith_snapshot_keeps_partner_hotel_and_actual_yoga_end():
    one = b.collect_chunk(source(b.TRACKSMITH), fetch, now=NOW)
    assert not one['complete'] and one['events'] == []
    assert one['checkpoint']['cursor'] == 8
    two = b.collect_chunk(source(b.TRACKSMITH), fetch, checkpoint=one['checkpoint'], now=NOW)
    assert two['complete'] and len(two['events']) == 10
    hotel = next(r for r in two['events'] if 'Newbury' in r['title'])
    assert hotel['venue_address'] == '1 Newbury St, Boston, MA 02116'
    yoga = next(r for r in two['events'] if r['starts_at'].startswith('2026-11-16'))
    assert yoga['ends_at'] == '2026-11-17T00:30:00+00:00'
    assert 'required sign up' in yoga['description']
    boston_sources.validate_records(two['events'], source(b.TRACKSMITH))


def test_checkpoint_rejects_mutated_prose_and_expiry():
    first = b.collect_chunk(source(b.TRACKSMITH), fetch, now=NOW)
    corrupt = deepcopy(first['checkpoint'])
    corrupt['events'][0]['description'] += ' Incorrectly appended content'
    with pytest.raises(ValueError, match='checkpoint_invalid'):
        b.collect_chunk(source(b.TRACKSMITH), fetch, checkpoint=corrupt, now=NOW)
    with pytest.raises(ValueError, match='checkpoint_invalid'):
        b.collect_chunk(source(b.TRACKSMITH), fetch, checkpoint=first['checkpoint'], now=NOW + timedelta(hours=5))


def test_trustees_city_natives_and_exact_existing_cohost_exclusion():
    result = b.collect_chunk(source(b.TRUSTEES), fetch, now=NOW)
    assert result['complete'] and len(result['events']) == 2
    assert {r['venue_address'] for r in result['events']} == {'30 Edgewater Drive, Mattapan, MA 02126'}
    assert all(len(r['description']) > 600 for r in result['events'])
    assert {d['reason'] for d in result['diagnostics']} == {
        'boston_additional_existing_public_overlap', 'boston_additional_outside_window'}
    assert all('450287' not in r['event_url'] for r in result['events'])


def test_central_rock_only_expands_current_explicit_monthly_rule():
    rows = b.collect(source(b.CENTRAL), fetch, now=NOW)
    assert [r['starts_at'] for r in rows] == ['2026-11-20T00:00:00+00:00', '2026-12-18T00:00:00+00:00']
    assert all(r['venue_address'] == '170 Alewife Brook Parkway, Cambridge, MA 02138' for r in rows)
    assert len(rows[0]['description']) == 1755
    with pytest.raises(ValueError, match='schedule_changed'):
        b.collect(source(b.CENTRAL), fetch, now=NOW + timedelta(days=150))


def test_rockspot_keeps_public_booking_not_private_inventory_or_closed_cohorts():
    card = {'url': b.SOURCES[b.ROCKSPOT][0] + '?day=2026-11-14',
        'title': 'Rock Spot South Boston public schedule', 'day': '2026-11-14'}
    rows = b._rock_page(card, fetch(card['url'], ''), NOW, [])
    assert len(rows) == 3
    assert all('Rental' not in r['title'] and 'Part 10' not in r['title'] for r in rows)
    assert any('Ladies Climbing' in r['title'] for r in rows)
    assert min(len(r['description']) for r in rows) > 500
    assert {r['venue_address'] for r in rows} == {'30 Old Colony Avenue, South Boston, MA 02127'}


def harbor_payload(**changes):
    url = next(u for u in PAYLOADS if 'brinks-robbery' in u)
    soup = BeautifulSoup(PAYLOADS[url], 'html.parser')
    script = soup.select_one('script#__NEXT_DATA__')
    data = json.loads(script.string)
    data['props']['pageProps']['context']['basicInfo'].update(changes)
    script.string = json.dumps(data)
    return {'url': url, 'title': 'Boston Harbor Now official calendar event'}, str(soup)


def test_harbor_full_native_overview_and_reviewed_conflicting_street():
    card, payload = harbor_payload()
    row = b._harbor_detail(card, payload, NOW, [])[0]
    assert row['venue_address'] == '523 Commercial Street, Boston, MA 02109'
    assert '423 Commercial Street' in row['description']
    assert len(row['description']) == 1813
    assert row['location_evidence_url'] == b.HARBOR_BOCCE_EVIDENCE
    assert (row['lat'], row['lng']) == (42.3686156, -71.0554974)


@pytest.mark.parametrize('changes', [
    {'isProtected': True}, {'isListed': False}, {'isOnline': True}, {'hideStartDate': True},
    {'status': 'canceled'}, {'isParentEvent': True}, {'isSeries': True},
])
def test_harbor_excludes_private_hidden_online_and_unexpanded_series(changes):
    card, payload = harbor_payload(**changes)
    diagnostics = []
    assert b._harbor_detail(card, payload, NOW, diagnostics) == []
    assert diagnostics[0]['reason'] == 'boston_additional_not_public'


def test_harbor_rejects_serialized_time_disagreement():
    card, payload = harbor_payload(startDate={'utc': '2026-11-21T16:00:00Z'})
    with pytest.raises(ValueError, match='time_conflict'):
        b._harbor_detail(card, payload, NOW, [])


def test_oversized_narratives_are_not_silently_truncated():
    with pytest.raises(ValueError, match='description_limit'):
        b._full('<p>' + 'Full published narrative. ' * 600 + '</p>')
