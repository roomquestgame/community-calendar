from datetime import date

from bs4 import BeautifulSoup

from roomquest.feed_registration import classify
from roomquest.registered_listings import SHANK, shank


def month_page(year, month, events=()):
    import calendar
    name = date(year, month, 1).strftime('%B %Y')
    by_day = {}
    for day, title, clock, event_id, cancelled in events:
        body = (f'<div>{title}</div><div>{clock}</div><div>$20.00</div>'
                f'<a class="details" aria-label="Show details for '
                f'{date(year, month, day).strftime("%B %-d, %Y")}" '
                f'href="https://shankhall.com/shows/{event_id}/">Show Details</a>')
        if cancelled:
            body = '<div>Canceled</div><strike>' + body + '</strike>'
        by_day.setdefault(day, []).append('<div class="event">' + body + '</div>')
    cells = ''.join(
        f'<div class="day_num"><span data-day="Mon">{day}</span>'
        f'<div class="event-wrap">{"".join(by_day.get(day, ()))}</div></div>'
        for day in range(1, calendar.monthrange(year, month)[1] + 1))
    return (f'<html><body class="schedule"><div class="calendar"><div class="header">'
            f'<h2>{name}</h2></div><div class="days">{cells}</div></div></body></html>')


def test_shank_home_follows_complete_first_party_schedule_not_ticketweb():
    home = ('<html><a href="https://shankhall.com/schedule/">Schedule</a>'
            '<a href="https://www.ticketweb.com/event/one/1">Tickets</a>'
            '<a href="https://www.ticketweb.com/event/two/2">Tickets</a></html>')
    assert classify('https://shankhall.com/', home) == {'calendar_page': SHANK}


def test_shank_collects_all_months_and_keeps_box_office_only_events():
    november = month_page(2026, 11, [(27, 'The R&B Cadets', '8:00pm', 749, False)])
    december = month_page(2026, 12, [
        (3, 'The Steepwater Band', '8:00pm', 751, False),
        (4, 'Cancelled Show', '8:00pm', 752, True),
    ])
    january = month_page(2027, 1, [(9, 'DIO RULES', '8:00pm', 753, False)])
    pages = {SHANK + '?202612': december, SHANK + '?202701': january}
    rows = list(shank(BeautifulSoup(november, 'html.parser'),
                      lambda url, accept: pages[url], date(2026, 11, 26)))
    assert [row['title'] for row in rows] == ['The R&B Cadets', 'The Steepwater Band', 'DIO RULES']
    assert all(row['venue_name'] == 'Shank Hall' for row in rows)
    assert rows[0]['event_url'] == 'https://shankhall.com/shows/749/'


def test_shank_rejects_partial_month_grid():
    broken = month_page(2026, 11).replace('<span data-day="Mon">30</span>', '')
    try:
        list(shank(BeautifulSoup(broken, 'html.parser'), lambda *_: '', date(2026, 11, 1)))
    except ValueError as exc:
        assert str(exc) == 'shank_calendar_day_grid_changed'
    else:
        raise AssertionError('partial month was accepted')
