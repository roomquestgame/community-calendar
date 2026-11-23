"""Real publisher HTML shape regressions: pagers, fixed times, source identity.

These compact fixtures reproduce the DOM contracts observed on 23 Nov 2026.
No fabricated dates or undocumented venue defaults enter the collector.
"""
from datetime import datetime, timezone
import json
from unittest.mock import Mock

import pytest
from bs4 import BeautifulSoup

from roomquest import registered_html_calendar as calendar
from roomquest.registered_native_content import CAPABILITY as NATIVE
from roomquest.registration_formats import source_key


UK = 'https://www.cornex.co.uk/events'
US = 'https://commonwealthbrewingcompany.com/events/'
UK_EVENT = UK + '/man-in-the-mirror-3'
US_EVENT = 'https://commonwealthbrewingcompany.com/event/ffx-holiday-artisan-market-2026-12-05/'


def source(url):
    return {'source_key': source_key(url), 'feed_url': url, 'kind': 'html',
            'platform_adapter': 'html', calendar.CAPABILITY: 1, NATIVE: 1}


def dated_uk(title='Man in the Mirror', date='25 November, 2026',
             clock='19:30', start='2026-11-25', country='UK'):
    item = {'@context': 'https://schema.org', '@type': 'Event',
            'name': title, 'startDate': start,
            'location': [{'@type': 'Place', 'name': 'Cambridge Corn Exchange',
                          'address': {'@type': 'PostalAddress',
                                      'streetAddress': '2 Wheeler Street',
                                      'addressLocality': 'Cambridge',
                                      'postalCode': 'CB2 3QB',
                                      'addressCountry': country}}]}
    return ('<html><head><link rel="canonical" href="' + UK_EVENT + '">'
            '<script type="application/ld+json">' + json.dumps(item) +
            '</script></head><main><h1>' + title + '</h1>'
            '<div class="event-details__item--date"><dd>' + date + '</dd></div>'
            '<div class="event-details__item--time"><dd>' + clock + '</dd></div>'
            '</main></html>')


def listing_with_pager(next_page=None, current=1, urls=()):
    links = ''.join('<article><a href="' + u + '">More info</a></article>'
                    for u in urls)
    pager = ('<nav aria-label="What\'s On listing pagination"><ul class="pagination">'
             + (('<li><a href="?page=1">1</a></li>') if current == 2 else '')
             + '<li><span>' + str(current) + '</span></li>'
             + (('<li><a href="' + next_page + '">2</a></li>'
                 '<li class="pagination__next"><a href="' + next_page +
                 '" aria-label="Next"></a></li>') if next_page else '')
             + '</ul></nav>')
    return '<html><main><h1>Upcoming Events</h1>' + links + pager + '</main></html>'


def facet_listing(total_rows=1, total_pages=1):
    config = {'preload_data': {'settings': {'pager': {
        'page': 1, 'per_page': 12, 'total_rows': total_rows,
        'total_pages': total_pages}}}}
    return ('<html><main><h1>Events</h1>'
            '<div id="events-feed"><div class="facetwp-template" data-name="events">'
            '<div class="excerpt-box"><a href="' + US_EVENT + '">Holiday Market</a></div>'
            '</div><div class="facetwp-pager"></div></div>'
            '</main><script>window.FWP_JSON = ' + json.dumps(config) + ';</script></html>')


def us_detail(day='December 5', venue='Fairfax', stamp='2026-12-05'):
    url = US_EVENT.replace('2026-12-05', stamp)
    return ('<html><head><link rel="canonical" href="' + url + '"></head>'
            '<main><h2 class="fl-heading">FFX: Holiday Artisan Market</h2>'
            '<a class="event-info-location" href="https://commonwealthbrewingcompany.com/location/fairfax/">'
            + venue + '</a>'
            '<div class="fl-module-html">' + day + ' 12:00 pm - 6:00 pm</div>'
            '<div class="fl-module-cp-content-builder">Publisher market description</div>'
            '</main><footer><div class="fl-col">'
            '<h5 class="fl-heading">Fairfax</h5>'
            '<address class="location-address">10426 Main St Fairfax, VA 22030</address>'
            '</div></footer></html>')


