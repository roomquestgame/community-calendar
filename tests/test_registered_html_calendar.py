"""Bounded HTML calendars: source scope, complete snapshots, and native facts.

Positive Schema.org samples are deliberately synthetic. Existing captured
bookstore fixtures exercise real calendar navigation and single-event guards.
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from roomquest import registered_html_calendar as calendar
from roomquest import registered_native_content as native
from roomquest import preview_worker
from roomquest.registration_formats import source_key


BASE = 'https://venue.example.org'
FEED = BASE + '/events'
ONE = BASE + '/event/reading'
TWO = BASE + '/event/concert'
FIXTURES = Path(__file__).parent / 'fixtures' / 'raleigh'
CAPTURED = Path(__file__).parent / 'fixtures' / 'registered_html_calendar' / 'lansdowne'


@pytest.fixture
def captured_lansdowne(monkeypatch):
    manifest = json.loads((CAPTURED / 'manifest.json').read_text())
    captured_at = datetime.fromisoformat(manifest['replay_time_utc'])

    class ClockMeta(type):
        def __instancecheck__(cls, value):
            return isinstance(value, datetime)

    class ReplayClock(datetime, metaclass=ClockMeta):
        @classmethod
        def now(cls, tz=None):
            return captured_at.astimezone(tz) if tz else captured_at.replace(tzinfo=None)

    monkeypatch.setattr(preview_worker, 'datetime', ReplayClock)
    pages = {page['url']: (CAPTURED / page['file']).read_text() for page in manifest['pages']}
    return manifest, pages


def source(url=FEED):
    return {'source_key': source_key(url), 'feed_url': url, 'kind': 'html',
            'platform_adapter': 'html', calendar.CAPABILITY: 1, native.CAPABILITY: 1}


def listing(urls=(ONE, TWO), *, extra='', heading='Upcoming Events'):
    return '<html><body><main><h1>' + heading + '</h1>' + ''.join(
        '<article><a href="' + url + '">Details</a></article>' for url in urls
    ) + extra + '</main></body></html>'


def event(url=ONE, **overrides):
    start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)
    return {'@context': 'https://schema.org', '@type': 'MusicEvent', '@id': '#event',
            'url': url, 'name': 'Publisher event', 'startDate': start.isoformat(),
            'endDate': (start + timedelta(hours=2)).isoformat(),
            'description': '<p>A conversation with the visiting artist.</p>',
            'image': '/images/poster.jpg',
            'location': {'@type': 'Place', 'name': 'Publisher Hall', 'address': {
                'streetAddress': '12 Main St', 'addressLocality': 'Richmond',
                'addressRegion': 'VA', 'postalCode': '23220'}}, **overrides}


def detail(data, *, canonical=None):
    return '<html><head>' + (
        '<link rel="canonical" href="' + canonical + '">' if canonical else ''
    ) + '<script type="application/ld+json">' + json.dumps(data) + '</script></head></html>'


def fetcher(pages):
    return Mock(side_effect=lambda url, _accept: pages[url])


def rockhouse_detail(item, narrative, *, title=None, date_label=None, clock=None, extra=''):
    at = datetime.fromisoformat(item['startDate'])
    title = item['name'] if title is None else title
    date_label = at.strftime('%A, %B %d, %Y') if date_label is None else date_label
    clock = at.strftime('%I:%M %p') if clock is None else clock
    body = ('<section id="RhpEventsSingle"><div class="singleEventDetails">'
            '<h1>' + title + '</h1><div class="eventStDate">' + date_label + '</div>'
            '<div class="eventDoorStartDate">Doors: 6 pm // Show: ' + clock + '</div>'
            '<div class="singleEventDescription">' + narrative + '</div>' + extra + '</div></section>')
    return detail(item, canonical=item['url']).replace('</html>', '<body>' + body + '</body></html>')


def test_one_parser_fetches_all_details_and_retains_their_own_native_evidence():
    pages = {FEED: listing(), ONE: detail(event()), TWO: detail(event(TWO))}
    fetch = fetcher(pages)
    rows = calendar.collect(source(), fetch)
    assert [call.args[0] for call in fetch.call_args_list] == [FEED, ONE, TWO]
    assert {row['id'] for row in rows} == {ONE + '#event', TWO + '#event'}
    for row in rows:
        assert row['venue_name'] == 'Publisher Hall'
        assert row['venue_address'] == '12 Main St, Richmond, VA, 23220'
        assert row['lat'] is None and row['lng'] is None
        assert row['description'] == 'A conversation with the visiting artist.'
        assert row['image_url'] == BASE + '/images/poster.jpg'
        assert row['image_evidence_url'] == row['event_url']
        assert row['registered_native_content']['extraction'] == calendar.VERSION
        native.validate_record(row, source())


def test_addressless_publisher_venue_uses_one_exact_contact_page_after_capture():
    contact_url = BASE + '/contact/'
    item = event(location={'@type': 'Place', 'name': 'Publisher Hall'})
    index = listing((ONE,), extra='<a href="/contact/">Contact</a>')
    contact = ('<html><head><meta property="og:site_name" content="Publisher Hall">'
               '</head><body><main>Publisher Hall, 35-47 Bethnal Green Road, '
               'London E1 6LA</main></body></html>')
    fetch = fetcher({ONE: detail(item), contact_url: contact})

    [row] = calendar.collect(source(), fetch, listing=index)

    assert [call.args[0] for call in fetch.call_args_list] == [ONE, contact_url]
    assert row['venue_address'] == (
        '35-47 Bethnal Green Road, London, E1 6LA, United Kingdom')
    assert row['location_provenance'] == 'publisher_contact_street_pending_geocode'
    assert row['publisher_details']['venue_address_evidence_url'] == contact_url


def test_addressless_publisher_venue_uses_one_exact_listing_footer_address():
    item = event(location={'@type': 'Place', 'name': 'Publisher Hall'})
    index = listing((ONE,), extra=(
        '<meta property="og:site_name" content="Publisher Hall">'
        '<footer>Publisher Hall, 35-47 Bethnal Green Road, '
        'London E1 6LA</footer>'))
    fetch = fetcher({ONE: detail(item)})

    [row] = calendar.collect(source(), fetch, listing=index)

    assert [call.args[0] for call in fetch.call_args_list] == [ONE]
    assert row['venue_address'] == (
        '35-47 Bethnal Green Road, London, E1 6LA, United Kingdom')
    assert row['publisher_details']['venue_address_evidence_url'] == FEED


def test_equivalent_contact_links_do_not_create_false_ambiguity():
    contact_url = BASE + '/contact/'
    item = event(location={'@type': 'Place', 'name': 'Publisher Hall'})
    index = listing((ONE,), extra=(
        '<a href="/contact">Contact</a><a href="/contact/">Contact us</a>'))
    contact = ('<meta property="og:site_name" content="Publisher Hall">'
               '<main>Publisher Hall, 35-47 Bethnal Green Road, '
               'London E1 6LA</main>')
    fetch = fetcher({ONE: detail(item), BASE + '/contact': contact,
                     contact_url: contact})

    [row] = calendar.collect(source(), fetch, listing=index)

    assert row['venue_address'].startswith('35-47 Bethnal Green Road')
    assert len(fetch.call_args_list) == 2


def test_detail_failure_logs_exact_public_url_and_preserves_reason(capsys):
    fetch = fetcher({ONE: '<html><body><main><h1>Reading</h1></main></body></html>'})
    with pytest.raises(ValueError, match='html_calendar_event_jsonld_missing'):
        calendar.collect(source(), fetch, listing=listing((ONE,)))
    log = capsys.readouterr().out
    assert 'registered_html_calendar_detail_error' in log
    assert 'html_calendar_event_jsonld_missing' in log
    assert ONE in log


def test_already_fetched_listing_is_reused_and_duplicate_links_fetch_once():
    fetch = fetcher({ONE: detail(event())})
    [row] = calendar.collect(source(), fetch, listing=listing((ONE, ONE + '/', ONE + '#tickets')))
    assert row['event_url'] == ONE
    assert [call.args[0] for call in fetch.call_args_list] == [ONE]


def test_equivalent_trailing_slash_identity_keeps_the_actual_fetched_evidence_url():
    fetch = fetcher({ONE: detail(event(ONE + '/'), canonical=ONE + '/')})
    [row] = calendar.collect(source(), fetch, listing=listing((ONE,)))
    assert row['event_url'] == ONE
    assert row['image_evidence_url'] == ONE
    native.validate_record(row, source())


def test_explicit_itemlist_supports_publisher_permalink_shapes():
    url = BASE + '/program/visiting-author'
    index = detail({'@type': 'ItemList', 'itemListElement': [
        {'@type': 'ListItem', 'position': 1, 'item': {'url': url}}]})
    assert calendar.supports_listing(FEED, index)
    [row] = calendar.collect(source(), fetcher({url: detail(event(url))}), listing=index)
    assert row['event_url'] == url


def test_whats_on_and_whatson_venues_use_same_complete_linked_detail_collector():
    date = (datetime.now(timezone.utc) + timedelta(days=14)).date()
    label = date.strftime('%B %d, %Y')
    for slug in ('whats-on', 'whatson'):
        listing_url = BASE + '/' + slug
        event_url = listing_url + '/evening-talk'
        page = listing((event_url,), heading="What's On")
        labelled = ('<html><body><main><h1>Evening Talk</h1>'
                    '<p><strong>Date</strong> ' + label + '</p>'
                    '<p><strong>Time</strong> 5:00 pm - 6:00 pm</p>'
                    '<p><strong>Where</strong> Studio - 136 Kingsland Road, London E2 8EA</p>'
                    '</main></body></html>')
        assert calendar.supports_listing(listing_url, page)
        fetch = fetcher({event_url: labelled})
        records = calendar.collect(source(listing_url), fetch, listing=page)
        assert len(records) == 1
        row = records[0]
        assert row['event_url'] == event_url
        assert row['timezone'] == 'Europe/London'
        assert row['venue_name'] == 'Studio'
        assert row['id'] == event_url + '#visible-event'
        native.validate_record(row, source(listing_url))


def test_wordpress_old_h2_title_and_labeled_details_are_supported_when_footer_agrees():
    day = (datetime.now(timezone.utc) + timedelta(days=17)).date()
    label = day.strftime('%B %d, %Y')
    event_url = BASE + '/event/friday-jazz-' + day.isoformat()
    html = ('<html><head><meta property="og:title" content="Friday Jazz - Oxford House">'
            '<meta property="og:site_name" content="Oxford House"></head><body>'
            '<main><h2>Welcome to live music</h2><h2>Friday Jazz</h2>'
            '<p><strong>Dates</strong> ' + label + ' - ' + label + '</p>'
            '<p><strong>Times</strong> 5:00 pm - 6:00 pm</p>'
            '<p><strong>Location</strong> Oxford House, Café</p></main>'
            '<footer><address>Oxford House, Derbyshire Street, London E2 6HG'
            '</address></footer></body></html>')
    [row] = calendar._detail(source(), html, event_url)
    assert row['venue_name'] == 'Oxford House, Café'
    assert 'Derbyshire Street' in row['venue_address']
    native.validate_record(row, source())


def test_wordpress_footer_can_name_venue_outside_its_semantic_address():
    day = (datetime.now(timezone.utc) + timedelta(days=17)).date()
    label = day.strftime('%B %d, %Y')
    event_url = BASE + '/event/friday-jazz-' + day.isoformat()
    html = ('<html><head><meta property="og:title" content="Friday Jazz - Oxford House">'
            '<meta property="og:site_name" content="Oxford House"></head><body>'
            '<main><h2>Welcome to live music</h2><h2>Friday Jazz</h2>'
            '<p><strong>Dates</strong> ' + label + ' - ' + label + '</p>'
            '<p><strong>Times</strong> 5:00 pm - 6:00 pm</p>'
            '<p><strong>Location</strong> Oxford House, Café</p></main>'
            '<footer><address>Derbyshire Street<br>Bethnal Green<br>London E2 6HG<br>UK'
            '</address><p>Oxford House by Bethnal Green © 2026</p></footer></body></html>')
    [row] = calendar._detail(source(), html, event_url)
    assert row['venue_name'] == 'Oxford House, Café'
    assert row['venue_address'] == ('Derbyshire Street, Bethnal Green, London E2 6HG, '
                                    'United Kingdom')
    native.validate_record(row, source())


@pytest.mark.parametrize('dates,times,venue', [
    ('27 November 2026 - 4 December 2026', '5pm - 6pm', 'Studio - 136 Kingsland Road, London E2 8EA'),
    ('27 November 2026', 'Times vary', 'Studio - 136 Kingsland Road, London E2 8EA'),
    ('27 November 2026', '5pm - 6pm', 'Online only'),
    ('27 November 2026', '5pm - 6pm', 'Studio'),
    ('27 November 2026', '6pm - 5pm', 'Studio - 136 Kingsland Road, London E2 8EA'),
])
def test_visible_event_fallback_never_invents_clock_recurrence_or_venue(dates, times, venue):
    html = ('<html><body><main><h1>Community Talk</h1>'
            '<p><strong>Date</strong> ' + dates + '</p>'
            '<p><strong>Time</strong> ' + times + '</p>'
            '<p><strong>Where</strong> ' + venue + '</p></main></body></html>')
    with pytest.raises(ValueError, match='html_calendar_event_jsonld_missing'):
        calendar._detail(source(), html, BASE + '/event/community-talk')


def hnm_detail(dates, times, *, location='The Studio - lower ground floor'):
    return ('<html><head><meta property="og:site_name" '
            'content="Horniman Museum and Gardens"><script src="' + BASE
            + '/wp-content/themes/horniman-theme/assets/js/main.min.js?ver=1"></script>'
            '</head><body><main><h1>Wildlife Photography</h1>'
            '<div class="event-details-widget">'
            '<div class="event-details-row"><div class="h3">Dates</div>'
            '<div class="event-details-line">' + dates + '</div></div>'
            '<div class="event-details-row"><div class="h3">Times</div>'
            '<div class="event-details-line">' + times + '</div></div>'
            '<div class="event-details-row" id="tickets"><div class="ticket-wrap">'
            '<div class="h3">Tickets</div><div class="event-details-line">Free</div>'
            '</div></div>'
            '<div class="event-details-row"><div class="h3">Location</div>'
            '<div class="event-details-line">' + location + '</div></div></div></main>'
            '<footer><div class="footer-col"><div class="h5">Horniman<br>'
            'Museum &amp; Gardens</div><div class="footer-address">'
            '100 London Road, Forest Hill<br>London SE23 3PQ</div></div></footer>'
            '</body></html>')


def test_hnm_theme_finite_detail_uses_exact_widget_and_footer_facts():
    event_url = BASE + '/event/wildlife-photography/'
    [row] = calendar._detail(
        source(), hnm_detail('17 December 2026 - 21 February 2027', '10am – 5.30pm'),
        event_url)
    assert row['starts_at'] == '2026-12-17T10:00:00+00:00'
    assert row['ends_at'] == '2027-02-21T17:30:00+00:00'
    assert row['venue_name'].startswith('Horniman Museum and Gardens — The Studio')
    assert row['venue_address'].endswith('SE23 3PQ, United Kingdom')
    native.validate_record(row, source())


@pytest.mark.parametrize('dates,times', [
    ('Sundays', '10am – 3pm'),
    ('2 December 2026 - 20 January 2027', 'Various times'),
    ('Daily, until March 2028', '10am – 5.30pm'),
    ('1 December', '12pm – 1.20pm'),
])
def test_hnm_theme_classifies_non_discrete_schedules_without_guessing(dates, times):
    assert calendar._detail(source(), hnm_detail(dates, times),
                            BASE + '/event/non-discrete/') == []


@pytest.mark.parametrize('url,body', [
    (ONE, listing()),
    (BASE + '/article/editorial', listing((ONE,), heading='Our favorites')),
    (BASE + '/', listing((ONE,))),
    (FEED, '<main><h1>Events</h1><p>Check back soon.</p></main>'),
    (FEED, '<main><h1>Events</h1><a href="https://other.example.org/event/a">A</a></main>'),
    (FEED, '<h1>Events</h1><nav><a href="/event/a">A</a><a href="/event/b">B</a></nav>'),
])
def test_calendar_scope_cannot_come_from_single_events_or_navigation(url, body):
    assert not calendar.supports_listing(url, body)


def test_homepage_requires_explicit_recurring_calendar_section():
    assert calendar.supports_listing(BASE + '/', listing())
    body = listing() + detail(event(BASE + '/'))
    assert not calendar.supports_listing(BASE + '/', body)


def test_homepage_highlights_follow_only_the_observed_full_calendar():
    homepage = BASE + '/'
    body = listing(extra='<nav><a href="/events/">Calendar</a><a href="/events">All Events</a></nav>')
    assert calendar.calendar_destination(homepage, body) == FEED + '/'
    assert not calendar.supports_listing(homepage, body)
    assert calendar.calendar_destination(FEED, body) is None
    assert calendar.calendar_destination(ONE, body) is None


def test_full_calendar_destination_does_not_erase_query_scopes_or_guess_a_choice():
    homepage = BASE + '/'
    assert calendar.calendar_destination(homepage, listing(extra='<a href="/events?venue=12">Events</a>')) == FEED + '?venue=12'
    for controls in (
        '<a href="/events?venue=12">Events</a><a href="/events?venue=34">Events</a>',
        '<a href="/events">Events</a><a href="/calendar">Calendar</a>',
    ):
        body = listing(extra=controls)
        assert calendar.calendar_destination(homepage, body) is None
        assert not calendar.supports_listing(homepage, body)
    assert calendar.calendar_destination(homepage, listing(extra='<a href="https://other.example.org/events">Events</a>')) is None


def test_venue_subsite_navigation_cannot_jump_to_the_operator_wide_calendar():
    url = BASE + '/boulder-theater-venue'
    body = listing(extra='<a href="/events">All Events</a>')
    assert calendar.calendar_destination(url, body) is None
    assert not calendar.supports_listing(url, body)


def test_actual_bookstore_event_page_is_never_a_recurring_source():
    url = 'https://www.blackbirdbooksandcoffee.com/event/2026-11-11/coffee-crochet'
    assert not calendar.supports_listing(url, (FIXTURES / 'blackbird-crochet.html').read_text())


def test_captured_lansdowne_homepage_highlights_cannot_replace_its_full_calendar(captured_lansdowne):
    manifest, pages = captured_lansdowne
    homepage, feed = manifest['homepage'], manifest['listing']
    assert not calendar.supports_listing(homepage, pages[homepage])
    assert calendar.calendar_destination(homepage, pages[homepage]).rstrip('/') == feed.rstrip('/')
    assert calendar.supports_listing(feed, pages[feed])
    highlights = calendar._links(homepage, calendar._html(pages[homepage]))
    complete = calendar._links(feed, calendar._html(pages[feed]))
    assert len(highlights) == 11 and len(complete) == 15
    assert set(complete) - set(highlights) == set(manifest['homepage_omits'])


def test_captured_detail_facts_bind_structural_narrative_and_image_evidence(captured_lansdowne):
    # These reduced fixtures keep actual event facts and DOM selectors, but
    # replace the publisher biographies with explicitly synthetic narrative.
    # This verifies extraction; it does not certify incomplete listing scope.
    manifest, pages = captured_lansdowne
    claim = source(manifest['listing'])
    rows = [row for url in manifest['detail_links']
            for row in calendar._detail(claim, pages[url], url)]
    assert len(rows) == 5
    assert {row['starts_at'] for row in rows} == {
        '2026-11-29T00:00:00+00:00', '2026-12-05T01:00:00+00:00',
        '2026-12-11T00:30:00+00:00', '2027-01-17T01:00:00+00:00',
        '2027-01-21T00:30:00+00:00',
    }
    for row in rows:
        assert row['venue_address'] == '31 N Lansdowne Ave, Lansdowne, Pennsylvania'
        assert row['ends_at'] is None and row['lat'] is None and row['lng'] is None
        assert row['description'].startswith('Synthetic fixture narrative.')
        assert row['registered_native_content']['description_field'] == 'rockhouse_event_description'
        assert row['image_evidence_url'] == row['event_url']
        native.validate_record(row, claim)
    original_lengths = [length for page in manifest['pages']
                        for length in page['native_description_original_chars']]
    assert max(original_lengths) > 6000


def test_captured_complete_rockhouse_widget_uses_its_own_scope(captured_lansdowne):
    manifest, pages = captured_lansdowne
    feed = manifest['listing']
    fetch = fetcher(pages)
    rows = calendar.collect(source(feed), fetch)
    assert len(rows) == 5
    assert [call.args[0] for call in fetch.call_args_list] == [feed, *manifest['detail_links']]
    assert all(row['registered_native_content']['description_field'] == 'rockhouse_event_description'
               for row in rows)
    # The real document carries WordPress SEO pagination. The reviewed RHP
    # archive contract owns a separate, fully rendered unfiltered List widget.
    assert calendar._html(pages[feed]).select_one('link[rel="next"]')


@pytest.mark.parametrize('mutation', ['flag', 'widget', 'view', 'filter', 'unclassed_filter', 'month', 'weekday'])
def test_rockhouse_scope_exception_requires_every_captured_contract_field(captured_lansdowne, mutation):
    manifest, pages = captured_lansdowne
    feed = manifest['listing']
    soup = calendar._html(pages[feed])
    if mutation == 'flag':
        soup.select_one('#isEventsArchivePage').decompose()
    elif mutation == 'widget':
        del soup.select_one('#rhp-events-pg-template')['id']
    elif mutation == 'view':
        soup.select_one('.eventDesktopView')['value'] = 'Grid'
    elif mutation in ('filter', 'unclassed_filter'):
        soup.select_one('#rhp_bar_rhp_gen')['value'] = 'music'
        if mutation == 'unclassed_filter':
            del soup.select_one('#rhp_bar_rhp_gen')['class']
    elif mutation == 'month':
        soup.select_one('.rhp-events-list-separator-month').string = 'November'
    else:
        soup.select_one('.singleEventDate').string = 'Mon, Nov 28'
    fetch = Mock()
    with pytest.raises(ValueError, match='html_calendar_rockhouse_scope_unverified'):
        calendar.collect(source(feed), fetch, listing=str(soup))
    fetch.assert_not_called()


@pytest.mark.parametrize('control', [
    '<div class="rhp__pagination"><a href="?rhp_paged=2">2</a></div>',
    '<div class="rhp-load-more"></div>',
    '<a href="?rhp_paged=2">More</a>',
    '<input type="hidden" name="rhp_paged" value="2">',
])
def test_rockhouse_native_pagination_remains_a_hold(captured_lansdowne, control):
    manifest, pages = captured_lansdowne
    feed = manifest['listing']
    soup = calendar._html(pages[feed])
    soup.select_one('#rhp-events-pg-template').append(calendar._html(control))
    fetch = Mock()
    with pytest.raises(ValueError, match='html_calendar_pagination_needed'):
        calendar.collect(source(feed), fetch, listing=str(soup))
    fetch.assert_not_called()


def test_rockhouse_widget_contract_never_erases_a_requested_filter(captured_lansdowne):
    manifest, pages = captured_lansdowne
    feed = manifest['listing']
    fetch = Mock()
    with pytest.raises(ValueError, match='html_calendar_rockhouse_scope_unverified'):
        calendar.collect(source(feed + '?rhp_bar_rhp_gen=music'), fetch, listing=pages[feed])
    fetch.assert_not_called()


@pytest.mark.parametrize('filename,url', [
    ('blackbird.html', 'https://www.blackbirdbooksandcoffee.com/events'),
    ('blackbird-page1.html', 'https://www.blackbirdbooksandcoffee.com/events?page=1'),
    ('quail_ridge.html', 'https://www.quailridgebooks.com/events'),
])
def test_actual_captured_pagination_cannot_be_certified_as_complete(filename, url):
    payload = (FIXTURES / filename).read_text()
    assert calendar.supports_listing(url, payload)
    next_page = 'https://www.blackbirdbooksandcoffee.com/events?page=1'
    fetch = fetcher({next_page: (FIXTURES / 'blackbird-page1.html').read_text()})
    with pytest.raises(ValueError, match='html_calendar_pagination_needed'):
        calendar.collect(source(url), fetch, listing=payload)
    assert fetch.call_count == (1 if filename == 'blackbird.html' else 0)


@pytest.mark.parametrize('control', [
    '<button>Load more</button>',
    '<a href="?month=next">Next Month</a>',
    '<button class="load-more">Browse</button>',
    '<nav class="pagination"><a href="?page=2">2</a></nav>',
    '<nav class="pagination"><button aria-current="page">1</button><button>2</button></nav>',
    '<button id="loadMoreEvents" class="eventList__showMore" data-offset="12" data-increment="12" data-options="events" disabled="disabled">More Events</button>',
    '<button id="loadMoreEvents" class="show_more_events" data-offset="6" disabled="true"><span>Load More Events</span></button>',
])
def test_pagination_requires_review_before_any_detail_is_fetched(control):
    fetch = Mock()
    with pytest.raises(ValueError, match='html_calendar_pagination_needed'):
        calendar.collect(source(), fetch, listing=listing(extra=control))
    fetch.assert_not_called()


def test_unrendered_facetwp_pager_cannot_certify_the_initial_events_as_complete():
    # Observed control/config shape from https://swallowhillmusic.org/concerts/
    # on 2026-11-22; event links are synthetic. The real preload reports 45 rows.
    control = ('<div class="facetwp-facet facetwp-facet-elevent_calendar_pager facetwp-type-pager" '
               'data-name="elevent_calendar_pager" data-type="pager"></div>'
               '<script>var FWP_JSON = {"preload_data":{"settings":{"pager":'
               '{"page":1,"per_page":9,"total_rows":45,"total_pages":5}}}};</script>')
    fetch = Mock()
    with pytest.raises(ValueError, match='html_calendar_pagination_needed'):
        calendar.collect(source(), fetch, listing=listing(extra=control))
    fetch.assert_not_called()


def loadomatic_page(url, current, total, urls, *, extra_query='', pager=''):
    config = ("<script>window.albany = function(common) { common.buildLoadOMatic({"
              "loadUrl: '" + url + "', currentPage: " + str(current) +
              ", totalPages: " + str(total) + ", extraQuery: '" + extra_query +
              "'}, false); }</script>")
    # Ten4 renders the listing wrapper and LoadOMatic controls as siblings.
    control = ('<div class="loadomatic"></div>'
               '<div class="loadomatic__elements">'
               '<button class="loadomatic__trigger loadomatic__trigger--hidden">'
               'Load more</button></div>' + pager)
    return listing(urls, extra=control + config)


def test_loadomatic_declared_pages_complete_before_any_detail_fetches():
    next_page = FEED + '?page=2'
    first = loadomatic_page(FEED, 1, 2, (ONE,))
    pager = ('<ul class="pagination"><li><button class="pagination__button" '
             'data-url="' + FEED + '">1</button>'
             '<li><span class="pagination__button pagination__button--current">2</span></ul>')
    last = loadomatic_page(next_page, 2, 2, (TWO,), pager=pager)
    fetch = fetcher({next_page: last, ONE: detail(event()), TWO: detail(event(TWO))})
    rows = calendar.collect(source(), fetch, listing=first)
    assert len(rows) == 2
    assert [call.args[0] for call in fetch.call_args_list] == [next_page, ONE, TWO]


@pytest.mark.parametrize('mutation,reason', [
    ('filtered', 'html_calendar_pagination_needed'),
    ('wrong_current', 'html_calendar_pagination_needed'),
    ('over_budget', 'html_calendar_pagination_needed'),
    ('wrong_url', 'html_calendar_pagination_scope_conflict'),
])
def test_loadomatic_requires_one_exact_unfiltered_bounded_contract(mutation, reason):
    current, total, url, extra = 1, 2, FEED, ''
    if mutation == 'filtered':
        extra = '&category=music'
    elif mutation == 'wrong_current':
        current = 2
    elif mutation == 'over_budget':
        total = calendar.MAX_LISTING_PAGES + 1
    elif mutation == 'wrong_url':
        url = BASE + '/calendar'
    fetch = Mock()
    with pytest.raises(ValueError, match=reason):
        calendar.collect(source(), fetch,
                         listing=loadomatic_page(url, current, total, (ONE,), extra_query=extra))
    fetch.assert_not_called()


def test_loadomatic_rejects_multiple_control_containers():
    markup = loadomatic_page(FEED, 1, 2, (ONE,)).replace(
        '<div class="loadomatic__elements">',
        '<div class="loadomatic__elements"></div><div class="loadomatic__elements">',
        1)
    fetch = Mock()
    with pytest.raises(ValueError, match='html_calendar_pagination_needed'):
        calendar.collect(source(), fetch, listing=markup)
    fetch.assert_not_called()


def hnm_page(urls, *, next_page=None, config=False):
    cards = '<div class="whatson-events-listing">' + ''.join(
        '<article><a href="' + url + '">Details</a></article>' for url in urls
    ) + '</div>'
    pager = (('<div class="paginate"><a class="btn btn-load" href="" '
              'data-container="whatson-events-listing" data-next-page="'
              + str(next_page) + '"><span>Load more</span></a></div>')
             if next_page else '')
    declared = (('<script>var HNM = {"ajaxurl":"' + BASE
                 + '/wp-admin/admin-ajax.php","baseurl":"' + BASE
                 + '"};</script><script src="' + BASE
                 + '/wp-content/themes/horniman-theme/assets/js/main.min.js?ver=1"></script>')
                if config else '')
    return '<html><body><main><h1>What\'s On</h1>' + cards + pager + declared + '</main></body></html>'


def test_hnm_ajax_theme_contract_collects_terminal_unfiltered_page():
    endpoint = BASE + '/wp-admin/admin-ajax.php?action=getEvents&page=2'
    first = hnm_page((ONE,), next_page=2, config=True)
    last = hnm_page((TWO,))
    fetch = fetcher({endpoint: last, ONE: detail(event()), TWO: detail(event(TWO))})
    rows = calendar.collect(source(), fetch, listing=first)
    assert len(rows) == 2
    assert [call.args[0] for call in fetch.call_args_list] == [endpoint, ONE, TWO]


@pytest.mark.parametrize('mutation', ['foreign_ajax', 'filtered', 'wrong_next', 'missing_theme'])
def test_hnm_ajax_theme_contract_rejects_ambiguous_or_filtered_controls(mutation):
    body = hnm_page((ONE,), next_page=3 if mutation == 'wrong_next' else 2, config=True)
    feed = FEED
    if mutation == 'foreign_ajax':
        body = body.replace(BASE + '/wp-admin/admin-ajax.php',
                            'https://other.example.org/wp-admin/admin-ajax.php')
    elif mutation == 'filtered':
        feed += '?category=music'
    elif mutation == 'missing_theme':
        body = body.replace('/wp-content/themes/horniman-theme/assets/js/main.min.js',
                            '/wp-content/themes/other/assets/js/main.min.js')
    fetch = Mock()
    with pytest.raises(ValueError, match='html_calendar_pagination_(?:needed|scope_conflict)'):
        calendar.collect(source(feed), fetch, listing=body)
    fetch.assert_not_called()


@pytest.mark.parametrize('next_page', [FEED + '/page/2/', FEED + '?page=2'])
def test_observed_next_pages_complete_before_any_detail_is_fetched(next_page):
    first = listing((ONE,), extra='<a rel="next" href="' + next_page + '">Next</a>')
    last = listing((TWO,), extra='<link rel="prev" href="' + FEED + '/">')
    fetch = fetcher({next_page: last, ONE: detail(event()), TWO: detail(event(TWO))})
    rows = calendar.collect(source(), fetch, listing=first)
    assert len(rows) == 2
    assert [call.args[0] for call in fetch.call_args_list] == [next_page, ONE, TWO]


def test_next_page_preserves_the_actual_calendar_query_selector():
    feed = FEED + '?venue=12'
    next_page = feed + '&page=2'
    first = listing((ONE,), extra='<link rel="next" href="' + next_page + '">')
    last = listing((TWO,), extra='<link rel="prev" href="' + feed + '">')
    fetch = fetcher({next_page: last, ONE: detail(event()), TWO: detail(event(TWO))})
    assert len(calendar.collect(source(feed), fetch, listing=first)) == 2


@pytest.mark.parametrize('next_page', [
    'https://other.example.org/events?page=2', FEED + '?venue=34&page=2',
    FEED + '?page=2', BASE + '/calendar/page/2/', FEED + '?venue=12&filter=all&page=2',
])
def test_pagination_cannot_escape_or_broaden_the_source_calendar_selector(next_page):
    feed = FEED + '?venue=12'
    fetch = Mock()
    with pytest.raises(ValueError, match='html_calendar_pagination_scope_conflict'):
        calendar.collect(source(feed), fetch,
            listing=listing((ONE,), extra='<link rel="next" href="' + next_page + '">'))
    fetch.assert_not_called()


def test_multiple_next_destinations_are_an_ambiguous_snapshot():
    fetch = Mock()
    body = listing((ONE,), extra='<link rel="next" href="?page=2"><link rel="next" href="?page=3">')
    with pytest.raises(ValueError, match='html_calendar_pagination_ambiguous'):
        calendar.collect(source(), fetch, listing=body)
    fetch.assert_not_called()


def test_repeated_or_cyclic_listing_pages_never_become_successful_empty():
    next_page = FEED + '?page=2'
    first = listing((ONE,), extra='<link rel="next" href="' + next_page + '">')
    for last, reason in (
        (listing((ONE,), extra='<link rel="next" href="?page=3">'), 'html_calendar_pagination_stalled'),
        (listing((TWO,), extra='<link rel="next" href="' + FEED + '">'), 'html_calendar_pagination_cycle'),
    ):
        fetch = fetcher({next_page: last})
        with pytest.raises(ValueError, match=reason):
            calendar.collect(source(), fetch, listing=first)
        assert fetch.call_count == 1


def test_four_page_wordpress_style_archive_completes_before_detail_fetches():
    # The previous 3-page cap blocked real archives with an explicit page 4.
    detail_urls = [BASE + '/event/four-page-' + str(n) for n in range(1, 5)]
    pages = {}
    for index, event_url in enumerate(detail_urls, start=1):
        current = FEED if index == 1 else FEED + '?page=' + str(index)
        next_page = FEED + '?page=' + str(index + 1)
        previous = FEED if index == 2 else FEED + '?page=' + str(index - 1)
        nav = ('<link rel="prev" href="' + previous + '">' if index > 1 else '')
        if index < 4:
            nav += '<link rel="next" href="' + next_page + '">'
        pages[current] = listing((event_url,), extra=nav)
        pages[event_url] = detail(event(event_url))
    fetch = fetcher(pages)
    records = calendar.collect(source(), fetch)
    assert len(records) == 4
    expected_pages = [FEED] + [FEED + '?page=' + str(n) for n in (2, 3, 4)]
    assert [call.args[0] for call in fetch.call_args_list][:4] == expected_pages
    assert [call.args[0] for call in fetch.call_args_list][4:] == detail_urls
    assert {row['event_url'] for row in records} == set(detail_urls)


def test_pagination_budget_refuses_a_prefix_before_fetching_event_details():
    pages = {}
    for index in range(1, calendar.MAX_LISTING_PAGES + 1):
        current = FEED if index == 1 else FEED + '?page=' + str(index)
        pages[current] = listing((BASE + '/event/show-' + str(index),),
            extra='<link rel="next" href="?page=' + str(index + 1) + '">')
    fetch = fetcher(pages)
    with pytest.raises(ValueError, match='html_calendar_pagination_limit'):
        calendar.collect(source(), fetch)
    assert fetch.call_count == calendar.MAX_LISTING_PAGES


def test_overbudget_calendar_is_not_silently_truncated_to_first_events():
    urls = [BASE + '/event/' + str(i) + '-concert' for i in range(calendar.MAX_DETAILS + 1)]
    fetch = Mock()
    with pytest.raises(ValueError, match='html_calendar_detail_limit'):
        calendar.collect(source(), fetch, listing=listing(urls))
    fetch.assert_not_called()


@pytest.mark.parametrize('url', [
    'https://other.example.org/event/away', 'https://www.venue.example.org/event/alias',
    'http://venue.example.org/event/http', 'https://venue.example.org:443/event/port',
    'https://127.0.0.1/event/private', 'javascript:alert(1)',
    BASE + '/events/category/music', BASE + '/events/2026/12',
])
def test_nonpublisher_and_calendar_index_links_are_not_fetched(url):
    fetch = fetcher({ONE: detail(event())})
    [row] = calendar.collect(source(), fetch, listing=listing((ONE, url)))
    assert row['event_url'] == ONE
    assert [call.args[0] for call in fetch.call_args_list] == [ONE]


@pytest.mark.parametrize('canonical,identity', [
    (TWO, ONE), (None, TWO), ('https://other.example.org/event/a', ONE),
])
def test_detail_canonical_and_event_identity_must_match_the_actual_fetch(canonical, identity):
    fetch = fetcher({ONE: detail(event(identity), canonical=canonical)})
    with pytest.raises(ValueError, match='html_calendar_(?:detail_identity_conflict|event_jsonld_missing)'):
        calendar.collect(source(), fetch, listing=listing((ONE,)))


def test_sidebar_events_are_not_imported_as_the_requested_detail():
    main = event()
    other = event(TWO, name='Unrelated sidebar event')
    [row] = calendar.collect(source(), fetcher({ONE: detail([main, other])}), listing=listing((ONE,)))
    assert row['title'] == 'Publisher event'


def test_page_local_multi_occurrence_jsonld_gets_stable_document_identities():
    page = BASE + '/event/four-day-festival'
    first = datetime.now(timezone.utc) + timedelta(days=2)
    rows = []
    for offset in range(4):
        starts = (first + timedelta(days=offset)).replace(microsecond=0)
        item = event(None, name='Four Day Festival',
                     startDate=starts.isoformat(), endDate=None)
        item.pop('@id', None)
        item.pop('url', None)
        rows.append(item)
    body = detail(rows, canonical=page).replace(
        '</head>', '<meta property="og:url" content="' + page + '"></head>').replace(
        '</html>', '<body><main><h1>Four Day Festival</h1></main></body></html>')
    result = calendar.collect(source(page.replace('/event/four-day-festival', '/events')),
                              fetcher({page: body}), listing=listing((page,)))
    assert len(result) == 4
    assert len({row['id'] for row in result}) == 4
    assert all(row['event_url'] == page for row in result)


def test_page_local_multi_occurrence_requires_document_and_clock_proof():
    page = BASE + '/event/four-day-festival'
    first = event(None, name='Four Day Festival',
                  startDate='2027-04-22T12:00:00+01:00', endDate=None)
    second = dict(first)
    for item in (first, second):
        item.pop('@id', None)
        item.pop('url', None)
    for body in (
        detail([first, second], canonical=page),
        detail([first, dict(second, startDate='2027-04-23T12:00:00')], canonical=page),
    ):
        with pytest.raises(ValueError, match='html_calendar_detail_identity_conflict'):
            calendar.collect(source(page.replace('/event/four-day-festival', '/events')),
                             fetcher({page: body}), listing=listing((page,)))


def test_local_place_and_image_references_keep_the_publishers_exact_facts():
    item = event()
    place = {**item['location'], '@id': '#place'}
    item['location'] = {'@id': '#place'}
    item['image'] = {'@id': '#poster'}
    poster = {'@id': '#poster', '@type': 'ImageObject', 'url': '/images/real.jpg', 'width': 800, 'height': 500}
    body = detail({'@graph': [item, place, poster]})
    [row] = calendar.collect(source(), fetcher({ONE: body}), listing=listing((ONE,)))
    assert row['venue_name'] == 'Publisher Hall'
    assert row['image_url'] == BASE + '/images/real.jpg'


def test_rockhouse_dom_narrative_is_bound_to_the_actual_event_and_not_truncated():
    at = (datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat() + 'T19:30:00-05:00'
    item = event(description=None, startDate=at, endDate=None)
    narrative = 'The visiting artist shares stories and performs songs. ' * 55 + 'Final event detail.'
    body = rockhouse_detail(item, '<p>' + narrative + '</p>')
    [row] = calendar.collect(source(), fetcher({ONE: body}), listing=listing((ONE,)))
    assert row['description'] == narrative
    assert row['registered_native_content']['description_field'] == 'rockhouse_event_description'
    assert row['registered_native_content']['evidence_url'] == ONE
    native.validate_record(row, source())


@pytest.mark.parametrize('change', [
    {'title': 'A different artist'}, {'date_label': 'Monday, January 01, 2001'},
    {'clock': '10:00 pm'}, {'extra': '<div class="singleEventDescription">Different body</div>'},
])
def test_rockhouse_body_requires_unambiguous_title_date_and_show_time_agreement(change):
    at = (datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat() + 'T19:30:00-05:00'
    item = event(description=None, startDate=at, endDate=None)
    body = rockhouse_detail(item, '<p>The actual artist narrative.</p>', **change)
    with pytest.raises(ValueError, match='html_calendar_description_(?:identity_conflict|ambiguous)'):
        calendar.collect(source(), fetcher({ONE: body}), listing=listing((ONE,)))


def test_jsonld_narrative_takes_priority_over_the_optional_dom_fallback():
    item = event()
    body = rockhouse_detail(item, '<p>Other visible text.</p>', title='Unrelated section')
    [row] = calendar.collect(source(), fetcher({ONE: body}), listing=listing((ONE,)))
    assert row['description'] == 'A conversation with the visiting artist.'
    assert row['registered_native_content']['description_field'] == 'description'


def test_unscoped_or_missing_dom_narrative_does_not_copy_site_metadata():
    item = event(description=None)
    body = detail(item, canonical=ONE).replace('</html>',
        '<body><meta name="description" content="The best venue in town.">'
        '<div class="singleEventDescription">An unrelated footer bio.</div></body></html>')
    [row] = calendar.collect(source(), fetcher({ONE: body}), listing=listing((ONE,)))
    assert row['description'] == ''
    assert row['registered_native_content']['description_field'] is None


def test_dom_narrative_still_requires_the_detail_canonical():
    item = event(description=None)
    body = rockhouse_detail(item, '<p>The actual artist narrative.</p>').replace(
        '<link rel="canonical" href="' + ONE + '">', '')
    with pytest.raises(ValueError, match='html_calendar_description_identity_conflict'):
        calendar.collect(source(), fetcher({ONE: body}), listing=listing((ONE,)))


def test_conflicting_event_and_venue_definitions_require_review():
    item = event()
    for graph, reason in (
        ([item, {**item, 'name': 'Different concert'}], 'conflicting_event_occurrence'),
        ([{**item, 'location': {'@id': '#place'}},
          {**item['location'], '@id': '#place'},
          {'@id': '#place', 'name': 'Different Hall'}], 'conflicting_jsonld_reference'),
    ):
        with pytest.raises(ValueError, match=reason):
            calendar.collect(source(), fetcher({ONE: detail(graph)}), listing=listing((ONE,)))


def test_failure_after_a_valid_detail_does_not_return_a_partial_snapshot():
    fetch = fetcher({ONE: detail(event()), TWO: '<main><h1>Unstructured concert</h1></main>'})
    with pytest.raises(ValueError, match='html_calendar_event_jsonld_missing'):
        calendar.collect(source(), fetch, listing=listing())
    assert fetch.call_count == 2


def test_naive_datetime_is_a_review_hold_without_inventing_the_venue_timezone():
    item = event(startDate='2026-11-28T19:00:00', endDate='2026-11-28T21:00:00')
    with pytest.raises(ValueError, match='timezone_unresolved'):
        calendar.collect(source(), fetcher({ONE: detail(item)}), listing=listing((ONE,)))


def test_cancellation_is_explicit_empty_not_a_failed_or_incomplete_fetch():
    item = event(eventStatus='https://schema.org/EventCancelled')
    assert calendar.collect(source(), fetcher({ONE: detail(item)}), listing=listing((ONE,))) == []


@pytest.mark.parametrize('capability', [None, True, '1', 0, 2])
@pytest.mark.parametrize('field', [calendar.CAPABILITY, native.CAPABILITY])
def test_capability_and_exact_source_identity_are_required_before_network(capability, field):
    fetch = Mock()
    claim = {**source(), field: capability}
    with pytest.raises(ValueError, match='unregistered_html_calendar'):
        calendar.collect(claim, fetch)
    fetch.assert_not_called()


def test_source_hash_cannot_authorize_a_different_listing():
    fetch = Mock()
    with pytest.raises(ValueError, match='unregistered_html_calendar'):
        calendar.collect({**source(), 'feed_url': BASE + '/shows'}, fetch)
    fetch.assert_not_called()


def test_deadline_expiration_after_fetch_does_not_return_a_partial_snapshot():
    fetch = fetcher({ONE: detail(event()), TWO: detail(event(TWO))})
    with patch.object(calendar, 'monotonic', side_effect=lambda: 2 if fetch.called else 0), \
            pytest.raises(ValueError, match='collection_deadline'):
        calendar.collect(source(), fetch, listing=listing(), deadline_at=1)
    assert fetch.call_count == 1


def test_deadline_also_covers_normalization_of_the_last_detail():
    fetch = fetcher({ONE: detail(event())})
    with patch.object(calendar, 'monotonic', side_effect=[0, 0, 0, 0, 2]), \
            pytest.raises(ValueError, match='collection_deadline'):
        calendar.collect(source(), fetch, listing=listing((ONE,)), deadline_at=1)


def test_malformed_and_oversize_detail_payloads_require_review():
    for body in (
        '<script type="application/ld+json">{bad}</script>',
        '<script type="application/ld+json">' + json.dumps(event()),
        '<html>' + 'x' * calendar.MAX_HTML_BYTES + '</html>',
    ):
        with pytest.raises(ValueError):
            calendar.collect(source(), fetcher({ONE: body}), listing=listing((ONE,)))


def test_different_query_selected_occurrences_are_not_collapsed():
    urls = [ONE + '?performance=1', ONE + '?performance=2']
    pages = {url: detail(event(url)) for url in urls}
    rows = calendar.collect(source(), fetcher(pages), listing=listing(urls))
    assert {row['event_url'] for row in rows} == set(urls)


def test_description_length_limit_preserves_native_evidence():
    item = event(description='x' * (native.MAX_DESCRIPTION + 1))
    row, = calendar.collect(source(), fetcher({ONE: detail(item)}), listing=listing((ONE,)))
    assert row['description'] == 'x' * native.MAX_DESCRIPTION
    native.validate_record(row, source())


# Publisher image regression: event metadata is preferred, and an unambiguous
# same-event WordPress upload is a narrowly scoped fallback for Cambridge PPF.
CAMBRIDGE_FEED = 'https://cambridgeppf.org/events-list/'
CAMBRIDGE_DETAIL = ('https://cambridgeppf.org/etn/healthy-walking-at-wandlebury-2/'
                    'healthy-walking-at-wandlebury-5/')
CAMBRIDGE_PHOTO = 'https://cambridgeppf.org/wp-content/uploads/2025/09/healthy-walkers-square.jpg'


def cambridge_detail(*, art='', image=None, title='Healthy Walking at Wandlebury'):
    payload = event(CAMBRIDGE_DETAIL, name=title, image=image)
    return (detail(payload).replace('</html>',
            '<body><main><h1>' + title + '</h1>' + art +
            '</main><aside><img src="/wp-content/uploads/2025/09/healthy-walkers-square.jpg"></aside>'
            '</body></html>'))


def test_cambridge_featured_photo_is_attached_to_existing_event_identity():
    page = cambridge_detail(art='<figure><img src="' + CAMBRIDGE_PHOTO + '"></figure>')
    [row] = calendar._detail(source(CAMBRIDGE_FEED), page, CAMBRIDGE_DETAIL)
    assert row['image_url'] == CAMBRIDGE_PHOTO
    assert row['image_evidence_url'] == CAMBRIDGE_DETAIL
    assert row['registered_native_content']['image_field'] == 'image'
    native.validate_record(row, source(CAMBRIDGE_FEED))


def test_cambridge_jsonld_event_image_takes_precedence():
    explicit = 'https://cambridgeppf.org/wp-content/uploads/2026/11/healthy-walking-poster.jpg'
    page = cambridge_detail(art='<img src="' + CAMBRIDGE_PHOTO + '">', image=explicit)
    [row] = calendar._detail(source(CAMBRIDGE_FEED), page, CAMBRIDGE_DETAIL)
    assert row['image_url'] == explicit


@pytest.mark.parametrize('art,title', [
    ('<img src="/wp-content/uploads/2025/09/park-logo.jpg">', 'Healthy Walking at Wandlebury'),
    ('<nav><img src="/wp-content/uploads/2025/09/healthy-walkers-square.jpg"></nav>', 'Healthy Walking at Wandlebury'),
    ('<img src="https://other.example.org/wp-content/uploads/healthy-walkers-square.jpg">', 'Healthy Walking at Wandlebury'),
    ('<img src="/wp-content/uploads/2025/09/healthy-walkers-square.jpg">'
     '<img src="/wp-content/uploads/2025/09/healthy-walking-poster.jpg">', 'Healthy Walking at Wandlebury'),
    ('<img src="/wp-content/uploads/2025/09/healthy-walkers-square.jpg">', 'Unrelated River Concert'),
])
def test_cambridge_rejects_ambiguous_unrelated_or_unsafe_art(art, title):
    page = cambridge_detail(art=art, title=title)
    [row] = calendar._detail(source(CAMBRIDGE_FEED), page, CAMBRIDGE_DETAIL)
    assert row.get('image_url') is None
    native.validate_record(row, source(CAMBRIDGE_FEED))


def test_cambridge_featured_fallback_does_not_apply_to_other_publishers():
    html = cambridge_detail(art='<img src="' + CAMBRIDGE_PHOTO + '">')
    [row] = calendar._detail(source(FEED), html.replace(CAMBRIDGE_DETAIL, ONE), ONE)
    assert row.get('image_url') is None



def test_fingerprint_tracks_one_detail_and_ignores_the_listing_and_source_label():
    first, second = event(ONE), event(TWO)

    def facts(name, heading, two):
        pages = {FEED: listing(heading=heading), ONE: detail(first), TWO: detail(two)}
        rows = calendar.collect({**source(), 'publisher_name': name}, fetcher(pages))
        return {row['id']: row['collector_event_content_v1'] for row in rows}

    baseline = facts('First label', 'Upcoming Events', second)
    assert baseline == facts('Renamed label', 'Events', second)
    changed = facts('First label', 'Upcoming Events', {**second, 'description': 'New programme'})
    assert changed[ONE + '#event'] == baseline[ONE + '#event']
    assert changed[TWO + '#event'] != baseline[TWO + '#event']
    assert changed[TWO + '#event']['facts']['description'] == 'New programme'
