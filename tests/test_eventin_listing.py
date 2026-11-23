from datetime import datetime, timezone
from html import escape
from urllib.parse import urlencode
from unittest.mock import Mock

import pytest

from roomquest import eventin_listing as etn
from roomquest import preview_worker
from roomquest import uk_registered_listings as uk


class FrozenMeta(type):
    def __instancecheck__(cls, value):
        return isinstance(value, datetime)


class FrozenDateTime(datetime, metaclass=FrozenMeta):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 11, 22, 10, tzinfo=timezone.utc)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    for module in (etn, uk, preview_worker):
        monkeypatch.setattr(module, 'datetime', FrozenDateTime)


COTON = 'Coton Reserve, Grantchester Rd, Cambridge CB23 7PY'
PARK = 'Wandlebury Country Park, Cambridge, CB22 3AE'
CHAPEL = 'Leper Chapel, Newmarket Road, Cambridge, CB5 8JJ'
WALK = 'Every Thursday at Wandlebury, come rain or shine, we have a FREE healthy walking group. '
WALK_DETAIL = WALK + ('Meet at 10am for a one hour walk for experienced walkers, and '
                      'meet at 10.30am for a slower 30 min walk for less experienced walkers.')


def card(slug, title, day, location, narrative):
    return ('<div class="etn-event-item"><div class="etn-event-content">'
            f'<div class="etn-event-date">{day}</div>'
            f'<h3 class="etn-event-title"><a href="https://cambridgeppf.org/etn/{slug}/">{title}</a></h3>'
            f'<div class="etn-event-location">{location}</div><p>{narrative}</p></div></div>')


def detail(title, location, first, last, narrative):
    start, end = (datetime.fromisoformat(value) for value in (first, last))
    day_label = start.strftime('%B %-d, %Y')
    if start.date() != end.date():
        day_label += ' - ' + end.strftime('%B %-d, %Y')
    hours = start.strftime('%-I:%M %p').lower() + ' - ' + end.strftime('%-I:%M %p').lower()
    params = urlencode({'text': title, 'location': location,
                        'dates': start.strftime('%Y%m%dT%H%M%S') + '/' + end.strftime('%Y%m%dT%H%M%S')})
    return (f'<h2 class="etn-event-entry-title">{escape(title)}</h2>'
            f'<div class="etn-event-content-body">{escape(narrative)}</div>'
            '<div class="etn-event-meta-info"><ul>'
            f'<li><span>Date : </span>{day_label}</li>'
            f'<li><span>Time : </span>{hours}<span class="etn-event-timezone">(Europe/London)</span></li>'
            f'<li><span>Venue : </span>{location}</li></ul></div>'
            f'<a href="https://calendar.google.com/calendar/r/eventedit?{escape(params)}">Google</a>')


def collect(body, fetch=None):
    return uk.collect({'feed_url': etn.URL, 'source_key': uk.source_key(etn.URL)},
                      fetch or Mock(side_effect=AssertionError('No request permitted')), listing=body)


def test_duplicate_styles_merge_only_consistent_evidence_and_no_detail_requests():
    short = card('work', 'Volunteer Work Party', 'November 24, 2026', '', 'Tue 24 Nov, 10.30am – 1.30pm Help care')
    full = card('work', 'Volunteer Work Party', 'November 24, 2026', COTON, 'Tue 24 Nov, 10.30am – 1.30pm Help care for the reserve.')
    rows = collect(short + full + full)
    assert len(rows) == 1
    assert rows[0]['starts_at'] == '2026-11-24T10:30:00+00:00'
    assert rows[0]['ends_at'] == '2026-11-24T13:30:00+00:00'
    assert rows[0]['venue_address'] == 'Grantchester Rd, Cambridge CB23 7PY, United Kingdom'
    assert rows[0]['timezone'] == 'Europe/London'


@pytest.mark.parametrize('changed', [
    ('November 24, 2026', 'November 25, 2026'),
    ('Volunteer Work Party', 'Other Event'),
    (COTON, CHAPEL),
    ('Tue 24 Nov, 10.30am – 1.30pm Work', 'Tue 24 Nov, 11am – 1pm Different'),
])
def test_conflicting_duplicate_card_is_held(changed):
    body = card('work', 'Volunteer Work Party', 'November 24, 2026', COTON, 'Tue 24 Nov, 10.30am – 1.30pm Work')
    with pytest.raises(ValueError, match='eventin_conflicting_cards'):
        collect(body + body.replace(*changed))


