"""Every published McGregor performance is retained or explicitly held."""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from bs4 import BeautifulSoup
import pytest

from roomquest import mcgregor_hall as hall, preview_worker

NOW = datetime(2026, 11, 10, 10, tzinfo=timezone.utc)
FIXTURE = Path(__file__).parent / 'fixtures/south_hill_expansion/mcgregor-shows.html'
SOURCE = {'source_key': hall.SOURCE_KEY, 'feed_url': hall.CALENDAR,
          'kind': 'html', 'platform_adapter': 'html', 'timezone': hall.TIMEZONE}


@pytest.fixture(autouse=True)
def stable_test_clock(monkeypatch):
    monkeypatch.setattr(preview_worker, '_future_datetime', lambda value: value.astimezone(timezone.utc))


def test_actual_publisher_cards_yield_six_upcoming_individual_performances():
    notes = {}
    rows = hall.parse(FIXTURE.read_text(), now=NOW, diagnostics=notes)
    assert len(rows) == 6 and notes['cards'] == 5 and not notes.get('held')
    assert rows[0]['id'] == 'mcgregor_hall:frozen--the-broadway-musical:2026-11-13T19:30'
    assert [row['starts_at'] for row in rows[:3]] == [
        '2026-11-14T00:30:00+00:00', '2026-11-14T20:00:00+00:00', '2026-11-15T20:00:00+00:00']
    assert all(row['ends_at'] is None for row in rows)
    assert all(row['venue_address'] == hall.ADDRESS for row in rows)
    assert all(row['lat'] is None and row['lng'] is None for row in rows)
    assert len({row['image_url'] for row in rows}) == 3
    assert all(row['image_evidence_url'] == hall.CALENDAR for row in rows)
    assert all(row['details_evidence_url'] == hall.CALENDAR for row in rows)
    assert rows[0]['event_url'] == 'https://www.mcgregorhall.org/frozen--the-broadway-musical'
    assert len(notes['excluded']) == 7


@pytest.mark.parametrize('replacement', [
    'Friday, Nov. 13, 2026 7:30PM', '11/13/2026 7:30PM',
    'Friday, November 13 7:30PM', 'Friday, November 13, 2026 7:30',
    'Saturday, November 13, 2026 7:30PM',
])
def test_unknown_schedule_line_holds_entire_show_without_partial_success(replacement):
    notes = {}
    text = FIXTURE.read_text().replace('Friday, November 13, 2026 7:30PM', replacement)
    rows = hall.parse(text, now=NOW, diagnostics=notes)
    assert len(rows) == 3
    assert not any('frozen' in row['id'] for row in rows)
    assert len(notes['held']) == 1
    assert notes['held'][0]['id'] == 'mcgregor_hall:frozen--the-broadway-musical'


def test_unknown_additional_performance_does_not_disappear():
    soup = BeautifulSoup(FIXTURE.read_text(), 'html.parser')
    item = soup.new_tag('li')
    item.string = 'Additional performance date to be announced'
    soup.select_one('ul').append(item)
    notes = {}
    rows = hall.parse(str(soup), now=NOW, diagnostics=notes)
    assert len(rows) == 3 and notes['held'][0]['reason'] == 'publisher_schedule_unresolved'


def test_summary_count_never_truncates_or_generates_performances():
    # The real card says "Four Performances" but prints five distinct dates.
    text = FIXTURE.read_text().replace('Four Performances:', 'Twenty Performances:')
    assert [r['id'] for r in hall.parse(text, now=NOW)] == [r['id'] for r in hall.parse(FIXTURE.read_text(), now=NOW)]


def test_standalone_audition_link_is_not_part_of_a_performance_description():
    rows = [row for row in hall.parse(FIXTURE.read_text(), now=NOW) if 'blacknativity' in row['id']]
    assert len(rows) == 2
    for row in rows:
        assert 'Audition information' not in row['description']
        assert 'Langston Hughes' in row['description']
        assert 'Directed by Karen-Leigh Albert' in row['description']
        assert 'a live band' in row['description']


def test_audition_keyword_inside_actual_event_prose_is_preserved():
    soup = BeautifulSoup(FIXTURE.read_text(), 'html.parser')
    link = soup.select_one('a[href="/black-nativity-auditions-and-information"]')
    link.parent.insert(0, 'The performance includes a scene about auditions. ')
    rows = [row for row in hall.parse(str(soup), now=NOW) if 'blacknativity' in row['id']]
    assert all('The performance includes a scene about auditions.' in row['description'] for row in rows)
    assert all('Audition information is available here!' in row['description'] for row in rows)


