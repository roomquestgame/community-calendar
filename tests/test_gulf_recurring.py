"""Regression coverage for reviewed Gulf publisher identity/time/location rules."""
from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from roomquest import gulf_recurring as gulf


NOW = datetime(2026, 11, 14, 14, 40, tzinfo=timezone.utc)
MAPLE_POLICY = ('<span>ALL SHOWS 21+</span><p>Everyone must show a valid form of ID at the door.</p>')


@pytest.fixture(autouse=True)
def fixed_preview_horizon(monkeypatch):
    # The collector's own supplied clock enforces the tested 60-day window.
    # Avoid the shared renderer additionally filtering fixed publisher fixtures
    # according to the wall clock on whichever day this regression suite runs.
    monkeypatch.setattr('roomquest.preview_worker._future_datetime',
                        lambda value: value.astimezone(timezone.utc))


def source(key):
    return dict(source_key=key, feed_url=gulf.SOURCES[key], kind='html',
                platform_adapter='html', timezone=gulf.ZONE)


def page(url, content):
    return f'<html><head><link rel="canonical" href="{url}"></head>{content}</html>'


def collect(key, pages):
    calls = []

    def fetch(url, accept):
        assert accept == 'text/html'
        calls.append(url)
        return pages[url]

    return gulf.collect(source(key), fetch, now=NOW), calls


def wix_event(key=gulf.WAMA):
    if key == gulf.MAPLE:
        venue, street, number, name, city, region, postal, lat, lng = (
            'Maple Leaf Bar', '8316 Oak St', '8316', 'Oak Street', 'New Orleans',
            'LA', '70118', 29.9489404, -90.1320744)
    elif key == gulf.NOTC:
        venue, street, number, name, city, region, postal, lat, lng = (
            'Tad Gormley Stadium', '5400 Marconi Dr', '5400', 'Marconi Drive',
            'New Orleans', 'LA', '70124', 29.989856, -90.0996099)
    else:
        venue, street, number, name, city, region, postal, lat, lng = (
            'Walter Anderson Museum of Art', '510 Washington Ave', '510',
            'Washington Avenue', 'Ocean Springs', 'MS', '39564', 30.4105399, -88.8275095)
    full_street = f'{street}, {city}, {region} {postal}, USA'
    return {
        'id': 'efe159e7-0207-457c-9b48-5e56111e5a8e',
        'title': 'Holiday Bazaar', 'slug': 'holiday-bazaar', 'status': 0,
        'publishedDate': '2026-10-01T12:00:00Z', 'description': 'Local artists and makers.',
        'mainImage': {'url': 'https://static.wixstatic.com/media/'
                            + gulf.WIX_OWNERS[key] + '_' + 'a' * 32 + '~mv2.jpg'},
        'scheduling': {'config': {'scheduleTbd': False, 'timeZoneId': gulf.ZONE,
                                 'startDate': '2026-12-05T17:00:00Z',
                                 'endDate': '2026-12-05T20:00:00Z', 'endDateHidden': False}},
        'location': {'name': venue, 'address': full_street, 'type': 0, 'tbd': False,
                     'coordinates': {'lat': lat, 'lng': lng},
                     'fullAddress': {'country': 'US', 'subdivision': region, 'city': city,
                                     'postalCode': postal, 'formattedAddress': full_street,
                                     'streetAddress': {'number': number, 'name': name},
                                     'geocode': {'latitude': lat, 'longitude': lng}}},
    }


def wix_page(key, events, *, has_more=False, featured=None, policy=None):
    widgets = {'calendar': {'events': {'hasMore': has_more, 'moreLoading': False, 'events': events}}}
    if featured is not None:
        widgets['featured'] = {'events': {'events': [featured], 'moreLoading': False}}
    data = {'appsWarmupData': {gulf.WIX_APP: widgets}}
    if policy is None:
        policy = MAPLE_POLICY if key == gulf.MAPLE else ''
    return page(gulf.SOURCES[key], '<script id="wix-warmup-data" type="application/json">'
                + json.dumps(data) + '</script>' + policy)


@pytest.mark.parametrize('key', list(gulf.SOURCES))
def test_canonical_publisher_is_required(key):
    payload = '<base href="https://elsewhere.example/"><link rel="canonical" href="https://elsewhere.example/">'
    with pytest.raises(ValueError, match='publisher_unverified'):
        collect(key, {gulf.SOURCES[key]: payload})


@pytest.mark.parametrize('field,value', [
    ('feed_url', gulf.SOURCES[gulf.WAMA] + '?page=2'), ('timezone', 'UTC'),
    ('kind', 'json'), ('platform_adapter', 'wix'), ('source_key', 'unreviewed_source'),
])
def test_unregistered_source_is_rejected_before_fetch(field, value):
    config = source(gulf.WAMA)
    config[field] = value
    with pytest.raises(ValueError, match='unregistered_gulf_recurring_source'):
        gulf.collect(config, lambda *_: pytest.fail('Unexpected network call'), now=NOW)


