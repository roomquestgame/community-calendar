from copy import deepcopy
from calendar import monthrange
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.parse import urlencode

import pytest

from roomquest import raleigh_direct_jcra as c

NOW = datetime(2026, 11, 15, 13, tzinfo=timezone.utc)
SOURCE = dict(source_key=c.SOURCE, feed_url=c.CALENDAR, kind='html', platform_adapter='html', timezone=c.ZONE)


def preview(title, start, end, venue, street, city, url, identity, **kwargs):
    return dict(id=identity, title=title, starts_at=start, ends_at=end, venue_name=venue,
                venue_address=street, venue_city=city, event_url=url, lat=None, lng=None)


def calendar(year, month, rows=()):
    label = datetime(year, month, 1).strftime('%B %Y')
    html = f'<title>JC Raulston Arboretum Events Calendar for {label}</title><h1>{label}</h1>'
    for day in range(1, monthrange(year, month)[1]+1):
        html += f'<div><h2 aria-label="{label.split()[0].lower()} {day}">{day}</h2>'
        for number, title, row_day, children in rows:
            if row_day != day:
                continue
            html += (f'<p class="calendar-text"><a href="/events/details.php?ID={number}">{title}</a>'
                + ('<span class="childrens-program-asterisk">✽</span>' if children else '') + ' In Person</p>')
        html += '</div>'
    return html


def hours(alert=''):
    value = '<main><section aria-labelledby="hours-heading">'
    for season, groups in [('April 1 through September 30', [('Monday — Thursday', '9 am - 4:30 pm'),
        ('Friday', '9 am - 7 pm'), ('Saturday — Sunday', '8 am - 7 pm')]),
        ('October 1 through March 31', [('Monday — Friday', '9 am - 4:30 pm'), ('Saturday — Sunday', '9 am - 5 pm')])]:
        value += '<h3>' + season + '</h3><dl>' + ''.join('<dt>'+a+'</dt><dd>'+b+'</dd>' for a,b in groups) + '</dl>'
    return value + '</section>' + alert + '</main>'


def detail(number=4410, title='Holiday Creations', heading=None, dates='20261206T140000/20261206T160000', body=None):
    heading = heading or ('<h2><li class="eventdates">Sunday, December 6, 2026 — '
        '<span class="text-smallcaps">2 pm</span> - <span class="text-smallcaps">4 pm</span></li></h2>')
    query = urlencode(dict(action='TEMPLATE', text=title, details='', dates=dates, ctz=c.ZONE,
        location='JC Raulston Arboretum, 4415 Beryl Road, Raleigh, NC 27606'))
    return (f'<main id="maincontent"><h1>{title}</h1>{heading}<div class="badge">In Person</div>'
        '<span class="badge">Children\'s Program</span>'
        f'<p>{body or "Create seasonal garden art with a teacher, explore materials and take your finished work home."}</p>'
        '<dl><dt>Location</dt><dd>Education Yurt, 4415 Beryl Road, Raleigh, NC 27606.</dd>'
        '<dt>Cost</dt><dd>$25 per participant.</dd></dl><div class="btn-group">'
        '<a href="https://calendar.google.com/calendar/render?' + query + '">Add to Google Calendar</a>'
        f'<a href="/events/save-to-calendar.php?ID={number}&mode=ical">iCal</a></div></main>')


def item(number='4410', title='Holiday Creations', days=None):
    return dict(id=number, url='https://jcra.ncsu.edu/events/details.php?ID='+number,
        title=title, days=days or ['2026-12-06'], children=True, listed_sold_out=False)


def test_supplemental_scope_and_month_identity():
    plan = c._plans(NOW)[1]
    page = calendar(2026, 12, [(1, 'Holiday Creations', 6, True), (2, 'Plant-Lover\'s Tour', 1, False),
        (3, 'Friends of the Arboretum Lecture', 10, False), (4, 'Art and Blooms at the JCRA', 12, False)])
    assert [x['id'] for x in c._listing(page, plan, NOW)] == ['1', '4']
    with pytest.raises(ValueError, match='calendar_changed'):
        c._listing(page.replace('December 2026', 'January 2027'), plan, NOW)
    with pytest.raises(ValueError, match='calendar_changed'):
        c._listing(page.replace('<h2 aria-label="december 31">31</h2>', ''), plan, NOW)


