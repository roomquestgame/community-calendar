"""TEC visible local clocks, event-specific venue evidence and complete fetches."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from unittest.mock import Mock

from bs4 import BeautifulSoup
import pytest

from roomquest import vance_arts as arts, preview_worker

NOW = datetime(2026, 11, 10, 10, tzinfo=timezone.utc)
ROOT = Path(__file__).parent / 'fixtures/south_hill_expansion'
CONCERT = 'https://vanceartscouncil.com/event/tidings-of-comfort-and-joy-2026/'
PARADE = 'https://vanceartscouncil.com/event/henderson-nc-christmas-parade-2026/'
SOURCE = {'source_key': arts.SOURCE_KEY, 'feed_url': arts.CALENDAR,
          'kind': 'html', 'platform_adapter': 'html', 'timezone': arts.TIMEZONE}


@pytest.fixture(autouse=True)
def stable_test_clock(monkeypatch):
    monkeypatch.setattr(preview_worker, '_future_datetime', lambda value: value.astimezone(timezone.utc))


def pages():
    return {arts.CALENDAR: (ROOT / 'vance-events.html').read_text(),
            CONCERT: (ROOT / 'vance-concert.html').read_text(),
            PARADE: (ROOT / 'vance-parade.html').read_text()}


def change_json(payload, function):
    soup = BeautifulSoup(payload, 'html.parser')
    script = soup.select_one('script[type="application/ld+json"]')
    data = json.loads(script.string)
    function(data)
    script.string = json.dumps(data)
    return str(soup)


def collect(documents=None):
    documents = documents or pages()
    fetch = Mock(side_effect=lambda url, accept: documents[url])
    return arts.collect(SOURCE, fetch, now=NOW), fetch


def test_actual_concert_uses_printed_local_time_and_parade_stays_held(capsys):
    rows, fetch = collect()
    assert len(rows) == 1
    row = rows[0]
    assert row['id'] == 'vance_arts:1314'
    assert row['starts_at'] == '2026-11-28T21:00:00+00:00'
    assert row['ends_at'] == '2026-11-29T00:00:00+00:00'
    assert row['timezone'] == 'America/New_York'
    assert row['venue_address'] == '201 Breckenridge Street, Henderson, NC 27536'
    assert row['lat'] is None and row['lng'] is None
    assert row['publisher_details'] == {'cost': 'Free'}
    assert row['image_url'] == 'https://vanceartscouncil.com/wp-content/uploads/2026/10/tidings-of-comfort-and-joy-2025-16.jpg'
    assert row['details_evidence_url'] == row['image_evidence_url'] == CONCERT
    assert 'annual Tidings of Comfort' in row['description']
    assert [call.args for call in fetch.call_args_list] == [
        (arts.CALENDAR, 'text/html'), (CONCERT, 'text/html'), (PARADE, 'text/html')]
    diagnostics = capsys.readouterr().err
    assert 'publisher_utc_default_visible_local_verified' in diagnostics
    assert '"id": "vance_arts:1484"' in diagnostics and 'event_venue_unreviewed' in diagnostics


@pytest.mark.parametrize('value', ['2026-11-28T15:00:00+00:00', '2026-11-28T16:00:00-06:00',
                                  '2026-11-28T16:00:00', '2026-11-29T16:00:00+00:00'])
def test_different_day_clock_or_unreviewed_offset_is_held_not_reinterpreted(value, capsys):
    docs = pages()
    docs[arts.CALENDAR] = change_json(docs[arts.CALENDAR], lambda rows: rows[0].update(startDate=value))
    with pytest.raises(ValueError, match='vance_event_evidence_unavailable'):
        collect(docs)
    assert 'publisher_schedule_conflict' in capsys.readouterr().err


def test_listing_and_detail_local_clocks_must_agree(capsys):
    docs = pages()
    docs[CONCERT] = docs[CONCERT].replace('November 28, 2026 @ 4:00 pm', 'November 28, 2026 @ 4:30 pm')
    with pytest.raises(ValueError, match='vance_event_evidence_unavailable'):
        collect(docs)
    assert 'publisher_schedule_conflict' in capsys.readouterr().err


def test_office_mailing_lineup_and_footer_addresses_never_fill_missing_venue():
    docs = pages()
    docs[PARADE] = docs[PARADE].replace('207 N. Garnett Street', '999 Other Street')
    rows, _ = collect(docs)
    assert [row['id'] for row in rows] == ['vance_arts:1314']


def test_venue_disagreement_between_detail_metadata_and_structured_event_is_held(capsys):
    docs = pages()
    docs[CONCERT] = change_json(docs[CONCERT], lambda rows: rows[0]['location']['address'].update(streetAddress='110 Young Street'))
    with pytest.raises(ValueError, match='vance_event_evidence_unavailable'):
        collect(docs)
    assert 'publisher_venue_conflict' in capsys.readouterr().err


def test_missing_description_remains_optional():
    docs = pages()
    soup = BeautifulSoup(docs[CONCERT], 'html.parser')
    soup.select_one('.tribe-events-single-event-description').decompose()
    docs[CONCERT] = str(soup)
    rows, _ = collect(docs)
    assert len(rows) == 1 and rows[0]['description'] == ''


def test_publisher_explicit_status_survives_without_cancellation_from_absence():
    docs = pages()
    for url in (arts.CALENDAR, CONCERT):
        docs[url] = change_json(docs[url], lambda rows: rows[0].update(eventStatus='https://schema.org/EventCancelled'))
    rows, _ = collect(docs)
    assert len(rows) == 1 and rows[0]['publisher_status'] == 'cancelled'


def test_private_event_never_becomes_a_public_candidate(capsys):
    docs = pages()
    docs[CONCERT] = docs[CONCERT].replace('Admission is free.', 'Private event. Invitation only.')
    with pytest.raises(ValueError, match='vance_event_evidence_unavailable'):
        collect(docs)
    assert 'nonpublic_event' in capsys.readouterr().err


def test_bad_image_is_omitted_without_external_network():
    docs = pages()
    for url in (arts.CALENDAR, CONCERT):
        docs[url] = change_json(docs[url], lambda rows: rows[0].update(image='https://other.example/flyer.jpg'))
    rows, fetch = collect(docs)
    assert len(rows) == 1 and 'image_url' not in rows[0]
    assert fetch.call_count == 3


def test_active_next_page_blocks_incomplete_snapshot_before_detail_fetch():
    docs = pages()
    soup = BeautifulSoup(docs[arts.CALENDAR], 'html.parser')
    del soup.select_one('.tribe-events-c-nav__next')['disabled']
    docs[arts.CALENDAR] = str(soup)
    fetch = Mock(side_effect=lambda url, accept: docs[url])
    with pytest.raises(ValueError, match='vance_pagination_requires_review'):
        arts.collect(SOURCE, fetch, now=NOW)
    assert fetch.call_count == 1


@pytest.mark.parametrize('mutation', [
    lambda text: text.replace('post-1484', 'post-1314'),
    lambda text: text.replace(PARADE, 'https://127.0.0.1/event/secret/'),
    lambda text: text.replace('tribe-events-view--list', 'tribe-events-view--unknown'),
])
def test_listing_identity_and_structure_failures_are_not_silently_skipped(mutation):
    docs = pages()
    docs[arts.CALENDAR] = mutation(docs[arts.CALENDAR])
    with pytest.raises(ValueError):
        collect(docs)


def test_unaccounted_structured_event_rejects_snapshot():
    docs = pages()
    def add(data):
        extra = deepcopy(data[0])
        extra['url'] = 'https://vanceartscouncil.com/event/extra/'
        data.append(extra)
    docs[arts.CALENDAR] = change_json(docs[arts.CALENDAR], add)
    with pytest.raises(ValueError, match='vance_manifest_mismatch'):
        collect(docs)


def test_detail_post_identity_must_match_the_listed_publisher_id():
    docs = pages()
    docs[CONCERT] = docs[CONCERT].replace('postid-1314', 'postid-1315')
    with pytest.raises(ValueError, match='vance_event_detail_mismatch'):
        collect(docs)


def test_late_detail_transport_failure_does_not_expose_earlier_success():
    docs = pages()
    error = preview_worker.PreviewError('publisher_http_403')
    def fetcher(url, accept):
        if url == PARADE:
            raise error
        return docs[url]
    fetch = Mock(side_effect=fetcher)
    with pytest.raises(preview_worker.PreviewError) as caught:
        arts.collect(SOURCE, fetch, now=NOW)
    assert caught.value is error and fetch.call_count == 3


@pytest.mark.parametrize(('field', 'value'), [('source_key', 'unrelated'), ('feed_url', arts.CALENDAR[:-1]),
                                            ('platform_adapter', 'wordpress'), ('timezone', 'UTC')])
def test_exact_source_binding_before_any_request(field, value):
    fetch = Mock()
    with pytest.raises(ValueError, match='unregistered_vance_source'):
        arts.collect({**SOURCE, field: value}, fetch, now=NOW)
    fetch.assert_not_called()


def test_expired_deadline_never_sends_a_request():
    fetch = Mock()
    with pytest.raises(ValueError, match='collection_deadline'):
        arts.collect(SOURCE, fetch, deadline_at=-1, now=NOW)
    fetch.assert_not_called()
