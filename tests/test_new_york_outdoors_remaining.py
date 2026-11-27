"""Complete municipal windows, physical venue binding, and native prose."""
from datetime import datetime, timedelta, timezone
import json
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest

from roomquest import new_york_outdoors_remaining as ny

NOW = datetime.now(timezone.utc).replace(microsecond=0)
START = (NOW + timedelta(days=3)).astimezone(ZoneInfo(ny.ZONE)).replace(hour=10, minute=0, second=0)


def source(key):
    url, kind, adapter = ny.SOURCES[key]
    return dict(source_key=key, feed_url=url, kind=kind, platform_adapter=adapter, timezone=ny.ZONE)


def city_event(**updates):
    item = dict(id=100, title='It’s My Park at Corlears Hook Park',
                url='https://cityparksfoundation.org/events/test-cleanup/',
                description='<p>Volunteer at Corlears Hook Park.</p><p>Meet throughout the entire park.</p>',
                start_date=START.strftime('%Y-%m-%d %H:%M:%S'),
                end_date=(START + timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S'),
                timezone=ny.ZONE, all_day=False, venue={'venue': 'Manhattan'},
                categories=[{'name': "Volunteer: It's My Park"}])
    item.update(updates)
    return item


def older_event(**updates):
    item = dict(dfta_id='C2501', providername='Florence E Smith OAC', eventname='Ping Pong',
                eventlocation='102-19 34 Avenue', city='Corona', state='NY', zipcode='11368',
                latitude='40.755742', longitude='-73.865988', isvirtual='No', islive='Yes',
                isrecurring='Yes', description='Two tables and paddles are available to borrow.',
                eventtype='Physical Activity', topics='Entertainment;Social & Community',
                eventaccessibility='Wheelchair Accessible',
                starttime=START.replace(tzinfo=None).isoformat(),
                endtime=(START + timedelta(hours=1)).replace(tzinfo=None).isoformat())
    item.update(updates)
    return item


def ranger_event(**updates):
    place = ny.RANGER_PLACES[0]
    item = dict(guid='1234567', title='Nature Walk', description='Walk with the Urban Park Rangers.',
                parkids='R022', categories='Nature | Urban Park Rangers | Hiking',
                location=place['native_location'], coordinates=f"{place['lat']}, {place['lng']}",
                link={'url': f'http://www.nycgovparks.org/events/{START:%Y/%m/%d}/nature-walk'},
                registration_description='Registration not required.',
                starttime=START.replace(tzinfo=None).isoformat(),
                endtime=(START + timedelta(hours=1)).replace(tzinfo=None).isoformat())
    item.update(updates)
    return item


def test_complete_description_over_shared_2000_cap_survives():
    body = 'Complete participation instructions and park meeting directions. ' * 60
    body += 'Corlears Hook Park.'
    row = ny._city_row(city_event(description='<p>' + body + '</p>'), NOW, set())
    assert len(row['description']) > 2000 and row['description'] == body
    assert row['venue_address'] == 'Jackson Street & Cherry Street, New York, NY 10002'
    assert 'approximate meeting point' in row['venue_name']
    facts = row['collector_event_content_v1']['facts']
    assert facts['venue_name'] == 'Manhattan'
    assert 'venue_address' not in facts
    assert 'source_latitude' not in facts


@pytest.mark.parametrize('body,reason', [('', 'description_missing'), ('x' * 12001, 'description_limit')])
def test_empty_or_oversized_narrative_is_held_without_truncation(body, reason):
    with pytest.raises(ValueError, match='ny_outdoors_remaining_' + reason):
        ny._older_row(older_event(description=body), NOW)


def test_city_venue_does_not_inherit_an_organizer_or_other_borough():
    with pytest.raises(ValueError, match='location_unresolved'):
        ny._city_row(city_event(venue={'venue': 'Brooklyn'}), NOW, set())
    with pytest.raises(ValueError, match='location_unresolved'):
        ny._city_row(city_event(title='It’s My Park at An Unknown Park'), NOW, set())


def test_specific_meeting_place_must_still_be_present():
    item = city_event(title='It’s My Park at Sara D. Roosevelt Park',
                      description='Meet at the north end of Sara D. Roosevelt Park.')
    with pytest.raises(ValueError, match='location_unresolved'):
        ny._city_row(item, NOW, set())


def test_city_known_cross_park_conflicts_are_held():
    for title, body in [
        ('It’s My Park at McKinley Park', 'Meet at the red shed at Leif Ericson Park.'),
        ('It’s My Park at Tilden Playground', 'Meet at Tilden Avenue; venue header is Tilyou Playground.'),
    ]:
        with pytest.raises(ValueError, match='location_unresolved|schedule_conflict'):
            ny._city_row(city_event(title=title, description=body, venue={'venue': 'Brooklyn'}), NOW, set())


def test_hidden_cancellation_template_has_no_effect_on_current_events():
    banner = 'Due to rain, all It’s My Park events this weekend are cancelled.'
    html = ('<main data-elementor-type="wp-page"><div class="elementor-hidden-desktop '
            'elementor-hidden-tablet elementor-hidden-mobile">' + banner + '</div></main>')
    assert ny._visible_cancellation_days(html, NOW) == set()


def test_visible_weekend_cancellation_applies_only_to_that_weekend():
    html = '<main data-elementor-type="wp-page">All It’s My Park events this weekend are cancelled.</main>'
    days = ny._visible_cancellation_days(html, NOW)
    day = NOW.astimezone(ZoneInfo(ny.ZONE)).date()
    saturday = day + timedelta(days=5 - day.weekday())
    assert days == {saturday, saturday + timedelta(days=1)}
    assert saturday + timedelta(days=7) not in days
    with pytest.raises(ValueError, match='cancellation_unresolved'):
        ny._visible_cancellation_days('<main data-elementor-type="wp-page">All It’s My Park events are cancelled.</main>', NOW)


def test_city_pagination_accounts_for_every_native_record():
    calls = []

    def fetch(url, accept):
        page = int(parse_qs(urlsplit(url).query)['page'][0])
        calls.append(page)
        return json.dumps(dict(total=2, total_pages=2, events=[city_event(id=page)]))

    assert len(ny._city_manifest(fetch, NOW, None)) == 2
    assert calls == [1, 2]
    with pytest.raises(ValueError, match='pagination_incomplete'):
        ny._city_manifest(lambda *_: json.dumps(dict(total=2, total_pages=1, events=[city_event()])), NOW, None)


def test_older_query_defines_complete_rolling_21_day_window_with_overflow_sentinel():
    query = parse_qs(urlsplit(ny._soda_query(ny.OLDER, NOW)).query)
    local = NOW.astimezone(ZoneInfo(ny.ZONE)).replace(tzinfo=None)
    assert query['$limit'] == ['501']
    assert f"starttime < '{(local + timedelta(days=21)).isoformat()}'" in query['$where'][0]
    assert 'isrecurring' not in query['$where'][0]
    with pytest.raises(ValueError, match='record_limit'):
        ny.collect(source(ny.OLDER), lambda *_: json.dumps([older_event()] * 501), now=NOW)


def test_older_query_cutoff_and_row_horizon_agree_across_daylight_saving_change():
    before_dst = datetime(2027, 3, 1, 17, 0, tzinfo=timezone.utc)
    query = parse_qs(urlsplit(ny._soda_query(ny.OLDER, before_dst)).query)['$where'][0]
    assert "endtime > '2027-03-01T12:00:00'" in query
    assert "starttime < '2027-03-22T13:00:00'" in query


def test_older_occurrence_uses_native_date_and_full_source_link_and_age_scope():
    row = ny._older_row(older_event(), NOW)
    assert row['starts_at'] == START.astimezone(timezone.utc).isoformat()
    assert row['description'] == older_event()['description']
    assert row['event_url'] == ny.SOURCES[ny.OLDER][0]
    assert row['age_min'] == 60 and row['audience'] == 'Adults 60+'
    assert row['native_is_recurring'] == 'Yes'
    assert row['accessibility'] == 'Wheelchair Accessible'
    facts = row['collector_event_content_v1']['facts']
    assert facts['venue_address'] == '102-19 34 Avenue'
    assert facts['provider_venue_id'] == 'C2501'
    assert facts['audience'] == ['Adults 60+']
    assert (facts['source_latitude'], facts['source_longitude']) == (40.755742, -73.865988)
    assert facts['native_options'] == {
        'accessibility': 'Wheelchair Accessible', 'is_recurring': 'Yes'}
    assert ny._older_row(older_event(starttime=(START + timedelta(days=22)).isoformat(),
                                    endtime=(START + timedelta(days=22, hours=1)).isoformat()), NOW) is None


def test_duplicate_older_occurrence_with_conflicting_prose_holds_both_originals():
    native = [older_event(description='First version of class participation requirements.'),
              older_event(description='Different version of class participation requirements.')]
    rows, held = ny.collect_with_diagnostics(source(ny.OLDER), lambda *_: json.dumps(native), now=NOW)
    assert rows == [] and len(held) == 2
    assert all(row['reason'] == 'ny_outdoors_remaining_schedule_conflict' for row in held)
    native[1] = native[0].copy()
    rows, held = ny.collect_with_diagnostics(source(ny.OLDER), lambda *_: json.dumps(native), now=NOW)
    assert len(rows) == 1 and held == []


def test_native_offsite_address_selects_actual_st_nicks_center_not_provider_hq():
    item = older_event(dfta_id='C7501', providername=ny.OLDER_SITES['C7501'][0],
                       eventlocation='120 Jackson St', zipcode='11211', city='Brooklyn',
                       latitude='40.71645', longitude='-73.946734', eventname='Bingo')
    row = ny._older_row(item, NOW)
    assert row['venue_name'] == ny.OLDER_SITES['C7502'][0]
    assert row['venue_address'] == '120 Jackson Street, Brooklyn, NY 11211'
    assert row['native_provider_id'] == 'C7501'


def test_delancey_floor_stays_in_street_component_without_extra_postal_comma():
    item = older_event(dfta_id='C3701', providername=ny.OLDER_SITES['C3701'][0],
                       eventlocation='175  Delancey street 4th floor', zipcode='10002', city='New York',
                       latitude='40.717466', longitude='-73.985004')
    row = ny._older_row(item, NOW)
    assert row['venue_address'] == '175 Delancey Street 4th Floor, New York, NY 10002'
    assert row['venue_address'].count(',') == 2


@pytest.mark.parametrize('change', [dict(isvirtual='Yes'), dict(islive='No'), dict(eventlocation=''),
                                   dict(latitude='40.8'), dict(dfta_id='unknown'), dict(state='NJ')])
def test_older_virtual_or_unreviewed_physical_locations_do_not_inherit_center_pin(change):
    with pytest.raises(ValueError, match='not_public|location_unresolved'):
        ny._older_row(older_event(**change), NOW)


def test_typed_socrata_link_unwraps_and_upgrades_only_exact_official_event_url():
    row = ny._ranger_row(ranger_event(), NOW)
    assert row['event_url'].startswith('https://www.nycgovparks.org/events/')
    facts = row['collector_event_content_v1']['facts']
    assert facts['venue_name'] == ny.RANGER_PLACES[0]['native_location']
    assert 'venue_address' not in facts
    assert facts['registration_text'] == 'Registration not required.'
    assert 'provider_venue_id' not in facts
    assert ny._parks_link({'url': 'http://attacker.test/events/2026/11/22/a'}) is None
    assert ny._parks_link({'url': 'http://www.nycgovparks.org.attacker.test/events/2026/11/22/a'}) is None
    assert ny._parks_link({'url': 'http://www.nycgovparks.org/admin/'}) is None


def test_ranger_source_is_separate_from_broad_unresolved_nyc_parks_source():
    assert 'municipal_mapsee_0e46855a44eb788f36a2c0ab' not in ny.SOURCES
    query = parse_qs(urlsplit(ny._soda_query(ny.RANGERS, NOW)).query)['$where'][0]
    assert "parkids like 'R%'" in query and "categories like '%Urban Park Rangers%'" in query
    with pytest.raises(ValueError, match='feed_changed'):
        ny._ranger_row(ranger_event(parkids='M105'), NOW)
    with pytest.raises(ValueError, match='feed_changed'):
        ny._ranger_row(ranger_event(categories='Fitness'), NOW)


def test_closed_registration_and_changed_ranger_meeting_point_are_held():
    with pytest.raises(ValueError, match='not_public'):
        ny._ranger_row(ranger_event(registration_description='Registration is closed.'), NOW)
    with pytest.raises(ValueError, match='location_unresolved'):
        ny._ranger_row(ranger_event(coordinates='40.7, -74.1'), NOW)


def test_reviewed_intersection_is_bound_to_exact_source_venue_address_and_point():
    place = ny.REVIEWED_INTERSECTIONS[0]
    assert ny.reviewed_venue_location(ny.CITY, place['venue_name'], place['venue_address']) == {
        'lat': place['lat'], 'lng': place['lng']}
    assert ny.reviewed_venue_location(ny.OLDER, place['venue_name'], place['venue_address']) is None
    assert ny.reviewed_venue_location(ny.CITY, 'Other venue', place['venue_address']) is None


def test_changed_source_registration_and_expired_budget_prevent_fetching():
    def fetch(*_):
        pytest.fail('No request should start for an invalid source or expired budget')
    changed = source(ny.OLDER)
    changed['feed_url'] += '?other=1'
    with pytest.raises(ValueError, match='unregistered'):
        ny.collect(changed, fetch, now=NOW)
    with pytest.raises(ValueError, match='deadline'):
        ny.collect(source(ny.OLDER), fetch, now=NOW, deadline_at=0)


def test_provider_label_is_outside_fingerprint_but_event_details_change_it():
    first_source = {**source(ny.OLDER), 'publisher_name': 'Old provider label'}
    renamed_source = {**source(ny.OLDER), 'publisher_name': 'Renamed provider label'}
    payload = json.dumps([older_event()])
    first = ny.collect(first_source, lambda *_: payload, now=NOW)[0]
    renamed = ny.collect(renamed_source, lambda *_: payload, now=NOW)[0]
    changed = ny.collect(first_source, lambda *_: json.dumps([
        older_event(description='Changed event participation details.')]), now=NOW)[0]
    assert renamed['collector_event_content_v1'] == first['collector_event_content_v1']
    assert changed['collector_event_content_v1'] != first['collector_event_content_v1']
