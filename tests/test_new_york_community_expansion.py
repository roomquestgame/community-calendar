from copy import deepcopy
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import Mock

from bs4 import BeautifulSoup

from roomquest import new_york_community_expansion as ny

NOW = datetime(2026, 11, 15, 1, 24, tzinfo=timezone.utc)


def source(key=ny.PROSPECT):
    return dict(source_key=key, feed_url=ny.SOURCES[key][0], kind='html',
                platform_adapter='html', timezone=ny.ZONE)


def prospect(identity=100, title='Winter bird walk', body='Complete program, accessibility and registration information.', start='2026-12-05 11:00:00', end='2026-12-05 12:00:00'):
    return dict(id=identity, title=title, description='<p>' + body + '</p>',
                url=f'https://www.prospectpark.org/event/winter-bird-walk-{identity}/',
                status='publish', timezone=ny.ZONE, start_date=start, end_date=end,
                utc_start_date=ny.timestamp(start, ny.ZONE).astimezone(timezone.utc).isoformat(),
                utc_end_date=ny.timestamp(end, ny.ZONE).astimezone(timezone.utc).isoformat(),
                all_day=False, hide_from_listings=False, categories=[dict(name='Birding')])


def prospect_detail(event, *, body=None, end=None):
    structured = dict(**{'@type': 'Event'}, url=event['url'], name=event['title'],
                      startDate=event['utc_start_date'], endDate=end or event['utc_end_date'],
                      eventStatus='https://schema.org/EventScheduled',
                      eventAttendanceMode='https://schema.org/OfflineEventAttendanceMode')
    return (f'<h1 class="page-title">{event["title"]}</h1>'
            '<div class="tribe-events-single-event-description">' + (body if body is not None else event['description']) + '</div>'
            '<div class="sidebar-location"><div class="sidebar-text">Audubon Center</div></div>'
            '<div class="sidebar-mapit"><a href="https://www.prospectpark.org/location/audubon-center/">Map</a></div>'
            '<script type="application/ld+json">' + json.dumps(structured) + '</script>')


def prospect_pages(*events):
    pages = {ny._api_url(ny.PROSPECT, NOW): json.dumps(dict(events=list(events), total=len(events), total_pages=1, next_rest_url=None))}
    pages.update({e['url']: prospect_detail(e) for e in events})
    return pages


def snug(identity=200, title='Public garden workshop', **changes):
    row = dict(id=identity, post_id=91, name=title, type='event', date='2026-12-05',
               time_start='11:00:00', time_end='12:00:00', status='Active',
               post_permalink=f'https://snug-harbor.org/event/public-garden-workshop/?slot_id={identity}',
               details=dict(ticket_link=dict(url='https://snug-harbor.org/tickets/')))
    row.update(changes)
    return row


def snug_detail(event, *, narrative='Complete garden workshop narrative and final accessibility conditions.', where='Visitor Info Booth at Chapel Road and Gazebo Road', clock='11:00 AM'):
    return (f'<main><h1 class="o-hero-3__title">{event["name"]}</h1>'
            '<div class="o-g-text-a-1__text"><p>' + narrative + '</p><p>WHERE: ' + where + '</p><p>ADMISSION: Free</p></div>'
            '<div class="o-hero-3__board-date-day">Dec 5, 2026</div>'
            '<div class="o-hero-3__time">' + clock + '</div></main>'
            '<script type="application/ld+json">{"@type":"Event","startDate":"2026-01-01","endDate":"2026-12-31"}</script>')


def snug_pages(*events):
    pages = {ny._api_url(ny.SNUG, NOW): json.dumps(dict(success=True, data=list(events)))}
    pages.update({e['post_permalink']: snug_detail(e) for e in events})
    return pages