@pytest.mark.parametrize('text', ['Private event', 'Moved to a new location', 'Venue: Elsewhere'])
def test_private_and_offsite_notices_never_inherit_the_hall(text):
    soup = BeautifulSoup(FIXTURE.read_text(), 'html.parser')
    soup.select_one('section .dmNewParagraph').append(BeautifulSoup('<p>' + text + '</p>', 'html.parser'))
    rows = hall.parse(str(soup), now=NOW)
    assert len(rows) == 3
    assert not any('frozen' in row['id'] for row in rows)


def test_source_and_occurrence_identity_changes_fail_closed():
    payload = FIXTURE.read_text()
    for text in (payload.replace('Shows &amp; Events', 'Unknown Listing'),
                 payload.replace('https://www.mcgregorhall.org/shows-events', 'https://example.com/events'),
                 payload.replace('href="/blacknativity"', 'href="https://127.0.0.1/secret"'),
                 payload.replace('href="/blacknativity"', 'href="/frozen--the-broadway-musical"')):
        with pytest.raises(ValueError):
            hall.parse(text, now=NOW)


def test_future_season_and_past_dates_do_not_slide_into_current_window():
    rows = hall.parse(FIXTURE.read_text(), now=NOW)
    assert not any('2027' in row['starts_at'] for row in rows)
    assert not any('2026-11-07' in row['id'] or '2026-11-08' in row['id'] for row in rows)
    assert hall.parse(FIXTURE.read_text(), now=datetime(2028, 11, 10, tzinfo=timezone.utc)) == []


def test_explicit_start_without_end_expires_after_three_hours():
    rows = hall.parse(FIXTURE.read_text(), now=datetime(2026, 11, 14, 3, 30, tzinfo=timezone.utc))
    assert len(rows) == 5 and not any('2026-11-13' in row['id'] for row in rows)


@pytest.mark.parametrize('url', [
    'https://irp.cdn-website.com/another/dms3rep/multi/flyer.jpg',
    'https://irp.cdn-website.com/34057905/dms3rep/multi/%2e%2e/flyer.jpg',
    'https://irp.cdn-website.com/34057905/dms3rep/multi/a%2Fflyer.jpg',
    'https://irp.cdn-website.com/34057905/dms3rep/multi/flyer.jpg?redirect=1',
    'https://irp.cdn-website.com:443/34057905/dms3rep/multi/flyer.jpg',
])
def test_image_scope_rejects_other_accounts_traversal_and_queries(url):
    assert hall.photo_url(url) is None


def test_unapproved_image_does_not_block_an_event_or_trigger_a_fetch():
    payload = FIXTURE.read_text().replace(
        'https://irp.cdn-website.com/34057905/dms3rep/multi/Frozen+Logo-4fb10a6c.jpg',
        'https://example.com/flyer.jpg')
    fetch = Mock(return_value=payload)
    rows = hall.collect(SOURCE, fetch, now=NOW)
    assert len(rows) == 6 and all('image_url' not in row for row in rows[:3])
    fetch.assert_called_once_with(hall.CALENDAR, 'text/html')


@pytest.mark.parametrize(('field', 'value'), [('feed_url', hall.CALENDAR + '/'), ('kind', 'json'),
                                            ('source_key', 'other'), ('timezone', 'UTC')])
def test_exact_source_tuple_checked_before_network(field, value):
    fetch = Mock()
    with pytest.raises(ValueError, match='unregistered_mcgregor_source'):
        hall.collect({**SOURCE, field: value}, fetch, now=NOW)
    fetch.assert_not_called()


def test_deadline_and_transport_denial_preserved_without_retry():
    fetch = Mock()
    with pytest.raises(ValueError, match='collection_deadline'):
        hall.collect(SOURCE, fetch, now=NOW, deadline_at=-1)
    fetch.assert_not_called()
    failure = preview_worker.PreviewError('robots_denied')
    fetch.side_effect = failure
    with pytest.raises(preview_worker.PreviewError) as result:
        hall.collect(SOURCE, fetch, now=NOW)
    assert result.value is failure and fetch.call_count == 1

