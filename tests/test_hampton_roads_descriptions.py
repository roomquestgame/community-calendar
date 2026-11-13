"""Narratives stay scoped to an event and reuse existing publisher requests."""
from datetime import datetime, timedelta
import json

import pytest

from roomquest import hampton_roads_public_events as public_events
from roomquest import hampton_roads_venues as venues


def source(module, key):
    return {'source_key': key, 'feed_url': module.SOURCES[key][0],
            'kind': 'html', 'platform_adapter': 'html', 'timezone': module.ZONE.key}


def publisher(pages):
    calls = []

    def fetch(url, accept):
        calls.append((url, accept))
        return pages[url]

    return fetch, calls


def next_day():
    return (datetime.now(venues.ZONE) + timedelta(days=2)).replace(hour=19, minute=0, second=0, microsecond=0)


def test_sevenvenues_retains_scoped_detail_for_every_showing():
    start = next_day()
    url = 'https://www.sevenvenues.com/events/detail/fixture-show'
    listing = f'<div class="eventItem"><h3 class="title"><a href="{url}">Fixture Show</a></h3></div>'
    detail = f'''
        <aside>Venue description and ticket policies.</aside>
        <div class="sidebar_event_venue"><a href="/venues/detail/harrison-opera-house">Opera House</a></div>
        <div class="event_showings">
          <li id="showing_1"><span class="showings_date"><span class="m-date__singleDate">{start:%A, %b %d, %Y}</span></span>
            <span class="first_wrapper"><span class="time">7:00 PM</span></span></li>
          <li id="showing_2"><span class="showings_date"><span class="m-date__singleDate">{start + timedelta(days=1):%A, %b %d, %Y}</span></span>
            <span class="first_wrapper"><span class="time">7:00 PM</span></span></li>
        </div>
        <h2>Event Details</h2><div class="event_description expandable">
          <p>A musical featuring songs &amp; dramatic storytelling.</p>
          <nav>Another concert</nav><script>unrelated()</script><p>Performed by the touring company.</p>
        </div>
        <div class="faq"><p>Parking and venue policies.</p></div>
        <div class="related_events"><p>Next week's other performance.</p></div>'''
    fetch, calls = publisher({venues.SOURCES[venues.SEVEN][0]: listing, url: detail})
    rows = venues.collect(source(venues, venues.SEVEN), fetch)
    assert len(rows) == 2
    assert {row['description'] for row in rows} == {
        'A musical featuring songs & dramatic storytelling.\nPerformed by the touring company.'}
    assert {row['id'] for row in rows} == {url}
    assert {row['event_url'] for row in rows} == {url}
    assert len({row['starts_at'] for row in rows}) == 2
    assert {row['venue_address'] for row in rows} == {'160 West Virginia Beach Boulevard, Norfolk, VA 23510'}
    assert calls == [(venues.SOURCES[venues.SEVEN][0], 'text/html'), (url, 'text/html')]


def test_nauticus_does_not_copy_an_unverified_content_container():
    start = next_day()
    url = 'https://nauticus.org/events/fixture-family-day/'
    listing = f'<div class="events-list"><div class="event"><span class="date">{start:%B %d} | 7PM</span><a class="title" href="{url}">Family Day</a></div></div>'
    detail = f'''<nav>All museum events</nav><h1>Family Day</h1>
      <div><h3 class="post-date">{start:%A, %B %d, %Y} | 7PM</h3></div>
      <div class="sidebar"><p>Another event's promotional text.</p></div>
      <div class="footer-links">Location, opening hours and contact details.</div>
      <footer>Newsletter subscription.</footer>'''
    fetch, calls = publisher({venues.SOURCES[venues.NAUTICUS][0]: listing, url: detail})
    row, = venues.collect(source(venues, venues.NAUTICUS), fetch)
    assert row['description'] == ''
    assert row['id'] == url
    assert row['venue_address'] == '1 Waterside Drive, Norfolk, VA 23510'
    assert calls == [(venues.SOURCES[venues.NAUTICUS][0], 'text/html'), (url, 'text/html')]


