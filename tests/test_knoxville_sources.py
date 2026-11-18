"""Knoxville primary calendars: complete narratives, own streets, exact identities."""
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from roomquest import knoxville_sources as knox
from roomquest import preview_worker
from roomquest.preview_worker import PreviewError

FIXTURES = Path(__file__).parent / 'fixtures' / 'knoxville'
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
FIXTURE_FILES = {knox.WDVX: 'wdvx_20261117.json', knox.HISTORY: 'ethc_20261117.json',
                 knox.CHAMBER: 'chamber_20261117.json'}
EMPTY_LOCATION_EVENT = (
    'BEGIN:VEVENT\r\nUID:event-9999-session-0@haxdb\r\nSUMMARY:Laser Cut Ornament\r\n'
    'DTSTART:20261205T190000Z\r\nDTEND:20261205T210000Z\r\n'
    'DESCRIPTION:Join us in the classroom to paint and make your own ornament.\r\n'
    'URL:https://events.knoxmakers.org/event/laser-cut-ornament-2\r\nEND:VEVENT\r\n')


@pytest.fixture(autouse=True)
def fixed_preview_horizon(monkeypatch):
    # Fixed publisher captures must not age out of the shared renderer's window.
    monkeypatch.setattr('roomquest.preview_worker._future_datetime',
                        lambda value: value.astimezone(timezone.utc))


def source(key):
    url, kind, adapter = knox.SOURCES[key]
    return dict(source_key=key, feed_url=url, kind=kind, platform_adapter=adapter, timezone=knox.ZONE)


def tribe_fetch(key, payload=None, calls=None):
    data = payload if payload is not None else (FIXTURES / FIXTURE_FILES[key]).read_text(encoding='utf-8')

    def fetch(url, accept):
        assert accept == 'application/json'
        assert url.startswith(knox.SOURCES[key][0] + '?')
        if calls is not None:
            calls.append(url)
        return data
    return fetch


def makers_fetch(extra=''):
    # Preserve the publisher's bare carriage returns inside DESCRIPTION text.
    with open(FIXTURES / 'knoxmakers_20261117.ics', encoding='utf-8', newline='') as handle:
        text = handle.read()
    text = text.replace('END:VCALENDAR', extra + 'END:VCALENDAR')

    def fetch(url, accept):
        assert (url, accept) == (knox.SOURCES[knox.MAKERS][0], 'text/calendar')
        return text
    return fetch


def test_registration_must_match_exactly():
    for changed in ({'feed_url': 'https://wdvx.com/wp-json/tribe/events/v1/events/'},
                    {'timezone': 'America/Chicago'}, {'kind': 'html'}):
        with pytest.raises(ValueError, match='unregistered_knoxville_source'):
            knox.collect(dict(source(knox.WDVX), **changed), tribe_fetch(knox.WDVX), now=NOW)
    with pytest.raises(ValueError, match='unregistered_knoxville_source'):
        knox.collect(dict(source(knox.WDVX), source_key='legacy_parks_outdoor_knoxville_tn'),
                     tribe_fetch(knox.WDVX), now=NOW)


def test_wdvx_keeps_complete_narrative_street_and_full_size_photo():
    calls = []
    rows = knox.collect(source(knox.WDVX), tribe_fetch(knox.WDVX, calls=calls), now=NOW)
    assert len(calls) == 1 and 'per_page=100' in calls[0] and 'start_date=2026-11-17' in calls[0]
    assert 'end_date=2027-01-16' in calls[0]
    assert len(rows) == 3
    longest = max(rows, key=lambda r: len(r['description']))
    assert len(longest['description']) > 2000  # no shared display cap
    assert '<' not in longest['description'] and '&#' not in longest['description']
    for row in rows:
        assert knox.event_url(knox.WDVX, row['event_url'])
        assert row['venue_address'].endswith(', TN 37902')
        assert row['timezone'] == knox.ZONE
        assert row['image_url'].startswith('https://wdvx.com/site/wp-content/uploads/')
        assert row['image_provenance'] == 'publisher_event_candidates_v1'
        assert row['publisher_categories'] and row['description'].strip()


def test_history_center_skips_closure_and_all_day_notices():
    rows = knox.collect(source(knox.HISTORY), tribe_fetch(knox.HISTORY), now=NOW)
    assert len(rows) == 1 and 'Holiday' not in rows[0]['title']
    assert rows[0]['venue_address'] == '601 S Gay St, Knoxville, TN 37902'


def test_chamber_excludes_online_and_uses_only_the_reviewed_blank_street():
    rows = knox.collect(source(knox.CHAMBER), tribe_fetch(knox.CHAMBER), now=NOW)
    venues = {r['venue_name']: r['venue_address'] for r in rows}
    assert 'Online' not in venues
    assert venues['Tennessee Theatre'] == '604 South Gay Street, Knoxville, TN 37902'
    # A suffix the publisher split into its own field joins the street.
    assert venues['Knoxville Museum Of Art'] == '1050 Worlds Fair Park DR, Knoxville, TN 37916'
    assert venues['Ancient Lore Village'] == '7107 Sevierville Pike, Knoxville, TN 37920'
    assert any(len(r['description']) > 2000 for r in rows)


