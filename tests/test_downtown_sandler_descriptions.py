"""Exact event pages supply prose, bounded to verified publisher containers."""
from datetime import datetime, timedelta
from html import escape

import pytest

from roomquest import downtown_norfolk as downtown
from roomquest import hampton_roads_public_events as sandler


DOWNTOWN_URL = 'https://www.downtownnorfolk.org/event/fixture-dance'
SANDLER_URL = 'https://www.sandlercenter.org/events/detail/fixture-show'


def downtown_page(*, url=DOWNTOWN_URL, title='Fixture Dance', content=None):
    # Structure verified on /event/blues-dance-at-the-wells-theatre and
    # /event/new-community-days-at-the-virginia-zoo-7 on 2026-11-13.
    content = '<h2 class="on-detail">Details</h2><p>Learn the dance, then join the social session.</p>' if content is None else content
    return f'''<head><link rel="canonical" href="{escape(url)}"></head>
      <main id="page-content"><div class="container-fluid"><div><h1>{escape(title)}</h1></div>
        <div class="row padding-top gx-5"><div class="col-lg-6 col-xl-5 padding-bottom">
          <h2 class="on-detail">Dates and Times</h2><ul class="datelist"><li>Monday at 7pm</li></ul>
          <h2 class="on-detail">Location</h2><p>Wells Theatre, 110 East Tazewell St</p>
          <p><a href="https://other.example.com/full-details">visit website</a></p>{content}
        </div><div class="col-lg-6"><p>Unrelated sibling image caption and sponsor.</p></div></div>
      </div></main><div class="footer-links">Generic downtown marketing.</div>'''


def sandler_page(*, url=SANDLER_URL, title='Fixture Show', content=None):
    # Sandler's live /events/detail/beat template supplies og:url and repeats
    # h1.title for responsive layouts; its prose is in column_1 .leftColumn.
    content = '<div class="event_description expandable"><p>A live concert by a touring ensemble.</p></div>' if content is None else content
    return f'''<head><meta property="og:url" content="{escape(url)}"></head>
      <div id="content" role="main"><div class="event_detail one_sidebar_right has_branding">
        <div class="title_section"><div class="event_heading below_branding"><h1 class="title no_tagline">{escape(title)}</h1></div></div>
        <div class="wrapper"><div id="column_1"><div class="leftColumn">
          <div class="event_heading above_sidebar"><h1 class="title no_tagline">{escape(title)}</h1></div>
          {content}</div></div>
          <div class="rightColumn"><div class="event_description"><p>Sidebar event and ticket policies.</p></div></div>
        </div></div></div><footer>Newsletter subscription.</footer>'''


def test_downtown_details_exclude_other_sections_columns_and_second_page():
    content = '''<h2 class="on-detail">Details</h2><p>Beginner lessons &amp; a social dance.</p>
      <p>No experience or partner needed. <a href="https://other.example.com/more">More information</a>.</p>
      <nav>Next event</nav><!-- Internal calendar note. --><aside>Related event.</aside>
      <h2>Other Events</h2><p>Unrelated workshop.</p>'''
    row = {'event_url': DOWNTOWN_URL, 'title': 'Fixture Dance'}
    result = downtown.description_from_detail(downtown_page(content=content), row)
    assert result == 'Beginner lessons & a social dance.\nNo experience or partner needed.\nMore information\n.'
    assert row == {'event_url': DOWNTOWN_URL, 'title': 'Fixture Dance'}


@pytest.mark.parametrize('change', [
    {'url': DOWNTOWN_URL + '-other'}, {'title': 'Another Event'},
])
def test_downtown_rejects_a_different_event(change):
    with pytest.raises(ValueError, match='invalid_downtown_norfolk_detail_identity'):
        downtown.description_from_detail(downtown_page(**change), {'event_url': DOWNTOWN_URL, 'title': 'Fixture Dance'})


def test_downtown_does_not_guess_identity_or_content_boundaries():
    row = {'event_url': DOWNTOWN_URL, 'title': 'Fixture Dance'}
    for payload in [downtown_page().replace('rel="canonical"', 'rel="alternate"'),
                    downtown_page().replace('col-lg-6 col-xl-5 padding-bottom', 'unknown-layout')]:
        with pytest.raises(ValueError, match='invalid_downtown_norfolk_detail_'):
            downtown.description_from_detail(payload, row)


@pytest.mark.parametrize('content', ['', '<h2 class="on-detail">Details</h2><p></p>'])
def test_downtown_matched_page_without_prose_stays_empty(content):
    assert downtown.description_from_detail(downtown_page(content=content), {
        'event_url': DOWNTOWN_URL, 'title': 'Fixture Dance'}) == ''


