"""Completeness, location and snapshot regressions for the reviewed NYC sources."""
from datetime import datetime, timedelta, timezone
from html import escape
import json
from urllib.parse import parse_qs, urlencode, urlsplit
from zoneinfo import ZoneInfo

import pytest

from roomquest import new_york_outdoors as ny


NOW = datetime.now(timezone.utc).replace(microsecond=0)
START = (NOW + timedelta(days=7)).astimezone(ZoneInfo(ny.ZONE)).replace(hour=10, minute=0, second=0)


def source(key):
    url, kind, adapter = ny.SOURCES[key]
    return dict(source_key=key, feed_url=url, kind=kind, platform_adapter=adapter, timezone=ny.ZONE)


def event(**updates):
    row = dict(id=123, title='Compost Build Community Volunteer Days',
               url='https://queensbotanical.org/event/compost-build/',
               description='<p>Join the QBG Compost Staff for our weekly on-site compost build.</p>',
               start_date=START.strftime('%Y-%m-%d %H:%M:%S'),
               end_date=(START + timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S'),
               timezone=ny.ZONE, all_day=False, venue={}, categories=[{'name': 'Volunteer'}])
    row.update(updates)
    return row


def sq_card(index=0, *, title='CARDIO THURSDAYS', body=None, location='Quisqueya Plaza',
            venue='Quisqueya Plaza'):
    start = (START + timedelta(days=index)).astimezone(timezone.utc)
    end = start + timedelta(hours=1)
    url = f'https://dyckmanrunclub.org/events/test-{index}'
    export = 'https://www.google.com/calendar/event?' + urlencode({
        'action': 'TEMPLATE', 'text': title,
        'dates': f'{start:%Y%m%dT%H%M%SZ}/{end:%Y%m%dT%H%M%SZ}', 'location': location})
    anchor = f'<a href="{escape(export, quote=True)}">Google Calendar</a>'
    listing = (f'<article class="eventlist-event--upcoming">'
               f'<a class="eventlist-title-link" href="{url}">{escape(title)}</a>'
               f'<div class="eventlist-excerpt">A listing excerpt.</div>{anchor}</article>')
    body = '<p>Join DRC for a free public run through the neighborhood.</p>' if body is None else body
    detail = (f'<meta property="og:url" content="{url}"><div class="eventitem">'
              f'<h1 class="eventitem-title">{escape(title)}</h1>{anchor}'
              f'<span class="eventitem-meta-address-line--title">{escape(venue)}</span>'
              f'<div class="eventitem-column-content"><div class="sqs-layout">{body}</div></div></div>')
    return url, listing, detail


def sq_fetch(cards):
    lookup = {url: detail for url, _, detail in cards}
    listing = '<div class="eventlist">' + ''.join(card for _, card, _ in cards) + '</div>'
    calls = []

    def fetch(url, accept):
        calls.append(url)
        assert 'format=' not in url  # Robots deny Squarespace JSON and ICS.
        return listing if url == ny.SOURCES[ny.DYCKMAN][0] else lookup[url]

    return fetch, calls


def test_complete_description_over_shared_display_cap_is_preserved():
    text = 'Composting instructions, safety notes and participation requirements. ' * 50
    row = ny._make_row(ny.QBG, event(description=f'<p>{text}</p>'), NOW, [])
    assert row['description'] == text.strip()
    assert len(row['description']) > 2000
    assert row['venue_address'] == '43-50 Main Street, Flushing, NY 11355'
    assert row['category'] == 'Volunteer'


def test_oversized_description_fails_instead_of_truncating():
    with pytest.raises(ValueError, match='ny_outdoors_description_limit'):
        ny._make_row(ny.QBG, event(description='<p>' + 'a' * 12001 + '</p>'), NOW, [])


@pytest.mark.parametrize('changes', [dict(description=''), dict(title='Garden is CLOSED'),
                                     dict(title='Cancelled: Compost Build'), dict(timezone='UTC')])
def test_missing_cancelled_and_unresolved_time_rows_are_held(changes):
    diagnostics = []
    assert ny._make_row(ny.QBG, event(**changes), NOW, diagnostics) is None
    assert len(diagnostics) == 1


def test_compost_drop_off_site_is_not_misclassified_as_offsite():
    row = ny._make_row(ny.LES, event(
        title='Mathews-Palmer Park', url='https://www.lesecologycenter.org/calendar/drop-off/',
        description='<p>This is a community-managed compost drop-off site. Please close the bin.</p>',
        venue=dict(venue='Mathews–Palmer Park', address='445 W 45th St', city='New York',
                   state='NY', zip='10036', geo_lat=40.7613707, geo_lng=-73.9930419)), NOW, [])
    assert row and row['venue_address'] == '445 W 45th St, New York, NY 10036'


def test_venue_hq_is_never_substituted_for_unlocated_event():
    row = event(title='Birding outing', url='https://vancortlandt.org/event/birding/',
                description='Join us for birding. Meeting place will be sent after registration.')
    assert ny._make_row(ny.VCP, row, NOW, []) is None


def test_reviewed_park_intersection_is_bound_to_venue_and_source():
    place = ny._named(ny.VCP, 'VCPA Learning Garden (approximate meeting point)')
    assert ny.reviewed_venue_location(ny.VCP, place['venue_name'], place['venue_address']) == {
        'lat': place['lat'], 'lng': place['lng']}
    assert ny.reviewed_venue_location(ny.VCP, 'Other garden', place['venue_address']) is None
    assert ny.reviewed_venue_location(ny.QBG, place['venue_name'], place['venue_address']) is None
    assert 'approximate' in place['venue_name']


def test_historical_cancellation_does_not_remove_other_dated_occurrences():
    row = ny._make_row(ny.VCP, event(
        title='Woodlawn Wednesdays: Forest Restoration',
        url='https://vancortlandt.org/event/woodlawn/',
        description='<p>October 25 was CANCELED. This session meets at Woodlawn Playground.</p>'), NOW, [])
    assert row and row['venue_address'].startswith('East 239th Street')


def test_randalls_wrong_export_timezone_requires_visible_local_clock():
    e = event(title='Winter Composting', url='https://randallsisland.org/events/winter-composting',
              timezone='UTC+0', description='Meet on the Urban Farm to compost together.',
              venue=dict(venue='Urban Farm'))
    assert ny._make_row(ny.RANDALLS, e, NOW, [], {}) is None
    clocks = {e['url']: (START.strftime('%Y-%m-%d'), '10:00:00', '12:00:00')}
    row = ny._make_row(ny.RANDALLS, e, NOW, [], clocks)
    assert row['starts_at'] == START.astimezone(timezone.utc).isoformat()
    assert row['venue_address'] == '11 Wards Meadow Loop, New York, NY 10035'
    clocks[e['url']] = (START.strftime('%Y-%m-%d'), '11:00:00', '12:00:00')
    assert ny._make_row(ny.RANDALLS, e, NOW, [], clocks) is None


def test_multihour_body_and_header_disagreement_is_held():
    assert ny._make_row(ny.VCP, event(title='Old Croton Aqueduct Tour',
        url='https://vancortlandt.org/event/old-croton/',
        description='Join our 3.5 hour walk. Meet at the Golf House.'), NOW, []) is None


def test_tec_pagination_must_account_for_all_publisher_records():
    calls = []

    def fetch(url, accept):
        page = int(parse_qs(urlsplit(url).query)['page'][0])
        calls.append(page)
        return json.dumps(dict(total=2, total_pages=2, events=[event(id=page)]))

    rows, _ = ny._tribe(ny.QBG, fetch, NOW)
    assert calls == [1, 2]
    # Same title/time/place is a duplicate even when publisher IDs differ.
    assert len(rows) == 1
    with pytest.raises(ValueError, match='ny_outdoors_pagination_incomplete'):
        ny._tribe(ny.QBG, lambda *_: json.dumps(dict(total=2, total_pages=1, events=[event()])), NOW)


def test_tec_mid_pagination_count_change_rejects_snapshot():
    def fetch(url, accept):
        page = int(parse_qs(urlsplit(url).query)['page'][0])
        return json.dumps(dict(total=2 if page == 1 else 3, total_pages=2, events=[event(id=page)]))
    with pytest.raises(ValueError, match='ny_outdoors_pagination_incomplete'):
        ny._tribe(ny.QBG, fetch, NOW)


def test_checkpoint_never_emits_partial_snapshot(monkeypatch):
    monkeypatch.setattr(ny, 'DETAILS_PER_CHUNK', 1)
    fetch, calls = sq_fetch([sq_card(0), sq_card(1)])
    first = ny.collect_chunk(source(ny.DYCKMAN), fetch, now=NOW)
    assert first['events'] == [] and not first['complete']
    assert len(calls) == 2
    assert first['checkpoint']['cursor'] == 1
    final = ny.collect_chunk(source(ny.DYCKMAN), fetch, checkpoint=first['checkpoint'], now=NOW)
    assert final['complete'] and len(final['events']) == 2 and final['checkpoint'] is None


def test_checkpoint_cannot_inject_another_event(monkeypatch):
    monkeypatch.setattr(ny, 'DETAILS_PER_CHUNK', 1)
    fetch, _ = sq_fetch([sq_card(0), sq_card(1)])
    cp = ny.collect_chunk(source(ny.DYCKMAN), fetch, now=NOW)['checkpoint']
    cp['events'][0]['event_url'] = 'https://dyckmanrunclub.org/events/other'
    with pytest.raises(ValueError, match='ny_outdoors_checkpoint_invalid'):
        ny.collect_chunk(source(ny.DYCKMAN), fetch, checkpoint=cp, now=NOW)


def test_manifest_change_restarts_snapshot(monkeypatch):
    monkeypatch.setattr(ny, 'DETAILS_PER_CHUNK', 1)
    fetch, _ = sq_fetch([sq_card(0), sq_card(1)])
    cp = ny.collect_chunk(source(ny.DYCKMAN), fetch, now=NOW)['checkpoint']
    changed, _ = sq_fetch([sq_card(0), sq_card(1), sq_card(2)])
    next_chunk = ny.collect_chunk(source(ny.DYCKMAN), changed, checkpoint=cp, now=NOW)
    assert next_chunk['checkpoint']['cursor'] == 1
    assert next_chunk['checkpoint']['manifest_count'] == 3


def test_empty_detail_does_not_fall_back_to_listing_excerpt():
    fetch, _ = sq_fetch([sq_card(0, body='')])
    final = ny.collect_chunk(source(ny.DYCKMAN), fetch, now=NOW)
    assert final['complete'] and final['events'] == []
    assert final['diagnostics'][0]['reason'] == 'ny_outdoors_description_or_location_missing'


def test_medal_party_with_workout_body_is_held():
    fetch, _ = sq_fetch([sq_card(0, title='DRC MEDAL PARTY', venue='809 Lounge',
                               location='112 Dyckman Street, New York, NY 10040')])
    final = ny.collect_chunk(source(ny.DYCKMAN), fetch, now=NOW)
    assert final['events'] == []
    assert final['diagnostics'][0]['reason'] == 'ny_outdoors_schedule_conflict'


def test_deadline_does_not_start_an_unbounded_fetch():
    def fetch(*_):
        pytest.fail('No network request should start after deadline')
    with pytest.raises(ValueError, match='ny_outdoors_deadline'):
        ny.collect(source(ny.QBG), fetch, deadline_at=0, now=NOW)


def test_source_and_event_host_contracts_are_exact():
    changed = source(ny.QBG)
    changed['feed_url'] = 'https://queensbotanical.org/other/'
    with pytest.raises(ValueError, match='unregistered_new_york_outdoors_source'):
        ny.collect(changed, lambda *_: '', now=NOW)
    assert not ny.event_url(ny.QBG, 'https://queensbotanical.org.attacker.test/event/a/')
    assert not ny.event_url(ny.QBG, 'https://user@queensbotanical.org/event/a/')
    assert not ny.photo_url(ny.QBG, 'https://example.com/photo.jpg')