def test_unverified_or_blank_details_are_held_not_invented():
    payload = json.loads((FIXTURES / FIXTURE_FILES[knox.CHAMBER]).read_text(encoding='utf-8'))
    museum = next(e for e in payload['events'] if 'Museum' in e['venue']['venue'])
    blank = dict(museum, id=1, description='<p> </p>')
    numberless = dict(museum, id=2, venue=dict(museum['venue'], address='Safety City Road'))
    unknown_blank_street = dict(museum, id=3, venue=dict(museum['venue'], venue='Some Hall', address=''))
    offsite = dict(museum, id=4, url='https://example.com/event/x/')
    payload['events'] = [blank, numberless, unknown_blank_street, offsite]
    assert knox.collect(source(knox.CHAMBER), tribe_fetch(knox.CHAMBER, json.dumps(payload)), now=NOW) == []


def test_pagination_is_bounded_and_never_follows_response_links():
    payload = json.loads((FIXTURES / FIXTURE_FILES[knox.WDVX]).read_text(encoding='utf-8'))
    payload['total_pages'] = 3
    with pytest.raises(ValueError, match='pagination_limit'):
        knox.collect(source(knox.WDVX), tribe_fetch(knox.WDVX, json.dumps(payload)), now=NOW)


def test_tn_street_requires_number_and_only_infers_tn_from_a_tn_zip():
    assert knox.tn_street('604 S Gay St', 'Knoxville', '', '37902') == '604 S Gay St, Knoxville, TN 37902'
    assert knox.tn_street('604 S Gay St', 'Knoxville', '', '30301') is None
    assert knox.tn_street('Safety City Road', 'Knoxville', 'TN', '37919') is None
    assert knox.tn_street('116 Childress St SW', 'Knoxville', 'Tennessee', '') == '116 Childress St SW, Knoxville, TN'


def test_photo_rule_accepts_only_publisher_uploads():
    good = 'https://wdvx.com/site/wp-content/uploads/2026/11/Blue-Plate.jpg'
    assert knox.photo_url(knox.WDVX, good) == good
    for bad in ('https://wdvx.com/site/wp-content/uploads/2026/11/wdvx-logo.png',
                'https://cdn.example.com/site/wp-content/uploads/2026/11/a.jpg',
                good + '?resize=150', 'http://wdvx.com/site/wp-content/uploads/2026/11/a.jpg'):
        assert knox.photo_url(knox.WDVX, bad) is None
    assert knox.photo_url(knox.MAKERS, good) is None


def test_makers_location_room_and_contraction_repair():
    rows = knox.collect(source(knox.MAKERS), makers_fetch(EMPTY_LOCATION_EVENT), now=NOW)
    assert rows and all(r['venue_address'] == '116 Childress St SW, Knoxville, TN' for r in rows)
    assert all(r['venue_name'].startswith('Knox Makers') for r in rows)
    assert all('�' not in r['description'] for r in rows)
    assert all(r['event_url'] != 'https://events.knoxmakers.org/event/laser-cut-ornament-2' for r in rows)
    assert all(r['timezone'] == knox.ZONE and r['description'].strip() for r in rows)


def test_wordpress_sources_record_the_publisher_image_stage(monkeypatch):
    from roomquest.preview_worker import _process_claimed_source
    calls = []

    def rpc(name, payload):
        calls.append((name, payload))
        return len(payload['p_events']) if name.endswith('record_staged_events') else None
    monkeypatch.setattr(preview_worker, 'fetch_publisher',
                        lambda url, accept, **kw: (FIXTURES / FIXTURE_FILES[knox.WDVX]).read_text(encoding='utf-8'))
    monkeypatch.setattr(preview_worker, 'supabase_rpc', rpc)
    assert _process_claimed_source(dict(source(knox.WDVX), id=1))['complete'] == 1
    name, payload = calls[-1]
    assert name == 'community_collector_record_preview_v3'
    assert payload['p_parser_capability'] == 'publisher_event_candidates_v1'

    calls.clear()
    monkeypatch.setattr(preview_worker, 'fetch_publisher', lambda url, accept, **kw: makers_fetch()(url, accept))
    assert _process_claimed_source(dict(source(knox.MAKERS), id=2))['complete'] == 1
    assert calls[-1][0] == 'community_collector_record_preview_v2'
    assert 'p_parser_capability' not in calls[-1][1]


def test_worker_branch_enforces_completeness_and_image_capability(monkeypatch):
    def fake_fetch(url, accept, **kwargs):
        assert kwargs['respect_robots'] is True and kwargs['allowed_hosts'] == ('wdvx.com',)
        return (FIXTURES / FIXTURE_FILES[knox.WDVX]).read_text(encoding='utf-8')
    monkeypatch.setattr(preview_worker, 'fetch_publisher', fake_fetch)
    result = preview_worker.preview_source(source(knox.WDVX))
    assert result['p_parser_capability'] == 'publisher_event_candidates_v1'
    assert result['p_future_count'] == len(result['p_events']) == 3

    monkeypatch.setattr(knox, 'collect', lambda *a, **k: [{'description': '', 'venue_address': 'x'}])
    with pytest.raises(PreviewError, match='knoxville_incomplete_event'):
        preview_worker.preview_source(source(knox.WDVX))
