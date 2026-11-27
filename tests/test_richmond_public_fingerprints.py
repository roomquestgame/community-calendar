from datetime import datetime, timedelta
import json
from zoneinfo import ZoneInfo

from roomquest import preview_worker
from roomquest import richmond_public_calendars as calendars


def volunteer_payload(description='Meet at 50 Evergreen Road, Richmond.'):
    start = (datetime.now(ZoneInfo(calendars.ZONE)) + timedelta(days=1)).replace(
        hour=9, minute=0, second=0, microsecond=0)
    shift = {
        'opportunityName': 'Park Cleanup',
        'organizationServedName': 'Friends of the Park',
        'locationType': 'Address', 'locationState': 'VA', 'locationCity': 'Richmond',
        'locationZipCode': '23223', 'timezone': calendars.ZONE,
        'opportunityType': 'Project', 'volunteersStillNeeded': '5',
        'description': description,
        'startDateTimeISO': start.isoformat(),
        'endDateTimeISO': (start + timedelta(hours=2)).isoformat(),
        'opportunityLink': 'https://www.cfengage.org/opportunity/a0CNw0000JM6ICdMQN',
        'occurrenceId': 'a0CNw0000JM6ICdMQN',
    }
    return json.dumps({'items': [{'overMaxToReturn': False, 'occurrences': [shift]}]})


def source(key, *, publisher_name='Original provider label'):
    return {'source_key': key, 'feed_url': calendars.SOURCES[key][0],
            'kind': 'html', 'platform_adapter': 'html', 'timezone': calendars.ZONE,
            'publisher_name': publisher_name}


def test_volunteer_fingerprint_uses_event_facts_not_provider_label():
    payload = volunteer_payload()
    first = calendars.collect(source(calendars.CFENGAGE), lambda *_: '',
                              render_volunteers=lambda: payload)
    renamed = calendars.collect(source(calendars.CFENGAGE, publisher_name='Renamed provider label'),
                                lambda *_: '', render_volunteers=lambda: payload)
    assert first[0]['id'] == renamed[0]['id']
    assert first[0]['collector_event_content_v1'] == renamed[0]['collector_event_content_v1']
    facts = first[0]['collector_event_content_v1']['facts']
    assert facts['venue_address'] == '50 Evergreen Road, Richmond, VA 23223'
    assert facts['publisher_event_type'] == 'Project'


def test_volunteer_narrative_edit_changes_input_not_occurrence_id():
    [first] = calendars.volunteer_shifts(volunteer_payload())
    [changed] = calendars.volunteer_shifts(
        volunteer_payload('Bring gloves and meet at 50 Evergreen Road, Richmond.'))
    assert first['id'] == changed['id']
    assert first['collector_event_content_v1'] != changed['collector_event_content_v1']


def test_runsignup_retains_event_owned_detail_facts():
    now = datetime.now(ZoneInfo(calendars.ZONE))
    item = {
        '@type': 'SportsEvent', 'name': 'Community 5K',
        'startDate': (now + timedelta(days=1)).isoformat(),
        'description': '<p>A complete publisher race narrative.</p>',
        'location': {'@type': 'Place', 'name': 'Dorey Park', 'address': {
            'streetAddress': 'Dorey Park', 'addressLocality': 'Henrico',
            'addressRegion': 'VA', 'postalCode': '23231',
        }},
    }
    page = '<h2 class="rsuWebsiteSection__title">Race Location</h2>'
    page += '<p>Dorey Park<br>2999 Darbytown Rd<br>Henrico, VA 23231 US</p>'
    page += f'<script type="application/ld+json">{json.dumps(item)}</script>'
    [row] = calendars.race_events(
        page, '123', 'https://runsignup.com/Race/VA/Henrico/Run', now)
    facts = row['collector_event_content_v1']['facts']
    assert facts['description'] == 'A complete publisher race narrative.'
    assert facts['venue_name'] == 'Dorey Park'
    assert facts['venue_address'] == '2999 Darbytown Rd, Henrico, VA 23231'
    assert facts['publisher_event_type'] == 'SportsEvent'


def test_normal_path_keeps_richmond_facts_and_admin_sample_strips(monkeypatch):
    [row] = calendars.volunteer_shifts(volunteer_payload())
    calls = {}
    monkeypatch.setattr(calendars, 'collect', lambda *args, **kwargs: [row])
    monkeypatch.setattr(preview_worker, 'fetch_publisher', lambda *args, **kwargs: '')
    monkeypatch.setattr(preview_worker, 'supabase_rpc',
                        lambda name, payload: calls.setdefault(name, payload) and 0)
    preview_worker._process_claimed_source(source(calendars.CFENGAGE))
    staged = calls['community_collector_record_staged_events']['p_events']
    samples = calls['community_collector_record_preview_v2']['p_samples']
    assert staged[0]['collector_event_content_v1']['event_id'] == staged[0]['id']
    assert 'collector_event_content_v1' not in samples[0]
