"""Full rolling-feed facts through actual registration and recurring dispatch."""
from datetime import datetime, timezone
import json
from pathlib import Path
from unittest.mock import Mock, patch
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup
import pytest

from roomquest import feed_registration as registration
from roomquest import preview_worker as worker
from roomquest import registered_listings as listings
from roomquest import sustainable_ow as sow
from roomquest import uk_registered_listings as uk
from roomquest.registration_formats import source_key

FIXTURE = Path(__file__).parent / 'fixtures/sustainable_ow/feed.xml'
LATEST = 'https://sustainableow.co.uk/2026/11/06/events-and-activities-in-november-december-update/'
EARLIER = 'https://sustainableow.co.uk/2026/10/22/events-and-activities-in-november-december/'


class FrozenMeta(type):
    def __instancecheck__(cls, value):
        return isinstance(value, datetime)


class FrozenDateTime(datetime, metaclass=FrozenMeta):
    day = (2026, 11, 22)

    @classmethod
    def now(cls, tz=None):
        value = cls(*cls.day, 12, tzinfo=timezone.utc)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(FrozenDateTime, 'day', (2026, 11, 22))
    for module in (sow, worker, listings, uk):
        monkeypatch.setattr(module, 'datetime', FrozenDateTime)


def source():
    return dict(feed_url=sow.URL, source_key=source_key(sow.URL),
                kind='html', platform_adapter='html', timezone=sow.ZONE)


def xml():
    return ET.fromstring(FIXTURE.read_text())


def encoded(root):
    return ET.tostring(root, encoding='unicode')


def body(root, index=0):
    return root.findall('./channel/item')[index].find(sow.CONTENT + 'encoded')


def workshop(root, *, index=0, title=None, schedule=None, after=None):
    content = body(root, index)
    soup = BeautifulSoup(content.text, 'html.parser')
    heading = next(node for node in soup.select('h3') if node.get_text(' ', strip=True) == 'Christmas Wreath Workshop')
    timing = heading.find_next_sibling('h4')
    if title is not None:
        heading.string = title
    if schedule is not None:
        timing.string = schedule
    if after is not None:
        timing.insert_after(BeautifulSoup(after, 'html.parser'))
    content.text = str(soup)


def add_section(root, markup, index=0):
    content = body(root, index)
    content.text += markup


def collect(payload=None):
    fetch = Mock(return_value=payload if payload is not None else FIXTURE.read_text())
    rows = listings.collect(source(), fetch)
    fetch.assert_called_once_with(sow.URL, 'application/rss+xml,application/xml')
    return rows


def test_real_feed_has_one_latest_deduplicated_occurrence_with_published_facts():
    rows = collect()
    assert len(rows) == 1
    row = rows[0]
    assert row['title'] == 'Christmas Wreath Workshop'
    assert row['starts_at'] == '2026-12-09T19:30:00+00:00' and row['ends_at'] is None
    assert row['event_url'] == LATEST and row['id'].startswith('sow:')
    assert row['venue_name'] == "St Andrew's Church Hall"
    assert row['venue_address'] == 'High Street, Oakington, Cambridge CB24 3AG, United Kingdom'
    assert row['venue_city'] == 'Oakington' and row['timezone'] == 'Europe/London'
    assert row['lat'] is None and row['lng'] is None and row['reason'] == 'missing_verified_venue_geo'
    assert '£3 donation' in row['description'] and 'All ages welcome' in row['description']
    assert not any('native' in key or 'evidence' in key or 'image' in key for key in row)


@pytest.mark.parametrize('hint', [None, 'ical', 'wordpress'])
def test_normal_admin_registration_verifies_only_the_durable_feed_with_one_fetch(hint):
    fetch = Mock(return_value=FIXTURE.read_text())
    with patch.object(registration, 'fetch_publisher', fetch), patch.object(
            registration, 'supabase_rpc', side_effect=[{'id': 879, 'url': sow.URL, 'type_hint': hint}, True]) as rpc:
        assert registration.register('offline-ticket') == {'outcome': 'verified'}
    assert fetch.call_args.args == (sow.URL, registration.ACCEPT) and fetch.call_count == 1
    assert fetch.call_args.kwargs['respect_robots'] is True and fetch.call_args.kwargs['deadline_at'] > 0
    assert [call.args[0] for call in rpc.call_args_list] == [
        'community_collector_claim_registration', 'community_collector_finish_registration']
    assert rpc.call_args.args[1] == dict(p_ticket='offline-ticket', p_outcome='verified',
                                      p_type='html', p_endpoint=sow.URL)


