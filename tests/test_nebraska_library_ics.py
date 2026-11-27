from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from icalendar import Calendar, Event

from roomquest import nebraska_library_ics, preview_worker
from roomquest.nebraska_library_ics import BELLEVUE, LANDING, SOURCES, SUMP
from roomquest.preview_worker import PreviewError, preview_source


def source_for(key):
    return dict(source_key=key, feed_url=SOURCES[key], kind='ical',
                platform_adapter='ical', timezone='America/Chicago')


def feed(host, events):
    calendar = Calendar()
    calendar.add('version', '2.0')
    calendar.add('prodid', '-//EventQuest test//EN')
    start = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=2)
    for i, (title, room, visibility, status) in enumerate(events, 1):
        event = Event()
        for field, value in {
            'uid': f'LibCal-123-{i}', 'summary': title, 'location': room, 'class': visibility,
            'status': status, 'dtstamp': start, 'dtstart': start + timedelta(hours=i),
            'dtend': start + timedelta(hours=i + 1), 'url': f'https://{host}/event/{i}',
            'description': 'Bring a book and join the discussion.',
            'categories': ['Book Club'],
        }.items():
            event.add(field, value)
        calendar.add_component(event)
    return calendar.to_ical().decode()


def test_bellevue_timed_programs_only():
    source = source_for('bellevue_public_library_ne')
    payload = feed('bellevue-lib.libcal.com', [
        ('Book Club', 'Room 1', 'PUBLIC', 'CONFIRMED'),
        ('Outside Group', 'Room 1', 'PUBLIC', 'CONFIRMED'),
        ('Internal Workshop', 'Room 1', 'PRIVATE', 'CONFIRMED'),
        ('Postponed: Family Games', 'Room 2', 'PUBLIC', 'CONFIRMED'),
        ('Film Night', 'Community Park', 'PUBLIC', 'CONFIRMED'),
        ('Storytime', 'Room 1', 'PUBLIC', 'CANCELLED'),
    ])
    with patch('roomquest.preview_worker.fetch_publisher', return_value=payload) as fetch:
        result = preview_source(source)
    assert fetch.call_args.kwargs['respect_robots'] is True
    assert fetch.call_args.kwargs['allowed_hosts'] == ('bellevue-lib.libcal.com',)
    assert result['p_future_count'] == 1
    event = result['p_events'][0]
    assert (event['venue_name'], event['venue_address'], event['venue_city']) == BELLEVUE
    assert event['publisher_categories'] == ['Book Club']
    assert event['description'] == 'Bring a book and join the discussion.'
    assert event['lat'] is event['lng'] is None
    facts = event['collector_event_content_v1']['facts']
    assert event['collector_event_content_v1']['event_id'] == event['id']
    assert facts['meeting_location'] == 'Room 1'
    assert facts['publisher_categories'] == ['Book Club']
    assert facts['publisher_status'] == 'confirmed'
    assert facts['description'] == 'Bring a book and join the discussion.'
    assert facts['source_timezone'] == 'America/Chicago'
    assert 'Bellevue Public Library' not in str(facts)
    assert '2206 Longo Drive' not in str(facts)
    assert 'collector_event_content_v1' not in result['p_samples'][0]


def test_papillion_distinguishes_branches():
    source = source_for('papillion_public_library_ne')
    payload = feed('papillion.libcal.com', [
        ('Anime Club', 'South Meeting Room, Sump Memorial Library', 'PUBLIC', 'CONFIRMED'),
        ('Makerspace', 'Digital Makerspace, Digital Library at Papillion Landing', 'PUBLIC', 'CONFIRMED'),
        ('Room Only', 'South Meeting Room', 'PUBLIC', 'CONFIRMED'),
        ('Conflicting Branch', 'Sump Memorial Library, Digital Library at Papillion Landing', 'PUBLIC', 'CONFIRMED'),
    ])
    with patch('roomquest.preview_worker.fetch_publisher', return_value=payload):
        result = preview_source(source)
    assert [(r['venue_name'], r['venue_address'], r['venue_city']) for r in result['p_events']] == [SUMP, LANDING]


def test_wrong_feed_is_rejected_before_fetch():
    source = source_for('bellevue_public_library_ne')
    source['feed_url'] = SOURCES['papillion_public_library_ne']
    with patch('roomquest.preview_worker.fetch_publisher') as fetch:
        with pytest.raises(PreviewError, match='unregistered_nebraska_library'):
            preview_source(source)
    fetch.assert_not_called()


def test_provider_label_change_is_not_a_fingerprint_input():
    source = source_for('bellevue_public_library_ne')
    payload = feed('bellevue-lib.libcal.com', [
        ('Book Club', 'Room 1', 'PUBLIC', 'CONFIRMED'),
    ])
    first = nebraska_library_ics.collect(source, payload)[0]
    renamed = deepcopy(first)
    renamed.update(venue_name='Bellevue Library', venue_address='Changed display label')
    assert renamed['id'] == first['id']
    assert renamed['collector_event_content_v1'] == first['collector_event_content_v1']


def test_event_narrative_change_changes_facts_not_occurrence_id():
    source = source_for('bellevue_public_library_ne')
    initial = feed('bellevue-lib.libcal.com', [
        ('Book Club', 'Room 1', 'PUBLIC', 'CONFIRMED'),
    ])
    changed = initial.replace('Bring a book and join the discussion.',
                              'Bring this month’s selection and join the discussion.')
    first = nebraska_library_ics.collect(source, initial)[0]
    second = nebraska_library_ics.collect(source, changed)[0]
    assert second['id'] == first['id']
    assert second['collector_event_content_v1'] != first['collector_event_content_v1']


def test_full_narrative_is_fingerprinted_but_display_remains_bounded():
    source = source_for('bellevue_public_library_ne')
    narrative = 'A' * 2500
    payload = feed('bellevue-lib.libcal.com', [
        ('Book Club', 'Room 1', 'PUBLIC', 'CONFIRMED'),
    ]).replace('Bring a book and join the discussion.', narrative)
    row = nebraska_library_ics.collect(source, payload)[0]
    assert len(row['description']) == 2000
    assert row['collector_event_content_v1']['facts']['description'] == narrative


def test_narrative_above_live_limit_is_rejected():
    source = source_for('bellevue_public_library_ne')
    payload = feed('bellevue-lib.libcal.com', [
        ('Book Club', 'Room 1', 'PUBLIC', 'CONFIRMED'),
    ]).replace('Bring a book and join the discussion.', 'A' * (nebraska_library_ics.MAX_DESCRIPTION + 1))
    with pytest.raises(ValueError, match='publisher_description_limit'):
        nebraska_library_ics.collect(source, payload)


def test_normal_path_keeps_original_facts_and_admin_sample_strips(monkeypatch):
    source = source_for('bellevue_public_library_ne')
    payload = feed('bellevue-lib.libcal.com', [
        ('Book Club', 'Room 1', 'PUBLIC', 'CONFIRMED'),
    ])
    calls = {}
    monkeypatch.setattr(preview_worker, 'fetch_publisher', lambda *args, **kwargs: payload)
    monkeypatch.setattr(preview_worker, 'supabase_rpc',
                        lambda name, body: calls.setdefault(name, body) and 0)
    preview_worker._process_claimed_source(source)
    staged = calls['community_collector_record_staged_events']['p_events']
    samples = calls['community_collector_record_preview_v2']['p_samples']
    assert staged[0]['collector_event_content_v1']['event_id'] == staged[0]['id']
    assert 'collector_event_content_v1' not in samples[0]