def test_downtown_duplicate_details_are_not_combined():
    content = '<h2 class="on-detail">Details</h2><p>One.</p><h2 class="on-detail">Details</h2><p>Two.</p>'
    with pytest.raises(ValueError, match='invalid_downtown_norfolk_detail_content'):
        downtown.description_from_detail(downtown_page(content=content), {'event_url': DOWNTOWN_URL, 'title': 'Fixture Dance'})


def test_sandler_matches_og_url_and_responsive_titles_without_sidebar_copy():
    content = '<div class="event_description"><p>Enjoy chamber music &amp; improvisation.</p><nav>Other shows</nav><script>unrelated()</script></div>'
    row = {'event_url': SANDLER_URL, 'title': 'Fixture Show'}
    assert sandler.description_from_detail(sandler_page(content=content), row) == 'Enjoy chamber music & improvisation.'
    assert row == {'event_url': SANDLER_URL, 'title': 'Fixture Show'}


@pytest.mark.parametrize('payload', [
    sandler_page(url=SANDLER_URL + '-other'), sandler_page(title='Another Show'),
    sandler_page().replace('property="og:url"', 'property="og:image"'),
    sandler_page().replace('</head>', f'<link rel="canonical" href="{SANDLER_URL}-other"></head>'),
    sandler_page().replace('<h1 class="title no_tagline">Fixture Show</h1>', '<h1 class="title">Another Show</h1>', 1),
])
def test_sandler_rejects_wrong_or_missing_event_identity(payload):
    with pytest.raises(ValueError, match='invalid_sandler_detail_identity'):
        sandler.description_from_detail(payload, {'event_url': SANDLER_URL, 'title': 'Fixture Show'})


@pytest.mark.parametrize('content', ['', '<div class="event_description"></div>'])
def test_sandler_matched_page_without_prose_does_not_use_sidebar(content):
    assert sandler.description_from_detail(sandler_page(content=content), {
        'event_url': SANDLER_URL, 'title': 'Fixture Show'}) == ''


def test_sandler_rejects_ambiguous_primary_descriptions():
    content = '<div class="event_description">One.</div><div class="event_description">Two.</div>'
    with pytest.raises(ValueError, match='invalid_sandler_detail_content'):
        sandler.description_from_detail(sandler_page(content=content), {'event_url': SANDLER_URL, 'title': 'Fixture Show'})


@pytest.mark.parametrize('module,page,url', [(downtown, downtown_page, DOWNTOWN_URL), (sandler, sandler_page, SANDLER_URL)])
def test_detail_title_comparison_retains_existing_180_character_row_contract(module, page, url):
    title = 'A publisher event title ' * 12
    assert module.description_from_detail(page(title=title), {'event_url': url, 'title': title.strip()[:180]})


@pytest.mark.parametrize('multiple', [False, True])
def test_sandler_listing_mode_keeps_event_facts_and_existing_fetch_count(multiple):
    start = (datetime.now(sandler.ZONE) + timedelta(days=2)).replace(hour=19, minute=0, second=0, microsecond=0)
    date = f'<span class="m-date__singleDate">{start:%b %d / %Y}</span>'
    when = '' if multiple else f'{date}<span class="time"><span class="start">7:00 PM</span></span>'
    listing = f'<div class="eventItem"><div class="info"><h3 class="title"><a href="{SANDLER_URL}">Fixture Show</a></h3>{when}</div></div>'
    detail = f'''<div class="event_showings"><li id="showing_1"><span class="showings_date">{date}</span>
       <span class="wrapper"><span class="time">{start:%A} at 7:00pm</span></span></li></div>
       <div class="event_description"><p>The existing multishow description.</p></div>'''
    source = {'source_key': sandler.SANDLER, 'feed_url': sandler.SOURCES[sandler.SANDLER][0],
              'kind': 'html', 'platform_adapter': 'html', 'timezone': sandler.ZONE.key}
    pages = {source['feed_url']: listing, SANDLER_URL: detail}
    calls = []

    def fetch(url, accept):
        calls.append((url, accept))
        return pages[url]

    ordinary, = sandler.collect(source, fetch)
    ordinary_calls = calls[:]
    calls.clear()
    manifest_row, = sandler.collect(source, fetch, listing_only=True)
    assert {k: v for k, v in manifest_row.items() if k != 'description'} == {
        k: v for k, v in ordinary.items() if k != 'description'}
    assert manifest_row['description'] == ''
    assert calls == ordinary_calls
    assert len(calls) == (2 if multiple else 1)
