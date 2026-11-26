from datetime import date

from bs4 import BeautifulSoup

from roomquest.registered_listings import SHANK, shank


def home_page():
    return '''<html><section id="page-content"><div class="playbox"><div class="text"><div>
      <h3>Box Office Show</h3><h4><span>Friday January 8, 2027</span><span>8:00pm</span></h4>
      <a aria-label="Show details for January 8, 2027" href="/shows/874/">Details</a>
    </div></div></div></section><div class="quick-cal">
      <a href="/shows/749/"><h3>November 27</h3>Ticketed Show</a>
      <a href="/shows/673/"><h3>December 18</h3>Clock Missing</a>
      <a href="/shows/874/"><h3>January 8</h3>Box Office Show</a>
    </div></html>'''


def tickets_page():
    return '''<section id="page-content"><div class="playbox"><div class="text">
      <a aria-label="Get tickets for November 27, 2026" href="https://www.ticketweb.com/event/show/1"><strong>Ticketed Show</strong></a>
      <div>8:00pm</div><div>$20.00</div></div></div></section>'''


def schedule_page():
    return '''<div class="calendar"><div class="header"><h2>November 2026</h2></div><div class="days">
      <div class="day_num"><div class="event"><div>Ticketed Show</div><div>8:00pm</div><div>$20.00</div>
      <a class="details" aria-label="Show details for November 27, 2026" href="/shows/749/">Details</a>
      </div></div></div></div>'''


def test_shank_collects_all_months_and_keeps_box_office_only_events():
    pages = {SHANK + 'tickets/': tickets_page(), SHANK + 'schedule/': schedule_page()}
    rows = list(shank(BeautifulSoup(home_page(), 'html.parser'),
                      lambda url, accept: pages[url], date(2026, 11, 26)))
    assert [row['title'] for row in rows] == ['Ticketed Show', 'Box Office Show']
    assert all(row['venue_name'] == 'Shank Hall' for row in rows)
    assert rows[0]['event_url'] == 'https://shankhall.com/shows/749/'


def test_shank_rejects_when_too_many_inventory_clocks_are_unverified():
    broken = home_page().replace(
        '<a href="/shows/874/"><h3>January 8</h3>Box Office Show</a>',
        '<a href="/shows/900/"><h3>December 19</h3>Missing Two</a>'
        '<a href="/shows/901/"><h3>December 20</h3>Missing Three</a>'
        '<a href="/shows/902/"><h3>December 21</h3>Missing Four</a>'
        '<a href="/shows/874/"><h3>January 8</h3>Box Office Show</a>')
    pages = {SHANK + 'tickets/': tickets_page(), SHANK + 'schedule/': schedule_page()}
    try:
        list(shank(BeautifulSoup(broken, 'html.parser'), lambda url, accept: pages[url],
                   date(2026, 11, 26)))
    except ValueError as exc:
        assert str(exc) == 'shank_schedule_facts_incomplete'
    else:
        raise AssertionError('incomplete schedule facts were accepted')
