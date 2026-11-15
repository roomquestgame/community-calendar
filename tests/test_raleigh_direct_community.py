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