def test_two_explicit_carol_sessions_and_overnight_communion():
    body = card('carols', 'Christmas Carols', 'December 13, 2026', CHAPEL,
                'Sun 13 Dec, 4pm – 5pm & 5pm – 6pm. Carols in the chapel.')
    body += card('communion', 'Midnight Communion', 'December 24, 2026', CHAPEL,
                 'Thur 24 Dec, 11.30pm – 12.30am. Simple service.')
    rows = collect(body)
    assert len(rows) == 3
    assert rows[0]['starts_at'].startswith('2026-12-13T16:00')
    assert rows[1]['starts_at'].startswith('2026-12-13T17:00')
    assert rows[2]['ends_at'] == '2026-12-25T00:30:00+00:00'


def test_unconfirmed_location_is_held_without_fetch():
    valid = card('work', 'Work', 'November 24, 2026', COTON, 'Tue 24 Nov, 10.30am – 1.30pm Work.')
    tbc = card('tbc', 'Unconfirmed', 'November 24, 2026', 'Location TBC', 'Tue 24 Nov, 10.30am – 1.30pm Work.')
    assert len(collect(valid + tbc)) == 1


def test_only_listed_walking_dates_use_one_explicit_weekly_template():
    first_slug = 'healthy-walking-at-wandlebury-2/healthy-walking-at-wandlebury-5'
    second_slug = 'healthy-walking-at-wandlebury-2/healthy-walking-at-wandlebury-6'
    body = card(first_slug, 'Healthy Walking at Wandlebury', 'November 26, 2026', PARK, WALK)
    body += card(second_slug, 'Healthy Walking at Wandlebury', 'December 3, 2026', PARK, WALK)
    fetch = Mock(return_value=detail('Healthy Walking at Wandlebury', PARK, '2026-11-26T10:00', '2026-11-26T11:00', WALK_DETAIL))
    rows = collect(body, fetch)
    assert len(rows) == 4
    assert [r['starts_at'] for r in rows] == [
        '2026-11-26T10:00:00+00:00', '2026-11-26T10:30:00+00:00',
        '2026-12-03T10:00:00+00:00', '2026-12-03T10:30:00+00:00']
    fetch.assert_called_once_with('https://cambridgeppf.org/etn/' + first_slug + '/', 'text/html')


def test_changed_walking_template_is_held():
    slug = 'healthy-walking-at-wandlebury-2/healthy-walking-at-wandlebury-5'
    body = card(slug, 'Healthy Walking at Wandlebury', 'November 26, 2026', PARK, WALK)
    page = detail('Healthy Walking at Wandlebury', PARK, '2026-11-26T10:00', '2026-11-26T11:00',
                  WALK_DETAIL.replace('10.30am', '11.30am'))
    with pytest.raises(ValueError, match='eventin_series_schedule_unverified'):
        collect(body, Mock(return_value=page))


def test_family_date_and_session_cartesian_product_is_publisher_explicit():
    narrative = 'Sat 5 Dec & Sun 6 Dec, 10am – 12pm, 1pm – 3pm & 4pm – 6pm (Adults/Older Teens) Each workshop lasts for 2-hours.'
    body = card('wreath', 'Winter Wreath Making for Families', 'December 5, 2026', PARK, narrative)
    page = detail('Winter Wreath Making for Families', PARK, '2026-12-05T10:00', '2026-12-06T18:00', narrative)
    rows = collect(body, Mock(return_value=page))
    assert len(rows) == 6
    assert all(r['starts_at'][:10] in ('2026-12-05', '2026-12-06') for r in rows)
    assert sum(r['title'].endswith('(Adults/Older Teens)') for r in rows) == 2


def test_changed_family_slots_do_not_become_one_continuous_event():
    narrative = 'Sat 5 Dec & Sun 6 Dec, 10am – 12pm, 1pm – 3pm & 4pm – 6pm (Adults/Older Teens)'
    body = card('wreath', 'Winter Wreath Making for Families', 'December 5, 2026', PARK, narrative)
    page = detail('Winter Wreath Making for Families', PARK, '2026-12-05T10:00', '2026-12-06T18:00', 'Sessions to be confirmed.')
    with pytest.raises(ValueError, match='eventin_family_schedule_unverified'):
        collect(body, Mock(return_value=page))


