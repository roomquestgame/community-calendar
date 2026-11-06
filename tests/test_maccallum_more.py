"""Dated event-card discovery and actual publisher facts without default venues."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from bs4 import BeautifulSoup
import pytest

from roomquest import preview_worker
from roomquest import maccallum_more as parser

FIXTURES = Path(__file__).with_name('fixtures') / 'mecklenburg_batch2'
NOW = datetime(2026, 11, 6, 13, tzinfo=timezone.utc)
SOURCE = {'source_key': parser.SOURCE_KEY, 'feed_url': parser.CALENDAR,
          'kind': 'html', 'platform_adapter': 'html', 'timezone': parser.TIMEZONE}


class ClockMeta(type):
    def __instancecheck__(cls, value):
        return isinstance(value, datetime)


class FrozenDatetime(datetime, metaclass=ClockMeta):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def fixed_normalizer_clock(monkeypatch):
    monkeypatch.setattr(preview_worker, 'datetime', FrozenDatetime)


def fixture(name):
    return (FIXTURES / name).read_text()


def cards():
    return parser.discover(fixture('maccallum_home.html'))


def event_card(slug='grand-illumination'):
    return next(c for c in cards() if c['url'].endswith('/' + slug))


def detail():
    return BeautifulSoup(fixture('maccallum_grand_illumination.html'), 'html.parser')


def set_field(soup, field, value):
    node = next(n for n in soup.select('li') if n.get_text(' ', strip=True).lower().startswith(field.lower() + ':'))
    node.clear()
    node.append(field + ': ' + value)


def parse(body=None, card=None, diagnostics=None, now=NOW):
    return parser.parse_event(str(body) if body is not None else fixture('maccallum_grand_illumination.html'),
                              card or event_card(), now=now, diagnostics=diagnostics)


def test_real_event_uses_explicit_year_actual_address_free_facts_and_card_image():
    row = parse()
    assert row['starts_at'] == '2026-12-11T23:00:00+00:00'
    assert row['ends_at'] is None and row['lat'] is None and row['lng'] is None
    assert row['venue_address'] == '603 Hudgins Street, Chase City, VA 23924'
    assert row['venue_name'] == 'MacCallum More Museum & Gardens'
    assert row['event_url'] == row['details_evidence_url'] == event_card()['url']
    assert row['image_evidence_url'] == parser.CALENDAR
    assert row['image_url'] == event_card()['image']
    assert row['image_provenance'] == 'publisher_event_candidates_v1'
    assert row['publisher_details']['cost'] == 'FREE'
    assert row['publisher_details']['audience'] == 'Everyone is welcome.'
    assert 'outdoor event' in row['description']
    assert len(row['description']) <= 2000 and 'image_verified_at' not in row


def test_actual_catalog_discovery_collects_every_visible_card_and_excludes_sales():
    assert {c['url'].rsplit('/', 1)[1] for c in cards()} == {
        'grand-illumination', 'juried-art-show', 'porch-goose-raffle'}
    pages = {parser.CALENDAR: fixture('maccallum_home.html')}
    for card in cards():
        pages[card['url']] = fixture('maccallum_' + card['url'].rsplit('/', 1)[1].replace('-', '_') + '.html')
    fetch = Mock(side_effect=lambda url, accept: pages[url])
    rows = parser.collect(SOURCE, fetch, now=NOW)
    assert len(rows) == 1 and rows[0] == parse()
    assert len(fetch.call_args_list) == 4
    assert {c.args[0] for c in fetch.call_args_list} == set(pages)


@pytest.mark.parametrize('field,value', [
    ('Date', 'December 11'), ('Time', 'Evening'), ('Time', '6:00 PM – 5:00 PM'),
    ('Address', ''), ('Location', ''),
])
def test_ambiguous_date_time_or_venue_is_held(field, value):
    soup = detail()
    set_field(soup, field, value)
    diagnostic = {}
    assert parse(soup, diagnostics=diagnostic) is None
    assert diagnostic['held']


def test_conflicting_intro_and_details_or_title_year_is_held():
    soup = detail()
    set_field(soup, 'Time', '7:00 PM')
    diagnostic = {}
    assert parse(soup, diagnostics=diagnostic) is None
    assert diagnostic['held']
    soup = detail()
    soup.select_one('h1.main-page-title').string = 'Grand Illumination 2027'
    assert parse(soup) is None


@pytest.mark.parametrize('status', ['Cancelled', 'Postponed'])
def test_explicit_same_occurrence_status_survives_missing_venue(status):
    soup = detail()
    soup.select_one('h1.main-page-title').string = status + ': Grand Illumination 2026'
    set_field(soup, 'Address', '')
    set_field(soup, 'Location', '')
    row = parse(soup)
    assert row['publisher_status'] == status.lower()
    assert row['id'] == parse()['id'] and row['starts_at'] == parse()['starts_at']
    assert not row['venue_address']


def test_card_content_is_validated_before_description_is_truncated():
    soup = detail()
    body = soup.select_one('h1.main-page-title').find_next_sibling('div', class_='rte')
    body.insert(0, 'Publisher background. ' * 150)
    row = parse(soup)
    assert row is not None and len(row['description']) <= 2000
    body.append(' Private event.')
    diagnostic = {}
    assert parse(soup, diagnostics=diagnostic) is None
    assert diagnostic['excluded']


def test_status_evidence_retains_the_published_start_after_the_unknown_end_fallback():
    soup = detail()
    soup.select_one('h1.main-page-title').string = 'Cancelled: Grand Illumination 2026'
    set_field(soup, 'Address', '')
    set_field(soup, 'Location', '')
    row = parse(soup, now=datetime(2026, 12, 13, 0, tzinfo=timezone.utc))
    assert row['starts_at'] == '2026-12-11T23:00:00+00:00'
    assert row['ends_at'] is None and not row['venue_address']
    assert row['publisher_status'] == 'cancelled' and row['id'] == parse()['id']


def test_missing_or_unreviewed_image_is_valid_no_image_without_generic_substitution():
    for value in (None, 'https://other.example/image.jpg',
                  event_card()['image'] + '&redirect=https://other.example'):
        card = dict(event_card(), image=value)
        row = parse(card=card)
        assert row is not None and 'image_url' not in row
        assert row['image_extractor_version'] == 'publisher_event_candidates_v1'


def test_unlinked_page_identity_and_unsafe_card_links_are_rejected():
    with pytest.raises(ValueError, match='identity_conflict'):
        parse(card=dict(event_card(), title='Unrelated production'))
    for url in ('https://other.example/pages/event', '/pages/grand-illumination?x=1',
                '/pages/../admin', 'https://user@maccallummore.org/pages/grand-illumination'):
        with pytest.raises(ValueError, match='url_unverified'):
            parser.event_url(url)


def test_listing_pagination_caps_and_duplicate_conflicts_fail():
    soup = BeautifulSoup(fixture('maccallum_home.html'), 'html.parser')
    card = soup.select_one('.multicolumn-card')
    card.append(soup.new_tag('a', rel='next', href='/pages/next'))
    with pytest.raises(ValueError, match='pagination'):
        parser.discover(str(soup))
    soup = BeautifulSoup(fixture('maccallum_home.html'), 'html.parser')
    card = soup.select_one('.multicolumn-card')
    for _ in range(parser.MAX_DETAIL_PAGES):
        card.parent.append(deepcopy(card))
    with pytest.raises(ValueError, match='page_limit'):
        parser.discover(str(soup))


@pytest.mark.parametrize('field,value', [
    ('source_key', 'unrelated'), ('feed_url', parser.CALENDAR + '?crawl=all'),
    ('kind', 'json'), ('platform_adapter', 'jsonld'), ('timezone', 'UTC'),
])
def test_source_identity_fails_before_fetch(field, value):
    fetch = Mock()
    with pytest.raises(ValueError, match='unregistered'):
        parser.collect(dict(SOURCE, **{field: value}), fetch, now=NOW)
    fetch.assert_not_called()


def test_partial_fetch_and_expired_budget_never_return_healthy_empty():
    fetch = Mock(side_effect=[fixture('maccallum_home.html'), OSError('unavailable')])
    with pytest.raises(OSError):
        parser.collect(SOURCE, fetch, now=NOW)
    expired = Mock()
    with pytest.raises(ValueError, match='collection_deadline'):
        parser.collect(SOURCE, expired, deadline_at=0, now=NOW)
    expired.assert_not_called()