def test_recurring_collection_uses_same_reader_and_existing_candidate_contract():
    fetch = Mock(return_value=FIXTURE.read_text())
    with patch.object(worker, 'fetch_publisher', fetch), patch.object(worker, 'supabase_rpc') as rpc:
        result = worker.preview_source(source(), deadline_at=worker.monotonic() + 45)
    rpc.assert_not_called()
    assert fetch.call_args.args == (sow.URL, 'application/rss+xml,application/xml') and fetch.call_count == 1
    assert fetch.call_args.kwargs == dict(respect_robots=True, deadline_at=fetch.call_args.kwargs['deadline_at'],
                                         allowed_hosts=('sustainableow.co.uk',))
    assert result['p_future_count'] == 1 and result['p_venue_count'] == 0 and result['p_error'] is None
    assert result['p_parser_capability'] == 'publisher_event_candidates_v1'
    assert result['p_events'] == collect()


def test_future_titles_dates_and_additional_events_are_dynamic_not_fixed_to_wreath():
    root = xml()
    for index in (0, 1):
        workshop(root, index=index, title='Community botanical skills evening',
                 schedule='Wednesday 16 December, 6:00pm to 8:00pm at Oakington Church Hall')
    add_section(root, '<h3>Garden seed exchange</h3><h4>Saturday 19 December, 10:00am–11:30am at Oakington Church Hall</h4><p>Synthetic new event.</p>')
    rows = collect(encoded(root))
    assert [(row['title'], row['starts_at'], row['ends_at']) for row in rows] == [
        ('Community botanical skills evening', '2026-12-16T18:00:00+00:00', '2026-12-16T20:00:00+00:00'),
        ('Garden seed exchange', '2026-12-19T10:00:00+00:00', '2026-12-19T11:30:00+00:00')]


@pytest.mark.parametrize('markup', [
    '<h3>New practical workshop, Wednesday 16 December, 7:30pm at Oakington Church Hall</h3><p>Materials included.</p>',
    '<h3>New practical workshop, Wednesday 16 December</h3><h4>7:30pm at Oakington Church Hall</h4><p>Materials included.</p>',
    '<h3>New practical workshop, Wednesday 16 December</h3><p>We meet on 16 December at 7:30pm at Oakington Church Hall.</p>',
    '<h3>New practical workshop</h3><h4>Learn a practical skill together</h4><h4>Wednesday 16 December, 7:30pm at Oakington Church Hall</h4><p>Materials included.</p>',
    '<h3>Other notices</h3><h4>New practical workshop, Wednesday 16 December, 7:30pm at Oakington Church Hall</h4><p>Materials included.</p>',
])
def test_observed_heading_and_paragraph_schedule_shapes_extract_new_future_events(markup):
    root = xml()
    add_section(root, markup)
    rows = collect(encoded(root))
    assert len(rows) == 2 and rows[-1]['title'] == 'New practical workshop'
    assert rows[-1]['starts_at'] == '2026-12-16T19:30:00+00:00'


def test_post_title_date_and_initial_paragraph_time_are_kept_in_the_same_section():
    root = xml()
    item = root.findall('./channel/item')[4]
    item.find('title').text = 'Shared community supper on 16 December'
    body(root, 4).text = '<p>At 7pm at Oakington Church Hall. All welcome.</p><p>Synthetic full supper narrative with attendance information.</p>'
    rows = collect(encoded(root))
    assert rows[-1]['title'] == 'Shared community supper'
    assert rows[-1]['starts_at'] == '2026-12-16T19:00:00+00:00'