@pytest.mark.parametrize('old,new,reason', [
    ('Europe/London', 'UTC', 'identity_unverified'),
    ('20261126T100000', '20261126T090000', 'schedule_conflict'),
    ('November 26, 2026', 'November 25, 2026', 'schedule_conflict'),
    (PARK, CHAPEL, 'venue_conflict'),
])
def test_detail_calendar_links_must_agree_with_visible_fields(old, new, reason):
    slug = 'healthy-walking-at-wandlebury-2/healthy-walking-at-wandlebury-5'
    body = card(slug, 'Healthy Walking at Wandlebury', 'November 26, 2026', PARK, WALK)
    page = detail('Healthy Walking at Wandlebury', PARK, '2026-11-26T10:00', '2026-11-26T11:00', WALK_DETAIL)
    with pytest.raises(ValueError, match=reason):
        collect(body, Mock(return_value=page.replace(old, new)))


def test_ongoing_bounded_range_retains_publisher_start_and_end():
    narrative = 'Sat 21 Nov – Sun 10 Jan Trail runs at Wandlebury.'
    body = card('trail', 'Reindeer Round-Up Trail', 'November 21, 2026', PARK, narrative)
    page = detail('Reindeer Round-Up Trail', PARK, '2026-11-21T08:00', '2027-01-10T17:00', narrative)
    row = collect(body, Mock(return_value=page))[0]
    assert row['starts_at'] == '2026-11-21T08:00:00+00:00'
    assert row['ends_at'] == '2027-01-10T17:00:00+00:00'


def test_detail_budget_stops_before_ninth_fetch():
    body = ''.join(card('other-' + str(i), 'Other', 'November 26, 2026', PARK, 'Starts soon.') for i in range(9))
    page = detail('Other', PARK, '2026-11-26T10:00', '2026-11-26T11:00', 'Published description.')
    fetch = Mock(return_value=page)
    with pytest.raises(ValueError, match='eventin_calendar_detail_limit'):
        collect(body, fetch)
    assert fetch.call_count == 8


CAMBRIDGE_WALK_IMAGE = 'https://cambridgeppf.org/wp-content/uploads/2025/09/healthy-walkers-square.jpg'


def test_wandlebury_eventin_detail_image_reused_across_explicit_sessions_and_dates():
    first_slug = 'healthy-walking-at-wandlebury-2/healthy-walking-at-wandlebury-5'
    second_slug = 'healthy-walking-at-wandlebury-2/healthy-walking-at-wandlebury-6'
    body = (card(first_slug, 'Healthy Walking at Wandlebury', 'November 26, 2026', PARK, WALK)
            + card(second_slug, 'Healthy Walking at Wandlebury', 'December 3, 2026', PARK, WALK))
    page = detail('Healthy Walking at Wandlebury', PARK,
                  '2026-11-26T10:00', '2026-11-26T11:00', WALK_DETAIL)
    page += '<div class="etn-event-thumb"><img src="' + CAMBRIDGE_WALK_IMAGE + '"></div>'
    fetch = Mock(return_value=page)
    rows = collect(body, fetch)
    assert len(rows) == 4
    assert all(row['image_url'] == CAMBRIDGE_WALK_IMAGE for row in rows)
    assert all(row['image_provenance'] == 'publisher_event_candidates_v1' for row in rows)
    assert all(row['image_extractor_version'] == 'publisher_event_candidates_v1' for row in rows)
    assert all(row['image_evidence_url'].startswith('https://cambridgeppf.org/etn/')
               for row in rows)
    fetch.assert_called_once()


@pytest.mark.parametrize('image_html', [
    '<div class="etn-event-thumb"><img src="https://other.example.com/wp-content/uploads/healthy-walkers-square.jpg"></div>',
    '<div class="etn-event-thumb"><img src="/wp-content/uploads/2025/09/logo.jpg"></div>',
    '<aside><img class="wp-post-image" src="/wp-content/uploads/2025/09/healthy-walkers-square.jpg"></aside>',
    '<div class="etn-event-thumb"><img src="/wp-content/uploads/2025/09/healthy-walkers-square.jpg">'
    '<img src="/wp-content/uploads/2025/09/healthy-walking-poster.jpg"></div>',
    '<div class="etn-event-thumb"><img src="/wp-content/uploads/2025/09/sponsor-poster.jpg"></div>',
])
def test_eventin_rejects_offsite_brand_related_or_ambiguous_images(image_html):
    slug = 'healthy-walking-at-wandlebury-2/healthy-walking-at-wandlebury-5'
    body = card(slug, 'Healthy Walking at Wandlebury', 'November 26, 2026', PARK, WALK)
    page = detail('Healthy Walking at Wandlebury', PARK,
                  '2026-11-26T10:00', '2026-11-26T11:00', WALK_DETAIL) + image_html
    rows = collect(body, Mock(return_value=page))
    assert len(rows) == 2
    assert all(row.get('image_url') is None for row in rows)