@pytest.mark.parametrize('key', [public_events.PRINCE, public_events.FLOURISH])
def test_bookstores_retain_exact_event_schema_narrative(key):
    start = next_day()
    if key == public_events.PRINCE:
        url = f'https://prince-books.com/event/{start:%Y-%m-%d}/fixture-reading'
        listing = f'<h3 class="event-list__title"><a href="{url}">Author Reading</a></h3>'
        place = {'@type': 'Place', 'name': 'Prince Books', 'address': {
            'streetAddress': '109 E. Main Street', 'addressLocality': 'Norfolk', 'addressRegion': 'VA'}}
    else:
        url = 'https://flourishbookstore.com/events/fixture-reading/'
        listing = f'<a class="flourish-schedule-row" href="{url}">Author Reading</a>'
        place = {'@type': 'Place', 'name': 'Vibrant Shore Brewing', 'address': {
            'streetAddress': '505 18th St, Virginia Beach, VA 23451', 'addressLocality': 'Virginia Beach', 'addressRegion': 'VA'}}
    event = {'@type': 'Event', 'name': 'Author Reading', 'url': url, 'startDate': start.isoformat(),
             'location': place, 'description': '<p>Meet the author &amp; discuss the new novel.</p><nav>Other events</nav>'}
    detail = '<script type="application/ld+json">' + json.dumps({'@graph': [
        {'@type': 'BookStore', 'description': 'A generic store biography.'}, event,
        {'@type': 'Event', 'url': url + 'other', 'description': 'Unrelated event.'}]}) + '</script>'
    fetch, calls = publisher({public_events.SOURCES[key][0]: listing, url: detail})
    row, = public_events.collect(source(public_events, key), fetch)
    assert row['description'] == 'Meet the author & discuss the new novel.'
    assert row['id'] == row['event_url'] == url
    assert len(calls) == 2


def test_sandler_reuses_multishow_detail_and_excludes_sidebar():
    start = next_day()
    url = 'https://www.sandlercenter.org/events/detail/fixture-show'
    listing = f'<div class="eventItem"><div class="info"><h3 class="title"><a href="{url}">Fixture Show</a></h3></div></div>'
    detail = f'''<div class="event_showings"><li id="showing_1">
        <span class="showings_date"><span class="m-date__singleDate">{start:%b %d / %Y}</span></span>
        <span class="wrapper"><span class="time">{start:%A} at 7:00pm</span></span>
      </li></div><div class="event_description"><p>Chamber music from a visiting ensemble.</p></div>
      <div class="faq"><p>Related links and ticket policies.</p></div>
      <aside><p>Another show.</p></aside>'''
    fetch, calls = publisher({public_events.SOURCES[public_events.SANDLER][0]: listing, url: detail})
    row, = public_events.collect(source(public_events, public_events.SANDLER), fetch)
    assert row['description'] == 'Chamber music from a visiting ensemble.'
    assert row['id'] == row['event_url'] == url
    assert calls == [(public_events.SOURCES[public_events.SANDLER][0], 'text/html'), (url, 'text/html')]


@pytest.mark.parametrize('narrative', ['', '<div class="event_description"><p>Publisher listing prose.</p></div>'])
def test_sandler_listing_never_adds_a_description_fetch(narrative):
    start = next_day()
    url = 'https://www.sandlercenter.org/events/detail/fixture-show'
    listing = f'''<div class="eventItem"><div class="info"><h3 class="title"><a href="{url}">Fixture Show</a></h3>
      <span class="m-date__singleDate">{start:%b %d / %Y}</span><span class="time"><span class="start">7:00 PM</span></span>
      {narrative}</div></div><aside>Unrelated event narrative.</aside>'''
    fetch, calls = publisher({public_events.SOURCES[public_events.SANDLER][0]: listing})
    row, = public_events.collect(source(public_events, public_events.SANDLER), fetch)
    assert row['description'] == ('Publisher listing prose.' if narrative else '')
    assert row['id'] == url
    assert calls == [(public_events.SOURCES[public_events.SANDLER][0], 'text/html')]
