"""Native schedule, full-narrative and complete-capture boundaries."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
from unittest.mock import Mock, patch
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import pytest

from roomquest import raleigh_direct_community as c


NOW = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)
LONG_BODY = 'Complete café workshop instructions. ' * 100 + 'Keep <this instruction>. Final condition.'


def source(key):
    return dict(source_key=key, feed_url=c.SOURCES[key][0], kind='html',
                platform_adapter='html', timezone=c.ZONE)


def preview(title, start, end, venue, street, city, url, identity, *args, **kwargs):
    return dict(id=identity, title=title, starts_at=start, ends_at=end, venue_name=venue,
                venue_address=street, venue_city=city, event_url=url, lat=None, lng=None)


def goodnights(*, body=None, clock='Tue Nov 17 2026, 07:00 PM', address='401 Woodburn Rd', name='Live comedy'):
    event = {'@type': 'Event', 'name': name, 'url': 'https://www.goodnightscomedy.com/shows/123',
             'startDate': '2026-11-18T00:00:00Z', 'description': body if body is not None else '<p>Full performer biography.</p>',
             'location': {'address': {'streetAddress': address, 'addressLocality': 'Raleigh', 'addressRegion': 'NC'}}}
    clock_markup = '<span class="event-date">' + clock + '</span>' if clock else ''
    return ('<script type="application/ld+json">' + json.dumps({'@type': 'Place', 'Events': [event]}) + '</script>'
            '<div class="event-list-item"><h2 class="el-header">' + name + '</h2><div class="el-showtimes">'
            + clock_markup + '<a href="/shows/123">Tickets</a></div></div>')


def fair(body='The Raleigh Market is open from 9am-5pm.', days='Every Saturday and Sunday', title='The Raleigh Market'):
    result = '<h1>2026 NC State Fair Event Calendar</h1>'
    for month in c.MONTHS:
        result += '<h2>' + month.title() + '</h2><table>'
        if month == 'november':
            result += '<tr><td>' + days + '</td><td><strong>' + title + '</strong><p>' + body + '</p></td><td>Outside Grounds</td></tr>'
        result += '</table>'
    return result


def square_card(number):
    start = NOW.replace(hour=18) + timedelta(days=number)
    end = start + timedelta(hours=2)
    query = urlencode({'action': 'TEMPLATE', 'dates': start.strftime('%Y%m%dT%H%M%SZ') + '/' + end.strftime('%Y%m%dT%H%M%SZ')})
    url = c.SOURCES[c.OGK][0] + '/' + str(number)
    card = ('<article class="eventlist-event--upcoming"><a class="eventlist-title-link" href="' + url + '">Cook together</a>'
            '<a class="eventlist-meta-export-google" href="https://www.google.com/calendar/event?' + query + '">Export</a></article>')
    schema = {'@type': 'Event', 'startDate': start.isoformat(), 'endDate': end.isoformat()}
    detail = ('<script type="application/ld+json">' + json.dumps(schema) + '</script><article class="eventitem">'
              '<h1 class="eventitem-title">Cook together</h1><div class="eventitem-column-content">'
              '<p>Prepare meals for neighbors. Meet at 225 South Wilmington Street.</p>'
              '<p>' + LONG_BODY.replace('<', '&lt;').replace('>', '&gt;') + '</p></div></article>')
    return card, url, detail


def game_page():
    return '<iframe src="/GT_WebCalendar.html"></iframe>'


def game_frame():
    return "const SUPABASE_URL = 'https://" + c.GAME_API_HOST + "'; const SUPABASE_KEY = 'sb_publishable_" + 'a'*24 + "'; client.from('events');"


def game_event(**change):
    return dict(id='game-1', title='TCG tournament', description='Full tournament rules.', store_location='Raleigh',
                start_time='2026-11-17T18:00:00-05:00', end_time='2026-11-17T21:00:00-05:00', **change)


@patch.object(c, 'record', side_effect=preview)
def test_goodnights_keeps_every_native_show_and_complete_description(_):
    markup = '<p>' + LONG_BODY.replace('<', '&lt;').replace('>', '&gt;') + '</p>'
    chunk = c.collect_chunk(source(c.GOODNIGHTS), Mock(return_value=goodnights(body=markup)), now=NOW)
    assert chunk['complete'] and len(chunk['events']) == 1
    row = chunk['events'][0]
    assert row['description'] == LONG_BODY and len(row['description']) > 2000
    assert row['venue_address'] == c.VENUES[c.GOODNIGHTS][1]
    assert row['lat'] is None and row['lng'] is None
    replay = c.collect_chunk(source(c.GOODNIGHTS), Mock(side_effect=AssertionError('no refetch')), checkpoint=chunk['checkpoint'], now=NOW)
    assert replay['events'] == chunk['events']
    # A multi-show card can omit a visible individual clock; the explicit
    # publisher Event instances remain authoritative.
    assert len(c._goodnights(goodnights(clock=None), NOW, [])) == 1


@pytest.mark.parametrize('kwargs,reason', [({'clock': 'Tue Nov 17 2026, 08:00 PM'}, 'schedule_conflict'),
    ({'address': '500 Another Road'}, 'venue_unresolved'), ({'body': ''}, 'description_missing'),
    ({'body': 'x'*12001}, 'description_limit'), ({'name': 'Private event'}, 'nonpublic')])
def test_goodnights_holds_conflicts_blanks_and_private_events(kwargs, reason):
    diagnostics = []
    assert c._goodnights(goodnights(**kwargs), NOW, diagnostics) == []
    assert diagnostics[0]['reason'] == 'raleigh_direct_' + reason


@patch.object(c, 'record', side_effect=preview)
def test_fair_published_month_recurrence_and_full_building_address(_):
    rows = c._fair(fair(), NOW, [])
    assert len(rows) == 5
    assert all(datetime.fromisoformat(r['starts_at']).weekday() in (5, 6) for r in rows)
    assert all(r['starts_at'].startswith('2026-11-') for r in rows)
    assert all('Outside Grounds' in r['venue_name'] and r['venue_address'] == c.VENUES[c.FAIR][1] for r in rows)
    assert len({r['id'] for r in rows}) == len(rows)


def test_fair_ambiguous_times_are_held_and_weekdays_select_their_own_clocks():
    diagnostics = []
    assert c._fair(fair(body='Event Time Saturday 9-5. Admission $10.', days='21', title='Show'), NOW, diagnostics) == []
    assert diagnostics[0]['reason'] == 'raleigh_direct_schedule_missing'
    text = 'Event Time Saturday 9am-5pm. Sunday 10am-4pm. Admission $10.'
    assert c._fair_times(date(2026, 11, 21), text)[0].hour == 9
    assert c._fair_times(date(2026, 11, 22), text)[0].hour == 10
    with pytest.raises(ValueError, match='calendar_changed'):
        c._fair(fair().replace('2026 NC State Fair', 'Unknown State Fair'), NOW, [])


def fair_months(rows, year=2026):
    html = '<h1>' + str(year) + ' NC State Fair Event Calendar</h1>'
    for month, number in c.MONTHS.items():
        html += '<h2>' + month.title() + '</h2><table>'
        for days, title, body, venue in rows.get(number, []):
            html += ('<tr><td>' + days + '</td><td><strong>' + title + '</strong><p>'
                     + body + '</p></td><td>' + venue + '</td></tr>')
        html += '</table>'
    return html


@pytest.mark.parametrize('label,expected', [
    ('Every Saturday', [21, 28]),
    ('Every Monday, Wednesday and Friday', [16, 18, 20, 23, 25, 27, 30]),
    ('Every Tuesday & Thursday', [17, 19, 24, 26]),
    ('Every Saturday, and Sunday', [15, 21, 22, 28, 29]),
])
@patch.object(c, 'record', side_effect=preview)
def test_fair_explicit_weekdays_remain_inside_the_published_month(_, label, expected):
    rows = c._fair(fair(days=label), NOW, [])
    assert [datetime.fromisoformat(r['starts_at']).day for r in rows] == expected
    assert all(r['starts_at'].startswith('2026-11-') for r in rows)
    assert all(datetime.fromisoformat(r['starts_at']).hour == 9 for r in rows)


@pytest.mark.parametrize('label', ['Every first and third Saturday', 'Every other Saturday',
    'Every Saturday-Sunday', 'Every weekday', 'Every Sat', 'Every Saturday or Sunday'])
def test_fair_relative_ordinal_and_nonlisted_recurrence_is_held(label):
    diagnostics = []
    assert c._fair(fair(days=label), NOW, diagnostics) == []
    assert diagnostics[0]['reason'] == 'raleigh_direct_schedule_missing'


@pytest.mark.parametrize('closed', [
    'CLOSED November 21st and November 22nd',
    'CLOSED 11/21, 11/22',
    'CLOSED on Saturday Nov. 21, 2026, and Sunday Nov. 22, 2026',
])
@patch.object(c, 'record', side_effect=preview)
def test_fair_explicit_closures_remove_dates_without_changing_open_hours(_, closed):
    diagnostics = []
    rows = c._fair(fair(body='The Raleigh Market is open 9am-5pm. ' + closed), NOW, diagnostics)
    assert [datetime.fromisoformat(r['starts_at']).day for r in rows] == [15, 28, 29]
    assert all(datetime.fromisoformat(r['starts_at']).hour == 9 for r in rows)
    assert all(datetime.fromisoformat(r['ends_at']).hour == 17 for r in rows)
    assert len(diagnostics) == 2
    assert {d['reason'] for d in diagnostics} == {'raleigh_direct_nonpublic'}
    assert all(closed in r['description'] for r in rows)


@patch.object(c, 'record', side_effect=preview)
def test_fair_previous_month_closure_applies_to_same_series_in_later_month(_):
    markup = fair_months({
        1: [('Every Saturday and Sunday', 'The Raleigh Market',
             'The Raleigh Market is open 9am-5pm.</p><p>+++THE RALEIGH MARKET WILL BE CLOSED JAN 31ST /FEB 1ST+++', 'Outside Grounds')],
        2: [('Every Saturday and Sunday', 'The Raleigh Market', 'The Raleigh Market is open 9am-5pm.', 'Outside Grounds')],
    })
    diagnostics = []
    rows = c._fair(markup, datetime(2026, 2, 1, 12, tzinfo=timezone.utc), diagnostics)
    assert [datetime.fromisoformat(r['starts_at']).date() for r in rows] == [
        date(2026, 2, d) for d in (7, 8, 14, 15, 21, 22, 28)]
    assert len(diagnostics) == 1 and diagnostics[0]['reason'] == 'raleigh_direct_nonpublic'


@patch.object(c, 'record', side_effect=preview)
def test_fair_exact_closure_remains_evidence_when_earlier_recurrence_is_unsupported(_):
    markup = fair_months({
        1: [('Every first and third Saturday', 'The Raleigh Market',
             'The Raleigh Market is open 9am-5pm. CLOSED February 1', 'Outside Grounds')],
        2: [('Every Sunday', 'The Raleigh Market', 'The Raleigh Market is open 9am-5pm.', 'Outside Grounds')],
    })
    rows = c._fair(markup, datetime(2026, 2, 1, 12, tzinfo=timezone.utc), [])
    assert [datetime.fromisoformat(r['starts_at']).date() for r in rows] == [date(2026, 2, d) for d in (8, 15, 22)]


@patch.object(c, 'record', side_effect=preview)
def test_fair_closures_do_not_cross_native_title_or_venue_keys(_):
    rows = c._fair(fair_months({11: [
        ('Every Saturday', 'The Raleigh Market', 'The Raleigh Market is open 9am-5pm. CLOSED November 21', 'Outside Grounds'),
        ('Every Saturday', 'A Different Market', 'Event Time 9am-5pm.', 'Outside Grounds'),
        ('Every Saturday', 'The Raleigh Market', 'The Raleigh Market is open 9am-5pm.', 'Jim Graham Building'),
    ]}), NOW, [])
    assert len(rows) == 5
    on_closed_day = [r for r in rows if datetime.fromisoformat(r['starts_at']).day == 21]
    assert len(on_closed_day) == 2
    assert not any(r['title'] == 'The Raleigh Market' and r['venue_name'].startswith('Outside Grounds') for r in on_closed_day)


@pytest.mark.parametrize('note', ['CLOSED for the holiday', 'MAY BE CLOSED November 21',
    'NOT CLOSED November 21', 'CLOSED November 21-22', 'CLOSED 11/31',
    'CLOSED Saturday November 22', 'CLOSED November 21, 2027', 'Except the first Saturday'])
def test_fair_unresolved_closure_note_holds_the_same_series_even_from_an_earlier_month(note):
    markup = fair_months({
        1: [('Every Saturday', 'The Raleigh Market', 'The Raleigh Market is open 9am-5pm. ' + note, 'Outside Grounds')],
        11: [('Every Saturday', 'The Raleigh Market', 'The Raleigh Market is open 9am-5pm.', 'Outside Grounds')],
    })
    diagnostics = []
    assert c._fair(markup, NOW, diagnostics) == []
    assert diagnostics[0]['reason'] == 'raleigh_direct_schedule_conflict'


@patch.object(c, 'record', side_effect=preview)
def test_fair_closure_note_before_the_clock_does_not_become_a_clock_selector(_):
    rows = c._fair(fair(body='CLOSED November 21.</p><p>The Raleigh Market is open 9am-5pm.'), NOW, [])
    assert [datetime.fromisoformat(r['starts_at']).day for r in rows] == [15, 22, 28, 29]


@patch.object(c, 'record', side_effect=preview)
def test_fair_published_year_is_not_rolled_forward_at_the_window_boundary(_):
    markup = fair_months({12: [('Every Saturday', 'The Raleigh Market',
        'The Raleigh Market is open 9am-5pm. CLOSED January 31 / February 1', 'Outside Grounds')]})
    rows = c._fair(markup, datetime(2026, 12, 1, 12, tzinfo=timezone.utc), [])
    assert [datetime.fromisoformat(r['starts_at']).date() for r in rows] == [date(2026, 12, d) for d in (5, 12, 19, 26)]
    assert c._fair(markup, datetime(2027, 1, 1, 12, tzinfo=timezone.utc), []) == []


def test_fair_recurrence_keeps_existing_clock_and_venue_gates():
    diagnostics = []
    assert c._fair(fair(body='The Raleigh Market is open 9-5.', days='Every Saturday'), NOW, diagnostics) == []
    assert {d['reason'] for d in diagnostics} == {'raleigh_direct_schedule_missing'}
    diagnostics = []
    assert c._fair(fair().replace('Outside Grounds', 'Outside Grounds, South and East of Dorton Arena'), NOW, diagnostics) == []
    assert {d['reason'] for d in diagnostics} == {'raleigh_direct_venue_unresolved'}


@patch.object(c, 'record', side_effect=preview)
def test_square_details_resume_without_partial_staging_or_truncated_prose(_):
    triples = [square_card(i) for i in range(1, 6)]
    pages = {c.SOURCES[c.OGK][0]: '<div class="eventlist">' + ''.join(t[0] for t in triples) + '</div>',
             **{t[1]: t[2] for t in triples}}
    fetch = Mock(side_effect=lambda url, accept: pages[url])
    first = c.collect_chunk(source(c.OGK), fetch, now=NOW)
    assert not first['complete'] and first['events'] == [] and first['checkpoint']['cursor'] == 4
    second = c.collect_chunk(source(c.OGK), fetch, checkpoint=first['checkpoint'], now=NOW)
    assert second['complete'] and len(second['events']) == 5 and fetch.call_count == 6
    assert all(r['description'].endswith(LONG_BODY) for r in second['events'])
    assert all(r['venue_address'] == c.VENUES[c.OGK][1] for r in second['events'])
    changed = deepcopy(first['checkpoint']); changed['events'][0]['description'] = 'Shortened'
    with pytest.raises(ValueError, match='checkpoint_invalid'):
        c.collect_chunk(source(c.OGK), fetch, checkpoint=changed, now=NOW)
    with pytest.raises(ValueError, match='checkpoint_invalid'):
        c.collect_chunk(source(c.OGK), fetch, checkpoint=first['checkpoint'], now=NOW+timedelta(hours=5))


def test_square_moved_detail_and_unproven_street_are_held():
    card, url, detail = square_card(2)
    item = c._squarespace_manifest(c.OGK, '<div class="eventlist">' + card + '</div>', NOW, [])[0]
    for payload, reason in [(detail.replace('2026-11-17T18:', '2026-11-17T19:'), 'schedule_conflict'),
                            (detail.replace('225 South Wilmington Street', 'An undisclosed location'), 'venue_unresolved')]:
        with pytest.raises(ValueError, match=reason):
            c._squarespace_detail(c.OGK, item, payload, NOW)


@patch.object(c, 'record', side_effect=preview)
def test_game_public_native_descriptions_and_closure_holds(_):
    events = [game_event()]
    events += [{**game_event(), 'id': 'blank', 'description': ''},
               {**game_event(), 'id': 'closed', 'title': 'CHRISTMAS DAY! CLOSED!', 'description': 'CLOSED!'}]
    fetch = Mock(side_effect=lambda url, accept: game_page() if url == c.SOURCES[c.GAME][0] else game_frame())
    reader = Mock(return_value=json.dumps(events))
    chunk = c.collect_chunk(source(c.GAME), fetch, read_public_events=reader, now=NOW)
    assert chunk['complete'] and len(chunk['events']) == 1
    assert chunk['events'][0]['description'] == events[0]['description']
    assert {h['reason'] for h in chunk['checkpoint']['diagnostics']} == {'raleigh_direct_description_missing', 'raleigh_direct_nonpublic'}
    assert 'sb_publishable_' not in json.dumps(chunk)
    assert reader.call_args.kwargs['window_start'] == '2026-11-15'


def test_game_changed_iframe_or_api_identity_never_uses_public_key_reader():
    for page, frame in [('<iframe src="https://example.com/other"></iframe>', game_frame()),
                        (game_page(), game_frame().replace(c.GAME_API_HOST, 'other.supabase.co'))]:
        reader = Mock()
        with pytest.raises(ValueError, match='public_api_identity'):
            c._game_theory(page, Mock(return_value=frame), reader, NOW, [])
        reader.assert_not_called()


@patch.object(c, 'record', side_effect=preview)
def test_run_club_expands_only_the_explicit_weekday_for_28_days(_):
    page = '<h1>Run Club</h1><div class="ContentReset">Join us every Tuesday at 5:30pm at TRC Salvage Yard. All experience levels welcome.</div>2330 Salvage Yard Drive, Raleigh, NC 27604'
    rows = c._trc(page, NOW, [])
    assert len(rows) == 4
    assert all(datetime.fromisoformat(r['starts_at']).weekday() == 1 and datetime.fromisoformat(r['starts_at']).hour == 17 for r in rows)
    assert all(r['ends_at'] is None and r['schedule_window_days'] == 28 for r in rows)
    for change in [page.replace('Tuesday', 'Wednesday'), page.replace('27604', ''), page.replace('Run Club</h1>', 'Open Climb</h1>')]:
        with pytest.raises(ValueError, match='calendar_changed'):
            c._trc(change, NOW, [])


def test_unregistered_source_and_foreign_event_paths_fail_before_fetch():
    fetch = Mock()
    with pytest.raises(ValueError, match='unregistered'):
        c.collect_chunk({**source(c.GOODNIGHTS), 'feed_url': 'https://example.com/'}, fetch, now=NOW)
    fetch.assert_not_called()
    for url in ['https://www.goodnightscomedy.com.evil.example/shows/123', 'https://www.goodnightscomedy.com/shows/123?other=1']:
        assert not c.event_url(c.GOODNIGHTS, url)
    with pytest.raises(ValueError, match='checkpoint_required'):
        c.collect(source(c.GOODNIGHTS), fetch)
