from datetime import datetime, timedelta, timezone
from time import monotonic
from zoneinfo import ZoneInfo

from roomquest import council_bluffs_library as library
from roomquest import reviewed_chambers as chamber
from roomquest import sarpy_tourism as sarpy


def source(key, url, kind, adapter):
    return dict(source_key=key, feed_url=url, kind=kind, platform_adapter=adapter,
                timezone='America/Chicago')


def test_sarpy_keeps_explicit_venue_and_event_detail_link():
    start = datetime.now(timezone.utc) + timedelta(days=1)
    end = start + timedelta(hours=2)
    payload = f"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:123
DTSTART:{start:%Y%m%dT%H%M%SZ}
DTEND:{end:%Y%m%dT%H%M%SZ}
SUMMARY:Music Bingo
LOCATION:<p>Smash Park</p> - 8121 S 125th St  La Vista  NE 68128
DESCRIPTION:https://www.gosarpy.com/calendar.aspx?EID=123
URL:/common/modules/iCalendar/iCalendar.aspx?catID=34
END:VEVENT
END:VCALENDAR"""
    config = source(sarpy.KEY, sarpy.URL, 'ical', 'ical')
    row, = sarpy.collect(config, payload)
    assert row['event_url'] == 'https://www.gosarpy.com/calendar.aspx?EID=123'
    assert row['venue_name'] == 'Smash Park'
    assert row['venue_address'] == '8121 S 125th St, La Vista, NE 68128'
    assert not row['description'] and row['lat'] is None
    assert sarpy.collect(config, payload.replace('EID=123', 'EID=124')) == []
    assert sarpy.collect(config, payload.replace('8121 S 125th St', '')) == []


def test_siouxland_holds_ambiguous_address_and_member_flags():
    def event(number, address, visibility):
        return f"""<EventDisplay><EventID>{number}</EventID><Slug>ribbon-cutting</Slug>
        <Name>Ribbon Cutting</Name>
        <Status>APPROVED</Status><VisibilityFlags>{visibility}</VisibilityFlags>
        <IsAllDayEvent>false</IsAllDayEvent><StartDate>2026-11-12T15:00:00</StartDate>
        <EndDate>2026-11-12T16:00:00</EndDate>
        <LocationDesc><![CDATA[Fixture Hall<br>{address}<br>Sioux City, IA 51109]]></LocationDesc>
        </EventDisplay>"""
    body = '<ArrayOfEventDisplay>' + ''.join([
        event(101, '525 6th Street', 'Public'),
        event(102, '1801 & 1803 Wright Ave.', 'Public'),
        event(103, '525 6th Street', 'Public MemberOnly'),
    ]) + '</ArrayOfEventDisplay>'
    key = chamber.SIOUXLAND
    row, = chamber.collect(source(key, chamber.SOURCES[key][0], 'xml', 'growthzone'), body,
                           now=datetime(2026, 11, 7, 12, tzinfo=timezone.utc))
    assert row['id'] == '101'
    assert row['starts_at'] == '2026-11-12T21:00:00+00:00'
    assert row['venue_address'] == '525 6th Street, Sioux City, IA 51109'
    assert row['description'] == ''


def test_library_collects_two_sessions_and_keeps_only_own_programs():
    now = datetime.now(timezone.utc)
    day = now.date() + timedelta(days=1)

    def card(number, times, branch=library.VENUE, topics=True):
        labels = '<span>Arts &amp; Crafts</span>' if topics else ''
        return f"""<article class="node--type-lc-event moderation-state--published">
        <span class="lc-date-icon__item--month">{day:%b}</span><span class="lc-date-icon__item--day">{day.day}</span>
        <span class="lc-date-icon__item--year">{day.year}</span><div class="lc-event__info">
        <a class="lc-event__link" href="/event/sewing-{number}">Sewing Class</a>
        <div class="lc-event-info-item--time">{times}</div></div>
        <div class="lc-event__branch">Library Branch: {branch}</div>
        <div class="lc-event__room">Room: Meeting Room D</div>
        <div class="lc-event__program-types">{labels}</div>
        </article>"""
    pages = {
        library.URL: card(101, '9:00am–11:00am') + card(102, 'All Day') +
        '<div class="pager__item--next"><a href="?page=1">Next</a></div>',
        library.URL + '?page=1': card(103, '2:00pm–4:00pm') +
        card(104, '2:00pm–4:00pm', branch='Off Site') + card(105, '2:00pm–4:00pm', topics=False),
    }
    rows = library.collect(source(library.KEY, library.URL, 'html', 'html'),
                           lambda url, accept: pages[url], deadline_at=monotonic() + 5,
                           now=now)
    assert [row['id'] for row in rows] == ['101', '103']
    assert datetime.fromisoformat(rows[1]['starts_at']).astimezone(ZoneInfo(library.TIMEZONE)) == (
        datetime(day.year, day.month, day.day, 14, tzinfo=ZoneInfo(library.TIMEZONE)))
    assert rows[1]['venue_address'] == library.ADDRESS
    assert rows[1]['description'] == ''
    assert rows[1]['publisher_categories'] == ['Arts & Crafts']
    assert rows[1]['publisher_details']['meeting_location'] == 'Meeting Room D'
