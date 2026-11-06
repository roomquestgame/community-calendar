"""Published pantry dates and the source-scoped public calendar-render callback."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from unittest.mock import Mock

from bs4 import BeautifulSoup
import pytest

from roomquest import good_shepherd as parser
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


def fixture(name):
    return (FIXTURES / (name + '.html')).read_text()


def calendar():
    return BeautifulSoup(fixture('good_calendar_rendered'), 'html.parser')


def pantry(soup, day='20261110'):
    return next(n for n in soup.select('li.event') if 'd' + day in n.get('class', [])
                and n.find(class_='title', recursive=False).get_text(' ', strip=True) == 'Food Pantry')


def parse(value=None, ministry=None, **kwargs):
    return parser.parse(str(value) if value is not None else fixture('good_calendar_rendered'),
                        str(ministry) if ministry is not None else fixture('good_pantry'),
                        now=kwargs.pop('now', NOW), **kwargs)


def normalize_counts(soup):
    for td in soup.select('td[data-events-count]'):
        td['data-events-count'] = str(len(td.select('li.event')))


def test_actual_calendar_has_eight_explicit_future_dates_and_no_inferred_january():
    diagnostics = {}
    rows = parse(diagnostics=diagnostics)
    assert [r['starts_at'] for r in rows] == [day + 'T15:30:00+00:00' for day in (
        '2026-11-10', '2026-11-17', '2026-11-24', '2026-12-01',
        '2026-12-08', '2026-12-15', '2026-12-22', '2026-12-29')]
    assert all(r['ends_at'] == r['starts_at'][:10] + 'T17:00:00+00:00' for r in rows)
    assert all(r['venue_address'] == '1664 N Mecklenburg Avenue, South Hill, VA 23970' for r in rows)
    assert all(r['lat'] is None and r['lng'] is None for r in rows)
    assert all(r['event_url'] == r['details_evidence_url'] == parser.CALENDAR for r in rows)
    assert all(r['publisher_categories'] == [] and r['category'] == '' for r in rows)
    assert all('cost' not in r['publisher_details'] and 'image_url' not in r for r in rows)
    assert all('anyone who needs food' in r['publisher_details']['audience'] for r in rows)
    assert all('emergency basis pantry' in r['description'] for r in rows)
    assert diagnostics == {'calendar_rows': 199, 'outside_window': 14, 'other_program_rows': 177}


def test_collect_uses_only_two_gets_and_exact_injected_read_only_render_tokens():
    pages = {parser.CALENDAR: fixture('good_calendar'), parser.MINISTRY: fixture('good_pantry')}
    fetch = Mock(side_effect=lambda url, accept: pages[url])
    render = Mock(return_value=fixture('good_calendar_rendered'))
    rows = parser.collect(SOURCE, fetch, render_calendar=render, now=NOW)
    assert rows == parse()
    assert [c.args for c in fetch.call_args_list] == [(parser.CALENDAR, 'text/html'), (parser.MINISTRY, 'text/html')]
    render.assert_called_once_with(nonce='0123456789', args='a' * 40)


def test_regenerated_render_dom_id_keeps_occurrences_and_exact_public_request_binding():
    evidence = json.loads((FIXTURES / 'good_calendar_dynamic_id_observation.json').read_text())
    assert evidence['observation']['placeholder_render_id_equal'] is False
    assert evidence['observation']['rendered_id_valid'] is True
    initial = fixture('good_calendar')
    request = parser.calendar_request(initial)
    # Synthetic distinct IDs reproduce the observed relationship; the live
    # diagnostic deliberately replaced the original IDs with stable labels.
    regenerated = fixture('good_calendar_rendered').replace(request['calendar_id'], 'r999999999999999')
    pages = {parser.CALENDAR: initial, parser.MINISTRY: fixture('good_pantry')}
    fetch = Mock(side_effect=lambda url, accept: pages[url])
    render = Mock(return_value=regenerated)
    assert parser.collect(SOURCE, fetch, render_calendar=render, now=NOW) == parse()
    assert [call.args for call in fetch.call_args_list] == [(parser.CALENDAR, 'text/html'), (parser.MINISTRY, 'text/html')]
    render.assert_called_once_with(nonce=request['nonce'], args=request['args'])


@pytest.mark.parametrize('damage,reason', [
    ('invalid_id', 'identity_unverified'), ('duplicate_calendar', 'render_structure'),
    ('root_only_changed', 'months_incomplete'), ('truncated_grid', 'grid_incomplete'),
    ('wrong_month', 'window_unverified'),
])
def test_regenerated_dom_id_does_not_accept_invalid_duplicated_or_incoherent_calendars(damage, reason):
    initial = fixture('good_calendar')
    old_id = parser.calendar_request(initial)['calendar_id']
    soup = BeautifulSoup(fixture('good_calendar_rendered').replace(old_id, 'r999999999999999'), 'html.parser')
    node = soup.select_one('.ics-calendar')
    if damage == 'invalid_id':
        node['id'] = 'unrelated-calendar'
    elif damage == 'duplicate_calendar':
        node.insert_after(deepcopy(node))
    elif damage == 'root_only_changed':
        node['id'] = 'raaaaaaaaaaaaaaa'
    elif damage == 'truncated_grid':
        soup.select('table.ics-calendar-month-grid')[3].select_one('td.d_10').decompose()
    else:
        soup.select_one('select.ics-calendar-select')['data-this-month'] = '202610'
    pages = {parser.CALENDAR: initial, parser.MINISTRY: fixture('good_pantry')}
    with pytest.raises(ValueError, match=reason):
        parser.collect(SOURCE, lambda url, accept: pages[url],
                       render_calendar=Mock(return_value=str(soup)), now=NOW)


@pytest.mark.parametrize('damage,reason', [
    ('wrong_canonical', 'page_identity'), ('duplicate_placeholder', 'structure_unverified'),
    ('invalid_placeholder_id', 'request_unverified'),
])
def test_wrong_discovery_identity_still_fails_before_render(damage, reason):
    soup = BeautifulSoup(fixture('good_calendar'), 'html.parser')
    if damage == 'wrong_canonical':
        soup.select_one('link[rel=canonical]')['href'] = parser.MINISTRY
    elif damage == 'duplicate_placeholder':
        node = soup.select_one('.r34ics-ajax-container')
        node.insert_after(deepcopy(node))
    else:
        soup.select_one('.r34ics-ajax-container')['id'] = 'unrelated-ajax'
    fetch, render = Mock(return_value=str(soup)), Mock()
    with pytest.raises(ValueError, match=reason):
        parser.collect(SOURCE, fetch, render_calendar=render, now=NOW)
    fetch.assert_called_once_with(parser.CALENDAR, 'text/html')
    render.assert_not_called()


@pytest.mark.parametrize('old,new', [
    ('https:\\/\\/goodshepherdsouthhill.org\\/wp-admin\\/admin-ajax.php', 'https:\\/\\/other.example\\/write'),
    ('0123456789', 'invalid-token'), ('a' * 40, 'bad'),
    ('"debug":false', '"debug":true'), ('data-view="month"', 'data-view="list"'),
    ('data-r34icsymd="20261106"', 'data-r34icsymd="20261140"'),
])
def test_changed_public_render_contract_is_rejected_before_post(old, new):
    payload = fixture('good_calendar')
    assert old in payload
    fetch, render = Mock(return_value=payload.replace(old, new)), Mock()
    with pytest.raises(ValueError, match='request_unverified'):
        parser.collect(SOURCE, fetch, render_calendar=render, now=NOW)
    assert fetch.call_count == 1
    render.assert_not_called()


@pytest.mark.parametrize('old,new,reason', [
    ('1664 N Mecklenburg Avenue', '1665 N Mecklenburg Avenue', 'venue_unreviewed'),
    ('open on Tuesdays 10:30-12:00', 'open on Tuesdays 9:30-12:00', 'hours_unreviewed'),
    ('for any parishioner or anyone who needs food.', 'for enrolled members.', 'audience_unverified'),
    ('Drops of Love Food Pantry', 'Unrelated Ministry', 'identity_unverified'),
])
def test_named_ministry_facts_do_not_become_a_generic_church_default(old, new, reason):
    payload = fixture('good_pantry')
    assert old in payload
    diagnostics = {}
    assert parse(ministry=payload.replace(old, new), diagnostics=diagnostics) == []
    assert len(diagnostics['held']) == 8
    assert all(reason in h['reason'] for h in diagnostics['held'])


@pytest.mark.parametrize('notice,reason', [
    ('Members only.', 'nonpublic_program'),
    ('Temporary new location: another building.', 'venue_unreviewed'),
    ('The pantry is closed for the holiday.', 'status_requires_review'),
])
def test_full_ministry_text_is_checked_before_narrative_truncation(notice, reason):
    soup = BeautifulSoup(fixture('good_pantry'), 'html.parser')
    main = soup.select_one('main .entry-content')
    main.append(' Background details. ' * 120)
    assert len(parse(ministry=soup)[0]['description']) == 2000
    main.append(notice)
    diagnostics = {}
    assert parse(ministry=soup, diagnostics=diagnostics) == []
    assert all(reason in h['reason'] for h in diagnostics['held'])


def test_after_mass_closure_and_unrecognized_pantry_titles_are_held():
    for title in ('Food Pantry after Mass', 'No Food Pantry', 'Food Pantry — Closed'):
        soup = calendar()
        pantry(soup).find(class_='title', recursive=False).string = title
        diagnostics = {}
        rows = parse(soup, diagnostics=diagnostics)
        assert len(rows) == 7 and diagnostics['held']
        assert all(r['starts_at'][:10] != '2026-11-10' for r in rows)


def test_one_ambiguous_occurrence_is_held_without_losing_other_good_dates():
    soup = calendar()
    pantry(soup).find(class_='time', recursive=False).string = 'After Mass'
    diagnostics = {}
    assert len(parse(soup, diagnostics=diagnostics)) == 7
    assert diagnostics['held'][0]['reason'] == 'pantry_occurrence_hours_conflict'
    assert diagnostics['held'][0]['id'] == parse()[0]['id']


def test_current_real_calendar_month_and_date_containers_must_agree():
    soup = calendar()
    pantry(soup)['class'] = ['event', 'd20261111', 't103000']
    diagnostics = {}
    assert len(parse(soup, diagnostics=diagnostics)) == 7
    assert diagnostics['held'][0]['reason'] == 'publisher_date_conflict'


def test_future_new_date_is_accepted_only_when_published_in_the_grid():
    soup = calendar()
    january = soup.select('table.ics-calendar-month-grid')[-1]
    td = january.select_one('td.d_05')
    assert td is not None and not td.select('li.event')
    ul = soup.new_tag('ul', attrs={'class': 'events', 'aria-labelledby': 'r0123456789abcdef-20270105'})
    entry = deepcopy(pantry(soup))
    entry['class'] = ['event', 'd20270105', 't103000']
    ul.append(entry)
    td.append(ul)
    td['data-events-count'] = '1'
    rows = parse(soup)
    assert len(rows) == 9 and rows[-1]['starts_at'] == '2027-01-05T15:30:00+00:00'
    assert len({r['id'] for r in rows}) == 9


@pytest.mark.parametrize('status', ['Cancelled', 'Postponed'])
def test_exact_status_keeps_identity_after_start_without_current_venue_or_end(status):
    soup = calendar()
    pantry(soup).find(class_='title', recursive=False).string = status + ': Food Pantry'
    ministry = fixture('good_pantry').replace('1664 N Mecklenburg Avenue', '')
    rows = parse(soup, ministry=ministry, now=datetime(2026, 11, 11, 17, tzinfo=timezone.utc))
    assert len(rows) == 1
    assert rows[0]['id'] == parse()[0]['id']
    assert rows[0]['publisher_status'] == status.lower()
    assert rows[0]['starts_at'] == '2026-11-10T15:30:00+00:00'
    assert rows[0]['ends_at'] is None and not rows[0]['venue_address']


def test_conflicting_duplicate_or_explicit_status_is_not_silently_selected():
    soup = calendar()
    entry = deepcopy(pantry(soup))
    entry.find(class_='title', recursive=False).string = 'Cancelled: Food Pantry'
    pantry(soup).insert_after(entry)
    normalize_counts(soup)
    with pytest.raises(ValueError, match='conflicting_occurrence'):
        parse(soup)
    soup = calendar()
    entry = pantry(soup)
    entry.find(class_='title', recursive=False).string = 'Cancelled: Food Pantry'
    p = soup.new_tag('p')
    p.string = 'Status: Postponed'
    entry.append(p)
    diagnostic = {}
    assert len(parse(soup, diagnostics=diagnostic)) == 7
    assert diagnostic['held'][0]['reason'] == 'publisher_status_conflict'


def test_render_failure_clipped_grid_or_stale_month_is_a_hard_failure():
    with pytest.raises(ValueError, match='render_structure'):
        parse('1')
    soup = calendar()
    pantry(soup).decompose()
    with pytest.raises(ValueError, match='rows_incomplete'):
        parse(soup)
    soup = calendar()
    soup.select('table.ics-calendar-month-grid')[-1].decompose()
    with pytest.raises(ValueError, match='months_incomplete'):
        parse(soup)
    with pytest.raises(ValueError, match='window_unverified'):
        parse(fixture('good_calendar_rendered').replace('data-this-month="202611"', 'data-this-month="202610"'))


@pytest.mark.parametrize('damage', ['whole_month_cells', 'one_day', 'day_label', 'weekday'])
def test_clipped_or_mislabeled_day_grid_never_returns_healthy_partial_rows(damage):
    soup = calendar()
    table = soup.select('table.ics-calendar-month-grid')[3]
    if damage == 'whole_month_cells':
        for td in list(table.select('td')):
            td.decompose()
    elif damage == 'one_day':
        table.select_one('td.d_10').decompose()
    elif damage == 'day_label':
        table.select_one('td.d_10 .phone_only')['id'] = 'r0123456789abcdef-20261111'
    else:
        table.select_one('td.d_10')['data-dow'] = '3'
    with pytest.raises(ValueError, match='grid_incomplete'):
        parse(soup)


def test_published_empty_future_pantry_scope_is_valid_without_generated_recurrence():
    soup = calendar()
    for entry in list(soup.select('li.event')):
        if entry.find(class_='title', recursive=False).get_text(' ', strip=True) == 'Food Pantry':
            entry.decompose()
    normalize_counts(soup)
    assert parse(soup) == []


def test_caps_and_unknown_pagination_fail():
    soup = calendar()
    entry = pantry(soup)
    for _ in range(parser.MAX_ROWS):
        entry.insert_after(deepcopy(entry))
    with pytest.raises(ValueError, match='record_limit'):
        parse(soup)
    soup = calendar()
    soup.select_one('.ics-calendar').append(soup.new_tag('a', rel='next', href='/next'))
    with pytest.raises(ValueError, match='identity_unverified'):
        parse(soup)
    with pytest.raises(ValueError, match='document_limit'):
        parse('x' * (parser.MAX_DOCUMENT + 1))


@pytest.mark.parametrize('field,value', [
    ('source_key', 'unrelated'), ('feed_url', parser.MINISTRY),
    ('kind', 'json'), ('platform_adapter', 'ical'), ('timezone', 'UTC'),
])
def test_wrong_source_fails_before_any_network_callback(field, value):
    fetch, render = Mock(), Mock()
    with pytest.raises(ValueError, match='unregistered'):
        parser.collect(dict(SOURCE, **{field: value}), fetch, render_calendar=render, now=NOW)
    fetch.assert_not_called()
    render.assert_not_called()


def test_deadline_or_render_network_failure_does_not_retry_or_return_empty(monkeypatch):
    clock = iter([0, 0, 0, 0, 30])
    monkeypatch.setattr(parser, 'monotonic', lambda: next(clock))
    fetch = Mock(return_value=fixture('good_calendar'))
    render = Mock(return_value=fixture('good_calendar_rendered'))
    with pytest.raises(ValueError, match='collection_deadline'):
        parser.collect(SOURCE, fetch, render_calendar=render, now=NOW)
    assert fetch.call_count == render.call_count == 1
    monkeypatch.setattr(parser, 'monotonic', lambda: 0)
    render = Mock(side_effect=preview_worker.PreviewError('publisher_http_403'))
    with pytest.raises(preview_worker.PreviewError, match='403'):
        parser.collect(SOURCE, fetch, render_calendar=render, now=NOW)
    assert render.call_count == 1


def test_all_held_scope_is_not_reported_as_a_healthy_empty():
    pages = {parser.CALENDAR: fixture('good_calendar'),
             parser.MINISTRY: fixture('good_pantry').replace('1664 N Mecklenburg Avenue', '')}
    with pytest.raises(ValueError, match='evidence_unavailable'):
        parser.collect(SOURCE, lambda url, accept: pages[url],
                       render_calendar=Mock(return_value=fixture('good_calendar_rendered')), now=NOW)
