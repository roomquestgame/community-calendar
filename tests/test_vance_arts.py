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


def collect(documents=None, *, source=SOURCE):
    documents = documents or pages()
    fetch = Mock(side_effect=lambda url, accept: documents[url])
    return arts.collect(source, fetch, now=NOW), fetch


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


def test_separate_organizer_mission_is_omitted_but_concert_family_invitation_remains():
    rows, _ = collect()
    description = rows[0]['description']
    assert arts._ORGANIZER_MISSION not in description
    assert 'a special way for families, friends and neighbors' in description
    assert 'Bring your family and friends' in description
    assert 'Admission is free.' in description
    assert 'McGregor Hall Performing Arts Center' in description


def test_actual_event_audience_fact_is_not_removed_by_keyword_filtering():
    docs = pages()
    soup = BeautifulSoup(docs[CONCERT], 'html.parser')
    paragraph = soup.new_tag('p')
    paragraph.string = 'This concert welcomes school-aged children and at-risk youth.'
    soup.select_one('.tribe-events-single-event-description').append(paragraph)
    docs[CONCERT] = str(soup)
    rows, _ = collect(docs)
    assert 'This concert welcomes school-aged children and at-risk youth.' in rows[0]['description']


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


def test_reviewed_parade_lineup_reference_is_disclosed_and_keeps_publisher_schedule(capsys):
    legacy, _ = collect()
    rows, fetch = collect(source={**SOURCE, 'venue_association_contract_version': 1})
    assert len(rows) == 2 and rows[0] == legacy[0]
    parade = rows[1]
    assert parade['id'] == 'vance_arts:1484' and parade['event_url'] == PARADE
    assert parade['starts_at'] == '2026-12-05T19:30:00+00:00'
    assert parade['ends_at'] == '2026-12-05T22:00:00+00:00'
    assert parade['venue_name'] == 'Downtown Henderson parade — Raleigh Road lineup reference'
    assert parade['venue_address'] == '391 Raleigh Road, Henderson, NC 27536'
    assert parade['lat'] is parade['lng'] is None
    assert parade['venue_association'] == {
        'method': arts.ASSOCIATION_METHOD,
        'evidence_urls': [PARADE, 'https://www.kerrlake-nc.com/dining'],
        'matched_activity': parade['title'], 'venue_name': parade['venue_name'],
        'venue_address': parade['venue_address']}
    assert parade['location_provenance'] == arts.ASSOCIATION_METHOD
    assert parade['description'].startswith('Venue inferred from')
    assert 'approximate parade-lineup reference near Burger King on Raleigh Road' in parade['description']
    assert 'ends on Rose Avenue. It is not a fixed event venue.' in parade['description']
    assert 'Spectator admission is listed as free' in parade['description']
    assert parade['publisher_details'] == {'cost': 'Free'}
    assert 'Standard entries: $55' in parade['description']
    assert parade['details_evidence_url'] == parade['image_evidence_url'] == PARADE
    assert fetch.call_count == 3
    assert '"event": "vance_inferred"' in capsys.readouterr().err


@pytest.mark.parametrize('version', [None, True, False, '1', 0, 2, 1.0])
def test_parade_association_requires_exact_backend_receipt_capability(version):
    rows, _ = collect(source={**SOURCE, 'venue_association_contract_version': version})
    assert [row['id'] for row in rows] == ['vance_arts:1314']


@pytest.mark.parametrize(('old', 'new'), [
    ('Raleigh Road near Burger King', 'Raleigh Road near another landmark'),
    ('will conclude on Rose Avenue', 'will conclude on another street'),
    ('The parade will conclude', 'The new route will conclude'),
    ('The holiday season is just around the corner', 'Venue: A different hall. The holiday season is just around the corner'),
    ('The holiday season is just around the corner', 'Location: 500 Another Street. The holiday season is just around the corner'),
    ('Henderson, NC Christmas Parade 2026', 'Henderson, NC Holiday Parade 2026'),
    ('post-1484', 'post-1485'),
])
def test_changed_route_landmark_title_or_identity_cannot_reuse_parade_association(old, new):
    docs = pages()
    for url in (arts.CALENDAR, PARADE):
        docs[url] = docs[url].replace(old, new)
    if old == 'post-1484':
        docs[PARADE] = docs[PARADE].replace('postid-1484', 'postid-1485')
    rows, _ = collect(docs, source={**SOURCE, 'venue_association_contract_version': 1})
    assert [row['id'] for row in rows] == ['vance_arts:1314']


