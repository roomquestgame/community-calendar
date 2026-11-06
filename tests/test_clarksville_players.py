"""Reviewed performance facts, year evidence, omissions and durable identities."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

from bs4 import BeautifulSoup
import pytest

from roomquest import preview_worker
from roomquest import clarksville_players as parser

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


def home():
    return BeautifulSoup(fixture('players_home.html'), 'html.parser')


def steel(soup):
    return next(card for card in soup.select('[data-ux="ContentCard"]')
                if 'Steel Magnolias' in card.get_text())


def description(card):
    return card.select_one('[data-aid^="CONTENT_DESCRIPTION"][data-aid$="_RENDERED"]')


def parse(body=None, article=None, diagnostics=None, now=NOW):
    return parser.parse(str(body) if body is not None else fixture('players_home.html'),
                        article if article is not None else fixture('players_auditions.html'),
                        now=now, diagnostics=diagnostics)


def test_real_show_has_three_separate_performances_unknown_ends_and_actual_artwork():
    rows = parse()
    assert len(rows) == 3 and len({r['id'] for r in rows}) == 3
    assert [r['starts_at'] for r in rows] == [
        '2026-11-14T00:30:00+00:00', '2026-11-15T00:30:00+00:00', '2026-11-15T19:30:00+00:00']
    for row in rows:
        assert row['title'] == 'Steel Magnolias'
        assert row['ends_at'] is None and row['lat'] is None and row['lng'] is None
        assert row['venue_address'] == parser.THEATER_ADDRESS
        assert row['venue_name'] == 'Clarksville Fine Arts Center'
        assert row['timezone'] == 'America/New_York'
        assert row['event_url'] == row['details_evidence_url'] == parser.CALENDAR
        assert row['image_evidence_url'] == parser.CALENDAR
        assert row['image_provenance'] == 'publisher_event_candidates_v1'
        assert '/a33c590a-25e0-4bb6-979e-3d018e2af1b1/Steel%20Magnolias.jpg/' in row['image_url']
        assert '2026' in row['description'] and len(row['description']) <= 2000
        assert 'image_verified_at' not in row
        assert row['publisher_details']['registration'].endswith('https://clarksvilleplayers.ludus.com/')


def test_missing_year_evidence_is_held_without_current_year_guess():
    diagnostic = {}
    assert parse(article='<p>No production date evidence.</p>', diagnostics=diagnostic) == []
    assert diagnostic['held']


def test_conflicting_year_or_weekday_is_held():
    assert parse(article=fixture('players_auditions.html').replace('2026', '2027')) == []
    soup = home()
    node = description(steel(soup))
    node.clear()
    node.append('Friday, November 14th @ 7:30pm')
    diagnostic = {}
    assert not parse(soup, diagnostics=diagnostic)
    assert any(r['reason'] == 'publisher_schedule_conflict' for r in diagnostic['held'])


def test_responsive_duplicate_does_not_duplicate_occurrences_or_change_ids():
    original = parse()
    soup = home()
    steel(soup).parent.append(deepcopy(steel(soup)))
    assert parse(soup) == original
    assert {r['id'] for r in parse(fixture('players_home.html').replace('7:30pm', '7:30 pm'))} == {r['id'] for r in original}


def test_venue_requires_same_production_evidence_without_business_geo_fallback():
    diagnostic = {}
    article = fixture('players_auditions.html').replace('914', '999')
    assert parse(article=article, diagnostics=diagnostic) == []
    assert any(r['reason'] == 'event_venue_unreviewed' for r in diagnostic['held'])


@pytest.mark.parametrize('status', ['Cancelled', 'Postponed'])
def test_explicit_status_retains_occurrence_when_venue_disappears(status):
    soup = home()
    heading = steel(soup).select_one('[data-aid^="CONTENT_HEADLINE"][data-aid$="_RENDERED"]')
    heading.string = status + ': Steel Magnolias'
    rows = parse(soup, article=fixture('players_auditions.html').replace('914', '999'))
    assert len(rows) == 3
    assert {r['id'] for r in rows} == {r['id'] for r in parse()}
    assert all(r['publisher_status'] == status.lower() for r in rows)
    assert all(not r['venue_address'] for r in rows)


def test_parsing_uses_full_card_before_bounding_output_description():
    soup = home()
    node = description(steel(soup))
    node.insert(0, 'Publisher background. ' * 150)
    rows = parse(soup)
    assert len(rows) == 3 and all(len(r['description']) <= 2000 for r in rows)
    node.append(' Private event.')
    assert parse(soup) == []


def test_status_evidence_keeps_exact_past_start_without_fabricating_an_end():
    soup = home()
    heading = steel(soup).select_one('[data-aid^="CONTENT_HEADLINE"][data-aid$="_RENDERED"]')
    heading.string = 'Cancelled: Steel Magnolias'
    rows = parse(soup, article=fixture('players_auditions.html').replace('914', '999'),
                 now=datetime(2026, 11, 15, 1, 30, tzinfo=timezone.utc))
    assert len(rows) == 3
    assert rows[0]['starts_at'] == '2026-11-14T00:30:00+00:00'
    assert rows[0]['ends_at'] is None and not rows[0]['venue_address']
    assert rows[0]['publisher_status'] == 'cancelled'
    assert {r['id'] for r in rows} == {r['id'] for r in parse()}


def test_unreviewed_artwork_stays_valid_no_image():
    soup = home()
    for image in steel(soup).select('img'):
        image['src'] = 'https://other.example/unrelated.jpg'
    rows = parse(soup)
    assert len(rows) == 3 and all('image_url' not in r for r in rows)
    assert all(r['image_extractor_version'] == 'publisher_event_candidates_v1' for r in rows)


def test_known_end_policy_retains_ongoing_and_expires_unknown_end_at_three_hours():
    start = datetime(2026, 11, 14, 0, 30, tzinfo=timezone.utc)
    assert len(parse(now=start + timedelta(hours=2))) == 3
    assert len(parse(now=start + timedelta(hours=3))) == 2


def test_unknown_pagination_and_card_cap_fail_the_snapshot():
    soup = home()
    section = steel(soup).find_parent('section')
    node = soup.new_tag('a', rel='next', href='/page/2')
    section.append(node)
    with pytest.raises(ValueError, match='pagination'):
        parse(soup)
    soup = home()
    card = steel(soup)
    for _ in range(parser.MAX_CARDS):
        card.parent.append(deepcopy(card))
    with pytest.raises(ValueError, match='record_limit'):
        parse(soup)


@pytest.mark.parametrize('field,value', [
    ('source_key', 'unrelated'), ('feed_url', parser.CALENDAR + '?crawl=all'),
    ('kind', 'json'), ('platform_adapter', 'jsonld'), ('timezone', 'UTC'),
])
def test_source_identity_fails_before_fetch(field, value):
    fetch = Mock()
    with pytest.raises(ValueError, match='unregistered'):
        parser.collect(dict(SOURCE, **{field: value}), fetch, now=NOW)
    fetch.assert_not_called()


def test_collect_only_uses_reviewed_pages_and_does_not_succeed_after_partial_fetch():
    pages = {parser.CALENDAR: fixture('players_home.html'),
             parser.AUDITIONS: fixture('players_auditions.html')}
    fetch = Mock(side_effect=lambda url, accept: pages[url])
    assert len(parser.collect(SOURCE, fetch, now=NOW)) == 3
    assert [c.args[0] for c in fetch.call_args_list] == [parser.CALENDAR, parser.AUDITIONS]
    failed = Mock(side_effect=[pages[parser.CALENDAR], OSError('unavailable')])
    with pytest.raises(OSError):
        parser.collect(SOURCE, failed, now=NOW)
    expired = Mock()
    with pytest.raises(ValueError, match='collection_deadline'):
        parser.collect(SOURCE, expired, deadline_at=0, now=NOW)
    expired.assert_not_called()