def test_wix_keeps_own_event_pin_image_and_multiday_span():
    item = wix_event()
    item['scheduling']['config'].update(startDate='2026-12-18T17:00:00Z', endDate='2027-01-03T23:00:00Z')
    rows, calls = collect(gulf.WAMA, {gulf.SOURCES[gulf.WAMA]: wix_page(gulf.WAMA, [item])})
    row, = rows
    assert calls == [gulf.SOURCES[gulf.WAMA]]
    assert row['ends_at'] == '2027-01-03T23:00:00+00:00'
    assert row['lat'] == 30.4105399 and row['lng'] == -88.8275095
    assert row['image_url'] == item['mainImage']['url']
    assert row['image_evidence_url'] == gulf.SOURCES[gulf.WAMA]
    assert row['details_evidence_url'] == row['event_url']
    assert row['description'] == 'Local artists and makers.'


@pytest.mark.parametrize('change', ['street_number', 'street_name', 'coordinates', 'status', 'schedule_tbd'])
def test_wix_holds_conflicting_venue_or_unpublished_event(change):
    item = wix_event()
    if change == 'street_number':
        item['location']['address'] = item['location']['fullAddress']['formattedAddress'] = (
            '3500 Park Rd, Ocean Springs, MS 39564, USA')
    elif change == 'street_name':
        item['location']['fullAddress']['streetAddress']['name'] = 'Park Road'
    elif change == 'coordinates':
        item['location']['coordinates']['lat'] += 0.1
    elif change == 'status':
        item['status'] = 1
    else:
        item['scheduling']['config']['scheduleTbd'] = True
    rows, _ = collect(gulf.WAMA, {gulf.SOURCES[gulf.WAMA]: wix_page(gulf.WAMA, [item])})
    assert rows == []


def test_wix_uses_complete_list_and_does_not_expand_recurrence():
    first = wix_event(gulf.MAPLE)
    far = deepcopy(first)
    far.update(id='73e0745c-56ad-43b5-ba84-208de3e2a437', slug='beyond-horizon')
    far['scheduling']['config'].update(startDate='2027-01-30T17:00:00Z', endDate='2027-01-30T20:00:00Z')
    first['scheduling']['config']['recurrences'] = {'occurrences': [], 'status': 0}
    payload = wix_page(gulf.MAPLE, [first, far], featured=first)
    rows, _ = collect(gulf.MAPLE, {gulf.SOURCES[gulf.MAPLE]: payload})
    assert [row['id'] for row in rows] == [first['id']]


def test_maple_preserves_visible_21_plus_calendar_policy_for_every_event():
    first = wix_event(gulf.MAPLE)
    second = deepcopy(first)
    second.update(id='73e0745c-56ad-43b5-ba84-208de3e2a437', slug='second-show')
    rows, calls = collect(gulf.MAPLE, {gulf.SOURCES[gulf.MAPLE]: wix_page(gulf.MAPLE, [first, second])})
    assert len(rows) == 2 and calls == [gulf.SOURCES[gulf.MAPLE]]
    for row in rows:
        assert row['publisher_details']['audience'] == (
            '21+; valid ID required at the door. Calendar policy: https://www.mapleleafbar.com/calendar')
        assert row['details_evidence_url'] == row['event_url']
    other, _ = collect(gulf.WAMA, {gulf.SOURCES[gulf.WAMA]: wix_page(gulf.WAMA, [wix_event()], policy=MAPLE_POLICY)})
    assert 'audience' not in other[0]['publisher_details']


@pytest.mark.parametrize('policy', ['', MAPLE_POLICY.replace('21+', '18+'),
                                    '<script>' + MAPLE_POLICY + '</script>'])
def test_maple_does_not_emit_unverified_or_script_only_audience_policy(policy):
    with pytest.raises(ValueError, match='gulf_maple_audience_unverified'):
        collect(gulf.MAPLE, {gulf.SOURCES[gulf.MAPLE]: wix_page(gulf.MAPLE, [wix_event(gulf.MAPLE)], policy=policy)})


def test_wix_pagination_and_conflicting_duplicates_fail_closed():
    first = wix_event()
    payload = wix_page(gulf.WAMA, [first], has_more=True, featured=first)
    with pytest.raises(ValueError, match='pagination_requires_review'):
        collect(gulf.WAMA, {gulf.SOURCES[gulf.WAMA]: payload})
    conflict = deepcopy(first)
    conflict['title'] = 'Conflicting title'
    with pytest.raises(ValueError, match='identity_conflict'):
        collect(gulf.WAMA, {gulf.SOURCES[gulf.WAMA]: wix_page(gulf.WAMA, [first, conflict])})


