"""Publisher facts, refresh durability and strict supplementary completeness."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from roomquest import preview_worker, revize, south_hill_markets as markets

FIXTURES = Path(__file__).parent / 'fixtures/south_hill_markets'
NOW = datetime(2026, 11, 10, 14, tzinfo=timezone.utc)
LISTING = (FIXTURES / 'market_listing.html').read_text()
OPEN_TEXT = (FIXTURES / 'open_house_2026.txt').read_text()
HOME_TEXT = (FIXTURES / 'hometown_2026.txt').read_text()
OPEN_URL = 'https://www.southhillva.gov/Christmas%20Open%20House%202026.pdf?t=202609031321470'
HOME_URL = 'https://www.southhillva.gov/Christmas%20Application%202026.pdf?t=202609031323400'
SOURCE = {'source_key': revize.SOURCE_KEY, 'feed_url': revize.FEED_URL,
          'kind': 'json', 'platform_adapter': 'revize', 'timezone': revize.TIMEZONE}


def freeze(monkeypatch, value):
    actual = datetime

    class Meta(type):
        def __instancecheck__(cls, item):
            return isinstance(item, actual)

    class Clock(actual, metaclass=Meta):
        @classmethod
        def now(cls, tz=None):
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    monkeypatch.setattr(preview_worker, 'datetime', Clock)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    freeze(monkeypatch, NOW)


def pdf_bytes(*texts, encrypt=False):
    """Synthetic PDF container; actual publisher text excerpts are separate."""
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({
        NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/Helvetica')}))
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject('/Resources')] = DictionaryObject({
            NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        lines = []
        for line in text.splitlines():
            value = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            lines.append(f'({value}) Tj T*')
        stream = DecodedStreamObject()
        stream.set_data(('BT /F1 9 Tf 12 TL 36 750 Td\n' + '\n'.join(lines) + '\nET').encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    if encrypt:
        writer.encrypt('private')
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def parse(text=OPEN_TEXT, url=OPEN_URL, now=NOW):
    return markets.parse_text(text, document_url=url, now=now)


def test_two_publisher_forms_have_correct_dates_venues_and_no_admission_price():
    first, second = parse(), parse(HOME_TEXT, HOME_URL)
    assert first['id'] == 'south_hill_market:christmas_open_house:2026-11-21'
    assert second['id'] == 'south_hill_market:hometown_christmas_market:2026-12-05'
    assert (first['starts_at'], first['ends_at']) == ('2026-11-21T14:00:00+00:00', '2026-11-21T19:00:00+00:00')
    assert (second['starts_at'], second['ends_at']) == ('2026-12-05T14:00:00+00:00', '2026-12-05T19:00:00+00:00')
    assert first['venue_name'] == 'South Hill Town Square'
    assert second['venue_name'] == 'The Exchange Warehouse'
    assert first['venue_address'] == '105 W Danville Street, South Hill, VA'
    assert second['venue_address'] == '408 W Danville Street, South Hill, VA'
    for row in (first, second):
        assert row['event_url'] == row['details_evidence_url'] == markets.CALENDAR
        assert row['publisher_details'] == {}
        assert '$25' not in row['description'] and 'free' not in row['description'].lower()
        assert 'Name:' not in row['description']
        assert row['lat'] is None and row['lng'] is None
        assert 'image_url' not in row and 'publisher_status' not in row
        assert row['timezone'] == 'America/New_York'


def test_discovery_is_from_current_document_links_only():
    assert markets.discover(LISTING, now=NOW) == [HOME_URL, OPEN_URL]
    assert markets.discover(LISTING.replace('%20', ' '), now=NOW) == [HOME_URL, OPEN_URL]
    assert markets.discover(LISTING.replace('2026', '2025'), now=NOW) == []
    empty = '<h2>Farmers Market</h2><h2>Document Center</h2><p>Every Saturday from May through October.</p>'
    assert markets.discover(empty, now=NOW) == []


def test_actual_pdf_reader_and_shared_fetch_contract_produce_bounded_evidence(capsys):
    calls = []
    first_pdf, second_pdf = pdf_bytes(OPEN_TEXT), pdf_bytes(HOME_TEXT)
    payloads = {markets.CALENDAR: LISTING, OPEN_URL: first_pdf, HOME_URL: second_pdf}

    def fetch(url, accept):
        calls.append((url, accept))
        return payloads[url]

    rows = markets.collect(SOURCE, fetch, now=NOW)
    assert len(rows) == 2
    assert calls == [(markets.CALENDAR, 'text/html'), (HOME_URL, 'application/pdf'), (OPEN_URL, 'application/pdf')]
    assert rows[0]['publisher_document'] == {
        'url': OPEN_URL, 'sha256': sha256(first_pdf).hexdigest(),
        'date_provenance': 'publisher_explicit_year'}
    log = capsys.readouterr().err
    assert 'south_hill_market_normalized' in log and '"documents": 2' in log and '"records": 2' in log


@pytest.mark.parametrize('fixture,url,source_id', [
    ('open_house_2026.pdf', OPEN_URL, 'south_hill_market:christmas_open_house:2026-11-21'),
    ('hometown_2026.pdf', HOME_URL, 'south_hill_market:hometown_christmas_market:2026-12-05'),
])
def test_original_publisher_pdf_bytes_match_receipt_and_extract(fixture, url, source_id):
    evidence = json.loads((FIXTURES / 'evidence.json').read_text())
    document = next(item for item in evidence['documents'] if item['pdf_fixture'] == fixture)
    payload = (FIXTURES / fixture).read_bytes()
    assert len(payload) == document['pdf_bytes']
    assert sha256(payload).hexdigest() == document['pdf_sha256']
    row = markets.parse_pdf(payload, document_url=url, now=NOW)
    assert row['id'] == source_id
    assert row['publisher_document']['sha256'] == document['pdf_sha256']
    assert row['publisher_details'] == {} and '$25' not in row['description']


def test_original_document_link_markup_with_unescaped_spaces_is_supported():
    html = (FIXTURES / 'market_links_capture.html').read_text()
    assert 'Christmas Open House 2026.pdf?' in html
    assert markets.discover(html, now=NOW) == [HOME_URL, OPEN_URL]


def test_unknown_or_yearless_market_label_cannot_silently_become_healthy_zero():
    html = LISTING.replace('>Christmas Open House 2026<', '>Christmas Open House<')
    with pytest.raises(ValueError, match='document_label_unresolved'):
        markets.discover(html, now=NOW)


def test_document_limit_is_checked_before_fetch():
    links = ''.join(f'<a href="Christmas%20Open%20House%202026.pdf?t=2026090313214{i:02d}">'
                    'Christmas Open House 2026</a>' for i in range(5))
    html = '<h2>Farmers Market</h2><h2>Document Center</h2>' + links
    with pytest.raises(ValueError, match='document_limit'):
        markets.discover(html, now=NOW)


def test_later_year_documents_work_without_changing_collector_constants(monkeypatch):
    current = datetime(2027, 11, 10, 14, tzinfo=timezone.utc)
    freeze(monkeypatch, current)
    text = OPEN_TEXT.replace('2026', '2027').replace('November 21', 'November 20')
    url = OPEN_URL.replace('House%202026', 'House%202027')
    listing = LISTING.replace('2026', '2027')
    assert len(markets.discover(listing, now=current)) == 2
    row = parse(text, url, current)
    assert row['id'] == 'south_hill_market:christmas_open_house:2027-11-20'
    assert row['starts_at'] == '2027-11-20T14:00:00+00:00'


def test_start_time_and_cache_query_edits_keep_occurrence_identity():
    before = parse()
    after = parse(OPEN_TEXT.replace('9\na.m.', '10\na.m.'), OPEN_URL.replace('1321470', '9999999'))
    assert after['id'] == before['id']
    assert after['starts_at'] == '2026-11-21T15:00:00+00:00'


def test_owner_earlier_explicit_same_date_conflict_rule(capsys):
    row = parse(OPEN_TEXT.replace('from 9-2.', 'from 10 a.m. to 3 p.m.'))
    assert row['starts_at'] == '2026-11-21T14:00:00+00:00'
    assert row['ends_at'] == '2026-11-21T19:00:00+00:00'
    assert 'earlier_explicit_same_date_time_selected' in capsys.readouterr().err


@pytest.mark.parametrize('text,reason', [
    (OPEN_TEXT.replace('9\na.m. to 2 p.m.', '9-2'), 'time_unresolved'),
    (OPEN_TEXT.replace('November 21, 2026', 'November 21'), 'date_conflict'),
    (OPEN_TEXT.replace('Saturday, November 21', 'Friday, November 21'), 'weekday_conflict'),
    (OPEN_TEXT.replace('November 21, 2026', 'November 21, 2027'), 'weekday_conflict'),
    (OPEN_TEXT.replace('November 21, 2026, from', 'November 22, 2026, from'), 'date_conflict'),
    (OPEN_TEXT.replace('9\na.m. to 2 p.m.', '9 p.m. to 2 p.m.'), 'time_conflict'),
    (OPEN_TEXT.replace('South Hill Town Square at 105 W Danville Street', 'Town office'), 'address_unresolved'),
    (OPEN_TEXT + '\nThis event has been cancelled.', 'status_unresolved'),
    (OPEN_TEXT + '\nPrivate event.', 'status_unresolved'),
])
def test_unresolved_facts_are_held_not_guessed(text, reason):
    with pytest.raises(ValueError, match=reason):
        parse(text)


def test_explicit_street_change_is_preserved_and_conflict_is_held():
    row = parse(OPEN_TEXT.replace('105 W Danville Street', '106 W Danville Street'))
    assert row['venue_address'] == '106 W Danville Street, South Hill, VA'
    with pytest.raises(ValueError, match='address_unresolved'):
        parse(OPEN_TEXT + '\nSouth Hill Town Square at 999 W Danville Street.')


def test_ongoing_retained_until_actual_end_and_past_never_rolls_year(monkeypatch):
    current = datetime(2026, 11, 21, 18, 55, tzinfo=timezone.utc)
    freeze(monkeypatch, current)
    assert parse(now=current) is not None
    assert parse(now=datetime(2026, 11, 21, 19, tzinfo=timezone.utc)) is None
    current = datetime(2027, 11, 10, 14, tzinfo=timezone.utc)
    freeze(monkeypatch, current)
    assert parse(now=current) is None


def test_horizon_is_bounded(monkeypatch):
    current = datetime(2026, 9, 1, 14, tzinfo=timezone.utc)
    freeze(monkeypatch, current)
    assert parse(now=current) is None


@pytest.mark.parametrize('url', [
    OPEN_URL.replace('www.southhillva.gov', 'evil.example'),
    OPEN_URL.replace('https:', 'http:'),
    OPEN_URL + '&callback=anything', OPEN_URL + '#fragment',
    OPEN_URL.replace('www.southhillva.gov', 'user@www.southhillva.gov'),
    OPEN_URL.replace('www.southhillva.gov', 'www.southhillva.gov:443'),
    OPEN_URL.replace('Christmas%20', 'Christmas%2520'),
])
def test_document_host_path_and_query_are_closed(url):
    assert markets.document_identity(url) is None
    bad = LISTING.replace('Christmas%20Open%20House%202026.pdf?t=202609031321470', url)
    with pytest.raises(ValueError, match='document_identity_mismatch'):
        markets.discover(bad, now=NOW)


@pytest.mark.parametrize('field,value', [
    ('source_key', 'another_source'), ('feed_url', markets.CALENDAR),
    ('kind', 'html'), ('platform_adapter', 'html'), ('timezone', 'UTC'),
])
def test_exact_existing_source_required_before_network(field, value):
    source = {**SOURCE, field: value}
    with pytest.raises(ValueError, match='unregistered_south_hill_market_source'):
        markets.collect(source, lambda *_: pytest.fail('must not fetch'), now=NOW)


def test_partial_pdf_failure_never_returns_partial_supplement(capsys):
    def fetch(url, accept):
        if url == markets.CALENDAR:
            return LISTING
        return pdf_bytes(HOME_TEXT) if url == HOME_URL else b'<html>blocked</html>'

    with pytest.raises(ValueError, match='invalid_south_hill_market_pdf'):
        markets.collect(SOURCE, fetch, now=NOW)
    log = capsys.readouterr().err
    assert 'south_hill_market_held' in log and revize.SOURCE_KEY in log
    assert 'south_hill_market_normalized' not in log


def test_publisher_rejection_is_preserved_without_retry(capsys):
    calls = []

    def fetch(url, accept):
        calls.append(url)
        if url == markets.CALENDAR:
            return LISTING
        raise preview_worker.PreviewError('publisher_http_403')

    with pytest.raises(preview_worker.PreviewError, match='publisher_http_403'):
        markets.collect(SOURCE, fetch, now=NOW)
    assert calls == [markets.CALENDAR, HOME_URL]
    assert 'publisher_http_403' in capsys.readouterr().err


@pytest.mark.parametrize('payload,reason', [
    (b'%PDF-broken', 'invalid_south_hill_market_pdf'),
    (b'%PDF-' + b'x' * markets.MAX_PDF, 'invalid_south_hill_market_pdf'),
    (pdf_bytes(''), 'pdf_text_unavailable'),
    (pdf_bytes(OPEN_TEXT, OPEN_TEXT, OPEN_TEXT, OPEN_TEXT), 'pdf_page_limit'),
    (pdf_bytes(OPEN_TEXT, encrypt=True), 'pdf_encrypted'),
])
def test_pdf_size_pages_encryption_and_text_are_bounded(payload, reason):
    with pytest.raises(ValueError, match=reason):
        markets.parse_pdf(payload, document_url=OPEN_URL, now=NOW)


def test_deadline_prevents_network(monkeypatch):
    monkeypatch.setattr(markets, 'monotonic', lambda: 10)
    with pytest.raises(ValueError, match='collection_deadline'):
        markets.collect(SOURCE, lambda *_: pytest.fail('must not fetch'), deadline_at=10, now=NOW)


def test_deadline_after_document_fetch_prevents_parse(monkeypatch):
    tick = [0]
    monkeypatch.setattr(markets, 'monotonic', lambda: tick[0])

    def fetch(url, accept):
        if url == markets.CALENDAR:
            return LISTING
        tick[0] = 25
        return pdf_bytes(HOME_TEXT)

    with pytest.raises(ValueError, match='collection_deadline'):
        markets.collect(SOURCE, fetch, deadline_at=24, now=NOW)


def test_shared_preview_preserves_existing_revize_occurrences_and_source(monkeypatch):
    captured = (Path(__file__).parent / 'fixtures/south_hill/town_20261106.json').read_text()
    ordinary = revize.parse(captured, now=NOW)
    before = deepcopy(ordinary)
    calls = []
    payloads = {
        revize.FEED_URL: captured,
        markets.CALENDAR: (FIXTURES / 'market_links_capture.html').read_text(),
        OPEN_URL: (FIXTURES / 'open_house_2026.pdf').read_bytes(),
        HOME_URL: (FIXTURES / 'hometown_2026.pdf').read_bytes(),
    }

    def fetch(url, accept, **policy):
        assert policy['respect_robots'] is True
        assert policy['allowed_hosts'] == ('www.southhillva.gov',)
        assert policy['deadline_at'] is not None
        calls.append((url, accept))
        return payloads[url]

    monkeypatch.setattr(preview_worker, 'fetch_publisher', fetch)
    result = preview_worker.preview_source({**SOURCE, 'south_hill_market_contract_version': 1})
    combined = result['p_events']
    supplemental = [row for row in combined if row['id'].startswith('south_hill_market:')]
    assert ordinary == before
    assert len(supplemental) == 2 and result['p_future_count'] == len(before) + 2
    assert {row['id'] for row in ordinary}.isdisjoint({row['id'] for row in supplemental})
    assert all(row in combined for row in before)
    assert any(row['id'] == 'revize:72__20261204T230000Z' for row in combined)
    assert result['p_source_key'] == revize.SOURCE_KEY
    assert result['p_parser_capability'] == 'publisher_event_candidates_v1'
    assert len(calls) == 4