def test_uk_real_numbered_span_pager_follows_all_pages_before_details():
    next_page = UK + '?page=2'
    first = listing_with_pager(next_page=next_page, urls=[UK_EVENT])
    second = listing_with_pager(current=2, urls=[])
    calls = Mock(side_effect=lambda u, accept: {
        next_page: second, UK_EVENT: dated_uk()}[u])
    rows = calendar.collect(source(UK), calls, listing=first)
    assert len(rows) == 1
    assert rows[0]['venue_address'].endswith('Cambridge, CB2 3QB, UK')
    assert str(rows[0]['starts_at']).startswith('2026-11-25T19:30')
    assert [x.args[0] for x in calls.call_args_list] == [next_page, UK_EVENT]


@pytest.mark.parametrize('date,clock,title,country', [
    ('24 November, 2026', '19:30', 'Man in the Mirror', 'UK'),
    ('25 November, 2026', '19:30', 'Wrong title', 'GB'),
    ('25 November, 2026', '19:30', 'Man in the Mirror', 'US'),
    ('25 November, 2026', '01:30', 'Man in the Mirror', 'UK'),
])
def test_uk_event_requires_matching_publisher_date_title_country(date, clock, title, country):
    url = UK_EVENT
    payload = dated_uk(title=title, date=date, clock=clock, country=country)
    if title == 'Wrong title':
        payload = payload.replace('<h1>Wrong title</h1>', '<h1>Unrelated event</h1>')
    with pytest.raises(ValueError, match='html_calendar_detail_identity_conflict'):
        calendar._detail(source(UK), payload, url)


def test_uk_range_with_one_fixed_time_uses_only_jsonld_first_day():
    url = UK_EVENT
    payload = dated_uk(date='25 - 26 November, 2026')
    rows = calendar._detail(source(UK), payload, url)
    assert len(rows) == 1
    assert rows[0]['starts_at'].startswith('2026-11-25T19:30')


def test_uk_variable_time_performance_never_invents_occurrences():
    assert calendar._detail(source(UK),
        dated_uk(date='25 - 26 November, 2026', clock='Times vary by date'),
        UK_EVENT) == []


def test_facetwp_one_page_preload_must_match_rendered_rows():
    soup = BeautifulSoup(facet_listing(), 'html.parser')
    assert calendar._pagination(soup, US, collection_url=US) == (None, set())
    for config in (facet_listing(total_rows=9), facet_listing(total_pages=2)):
        with pytest.raises(ValueError, match='html_calendar_pagination_needed'):
            calendar._pagination(BeautifulSoup(config,'html.parser'), US, collection_url=US)


def test_us_publisher_detail_card_uses_matching_venue_address_and_clock():
    rows = calendar._detail(source(US), us_detail(), US_EVENT)
    assert len(rows) == 1
    assert rows[0]['venue_address'] == '10426 Main St, Fairfax, VA 22030'
    assert rows[0]['starts_at'].startswith('2026-12-05T17:00')


@pytest.mark.parametrize('day,venue,stamp', [
    ('December 6','Fairfax','2026-12-05'),
    ('December 5','Wrong venue','2026-12-05'),
    ('December 5','Fairfax','2026-12-06'),
])
def test_us_publisher_card_fails_closed_on_conflicting_date_or_venue(day,venue,stamp):
    # The collector's own canonical check ensures the fetched event URL agrees.
    body = us_detail(day=day,venue=venue,stamp=stamp)
    if stamp == '2026-12-06':
        body = body.replace('2026-12-06/', '2026-12-05/')
        body = body.replace('2026-12-05/', '2026-12-06/', 1)
    with pytest.raises(ValueError, match='html_calendar_event_jsonld_missing|html_calendar_detail_identity_conflict'):
        calendar._detail(source(US), body, US_EVENT)