def test_eventin_never_extracts_photo_from_unfetched_timed_card():
    body = card('work', 'Volunteer Work Party', 'November 24, 2026', COTON,
                'Tue 24 Nov, 10.30am – 1.30pm Help care for the reserve.')
    rows = collect(body)
    assert len(rows) == 1
    assert rows[0].get('image_url') is None


def test_eventin_ordinary_wordpress_figure_exposes_original_walking_photo():
    slug = 'healthy-walking-at-wandlebury-2/healthy-walking-at-wandlebury-5'
    body = card(slug, 'Healthy Walking at Wandlebury', 'November 26, 2026', PARK, WALK)
    page = detail('Healthy Walking at Wandlebury', PARK,
                  '2026-11-26T10:00', '2026-11-26T11:00', WALK_DETAIL)
    page += ('<main><figure class="wp-block-image"><img src="'
             'https://cambridgeppf.org/wp-content/uploads/2025/09/'
             'healthy-walkers-square.jpg"></figure></main>')
    rows = collect(body, Mock(return_value=page))
    assert len(rows) == 2
    assert {row.get('image_url') for row in rows} == {CAMBRIDGE_WALK_IMAGE}
    assert all(row.get('image_evidence_url', '').endswith('/' + slug + '/')
               for row in rows)


@pytest.mark.parametrize('wrapper', [
    '<aside>{}</aside>',
    '<nav>{}</nav>',
    '<div class="related-events">{}</div>',
    '<div class="sidebar">{}</div>',
    '<div class="recommended-events">{}</div>',
])
def test_eventin_general_fallback_rejects_secondary_event_artwork(wrapper):
    slug = 'healthy-walking-at-wandlebury-2/healthy-walking-at-wandlebury-5'
    body = card(slug, 'Healthy Walking at Wandlebury', 'November 26, 2026', PARK, WALK)
    photo = '<img src="' + CAMBRIDGE_WALK_IMAGE + '">'
    page = detail('Healthy Walking at Wandlebury', PARK,
                  '2026-11-26T10:00', '2026-11-26T11:00', WALK_DETAIL)
    rows = collect(body, Mock(return_value=page + wrapper.format(photo)))
    assert len(rows) == 2
    assert all(row.get('image_url') is None for row in rows)



def test_actual_cambridge_walking_jpg_filename_matches_image_parser():
    """Regression for incorrect double escaping of the image-extension regex."""
    from bs4 import BeautifulSoup
    url = ('https://cambridgeppf.org/etn/healthy-walking-at-wandlebury-2/'
           'healthy-walking-at-wandlebury-5/')
    html = ('<main><h2 class="etn-event-entry-title">Healthy Walking at Wandlebury</h2>'
            '<figure><img src="https://cambridgeppf.org/wp-content/uploads/'
            '2025/09/healthy-walkers-square.jpg"></figure></main>')
    result = etn.event_photo(BeautifulSoup(html, 'html.parser'),
                             'Healthy Walking at Wandlebury', url)
    assert result == CAMBRIDGE_WALK_IMAGE


def test_real_jpg_path_guard_excludes_unrelated_uploads():
    from bs4 import BeautifulSoup
    url = ('https://cambridgeppf.org/etn/healthy-walking-at-wandlebury-2/'
           'healthy-walking-at-wandlebury-5/')
    for name in ('logo.jpg', 'healthy-walkers-square.svg', 'walking-festival.jpg'):
        html = ('<main><figure><img src="https://cambridgeppf.org/'
                'wp-content/uploads/2025/09/' + name + '"></figure></main>')
        assert etn.event_photo(BeautifulSoup(html, 'html.parser'),
                               'Healthy Walking at Wandlebury', url) is None