def test_parade_association_does_not_override_partial_publisher_address():
    docs = pages()
    soup = BeautifulSoup(docs[PARADE], 'html.parser')
    tag = soup.new_tag('span', attrs={'class': 'tribe-street-address'})
    tag.string = '500 Another Street'
    soup.select_one('.tribe-events-meta-group-venue').append(tag)
    docs[PARADE] = str(soup)
    rows, _ = collect(docs, source={**SOURCE, 'venue_association_contract_version': 1})
    assert [row['id'] for row in rows] == ['vance_arts:1314']


@pytest.mark.parametrize('replacements', [
    [('December 5, 2026', 'December 6, 2026'), ('2026-12-05', '2026-12-06')],
    [('2:30 pm', '3:30 pm'), ('14:30:00', '15:30:00')],
    [('5:00 pm', '6:00 pm'), ('17:00:00', '18:00:00')],
])
def test_parade_association_is_bounded_to_reviewed_date_and_clocks(replacements):
    docs = pages()
    for url in (arts.CALENDAR, PARADE):
        for old, new in replacements:
            docs[url] = docs[url].replace(old, new)
    rows, _ = collect(docs, source={**SOURCE, 'venue_association_contract_version': 1})
    assert [row['id'] for row in rows] == ['vance_arts:1314']


def test_explicit_complete_publisher_venue_takes_precedence_over_lineup_reference():
    docs = pages()
    soup = BeautifulSoup(docs[PARADE], 'html.parser')
    group = soup.select_one('.tribe-events-meta-group-venue')
    for css, value in [('tribe-street-address', '500 Another Street'), ('tribe-locality', 'Henderson'),
                       ('tribe-region', 'NC'), ('tribe-postal-code', '27536')]:
        tag = soup.new_tag('span', attrs={'class': css})
        tag.string = value
        group.append(tag)
    docs[PARADE] = change_json(str(soup), lambda rows: rows[0]['location']['address'].update(
        streetAddress='500 Another Street', addressLocality='Henderson', addressRegion='NC', postalCode='27536'))
    rows, _ = collect(docs, source={**SOURCE, 'venue_association_contract_version': 1})
    parade = rows[1]
    assert parade['venue_address'] == '500 Another Street, Henderson, NC 27536'
    assert 'venue_association' not in parade and 'Venue inferred from' not in parade['description']
    assert parade['location_provenance'] == 'publisher_event_address_pending_geocode'


@pytest.mark.parametrize('url', [arts.CALENDAR, PARADE])
def test_inferred_parade_point_cannot_authorize_utc_schedule_repair(url):
    docs = pages()
    def utc(rows):
        item = next(row for row in rows if row['url'] == PARADE)
        item['startDate'] = '2026-12-05T14:30:00+00:00'
        item['endDate'] = '2026-12-05T17:00:00+00:00'
    docs[url] = change_json(docs[url], utc)
    rows, _ = collect(docs, source={**SOURCE, 'venue_association_contract_version': 1})
    assert [row['id'] for row in rows] == ['vance_arts:1314']


def test_parade_free_admission_disclosure_tracks_current_cost_not_old_review():
    docs = pages()
    soup = BeautifulSoup(docs[PARADE], 'html.parser')
    soup.select_one('.tribe-events-event-cost').string = '$10'
    docs[PARADE] = str(soup)
    rows, _ = collect(docs, source={**SOURCE, 'venue_association_contract_version': 1})
    assert rows[1]['publisher_details'] == {'cost': '$10'}
    assert 'Spectator admission is listed as free' not in rows[1]['description']