@patch.object(c, 'record', side_effect=preview)
def test_full_native_prose_and_explicit_clocks_are_preserved(_):
    body = 'Participants explore seasonal materials with the instructor. ' * 70
    rows = c._detail(item(), detail(body=body), NOW, c._hours(hours(), NOW))
    assert len(rows) == 1 and len(rows[0]['description']) > 4000
    assert body.strip() in rows[0]['description']
    assert rows[0]['starts_at'] == '2026-12-06T14:00:00-05:00'
    assert rows[0]['venue_address'] == c.VENUE[1]
    assert rows[0]['publisher_categories'] == ["Children's Program"]
    with pytest.raises(ValueError, match='schedule_unresolved'):
        c._detail(item(), detail().replace('Sunday, December 6, 2026', 'Saturday, December 5, 2026'), NOW, {})


@patch.object(c, 'record', side_effect=preview)
def test_visible_range_and_complete_month_grid_replace_broken_export_placeholders(_):
    native = detail(number=4502, title='Garden Story Walk',
        heading='<h2>Saturday, January 2 through Sunday, January 10, 2027 — during garden open hours</h2>',
        dates='20270110T000000/20270110T200000')
    entry = item('4502', 'Garden Story Walk', [f'2027-01-{day:02}' for day in range(2,11)])
    rows = c._detail(entry, native, NOW, c._hours(hours(), NOW))
    assert len(rows) == 9
    assert rows[0]['starts_at'] == '2027-01-02T09:00:00-05:00'
    assert rows[0]['ends_at'] == '2027-01-02T17:00:00-05:00'
    assert rows[2]['ends_at'] == '2027-01-04T16:30:00-05:00'
    entry['days'].pop()
    with pytest.raises(ValueError, match='schedule_unresolved'):
        c._detail(entry, native, NOW, c._hours(hours(), NOW))


@patch.object(c, 'record', side_effect=preview)
def test_explicit_early_closure_overrides_regular_hours_and_unknown_closure_holds(_):
    alert = ('<h3>Upcoming Early Closure Alert</h3><p>The JC Raulston Arboretum will close at 2 pm '
        'on Moonlight in the Garden event nights: Thursday, November 5 and Fridays and Saturdays, November 6, 7, 13, 14, 20 and 21.</p>')
    native = detail(number=4344, title='Garden Story Walk',
        heading='<h2>Saturday, November 21 through Sunday, November 22 — during garden open hours</h2>',
        dates='20261121T000000/20261122T200000')
    entry = item('4344', 'Garden Story Walk', ['2026-11-21','2026-11-22'])
    rows = c._detail(entry, native, NOW, c._hours(hours(alert), NOW))
    assert rows[0]['ends_at'] == '2026-11-21T14:00:00-05:00'
    assert rows[1]['ends_at'] == '2026-11-22T17:00:00-05:00'
    unknown = c._hours(hours('<h3>Upcoming Early Closure Alert</h3><p>Closed some afternoons.</p>'), NOW)
    with pytest.raises(ValueError, match='schedule_unresolved'):
        c._detail(entry, native, NOW, unknown)


@pytest.mark.parametrize('change,reason', [('invitation only', 'not_public'), ('sold out', 'sold_out')])
def test_unavailable_programs_are_held(change, reason):
    with pytest.raises(ValueError, match=reason):
        c._detail(item(), detail(body='This program is '+change+'. A public schedule alone does not admit this event.'), NOW, {})


@patch.object(c, 'record', side_effect=preview)
def test_checkpoint_requires_complete_listing_and_every_detail_outcome(_):
    plans = c._plans(NOW)
    pages = {plans[0]['url']: calendar(2026,11), plans[1]['url']: calendar(2026,12,[(4410,'Holiday Creations',6,True)]),
        plans[2]['url']: calendar(2027,1), c.HOURS: hours(), item()['url']: detail()}
    checkpoint = None
    for n in range(5):
        result = c.collect_chunk(SOURCE, lambda url, accept: pages[url], now=NOW,
            checkpoint=checkpoint, max_fetches=1)
        checkpoint = result['checkpoint']
        assert result['complete'] is (n == 4)
        assert bool(result['events']) is (n == 4)
    c._checkpoint(checkpoint, NOW)
    assert not c.checkpoint_complete(dict(checkpoint, listed_pages=[]))
    assert not c.checkpoint_complete(dict(checkpoint, outcomes=[]))
    corrupted = deepcopy(checkpoint)
    corrupted['events'][0]['venue_address'] = '999 Wrong Road, Raleigh, NC 27606'
    c._seal(corrupted)
    with pytest.raises(ValueError, match='checkpoint_invalid'):
        c._checkpoint(corrupted, NOW)