def test_notc_rivertown_district_has_no_precise_pin():
    item = wix_event(gulf.NOTC)
    location = item['location']
    location.update(name='Rivertown', address='Rivertown, Kenner, LA 70062, USA')
    location['fullAddress'].update(city='Kenner', formattedAddress=location['address'],
                                   streetAddress={'number': '', 'name': ''})
    rows, _ = collect(gulf.NOTC, {gulf.SOURCES[gulf.NOTC]: wix_page(gulf.NOTC, [item])})
    row, = rows
    assert row['lat'] is row['lng'] is None
    assert row['reason'] == 'missing_verified_venue_geo'
    assert row['publisher_details'] == {
        'meeting_location': 'Rivertown district; exact starting point is not supplied.'}


def rapahope_pages():
    url = gulf.SOURCES[gulf.RAPA] + '/turkeytrot'
    event = {'@type': 'Event', '@context': 'https://schema.org',
             'name': 'Turkey Trot for Hope — Rapahope',
             'startDate': '2026-11-26T08:00:00-0600', 'endDate': '2026-11-26T10:00:00-0600',
             'location': {'@type': 'Place', 'name': 'Mardi Gras Park',
                          'address': '104 South Royal Street\nMobile, AL, 36602\nUnited States'}}
    image = ('https://images.squarespace-cdn.com/content/v1/5e7d112f9b046e73144336fd/'
             '1787078182673-QFB0ZGN19LS9ISHWB4KK/Turkey+Trot+2026+Logo+Wide.png')
    index = page(gulf.SOURCES[gulf.RAPA], f'''
      <div class="eventlist"><article class="eventlist-event--upcoming">
        <a class="eventlist-title-link" href="/fundraising/holidaycards">Holiday Cards</a>
      </article><article class="eventlist-event--upcoming">
        <a class="eventlist-title-link" href="/fundraising/turkeytrot">Turkey Trot for Hope</a>
        <time class="event-time-localized-start" datetime="2026-11-26">8:00 AM</time>
        <time class="event-time-localized-end" datetime="2026-11-26">10:00 AM</time>
        <img class="eventlist-thumbnail" src="{image}">
      </article></div>''')
    metadata = {'og:street-address': '104 South Royal Street', 'og:locality': 'Mobile',
                'og:region': 'AL', 'og:postal-code': '36602', 'og:latitude': '30.682088',
                'og:longitude': '-88.0151655'}
    detail = page(url, ''.join(f'<meta property="{key}" content="{value}">' for key, value in metadata.items())
                  + '<script type="application/ld+json">' + json.dumps(event) + '</script>'
                  + '<body id="item-64b812b221cff33e72aee35e"><h1 class="eventitem-title">Turkey Trot for Hope</h1>'
                  + '<div class="eventitem-column-content">Run to support camp for children with cancer.</div></body>')
    return {gulf.SOURCES[gulf.RAPA]: index, url: detail}


def test_rapahope_fetches_only_normal_html_and_ignores_merchandise_campaign():
    pages = rapahope_pages()
    rows, calls = collect(gulf.RAPA, pages)
    row, = rows
    assert set(calls) == set(pages)
    assert all('?' not in url for url in calls)
    assert row['starts_at'] == '2026-11-26T14:00:00+00:00'
    assert row['ends_at'] == '2026-11-26T16:00:00+00:00'
    assert row['venue_address'] == '104 South Royal Street, Mobile, AL 36602'
    assert row['lat'] == 30.682088 and row['lng'] == -88.0151655
    assert row['id'] == '64b812b221cff33e72aee35e'
    assert row['image_evidence_url'] == gulf.SOURCES[gulf.RAPA]


def test_rapahope_rejects_detail_time_conflicts_and_headquarters_pin():
    pages = rapahope_pages()
    url = gulf.SOURCES[gulf.RAPA] + '/turkeytrot'
    pages[url] = pages[url].replace('T08:00:00-0600', 'T09:00:00-0600')
    with pytest.raises(ValueError, match='identity_conflict'):
        collect(gulf.RAPA, pages)
    pages = rapahope_pages()
    pages[url] = pages[url].replace('content="104 South Royal Street"', 'content="205 Lambert Avenue"')
    assert collect(gulf.RAPA, pages)[0] == []


def market_page():
    parts = ['<base href="https://crescentcityfarmersmarket.org/">']
    dates = {'Uptown': ('November 17, 2026', '8 am - 12 pm'),
             'Mid-City': ('November 19, 2026', '3 pm - 7 pm'),
             'City Park': ('November 15, 2026', '8 am - 12 pm')}
    for name, (venue, street, _, _) in gulf.MARKET_PLACES.items():
        day, hours = dates[name]
        parts.append(f'<div class="card"><div class="card-divider"><span class="text-uc">{name}</span></div>'
                     f'<div class="card-section"><h4>{day}</h4><h5>{hours}</h5><p>{venue}<br>{street}</p></div></div>')
    return ''.join(parts)