def test_latest_update_supersedes_old_time_without_duplicate_and_identity_ignores_post_url():
    baseline = collect()[0]
    root = xml()
    workshop(root, schedule='Wednesday 9 December, 8:30pm at Oakington Church Hall')
    assert [row['starts_at'] for row in collect(encoded(root))] == ['2026-12-09T20:30:00+00:00']
    # Remove the newest announcement; the earlier identical occurrence keeps its ID.
    root = xml()
    content = body(root)
    content.text = '<h3>Community update</h3><p>Synthetic non-event news containing no schedule.</p>'
    older = collect(encoded(root))[0]
    assert older['id'] == baseline['id'] and older['event_url'] == EARLIER


def test_same_day_distinct_sessions_are_preserved_when_both_are_explicit_in_latest_post():
    root = xml()
    add_section(root, '<h3>Christmas Wreath Workshop</h3><h4>Wednesday 9 December, 3:00pm at Oakington Church Hall</h4><p>Synthetic second session.</p>')
    rows = collect(encoded(root))
    assert [row['starts_at'] for row in rows] == ['2026-12-09T15:00:00+00:00', '2026-12-09T19:30:00+00:00']
    assert len({row['id'] for row in rows}) == 2


@pytest.mark.parametrize('schedule,start,end', [
    ('Wednesday 9 December, 7.30pm at Oakington Church Hall', '19:30', None),
    ('Wednesday 9 December, 19:30–21:00 at Oakington Church Hall', '19:30', '21:00'),
    ('Wednesday 9 December, 7–9pm at Oakington Church Hall', '19:00', '21:00'),
    ('Wednesday 9 December, 10–11:30 at Oakington Church Hall', '10:00', '11:30'),
    ('Wednesday 9 December, 12–4pm at Oakington Church Hall (optional help at 10am)', '12:00', '16:00'),
    ('Wednesday 9 December. Doors open 7pm, screening begins 7.30pm at Oakington Church Hall', '19:30', None),
])
def test_published_clock_formats_ranges_and_missing_end_are_explicit(schedule, start, end):
    root = xml()
    workshop(root, schedule=schedule)
    row = collect(encoded(root))[0]
    assert row['starts_at'] == '2026-12-09T' + start + ':00+00:00'
    assert row['ends_at'] == ('2026-12-09T' + end + ':00+00:00' if end else None)


@pytest.mark.parametrize('schedule,reason', [
    ('Wednesday 9 December at Oakington Church Hall. £3.50 donation', 'event_time_unverified'),
    ('Wednesday 9 December at Oakington Church Hall. Materials cost 3.50', 'event_time_unverified'),
    ('Wednesday 9 December, 7:75pm at Oakington Church Hall', 'event_time_unverified'),
    ('Wednesday 9 December, 13pm at Oakington Church Hall', 'event_time_unverified'),
    ('Wednesday 9 December, 9pm–7pm at Oakington Church Hall', 'event_time_conflict'),
    ('Monday 9 December, 7:30pm at Oakington Church Hall', 'event_weekday_conflict'),
    ('Wednesday 9 December, 7:30pm at Cambridge Library', 'event_venue_unverified'),
    ('Wednesday 9 December, 7:30pm at St Andrew’s Church Hall, Bristol', 'event_venue_unverified'),
    ('Wednesday 9 December, 7:30pm at Oakington Church Hall, Bristol', 'event_venue_unverified'),
    ('Wednesday 9 December, 7:30pm NOT at Oakington Church Hall', 'event_venue_unverified'),
])
def test_unverified_future_required_facts_hold_instead_of_using_older_announcement(schedule, reason):
    root = xml()
    workshop(root, schedule=schedule)
    with pytest.raises(ValueError, match='^sow_' + reason + '$'):
        collect(encoded(root))


@pytest.mark.parametrize('extra,reason', [
    ('<h4>Wednesday 9 December, 8:30pm at Oakington Church Hall</h4>', 'event_time_conflict'),
    ('<p>Wednesday 9 December, 8:30pm at Oakington Church Hall</p>', 'event_time_conflict'),
    ('<h4>Wednesday 9 December, 7:30pm at Cambridge Library</h4>', 'event_venue_unverified'),
])
def test_all_explicit_schedule_lines_agree_on_time_and_venue(extra, reason):
    root = xml()
    workshop(root, after=extra)
    with pytest.raises(ValueError, match='^sow_' + reason + '$'):
        collect(encoded(root))


