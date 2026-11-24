"""Wix public warmup: full inventory evidence, not first-page assumptions."""
import json

import pytest

from roomquest import wix_public_events as wix

SITE = 'https://shows.example.org/events'
ID = '0571b1bc-5f97-40ac-bd29-b73170f3df8b'
SLUG = 'london-music-night'
LINK = 'https://shows.example.org/event-details/' + SLUG
ADDRESS = '15 River Road, London E2 8EA'


def event(**overrides):
    return {'id': ID, 'status': 0, 'title': 'London Music Night',
            'slug': SLUG, 'description': 'A full evening of music.',
            'registration': {'restrictedTo': 1},
            'location': {
                'name': 'Town Hall', 'address': ADDRESS, 'tbd': False,
                'fullAddress': {'country': 'GB', 'city': 'London',
                                'postalCode': 'E2 8EA',
                                'formattedAddress': ADDRESS}},
            'scheduling': {'config': {
                'scheduleTbd': False,
                'timeZoneId': 'Europe/London',
                'startDate': '2026-12-05T19:00:00Z',
                'endDate': '2026-12-05T21:00:00Z'}},
            'mainImage': {'url': 'https://static.wixstatic.com/media/poster.jpg'},
            **overrides}


def html(events=None, *, total=None, more=False, anchor=True):
    events = [event()] if events is None else events
    inner = {'appsWarmupData': {wix.WIX_EVENTS: {
        'widget-on-page': {'events': {'events': events,
                                     'totalCount': len(events) if total is None else total,
                                     'hasMore': more}}
    }}}
    link = '<a href="' + LINK + '">London Music Night</a>' if anchor else ''
    return ('<html><body><main>' + link + '</main><script '
            'id="wix-warmup-data" type="application/json">' +
            json.dumps(inner) + '</script></body></html>')


def profile():
    return {'publisher_url': SITE, 'country': 'GB'}


def test_public_wix_event_already_linked_and_full_inventory():
    result = wix.extract(profile(), html(), '2026-12-01', '2026-12-30')
    assert result['complete'] is True
    assert result['inventory_count'] == 1
    [row] = result['events']
    assert row['id'] == 'wix:' + ID
    assert row['event_url'] == LINK
    assert row['title'] == 'London Music Night'
    assert row['venue_name'] == 'Town Hall'
    assert row['venue_city'] == 'London'
    assert row['timezone'] == 'Europe/London'
    assert row['starts_at'] == '2026-12-05T19:00:00+00:00'
    assert row['description'] == 'A full evening of music.'


@pytest.mark.parametrize('payload', [
    html(total=2),
    html(more=True),
    html(anchor=False),
    html(events=[event(slug='different-title')]),
    html(events=[event(location={
        'name': 'Town Hall', 'address': ADDRESS, 'tbd': False,
        'fullAddress': {'country':'US','city':'London','postalCode':'E2 8EA',
                        'formattedAddress':ADDRESS}})]),
])
def test_partial_widget_or_identity_conflict_cannot_be_published(payload):
    with pytest.raises(ValueError, match='wix_public_'):
        wix.extract(profile(), payload, '2026-12-01', '2026-12-30')


def test_no_wix_events_widget_means_custom_cms_requires_other_adapter():
    with pytest.raises(ValueError, match='wix_public_widget_not_exposed'):
        wix.extract(profile(), '<html><main>Only a custom Wix CMS</main></html>',
                    '2026-12-01', '2026-12-30')


def test_cancellation_and_private_event_never_promoted():
    hidden = event(status=1)
    found = wix.extract(profile(), html(events=[hidden]), '2026-12-01', '2026-12-30')
    assert found['events'] == []
    member_only = event(registration={'restrictedTo': 2})
    found = wix.extract(profile(), html(events=[member_only]), '2026-12-01', '2026-12-30')
    assert found['events'] == []


def test_window_never_exceeds_sixty_days():
    with pytest.raises(ValueError, match='wix_public_window_invalid'):
        wix.extract(profile(), html(), '2026-11-24', '2027-01-23')


def test_contradictory_wix_totals_and_nonboolean_more_are_not_complete():
    for fragment in ('"hasMore": "false"', '"hasMore": 0',
                     '"total": 2, "hasMore": false'):
        payload = html().replace('"hasMore": false', fragment)
        with pytest.raises(ValueError, match='pagination_unverified'):
            wix.extract(profile(), payload, '2026-12-01', '2026-12-30')


def test_same_uuid_case_variants_must_not_replace_different_event_facts():
    original = event()
    alias = event(id=ID.upper())
    complete = wix.extract(profile(), html(events=[original, alias]), '2026-12-01', '2026-12-30')
    assert len(complete['events']) == 1
    alias['description'] = 'Conflicting event content.'
    with pytest.raises(ValueError, match='event_identity_conflict'):
        wix.extract(profile(), html(events=[original, alias]), '2026-12-01', '2026-12-30')


def test_explicit_hidden_end_date_is_not_exposed_as_verified_end():
    item = event()
    item['scheduling']['config']['endDateHidden'] = True
    found = wix.extract(profile(), html(events=[item]), '2026-12-01', '2026-12-30')
    assert found['events'][0]['ends_at'] is None


@pytest.mark.parametrize('item', [event(status=False), event(status=None),
    event(registration={'restrictedTo': True}), event(registration={})])
def test_malformed_status_or_visibility_is_not_a_verified_snapshot(item):
    with pytest.raises(ValueError, match='wix_public_event_(status|visibility)_unverified'):
        wix.extract(profile(), html(events=[item]), '2026-12-01', '2026-12-30')


def test_same_hostname_different_port_is_not_a_first_party_event_link():
    payload = html().replace(LINK, LINK.replace('shows.example.org', 'shows.example.org:444'))
    with pytest.raises(ValueError, match='event_link_unverified'):
        wix.extract(profile(), payload, '2026-12-01', '2026-12-30')


def test_real_wix_registration_route_shape_is_exactly_linked():
    # Publisher-observed path family on a public London Wix Events listing.
    target = LINK.replace('/event-details/', '/event-details-registration/')
    found = wix.extract(profile(), html().replace(LINK, target), '2026-12-01', '2026-12-30')
    assert found['events'][0]['event_url'] == target
    for bad in ('/other/event-details-registration/', '/event-details-registration/foo/'):
        payload = html().replace(LINK, LINK.replace('/event-details/', bad))
        with pytest.raises(ValueError, match='event_link_unverified'):
            wix.extract(profile(), payload, '2026-12-01', '2026-12-30')


def test_observed_uk_widget_without_counts_remains_on_hold_even_with_hasmore_false():
    # Both UK publisher listings in the read-only shadow expose this shape.
    payload = html().replace('"totalCount": 1, ', '')
    with pytest.raises(ValueError, match='pagination_unverified'):
        wix.extract(profile(), payload, '2026-12-01', '2026-12-30')
