"""The actual maintained class schedule, without guessed holiday years."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from bs4 import BeautifulSoup
import pytest

from roomquest import coopers_landing as parser
from roomquest import preview_worker

FIXTURES = Path(__file__).with_name('fixtures') / 'mecklenburg_batch3'
NOW = datetime(2026, 11, 6, 16, tzinfo=timezone.utc)
SOURCE = {'source_key': parser.SOURCE_KEY, 'feed_url': parser.CALENDAR, 'kind': 'html',
          'platform_adapter': 'html', 'timezone': parser.TIMEZONE}


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


def fixture():
    return (FIXTURES / 'cooper_classes.html').read_text()


def page():
    return BeautifulSoup(fixture(), 'html.parser')


def card(soup):
    return next(p for p in soup.select('#content-aa > p') if 'Mon. Dec. 7th' in p.get_text())


def parse(value=None, **kwargs):
    return parser.parse(str(value) if value is not None else fixture(), now=kwargs.pop('now', NOW), **kwargs)


def test_actual_class_retains_year_time_venue_price_registration_and_no_image():
    diagnostics = {}
    rows = parse(diagnostics=diagnostics)
    assert len(rows) == 1
    row = rows[0]
    assert row['starts_at'] == '2026-12-07T23:30:00+00:00'
    assert row['ends_at'] == '2026-12-08T01:30:00+00:00'
    assert row['venue_address'] == '801 Virginia Avenue, Clarksville, VA 23927'
    assert row['venue_name'] == "Cooper's Landing Inn Cooking School"
    assert row['id'] == 'coopers_landing:cb71c1d9204aa4fc9190668698b5d680'
    assert row['lat'] is None and row['lng'] is None
    assert row['event_url'] == row['details_evidence_url'] == parser.CALENDAR
    assert row['publisher_details']['cost'] == '$85 per person plus taxes.'
    assert 'charged in full' in row['publisher_details']['registration']
    assert '6:00 Wine & Cheese reception' in row['description']
    assert 'reserves the right to cancel' in row['description']
    assert 'publisher_status' not in row
    assert row['publisher_categories'] == [] and row['category'] == ''
    assert 'image_url' not in row and 'image_verified_at' not in row
    assert row['image_extractor_version'] == 'publisher_event_candidates_v1'
    assert diagnostics['schedule_cards'] == 10
    assert len(diagnostics['excluded']) == 5 and diagnostics['outside_window'] == 4


def test_collect_uses_one_injected_html_get_only():
    fetch = Mock(return_value=fixture())
    assert parser.collect(SOURCE, fetch, now=NOW) == parse()
    fetch.assert_called_once_with(parser.CALENDAR, 'text/html')


@pytest.mark.parametrize('old,new,reason', [
    ('2026 Classes', 'Classes', 'year_unresolved'),
    ('Mon. Dec. 7th', 'Mon. Dec. 7th 2027', 'year_unresolved'),
    ('Mon. Dec. 7th', 'Mon. Dec. 8th', 'schedule_conflict'),
    ('Mon. Dec. 7th', 'Mon. Invalid. 7th', 'date_unresolved'),
    ('6:30 class begins', '7:30 class begins', 'time_conflict'),
    ('6:30 class begins', 'Evening class begins', 'time_unresolved'),
    ('6:00 Wine &amp; Cheese reception', '7:00 Wine &amp; Cheese reception', 'time_conflict'),
    ('801 Virginia Avenue', '802 Virginia Avenue', 'venue_unreviewed'),
])
def test_missing_or_conflicting_facts_are_held(old, new, reason):
    diagnostics = {}
    assert parse(fixture().replace(old, new), diagnostics=diagnostics) == []
    assert any(reason in row['reason'] for row in diagnostics['held'])


def test_program_duration_conflict_is_not_silently_used():
    diagnostics = {}
    assert parse(fixture().replace('6:30 – 8:30', '6:30 – 9:30'), diagnostics=diagnostics) == []
    assert diagnostics['held'][0]['reason'] == 'publisher_time_conflict'


def test_future_refresh_discovers_a_new_year_and_class_without_generated_recurrence():
    soup = page()
    heading = next(n for n in soup.select('.menuitem') if 'Monday Night Evening' in n.get_text()).parent
    year = BeautifulSoup('<p><span class="menuitem">2027 Classes</span></p>', 'html.parser').p
    new = BeautifulSoup(str(card(soup)).replace('Mon. Dec. 7th', 'Mon. Jan. 4th')
                        .replace('Holiday Entertaining &amp; Heavy Hors d’oeuvres', 'Winter Soups'), 'html.parser').p
    heading.insert_before(year)
    heading.insert_before(new)
    rows = parse(soup)
    assert len(rows) == 2
    assert rows[1]['starts_at'] == '2027-01-04T23:30:00+00:00'
    assert 'Winter Soups' in rows[1]['title']
    assert rows[0]['id'] != rows[1]['id']


def test_unknown_end_is_preserved_when_published_range_is_removed():
    text = fixture().replace('All Monday night classes will be held from 6:30 – 8:30.', '')
    rows = parse(text)
    assert len(rows) == 1 and rows[0]['ends_at'] is None
    assert rows[0]['starts_at'] == parse()[0]['starts_at']


@pytest.mark.parametrize('notice,disposition', [
    ('Private class.', 'excluded'), ('Members only.', 'excluded'),
    ('Location: Other Room; 99 Another Street, Clarksville, VA 23927.', 'held'),
])
def test_full_card_text_is_checked_before_description_truncation(notice, disposition):
    soup = page()
    card(soup).append(' Publisher background. ' * 120)
    assert len(parse(soup)[0]['description']) == 2000
    card(soup).append(notice)
    diagnostics = {}
    assert parse(soup, diagnostics=diagnostics) == []
    assert diagnostics[disposition]


@pytest.mark.parametrize('status', ['Cancelled', 'Postponed'])
def test_exact_dated_status_survives_missing_venue_and_end_after_start(status):
    soup = page()
    card(soup).strong.string = status + ': Monday Night Local Cooking Class'
    soup.select_one('#widgetbody').decompose()
    text = str(soup).replace('All Monday night classes will be held from 6:30 – 8:30.', '')
    rows = parse(text, now=datetime(2026, 12, 9, 1, tzinfo=timezone.utc))
    assert len(rows) == 1
    assert rows[0]['id'] == parse()[0]['id']
    assert rows[0]['publisher_status'] == status.lower()
    assert rows[0]['starts_at'] == parse()[0]['starts_at']
    assert rows[0]['ends_at'] is None and rows[0]['venue_address'] == ''


def test_cancellation_with_retained_exact_date_time_survives_missing_program_details():
    soup = page()
    card(soup).strong.string = 'Cancelled: Monday Night Local Cooking Class'
    card(soup).em.decompose()
    soup.select_one('#widgetbody').decompose()
    heading = next(n for n in soup.select('.menuitem') if 'Monday Night Evening' in n.get_text()).parent
    for node in list(heading.find_next_siblings()):
        node.decompose()
    heading.decompose()
    rows = parse(soup)
    assert len(rows) == 1 and rows[0]['id'] == parse()[0]['id']
    assert rows[0]['publisher_status'] == 'cancelled' and rows[0]['ends_at'] is None
    assert rows[0]['title'] == 'Monday Night Local Cooking Class'


def test_duplicate_date_conflict_fails_instead_of_succeeding_partially():
    soup = page()
    copy = deepcopy(card(soup))
    copy.em.string = 'Topic: “A different class”'
    card(soup).insert_after(copy)
    with pytest.raises(ValueError, match='conflicting_occurrence'):
        parse(soup)


def test_malformed_structure_caps_and_pagination_fail():
    with pytest.raises(ValueError, match='structure_unverified'):
        parse('<html>unavailable</html>')
    soup = page()
    soup.select_one('#content-aa').append(soup.new_tag('a', rel='next', href='/?page=2'))
    with pytest.raises(ValueError, match='pagination'):
        parse(soup)
    soup = page()
    for _ in range(parser.MAX_CARDS):
        card(soup).insert_after(deepcopy(card(soup)))
    with pytest.raises(ValueError, match='record_limit'):
        parse(soup)
    with pytest.raises(ValueError, match='document_limit'):
        parse('x' * (parser.MAX_DOCUMENT + 1))


@pytest.mark.parametrize('field,value', [
    ('source_key', 'unrelated'), ('feed_url', 'https://cooperslandinginn.net/?page_id=99'),
    ('kind', 'json'), ('platform_adapter', 'wordpress'), ('timezone', 'UTC'),
])
def test_wrong_source_fails_before_any_fetch(field, value):
    fetch = Mock()
    with pytest.raises(ValueError, match='unregistered'):
        parser.collect(dict(SOURCE, **{field: value}), fetch, now=NOW)
    fetch.assert_not_called()


def test_deadline_and_all_held_are_failures_but_expired_catalog_is_empty(monkeypatch):
    clock = iter([0, 0, 20])
    monkeypatch.setattr(parser, 'monotonic', lambda: next(clock))
    fetch = Mock(return_value=fixture())
    with pytest.raises(ValueError, match='collection_deadline'):
        parser.collect(SOURCE, fetch, now=NOW)
    assert fetch.call_count == 1
    monkeypatch.setattr(parser, 'monotonic', lambda: 0)
    with pytest.raises(ValueError, match='evidence_unavailable'):
        parser.collect(SOURCE, Mock(return_value=fixture().replace('2026 Classes', 'Classes')), now=NOW)
    assert parse(now=datetime(2026, 12, 31, tzinfo=timezone.utc)) == []