def test_older_publication_dates_are_context_not_starts_and_do_not_roll_forward(monkeypatch):
    monkeypatch.setattr(FrozenDateTime, 'day', (2027, 11, 22))
    assert collect() == []  # old December 2026 never becomes December 2027


def test_explicit_next_year_can_enter_window_but_bare_january_stays_in_published_year():
    root = xml()
    add_section(root, '<h3>Future practical workshop</h3><h4>6 January next year, 7pm at Oakington Church Hall</h4><p>Synthetic future event.</p>')
    add_section(root, '<h3>Earlier practical workshop</h3><h4>6 January, 7pm at Oakington Church Hall</h4><p>Synthetic earlier event.</p>')
    rows = collect(encoded(root))
    assert [(row['title'], row['starts_at']) for row in rows] == [
        ('Christmas Wreath Workshop', '2026-12-09T19:30:00+00:00'),
        ('Future practical workshop', '2027-01-06T19:00:00+00:00')]


def test_complete_empty_is_healthy_recurring_but_cannot_verify_initial_registration(monkeypatch):
    monkeypatch.setattr(FrozenDateTime, 'day', (2026, 12, 10))
    assert collect() == []  # includes the now in-window, intentionally unscheduled Feb save-the-date
    fetch = Mock(return_value=FIXTURE.read_text())
    with patch.object(worker, 'fetch_publisher', fetch):
        result = worker.preview_source(source())
    assert result['p_events'] == [] and result['p_future_count'] == 0 and result['p_error'] is None
    with patch.object(registration, 'fetch_publisher', fetch), patch.object(
            registration, 'supabase_rpc', side_effect=[{'url': sow.URL}, True]) as rpc:
        assert registration.register('offline-ticket') == {'outcome': 'review'}
    assert rpc.call_args.args[1]['p_reason'] == 'no_extractable_events'


def test_latest_explicit_tbc_excludes_the_old_timed_occurrence_without_inventing_schedule():
    root = xml()
    workshop(root, schedule='Wednesday 9 December, time TBC at Oakington Church Hall')
    assert collect(encoded(root)) == []


def test_deadlines_services_save_dates_and_external_programmes_do_not_create_events():
    root = xml()
    add_section(root, '<h3>Bulk ordering</h3><p>The expression of interest deadline is 1 December.</p>'
                '<h3>Repair cafe reminder</h3><p>Save the date: 6 January next year.</p>'
                '<h3>Camera loan service</h3><p>Book training via <a href="https://other.example/programme/">the programme</a>.</p>')
    rows = collect(encoded(root))
    assert len(rows) == 1 and rows[0]['title'] == 'Christmas Wreath Workshop'


def test_images_metadata_and_adjacent_sections_cannot_supply_a_missing_clock_or_venue():
    root = xml()
    workshop(root, schedule='Wednesday 9 December at Oakington Church Hall',
             after='<figure><img data-image-meta=\'{"created_timestamp":1796844600,"latitude":52.2,"longitude":0.1}\'><figcaption>7:30pm</figcaption></figure>')
    add_section(root, '<h3>Unrelated workshop</h3><h4>Wednesday 16 December, 7:30pm at Oakington Church Hall</h4><p>Other event.</p>')
    with pytest.raises(ValueError, match='^sow_event_time_unverified$'):
        collect(encoded(root))


@pytest.mark.parametrize('change', ['count', 'duplicate', 'missing_content', 'excerpt_only', 'next_page',
                                  'wrong_site', 'wrong_self', 'wrong_domain', 'wrong_year', 'wrong_guid'])
