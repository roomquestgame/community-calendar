from datetime import datetime, timedelta, timezone

import pytest

from roomquest import discover_halifax, reviewed_chambers, south_boston_speedway


def test_halifax_xml_requires_public_only_and_exact_chamber():
    key = reviewed_chambers.HALIFAX
    url, tz = reviewed_chambers.SOURCES[key]
    now = datetime.now(timezone.utc)
    day = (now + timedelta(days=2)).date()
    source = dict(source_key=key, feed_url=url, timezone=tz, kind='xml', platform_adapter='growthzone')

    def event(ident, visibility, chamber=845):
        return f"""<EventDisplay><EventID>{ident}</EventID><CCID>{chamber}</CCID>
        <Status>APPROVED</Status><VisibilityFlags>{visibility}</VisibilityFlags><IsAllDayEvent>false</IsAllDayEvent>
        <Slug>tour</Slug><Name>Public Beverage Tour</Name><Description>Local shuttle tour.</Description>
        <StartDate>{day}T11:00:00</StartDate><EndDate>{day}T16:00:00</EndDate>
        <LocationDesc>Tour Departs from Woodbine Vineyards 1142 Hite Drive Buffalo Junction, VA 24529</LocationDesc>
        </EventDisplay>"""

    def collect(body):
        return reviewed_chambers.collect(source, '<ArrayOfEventDisplay>'+body+'</ArrayOfEventDisplay>', now=now)

    row, = collect(event(1, 'Public') + event(2, 'Public MemberOnly'))
    assert row['venue_address'] == '1142 Hite Drive, Buffalo Junction, VA 24529'
    assert row['event_url'] == 'https://www.halifaxchamber.net/events/details/tour-1'
    with pytest.raises(ValueError, match='publisher_identity_changed'):
        collect(event(1, 'Public', 1405))


def test_speedway_checks_green_flag_against_detail():
    speedway = south_boston_speedway
    day = datetime.now(timezone.utc).date() + timedelta(days=2)
    race = f'https://{speedway.HOST}/race-night'
    listing = (f'<link rel="canonical" href="{speedway.URL}"><h1>FULL {day.year} SCHEDULE</h1>'
               f'<section><h2>{day:%A}, {day:%B} {day.day}</h2><h2>GREEN FLAG: 2 PM</h2>'
               f'<a href="{race}">EVENT INFO</a></section>')
    detail = (f'<title>Race Night | {day:%B} {day.day}, {day.year}</title><link rel="canonical" href="{race}">'
              '<h5>GREEN FLAG: 2:00 PM</h5><footer>1188 James D. Hagood Highway<br>South Boston, VA 24592</footer>')
    source = dict(source_key=speedway.KEY, feed_url=speedway.URL, timezone=speedway.ZONE,
                  kind='html', platform_adapter='html')
    rows = speedway.collect(source, lambda url, _: listing if url == speedway.URL else detail)
    assert rows[0]['title'] == 'Race Night'
    assert rows[0]['venue_address'] == speedway.ADDRESS
    detail = detail.replace('2:00', '4:00')
    with pytest.raises(ValueError, match='speedway_race_detail_mismatch'):
        speedway.collect(source, lambda url, _: listing if url == speedway.URL else detail)


def test_discover_halifax_requires_complete_window_and_confirms_detail():
    tourism = discover_halifax
    day = datetime.now(timezone.utc).date() + timedelta(days=2)
    date = f'{day:%B} {day.day}, {day.year}'
    url = 'https://gohalifaxva.com/directory/public-music/'
    listing = ('<div class="directorist-header-found-title"><span>1</span></div>'
               f'<article class="directorist-listing-single"><h2 class="directorist-listing-title"><a href="{url}">'
               f'Public Music</a></h2><span class="directorist-listing-card-date">{date}</span>'
               '<span class="directorist-listing-card-time">6:00 PM</span></article>')
    assert tourism._directory(listing, day) == [(url, 'Public Music', day, '6:00 PM')]
    with pytest.raises(ValueError, match='halifax_directory_incomplete'):
        tourism._directory(listing.replace('<span>1', '<span>2'), day)
    values = {'Start Date': date, 'Start Time': '6:00 PM', 'End Time': '8:00 PM',
              'Address': 'Venue, 1142, Hite Drive, Buffalo Springs, Mecklenburg County, Virginia, 24529, United States'}
    fields = ''.join(f'<div class="directorist-single-info"><span class="directorist-single-info__label__text">'
                     f'{k}</span><span class="directorist-single-info__value">{v}</span></div>'
                     for k, v in values.items())
    detail = (f'<link rel="canonical" href="{url}"><h1 class="directorist-listing-details__listing-title">'
              f'Public Music</h1><div class="directorist-card-general-section">Description Live music.</div>{fields}')
    row = tourism._detail(detail, url, 'Public Music', day, '6:00 PM')
    assert row['venue_address'] == '1142 Hite Drive, Buffalo Springs, VA 24529'
    assert tourism._detail(detail, url, 'Public Music', day, '5:00 PM') is None
