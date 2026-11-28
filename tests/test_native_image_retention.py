"""Native calendar pictures survive shared parsing without extra requests."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from roomquest.collection_window import collection_scope
from roomquest.ics_adapter import parse as parse_ics
from roomquest.jsonld_adapter import parse as parse_jsonld
from roomquest.mapsee_adapter import parse_localist, parse_tribe
from roomquest.squarespace import parse as parse_reviewed_squarespace, parse_registered


BASE = 'https://calendar.example.org'
FEED = BASE + '/events/?ical=1'
PICTURE = BASE + '/images/workshop.jpg'
START = datetime(2030, 1, 10, 15, tzinfo=timezone.utc)
END = START + timedelta(hours=2)


@pytest.fixture(autouse=True)
def isolated_native_parse(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Native image retention must not request another URL')

    monkeypatch.setattr('socket.getaddrinfo', forbidden)
    monkeypatch.setattr('requests.sessions.Session.request', forbidden)
    monkeypatch.setattr('urllib.request.urlopen', forbidden)
    start = datetime(2030, 1, 1, tzinfo=timezone.utc)
    with collection_scope({'collection_window': {
        'version': 1, 'start': start.isoformat(),
        'end': (start + timedelta(days=60)).isoformat(),
    }}):
        yield


def ics_event(*extra, uid='workshop', start=START, end=END):
    return '\r\n'.join([
        'BEGIN:VEVENT', 'UID:' + uid, 'SUMMARY:Community workshop',
        'DTSTART:' + start.strftime('%Y%m%dT%H%M%SZ'),
        'DTEND:' + end.strftime('%Y%m%dT%H%M%SZ'),
        'URL:' + BASE + '/event/workshop/',
        'LOCATION:Actual Hall\\, 12 Main St\\, Raleigh\\, NC',
        'GEO:35.8;-78.6', 'DESCRIPTION:Make a creation.',
        'CATEGORIES:Arts,Community', *extra, 'END:VEVENT',
    ])


def ics_feed(*events):
    return '\r\n'.join(['BEGIN:VCALENDAR', 'VERSION:2.0', *events, 'END:VCALENDAR', ''])


@pytest.mark.parametrize('legacy,include_description', [(False, False), (True, False), (True, True)])
@pytest.mark.parametrize('property_value', [
    'IMAGE:' + PICTURE,
    'X-WP-IMAGES-URL:' + PICTURE,
    'ATTACH;FMTTYPE=image/jpeg:' + PICTURE,
])
def test_ics_native_image_is_independent_of_legacy_narrative_mode(legacy, include_description, property_value):
    [row] = parse_ics(ics_feed(ics_event(property_value)), {'url': FEED},
                      legacy=legacy, include_description=include_description)
    assert row['image_url'] == PICTURE
    assert row['id'] == 'workshop'
    assert row['starts_at'] == START.isoformat()
    assert row['ends_at'] == END.isoformat()
    assert row['venue_name'] == 'Actual Hall, 12 Main St, Raleigh, NC'
    assert (row['lat'], row['lng']) == (35.8, -78.6)
    assert row['description'] == 'Make a creation.'


def test_ics_recurrence_override_keeps_its_own_picture_and_identity():
    next_start = START + timedelta(days=7)
    override = ics_event(
        'RECURRENCE-ID:' + next_start.strftime('%Y%m%dT%H%M%SZ'),
        'IMAGE:' + BASE + '/images/special.jpg',
        start=next_start, end=END + timedelta(days=7),
    )
    rows = parse_ics(ics_feed(
        ics_event('RRULE:FREQ=WEEKLY;COUNT=3', 'IMAGE:' + PICTURE), override,
    ), {'url': FEED})
    rows.sort(key=lambda row: row['starts_at'])
    assert [row['id'] for row in rows] == [
        'workshop__20300110', 'workshop__20300117', 'workshop__20300124',
    ]
    assert [row['image_url'] for row in rows] == [
        PICTURE, BASE + '/images/special.jpg', PICTURE,
    ]
    assert [row['starts_at'] for row in rows] == [
        (START + timedelta(days=days)).isoformat() for days in (0, 7, 14)
    ]


def test_ics_native_image_removal_is_explicit_without_changing_event_facts():
    [before] = parse_ics(ics_feed(ics_event('IMAGE:' + PICTURE)), {'url': FEED})
    [after] = parse_ics(ics_feed(ics_event()), {'url': FEED})
    assert before.pop('image_url') == PICTURE
    assert after.pop('image_url') is None
    assert before == after


@pytest.mark.parametrize('property_value', [
    'IMAGE:', 'IMAGE:#poster', 'X-WP-IMAGES-URL:',
    'ATTACH;FMTTYPE=image/jpeg:', 'ATTACH;FMTTYPE=image/jpeg:#poster',
    'DESCRIPTION:<img src="">', 'X-ALT-DESC;FMTTYPE=text/html:<img src="#poster">',
])
def test_ics_empty_image_never_becomes_the_event_page(property_value):
    [row] = parse_ics(ics_feed(ics_event(property_value)), {'url': FEED})
    assert row['image_url'] is None
    assert row['event_url'] == BASE + '/event/workshop/'


def test_ical_new_image_semantics_reject_old_occurrence_baseline(monkeypatch):
    from roomquest import ical_source_semantics
    from roomquest.incremental_snapshot import Snapshot

    source = {'source_key': 'municipal_mapsee_' + 'a' * 24,
              'kind': 'ical', 'platform_adapter': 'ical', 'feed_url': FEED,
              'ical_optimization_enabled': True}
    [row] = parse_ics(ics_feed(ics_event('IMAGE:' + PICTURE)), {'url': FEED})
    output = {'p_future_count': 1, 'p_venue_count': 1, 'p_error': None}
    claim = {'policy_context': 'b' * 64}
    context = {'p_category': 'ical', 'p_ticket': 'active-ticket'}
    with monkeypatch.context() as old_release:
        old_release.setattr(ical_source_semantics, 'NORMALIZATION_VERSION',
                            'ical-publisher-facts-1')
        old = Snapshot(source, context, claim)
        claim.update(old.receipt(old.plan([row], output)),
                     baseline_id='00000000-0000-4000-8000-000000000001')
        # Prove the same valid baseline is ordinarily reused.
        cached = Snapshot(source, context, claim)
        assert cached.plan([row], output)['changed'] == []

    current = Snapshot(source, context, claim)
    assert current.context_hash != old.context_hash
    assert current.plan([row], output)['changed'][0]['event'] == row
    assert current.receipt(current.plan([row], output))['not_modified'] is False


def tribe_event(image):
    return {
        'id': 42, 'title': 'Community workshop', 'status': 'publish',
        'event_status': 'scheduled', 'timezone': 'America/New_York',
        'start_date': '2030-01-10 10:00:00', 'end_date': '2030-01-10 12:00:00',
        'utc_start_date': '2030-01-10 15:00:00', 'utc_end_date': '2030-01-10 17:00:00',
        'url': BASE + '/event/workshop/', 'description': '<p>Make a creation.</p>',
        'image': image, 'categories': [{'name': 'Arts'}],
        'venue': {'venue': 'Actual Hall', 'address': '12 Main St', 'city': 'Raleigh',
                  'state': 'NC', 'geo_lat': 35.8, 'geo_lng': -78.6},
    }


@pytest.mark.parametrize('strict', [False, True])
@pytest.mark.parametrize('image', [PICTURE, {'url': '/images/workshop.jpg', 'width': 1200, 'height': 800}])
def test_wordpress_native_featured_image_survives_common_parser(strict, image):
    [row] = parse_tribe({'events': [tribe_event(image)]}, strict_public=strict, retain_description=True)
    assert row['image_url'] == PICTURE
    assert row['id'] == '42'
    assert row['starts_at'] == START.isoformat()
    assert row['venue_address'] == '12 Main St, Raleigh, NC'
    assert row['description'] == 'Make a creation.'


@pytest.mark.parametrize('empty', [False, None, '', {'url': False}, {'url': ''}, {'@id': '#image'}])
def test_wordpress_missing_native_image_never_becomes_the_event_page(empty):
    [row] = parse_tribe({'events': [tribe_event(empty)]}, retain_description=True)
    assert 'image_url' in row and row['image_url'] is None
    assert row['event_url'] == BASE + '/event/workshop/'


def localist_payload():
    return {'events': [{'event': {
        'id': 42, 'title': 'Community workshop', 'status': 'live',
        'private': False, 'rejected': False, 'publish_status': 'published',
        'localist_url': BASE + '/event/workshop/', 'photo_url': PICTURE,
        'timezone': 'America/New_York', 'location_name': 'Actual Hall',
        'address': '12 Main St, Raleigh, NC', 'description': 'Make a creation.',
        'geo': {'latitude': 35.8, 'longitude': -78.6, 'city': 'Raleigh'},
        'event_instances': [{'event_instance': {'id': 71, 'event_id': 42,
                             'start': START.isoformat(), 'end': END.isoformat()}}],
    }}]}


@pytest.mark.parametrize('registered', [False, True])
def test_localist_native_image_and_original_content_agree(registered):
    data = localist_payload()
    [row] = parse_localist(data, registered=registered, retain_original=True)
    assert row['id'] == ('71' if registered else '42')
    assert row['image_url'] == PICTURE
    assert row['collector_event_content_v1']['facts']['source_image_url'] == PICTURE
    data['events'][0]['event']['photo_url'] = None
    [removed] = parse_localist(data, registered=registered, retain_original=True)
    assert removed['image_url'] is None
    assert removed['collector_event_content_v1']['facts']['source_image_url'] is None
    assert removed['id'] == row['id']


def jsonld_payload(image):
    return {
        '@context': 'https://schema.org', '@type': 'Event', '@id': BASE + '/event/workshop/',
        'name': 'Community workshop', 'url': BASE + '/event/workshop/',
        'startDate': START.isoformat(), 'endDate': END.isoformat(),
        'description': 'Make a creation.', 'image': image,
        'location': {'@type': 'Place', 'name': 'Actual Hall', 'address': {
            '@type': 'PostalAddress', 'streetAddress': '12 Main St',
            'addressLocality': 'Raleigh', 'addressRegion': 'NC',
        }},
    }


def test_jsonld_resolved_image_reference_is_retained_in_row_and_original_facts():
    event = jsonld_payload({'@id': '#workshop-image'})
    graph = {'@graph': [event, {'@type': 'ImageObject', '@id': '#workshop-image',
                               'contentUrl': '/images/workshop.jpg'}]}
    [row] = parse_jsonld(json.dumps(graph), BASE + '/calendar', retain_original=True)
    assert row['image_url'] == PICTURE
    assert row['collector_event_content_v1']['facts']['source_image_url'] == PICTURE
    assert row['id'] == BASE + '/event/workshop/'
    assert row['starts_at'] == START.isoformat()
    event.pop('image')
    [removed] = parse_jsonld(json.dumps(graph), BASE + '/calendar', retain_original=True)
    assert removed['image_url'] is None
    assert removed['collector_event_content_v1']['facts']['source_image_url'] is None
    assert removed['id'] == row['id']


def squarespace_payload():
    return {'upcoming': [{
        'id': 'workshop', 'title': 'Community workshop', 'workflowState': 1,
        'startDate': START.timestamp() * 1000, 'endDate': END.timestamp() * 1000,
        'fullUrl': '/events/workshop', 'assetUrl': '/images/workshop.jpg',
        'body': '<p>Make a creation.</p>', 'categories': ['Arts'],
        'location': {'addressTitle': 'Actual Hall', 'addressLine1': '12 Main St',
                     'addressLine2': 'Raleigh, NC', 'markerLat': 35.8, 'markerLng': -78.6},
    }]}


def test_squarespace_asset_image_survives_and_removal_updates_original_facts():
    data = squarespace_payload()
    [row] = parse_registered(data, BASE + '/events?format=json', retain_original=True)
    assert row['image_url'] == PICTURE
    assert row['collector_event_content_v1']['facts']['source_image_url'] == PICTURE
    assert row['id'] == 'workshop'
    assert (row['lat'], row['lng']) == (35.8, -78.6)
    data['upcoming'][0].pop('assetUrl')
    [removed] = parse_registered(data, BASE + '/events?format=json', retain_original=True)
    assert removed['image_url'] is None
    assert removed['collector_event_content_v1']['facts']['source_image_url'] is None
    assert removed['id'] == row['id']


def test_reviewed_squarespace_path_also_retains_native_asset():
    data = squarespace_payload()
    data['website'] = {'timeZone': 'America/Phoenix'}
    event = data['upcoming'][0]
    event['location'] = {'addressTitle': 'Mission Garden', 'addressLine1': '946 W Mission Ln',
                         'addressLine2': 'Tucson, AZ', 'markerLat': 32.213, 'markerLng': -110.984}
    event['assetUrl'] = PICTURE
    [row] = parse_reviewed_squarespace(json.dumps(data), {
        'feed_url': 'https://missiongarden.org/events?format=json',
    }, retain_original=True)
    assert row['image_url'] == PICTURE
    assert row['collector_event_content_v1']['facts']['source_image_url'] == PICTURE
    assert row['venue_address'] == '946 W Mission Ln, Tucson, AZ'