class NewYorkCommunityExpansionTests(unittest.TestCase):
    def test_prospect_full_native_body_and_actual_feature_point(self):
        body = 'Program activities, meeting details and accessibility. ' * 70 + 'Final cancellation policy.'
        event = prospect(body=body)
        pages = prospect_pages(event)
        result = ny.collect_chunk(source(), lambda url, accept: pages[url], now=NOW)
        self.assertTrue(result['complete'])
        row = result['events'][0]
        self.assertEqual(row['description'], body)
        self.assertGreater(len(row['description']), 2000)
        self.assertEqual((row['lat'], row['lng']), ny.VENUES['prospect_audubon'][3:])
        self.assertEqual(row['venue_address'], '101 East Drive, Brooklyn, NY 11225')
        ny._checkpoint(ny.PROSPECT, result['checkpoint'], NOW)

    def test_protected_email_placeholder_preserves_complete_native_feed(self):
        event = prospect(body='Contact events@prospectpark.org for the complete workshop. Final accessibility note.')
        item = ny._prospect_item(event, NOW)
        row = ny._detail(ny.PROSPECT, item, prospect_detail(event, body='<p>Contact [email\xa0protected] for the complete workshop. Final accessibility note.</p>'))
        self.assertIn('events@prospectpark.org', row['description'])
        with self.assertRaisesRegex(ValueError, 'detail_changed'):
            ny._detail(ny.PROSPECT, item, prospect_detail(event, body='<p>Short summary.</p>'))

    def test_repeated_native_end_is_unknown_without_fabricated_duration(self):
        event = prospect(start='2026-12-31 22:00:00', end='2026-12-31 22:00:00')
        item = ny._prospect_item(event, NOW)
        self.assertIsNone(item['ends_at'])
        row = ny._detail(ny.PROSPECT, item, prospect_detail(event))
        self.assertIsNone(row['ends_at'])

    def test_detail_clock_conflict_fails_closed(self):
        event = prospect()
        with self.assertRaisesRegex(ValueError, 'schedule_changed'):
            ny._detail(ny.PROSPECT, ny._prospect_item(event, NOW), prospect_detail(event, end='2026-12-05T18:00:00+00:00'))
        event = snug()
        with self.assertRaisesRegex(ValueError, 'schedule_changed'):
            ny._detail(ny.SNUG, ny._snug_item(event, NOW), snug_detail(event, clock='12:00 PM'))

    def test_prospect_incomplete_duplicate_and_capped_manifests_fail(self):
        event = prospect()
        for payload, reason in [
            (dict(events=[event], total=2, total_pages=1), 'pagination_incomplete'),
            (dict(events=[event, event], total=2, total_pages=1), 'pagination_incomplete'),
            (dict(events=[], total=201, total_pages=5), 'manifest_limit'),
            (dict(events=[event], total=1, total_pages=1, next_rest_url='more'), 'pagination_incomplete'),
        ]:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                ny._manifest(ny.PROSPECT, lambda url, accept: json.dumps(payload), float('inf'), NOW)

    def test_snug_full_page_or_duplicate_slot_is_never_complete(self):
        event = snug()
        for rows in ([event] * 500, [event, event]):
            with self.assertRaisesRegex(ValueError, 'pagination_incomplete'):
                ny._manifest(ny.SNUG, lambda url, accept: json.dumps(dict(success=True, data=rows)), float('inf'), NOW)

    def test_checkpoint_partial_rows_stay_private_then_resume_complete(self):
        events = [prospect(101), prospect(102)]
        pages = prospect_pages(*events)
        fetch = lambda url, accept: pages[url]
        first = ny.collect_chunk(source(), fetch, now=NOW, max_details=1)
        self.assertFalse(first['complete'])
        self.assertEqual(first['events'], [])
        self.assertEqual(len(first['checkpoint']['events']), 1)
        final = ny.collect_chunk(source(), fetch, now=NOW, checkpoint=first['checkpoint'])
        self.assertTrue(final['complete'])
        self.assertEqual(len(final['events']), 2)
        ny._checkpoint(ny.PROSPECT, final['checkpoint'], NOW)

    def test_changed_manifest_restarts_without_partial_publication(self):
        event = prospect(101)
        pages = prospect_pages(event)
        calls = 0
        def fetch(url, accept):
            nonlocal calls
            if url == ny._api_url(ny.PROSPECT, NOW):
                calls += 1
                if calls > 1:
                    return json.dumps(dict(events=[prospect(102)], total=1, total_pages=1))
            return pages[url]
        result = ny.collect_chunk(source(), fetch, now=NOW)
        self.assertFalse(result['complete'])
        self.assertEqual(result['events'], [])
        self.assertEqual(result['checkpoint']['cursor'], 0)
        self.assertEqual(result['checkpoint']['queue'][0]['id'], '102')

    def test_checkpoint_tampering_body_point_clock_and_provenance_rejected(self):
        event = prospect()
        pages = prospect_pages(event)
        state = ny.collect_chunk(source(), lambda url, accept: pages[url], now=NOW)['checkpoint']
        for field, value in [('description', 'Shortened summary'), ('lat', 0),
                             ('starts_at', '2026-12-05T18:00:00+00:00'),
                             ('location_provenance', ny.LOCATION_PROVENANCE['snug_c']),
                             ('event_url', 'https://evil.invalid/event/')]:
            altered = deepcopy(state)
            altered['events'][0][field] = value
            # Even internally consistent row hashes cannot change native bindings.
            altered['row_hashes'][altered['events'][0]['id']] = ny._digest(altered['events'][0])
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'checkpoint_invalid'):
                ny._checkpoint(ny.PROSPECT, altered, NOW)

    def test_healthy_partner_identity_excludes_future_mirrors(self):
        event = snug(900, "Staten Island Children’s Museum: New Future Workshop",
                     details=dict(ticket_link=dict(url='https://sichildrensmuseum.org/event/new-workshop/')))
        self.assertEqual(ny._snug_item(event, NOW)['held'], 'working_partner_source')
        event['details']['ticket_link']['url'] = 'https://sichildrensmuseum.org.evil.invalid/event/'
        self.assertIsNone(ny._snug_item(event, NOW)['held'])
        known = prospect(38564, 'Pre-Thanksgiving Birding in Prospect Park', start='2026-11-15 08:00:00', end='2026-11-15 12:00:00')
        self.assertEqual(ny._prospect_item(known, NOW)['held'], 'already_published_partner_occurrence')
        known['id'] = 38565
        self.assertIsNone(ny._prospect_item(known, NOW)['held'])

    def test_snug_native_occurrence_and_full_body_use_actual_meeting_feature(self):
        event = snug()
        body = 'Every workshop activity and registration term. ' * 60 + 'Final access instructions.'
        row = ny._detail(ny.SNUG, ny._snug_item(event, NOW), snug_detail(event, narrative=body))
        self.assertTrue(row['description'].startswith(body))
        self.assertIn('WHERE:', row['description'])
        self.assertEqual(row['starts_at'], '2026-12-05T16:00:00+00:00')
        self.assertEqual((row['lat'], row['lng']), ny.VENUES['snug_booth'][3:])
        self.assertTrue(row['location_is_approximate'])
        self.assertIn('approximate', row['venue_name'])

    def test_ambiguous_sessions_multivenue_and_unknown_meetup_are_held(self):
        event = snug()
        item = ny._snug_item(event, NOW)
        with self.assertRaisesRegex(ValueError, 'schedule_unresolved'):
            ny._detail(ny.SNUG, item, snug_detail(event, narrative='Session 1: 11:00–12:30. Session 2: 1:00–2:30.'))
        with self.assertRaisesRegex(ValueError, 'venue_unreviewed'):
            ny._detail(ny.SNUG, item, snug_detail(event, where="Carpenter’s Shop and Great Hall"))
        for different_room in ('Harbor Room', 'Dance Center'):
            with self.subTest(room=different_room), self.assertRaisesRegex(ValueError, 'venue_unreviewed'):
                ny._detail(ny.SNUG, item, snug_detail(event, where=different_room))
        with self.assertRaisesRegex(ValueError, 'venue_unreviewed'):
            ny._prospect_place(dict(id='999', url='https://www.prospectpark.org/event/unknown/', starts_at='', ends_at='', title='Fall Fix-Up'), BeautifulSoup('<main></main>', 'html.parser'), 'Variable meeting locations')

    def test_nonpublic_remote_and_blank_or_oversize_descriptions_never_publish(self):
        for title, reason in [('Garden hours', 'event_not_public'), ('Private wedding', 'event_not_public'), ('Master course | Virtual Session', 'remote_event')]:
            self.assertEqual(ny._snug_item(snug(title=title), NOW)['held'], reason)
        for text, reason in [('', 'description_missing'), ('x' * (ny.MAX_DESCRIPTION + 1), 'description_limit')]:
            with self.assertRaisesRegex(ValueError, reason):
                ny._body(text)

    def test_guarded_deadline_keeps_completed_work_private_and_resumable(self):
        event = prospect()
        pages = prospect_pages(event)
        def pause(url, accept):
            if url == event['url']:
                raise ValueError('collection_deadline')
            return pages[url]
        pending = ny.collect_chunk(source(), pause, now=NOW)
        self.assertFalse(pending['complete'])
        self.assertEqual(pending['events'], [])
        final = ny.collect_chunk(source(), lambda url, accept: pages[url], checkpoint=pending['checkpoint'], now=NOW)
        self.assertTrue(final['complete'])
        self.assertEqual(len(final['events']), 1)

    def test_exact_source_and_same_origin_paths_are_required(self):
        bad = source()
        bad['feed_url'] += '?changed=1'
        fetch = Mock()
        with self.assertRaisesRegex(ValueError, 'source_unregistered'):
            ny.collect_chunk(bad, fetch, now=NOW)
        fetch.assert_not_called()
        self.assertFalse(ny.event_url(ny.SNUG, 'https://snug-harbor.org/event/workshop/?slot_id=1&admin=1'))
        self.assertFalse(ny.event_url(ny.PROSPECT, 'https://www.prospectpark.org/event/../admin/'))
        self.assertIsNone(ny.photo_url(ny.SNUG, 'https://evil.invalid/wp-content/uploads/photo.jpg'))


if __name__ == '__main__':
    unittest.main()