def test_incomplete_or_wrong_publisher_feed_fails_closed(change):
    root = xml()
    channel, items = root.find('channel'), root.findall('./channel/item')
    if change == 'count': channel.remove(items[-1])
    elif change == 'duplicate':
        items[1].find(sow.WP + 'post-id').text = items[0].findtext(sow.WP + 'post-id')
    elif change == 'missing_content': items[0].remove(body(root))
    elif change == 'excerpt_only': body(root).text = items[0].findtext('description')
    elif change == 'next_page': ET.SubElement(channel, sow.ATOM + 'link', {'rel': 'next', 'href': sow.URL + '?paged=2'})
    elif change == 'wrong_site': channel.find(sow.WP + 'site').text = '123'
    elif change == 'wrong_self': channel.find(sow.ATOM + 'link').set('href', 'https://other.example/feed/')
    elif change == 'wrong_domain': items[0].find('link').text = LATEST.replace('sustainableow.co.uk', 'other.example')
    elif change == 'wrong_year': items[0].find('pubDate').text = 'Thu, 06 Nov 2025 08:37:46 +0000'
    elif change == 'wrong_guid': items[0].find('guid').text = 'http://other.example/?p=2070'
    with pytest.raises(ValueError, match='^sow_'):
        collect(encoded(root))


@pytest.mark.parametrize('payload', ['<rss>', '<rss version="2.0"><channel/></rss>',
                                     '<!DOCTYPE rss [<!ENTITY x "bad">]><rss version="2.0"><channel/></rss>'])
def test_malformed_xml_or_entity_declarations_are_not_interpreted(payload):
    with pytest.raises(ValueError, match='^sow_'):
        collect(payload)


@pytest.mark.parametrize('changed', [{'feed_url': LATEST}, {'feed_url': sow.HOME + '/'},
                                    {'feed_url': sow.URL + '?paged=2'}, {'source_key': 'wrong'}])
def test_unreviewed_original_article_or_other_source_never_fetches(changed):
    fetch = Mock()
    with pytest.raises(ValueError, match='^unregistered_html_source$'):
        listings.collect({**source(), **changed}, fetch)
    with patch.object(worker, 'fetch_publisher', fetch), pytest.raises(worker.PreviewError, match='^unregistered_html_source$'):
        worker.preview_source({**source(), **changed})
    fetch.assert_not_called()


@pytest.mark.parametrize('reason', ['robots_denied', 'publisher_http_401', 'publisher_http_403'])
def test_access_denial_stops_without_fallback_or_other_publisher_reads(reason):
    fetch = Mock(side_effect=worker.PreviewError(reason))
    with patch.object(registration, 'fetch_publisher', fetch), patch.object(
            registration, 'supabase_rpc', side_effect=[{'url': sow.URL}, True]) as rpc:
        assert registration.register('offline-ticket') == {'outcome': 'disabled'}
    assert fetch.call_count == 1 and rpc.call_args.args[1]['p_reason'] == reason
    fetch.reset_mock()
    with patch.object(worker, 'fetch_publisher', fetch), pytest.raises(worker.PreviewError, match='^' + reason + '$'):
        worker.preview_source(source())
    assert fetch.call_count == 1


def test_deadline_is_checked_before_and_after_the_single_read(monkeypatch):
    clock = [10]
    monkeypatch.setattr(sow, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(uk, 'monotonic', lambda: clock[0])
    fetch = Mock(return_value=FIXTURE.read_text())
    with pytest.raises(ValueError, match='^collection_deadline$'):
        listings.collect(source(), fetch, deadline_at=10)
    fetch.assert_not_called()

    def slow(url, accept):
        clock[0] = 20
        return FIXTURE.read_text()
    fetch.side_effect = slow
    with pytest.raises(ValueError, match='^collection_deadline$'):
        listings.collect(source(), fetch, deadline_at=20)
    assert fetch.call_count == 1


def test_generic_classifier_and_other_source_scope_are_unchanged():
    result = registration.classify(sow.URL, FIXTURE.read_text())
    assert result['p_outcome'] == 'review' and result['p_reason'] == 'no_reusable_calendar'
    assert LATEST not in listings.URLS
    assert not any('onlinesales.admin.cam.ac.uk' in value for value in listings.URLS)