def test_markets_omit_city_park_overlap_and_keep_other_explicit_next_dates():
    rows, calls = collect(gulf.MARKETS, {gulf.SOURCES[gulf.MARKETS]: market_page()})
    assert len(rows) == 2 and len(calls) == 1
    assert {row['id'] for row in rows} == {'uptown:2026-11-17', 'mid-city:2026-11-19'}
    assert all(row['event_url'] != gulf.MARKET_PAGES['City Park'] for row in rows)
    uptown = next(row for row in rows if row['id'].startswith('uptown:'))
    assert uptown['venue_address'] == '25 Walnut Street, New Orleans, LA'
    assert uptown['lat'] == 29.9256225 and uptown['lng'] == -90.1345546
    midcity = next(row for row in rows if row['id'].startswith('mid-city:'))
    assert midcity['ends_at'] == '2026-11-20T01:00:00+00:00'
    assert sum(row['lat'] is None for row in rows) == 1
    with pytest.raises(ValueError, match='venue_changed'):
        collect(gulf.MARKETS, {gulf.SOURCES[gulf.MARKETS]: market_page().replace('25 Walnut Street', '200 Broadway Street')})


def test_markets_still_validate_omitted_city_park_card():
    with pytest.raises(ValueError, match='venue_changed'):
        collect(gulf.MARKETS, {gulf.SOURCES[gulf.MARKETS]: market_page().replace('33 Dreyfous Drive', '1 Unknown Street')})
    with pytest.raises(ValueError, match='schedule_incomplete'):
        collect(gulf.MARKETS, {gulf.SOURCES[gulf.MARKETS]: market_page().replace('text-uc">City Park', 'omitted">City Park')})


def gallery_pages(year=2026):
    index = page(gulf.SOURCES[gulf.GALLERY], f'<h1 class="entry-title">{year} Dates</h1>'
                 '<div class="entry-content"><p>October 16 – “Ghoul-ery Night”<br>'
                 'November 20 – “Festival of Living Art”<br>December 18 – “Home for the Holidays”</p></div>'
                 '<script>countdown="2026-11-20T17:00:00Z"</script>')
    about = page(gulf.ABOUT, '<p>Gallery Night is almost always held on the third Friday of each month from 5–9 p.m.</p>'
                 '<p>Gallery Night is hosted on the streets of downtown Palafox between Main Street and Garden Street.</p>')
    return {gulf.SOURCES[gulf.GALLERY]: index, gulf.ABOUT: about}


def test_gallery_uses_heading_year_and_verified_local_hours_not_url_or_countdown():
    rows, calls = collect(gulf.GALLERY, gallery_pages())
    assert len(rows) == 2 and calls == [gulf.SOURCES[gulf.GALLERY], gulf.ABOUT]
    assert rows[0]['starts_at'] == '2026-11-20T23:00:00+00:00'
    assert rows[0]['ends_at'] == '2026-11-21T03:00:00+00:00'
    assert rows[0]['lat'] is None
    assert collect(gulf.GALLERY, gallery_pages(year=2025))[0] == []
    changed = gallery_pages()
    changed[gulf.ABOUT] = changed[gulf.ABOUT].replace('5–9 p.m.', '6–10 p.m.')
    with pytest.raises(ValueError, match='hours_changed'):
        collect(gulf.GALLERY, changed)


def test_event_and_image_guards_reject_unreviewed_hosts_and_owners():
    url = 'https://www.walterandersonmuseum.org/events-1/holiday-bazaar'
    assert gulf.event_url(gulf.WAMA, url)
    for bad in [url + '?format=json', url + '#x', url.replace('https:', 'http:'),
                url.replace('www.', 'www.evil.'), url.replace('/events-1/', '/events-1/%2e%2e/'),
                url.replace('www.', 'attacker@www.'), url.replace('.org/', '.org:443/')]:
        assert not gulf.event_url(gulf.WAMA, bad)
    for key in gulf.WIX_PREFIXES:
        candidate = wix_event(key)['mainImage']['url']
        assert gulf.photo_url(key, candidate) == candidate
        assert gulf.photo_url(gulf.RAPA, candidate) is None
        assert gulf.photo_url(key, candidate.replace(gulf.WIX_OWNERS[key], 'ffffff')) is None
        assert gulf.photo_url(key, candidate + '?width=300') is None
    assert gulf.photo_url(gulf.GALLERY, 'https://gallerynightpensacola.org/logo.png') is None

