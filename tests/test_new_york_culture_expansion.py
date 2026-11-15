from calendar import Calendar
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from html import escape
from hashlib import sha256
import json
from unittest.mock import Mock, patch

import pytest

from roomquest import new_york_culture_expansion as ny
from roomquest.preview_worker import PreviewError
from tests.test_new_york_arts import fake_record

NOW = datetime(2026, 11, 15, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def record_without_wall_clock():
    with patch.object(ny, 'record', side_effect=fake_record):
        yield


def source(key):
    return dict(source_key=key, feed_url=ny.SOURCES[key][0], kind='html', platform_adapter='html', timezone=ny.ZONE)


def astor_calendar(slugs=('wine-tasting',)):
    return ('<a class="date-title">November</a><span class="year">2026</span>'
            '<a href="/courses.ac?rel=nav">View All</a>'
            + ''.join('<div class="calendar-month-day"><span class="day">18</span>'
                      f'<a href="class-{slug}.ac">{slug.title()}</a></div>' for slug in slugs))


def astor_catalog(slugs=('wine-tasting',)):
    return ('<h1>All Astor Center Events</h1><ul class="event-teaser-list-md">'
            + ''.join(f'<li><a href="class-{slug}.ac"><span class="event-title">{slug.title()}</span></a></li>' for slug in slugs)
            + '</ul>')


def astor_detail(slug='wine-tasting', body='Taste wine and learn from a sommelier. Class is 2 hours long.', dates=None, venue='Astor Center'):
    dates = dates or [datetime(2026, 11, 18, 18, 30)]
    nodes = [dict(**{'@type':'Event'}, name=slug.title(), startDate=value.strftime('%m/%d/%Y %I:%M:%S %p'),
                  location=dict(name=venue, address='399 Lafayette Street, New York, NY 10003'), description='<p>'+escape(body)+'</p>') for value in dates]
    return (f'<h1>{slug.title()}</h1><script type="application/ld+json">{json.dumps(nodes)}</script>'
            f'<div class="event-description"><p>{escape(body)}</p></div>'
            + ''.join('<div class="event__date__cta__row"><div class="event__date">'
                      + value.strftime('%A, %b %d %I:%M %p') + '</div><div>Get Tickets</div></div>' for value in dates)
            + '<footer>Retail navigation must not enter the event description.</footer>')


def astor_fetch(slugs=('wine-tasting',), detail=None):
    def fetch(url, accept):
        assert accept == 'text/html'
        if url == ny.SOURCES[ny.ASTOR][0]:
            return astor_calendar(slugs[:1])
        if url == ny.ASTOR_CATALOG:
            return astor_catalog(slugs)
        slug = url.rsplit('/class-',1)[1][:-3]
        return detail(slug) if detail else astor_detail(slug)
    return fetch


def gw_event(slug='birding', title='Birding in Peace', start='2026-11-18T06:30:00-05:00', end='2026-11-18T08:00:00-05:00'):
    return dict(**{'@type':'Event'}, name=title, url='https://www.green-wood.com/event/'+slug+'/',
                startDate=start, endDate=end, description='Truncated listing excerpt ...',
                eventStatus='https://schema.org/EventScheduled', eventAttendanceMode='https://schema.org/OfflineEventAttendanceMode')


def gw_month(events, month='2026-11', next_url=None, counts=None):
    year, number = (int(x) for x in month.split('-'))
    counts = counts or {}
    cells=[]
    for day in Calendar(firstweekday=6).itermonthdates(year,number):
        date=day.isoformat()
        count=counts.get(date,sum(event['startDate'][:10] == date for event in events))
        cells.append('<div class="tribe-events-calendar-month__day-cell--desktop">'
                     f'<time class="tribe-events-calendar-month__day-date-daynum" datetime="{date}"></time>'
                     f'<span class="tribe-common-a11y-visual-hide">{count} events,</span></div>')
    return (f'<time class="tribe-events-c-top-bar__datepicker-time" datetime="{month}"></time>'
            f'<script type="application/ld+json">{json.dumps(events)}</script>' + ''.join(cells)
            + (f'<a rel="next" href="{next_url}">Next</a>' if next_url else ''))


def gw_detail(event, body='Discover birds before the gates open.', meeting='Check-in at the Main Entrance (500 25th Street).'):
    return (f'<link rel="canonical" href="{event["url"]}"><h1 class="tribe-events-single-event-title">{event["name"]}</h1>'
            f'<script type="application/ld+json">{json.dumps(event)}</script>'
            '<div id="tribe-events-content"><div id="post-7" class="tribe_events tribe_events_cat-walking-tour">'
            '<div class="tribe-events-schedule">Schedule controls</div>'
            '<div class="tribe-events-series-relationship-single-marker">Series controls</div>'
            f'<p>{escape(body)}</p><ul><li><strong>Where To Go:</strong> {escape(meeting)}</li>'
            '<li><strong>Accessibility &amp; Safety:</strong> Uneven terrain.</li><li>Final weather condition.</li></ul>'
            '<div class="tribe-block__events-link">Add to calendar Google Calendar</div></div></div>'
            '<footer>500 25th Street, Brooklyn, NY 11232. General cemetery visiting hours.</footer>')


def finish(key, fetch, max_details=3):
    state=None
    for _ in range(20):
        result=ny.collect_chunk(source(key),fetch,checkpoint=state,now=NOW,max_details=max_details)
        state=result['checkpoint']
        if result['complete']:
            return result
        assert result['events'] == []
    raise AssertionError('Snapshot did not complete')


def test_astor_catalog_discovers_later_classes_and_native_year_rollover_dates():
    dates=[datetime(2026,11,18,18,30),datetime(2027,1,8,18,30)]
    fetch=Mock(side_effect=astor_fetch(('wine-tasting','future-class'), lambda slug:astor_detail(slug,dates=dates)))
    result=finish(ny.ASTOR,fetch,max_details=1)
    assert len(result['events'])==4
    assert {row['starts_at'] for row in result['events']} == {'2026-11-18T18:30:00-05:00','2027-01-08T18:30:00-05:00'}
    assert all(row['venue_address']=='23 East 4th Street, New York, NY 10003' for row in result['events'])
    assert all('controls/' not in call.args[0] and 'images/' not in call.args[0] for call in fetch.call_args_list)


def test_astor_native_full_description_survives_two_thousand_characters():
    body='Full tasting explanation. '*120+'Final pairing requirement. Class is 2 hours long.'
    row=finish(ny.ASTOR,astor_fetch(detail=lambda slug:astor_detail(slug,body=body)))['events'][0]
    assert row['description']==body
    assert len(row['description'])>2000
    assert row['ends_at']=='2026-11-18T20:30:00-05:00'
    assert 'Retail navigation' not in row['description']


@pytest.mark.parametrize('body,reason',[('', 'description_missing'),('x'*12001,'description_limit')])
def test_astor_blank_or_oversize_body_is_held_without_substitution(body,reason):
    result=finish(ny.ASTOR,astor_fetch(detail=lambda slug:astor_detail(slug,body=body)))
    assert result['events']==[]
    assert result['checkpoint']['diagnostics'][0]['reason']==reason


def test_astor_full_body_disagreement_and_changed_venue_cannot_publish():
    payload=astor_detail().replace('<div class="event-description"><p>Taste wine','<div class="event-description"><p>Different wine')
    with pytest.raises(ValueError,match='detail_changed'):
        finish(ny.ASTOR,astor_fetch(detail=lambda slug:payload))
    result=finish(ny.ASTOR,astor_fetch(detail=lambda slug:astor_detail(slug,venue='Another Venue')))
    assert result['events']==[] and result['checkpoint']['diagnostics'][0]['reason']=='venue_unreviewed'


def test_astor_missing_duration_stays_unknown_and_remote_future_occurrence_is_excluded():
    dates=[datetime(2026,11,18,18,30),datetime(2027,4,8,18,30)]
    result=finish(ny.ASTOR,astor_fetch(detail=lambda slug:astor_detail(slug,body='Enjoy wine.',dates=dates)))
    assert len(result['events'])==1 and result['events'][0]['ends_at'] is None


def test_astor_calendar_class_missing_from_all_catalog_is_incomplete():
    def fetch(url,accept):
        return astor_calendar() if url==ny.SOURCES[ny.ASTOR][0] else astor_catalog(('another-class',))
    with pytest.raises(ValueError,match='manifest_incomplete'):
        finish(ny.ASTOR,fetch)


def test_greenwood_manifest_includes_hidden_daily_events_and_following_month():
    events=[gw_event('bird-'+str(i)) for i in range(4)]
    december=gw_event('workshop',start='2026-12-08T10:00:00-05:00',end='2026-12-08T11:00:00-05:00')
    url='https://www.green-wood.com/calendar/month/2026-12/'
    fetch=Mock(side_effect=[gw_month(events,next_url=url),gw_month([december],month='2026-12')])
    queue=ny._manifest(ny.GREENWOOD,fetch,float('inf'),NOW)
    assert len(queue)==5
    assert fetch.call_args.args == (url,'text/html')
    assert all('/wp-json/' not in call.args[0] for call in fetch.call_args_list)


@pytest.mark.parametrize('change', ['count','grid','next_host','month'])
def test_greenwood_incomplete_or_changed_month_is_rejected(change):
    event=gw_event()
    payload=gw_month([event])
    if change=='count': payload=gw_month([event],counts={'2026-11-18':4})
    if change=='grid': payload=payload.replace('datetime="2026-11-01"','datetime="2026-12-31"')
    if change=='next_host': payload=gw_month([event],next_url='https://unapproved.invalid/calendar/month/2026-12/')
    if change=='month': payload=gw_month([event],month='2026-12')
    with pytest.raises(ValueError,match='listing_changed|manifest_incomplete'):
        ny._manifest(ny.GREENWOOD,lambda u,a:payload,float('inf'),NOW)


def test_ended_related_metadata_cannot_mask_missing_or_extra_future_calendar_events():
    past=[gw_event('past-'+str(i),start='2026-11-13T06:30:00-05:00',end='2026-11-13T08:00:00-05:00') for i in range(2)]
    queue=ny._manifest(ny.GREENWOOD,lambda u,a:gw_month(past,counts={'2026-11-13':1}),float('inf'),NOW)
    assert queue==[]
    future=[gw_event('future-'+str(i)) for i in range(2)]
    with pytest.raises(ValueError,match='manifest_incomplete'):
        ny._manifest(ny.GREENWOOD,lambda u,a:gw_month(future,counts={'2026-11-18':1}),float('inf'),NOW)


def test_new_cancellation_on_detail_is_held_even_when_calendar_title_is_stale():
    event=gw_event()
    payload=gw_detail(event).replace('class="tribe-events-single-event-title">Birding in Peace',
                                   'class="tribe-events-single-event-title">Cancelled: Birding in Peace')
    result=finish(ny.GREENWOOD,lambda u,a:gw_month([event]) if u==ny.SOURCES[ny.GREENWOOD][0] else payload)
    assert result['events']==[] and result['checkpoint']['diagnostics'][0]['reason']=='event_not_public'


@pytest.mark.parametrize('meeting,place',[('Main Entrance (500 25th Street).','main'),
    ('Gothic Arch near the Main Entrance (500 25th Street).','arch'),
    ('The Green-House (750 Fifth Avenue), near the Main Entrance.','house'),
    ('Historic Chapel, a short distance from the Main Entrance (Fifth Avenue and 25th Street).','historic_chapel'),
    ('Modern Chapel near the Main Entrance at Fifth Avenue and 25th Street (500 25th Street).','modern_chapel')])
def test_greenwood_actual_meeting_street_and_complete_rules(meeting,place):
    event=gw_event()
    body='Full birding narrative. '*110+'Last narrative sentence.'
    def fetch(url,accept):
        return gw_month([event]) if url==ny.SOURCES[ny.GREENWOOD][0] else gw_detail(event,body,meeting)
    row=finish(ny.GREENWOOD,fetch)['events'][0]
    assert tuple(row[key] for key in ('venue_name','venue_address','venue_city','lat','lng'))==ny.VENUES[place]
    assert body in row['description'] and row['description'].endswith('Final weather condition.')
    assert 'Schedule controls' not in row['description'] and 'Series controls' not in row['description']
    assert 'General cemetery visiting hours' not in row['description']
    assert 'Add to calendar' not in row['description']
    if place in {'arch','historic_chapel','modern_chapel'}:
        assert row['location_is_approximate'] is True
        assert 'approximate meeting point' in row['venue_name']


def test_chapel_location_survives_native_whitespace_before_colon():
    event=gw_event()
    payload=gw_detail(event,meeting='Historic Chapel, near the Main Entrance (Fifth Avenue and 25th Street).')
    payload=payload.replace('Where To Go:', 'Where to go :')
    row=finish(ny.GREENWOOD,lambda u,a:gw_month([event]) if u==ny.SOURCES[ny.GREENWOOD][0] else payload)['events'][0]
    assert row['venue_name']==ny.VENUES['historic_chapel'][0]


def test_greenwood_unknown_actual_location_does_not_inherit_footer_address():
    event=gw_event()
    result=finish(ny.GREENWOOD,lambda u,a:gw_month([event]) if u==ny.SOURCES[ny.GREENWOOD][0] else gw_detail(event,meeting='Meet at a private site supplied to registrants.'))
    assert result['events']==[]
    assert result['checkpoint']['diagnostics'][0]['reason']=='venue_unreviewed'


@pytest.mark.parametrize('title',['Members Only: Evening Tour','Cancelled Walking Tour','Museum Hours','General Admission'])
def test_nonpublic_and_visiting_hours_items_are_never_hydrated_or_published(title):
    event=gw_event(title=title)
    fetch=Mock(return_value=gw_month([event]))
    result=finish(ny.GREENWOOD,fetch)
    assert result['events']==[]
    assert all(call.args[0]==ny.SOURCES[ny.GREENWOOD][0] for call in fetch.call_args_list)


def test_changed_detail_schedule_or_canonical_url_is_rejected():
    event=gw_event()
    for modified in [dict(event,startDate='2026-11-18T07:30:00-05:00'),dict(event,url='https://www.green-wood.com/event/another/')]:
        with pytest.raises(ValueError,match='schedule_changed|identity_changed'):
            finish(ny.GREENWOOD,lambda u,a:gw_month([event]) if u==ny.SOURCES[ny.GREENWOOD][0] else gw_detail(modified))


def test_only_exact_reviewed_canonical_alias_is_accepted():
    event=gw_event('rest-in-pace-green-house-2/2026-11-15',start='2026-11-15T12:00:00-05:00',end='2026-11-15T13:30:00-05:00')
    alias=ny.GREENWOOD_CANONICAL_ALIASES[event['url']]
    payload=gw_detail(event).replace(f'<link rel="canonical" href="{event["url"]}">',f'<link rel="canonical" href="{alias}">')
    result=finish(ny.GREENWOOD,lambda u,a:gw_month([event]) if u==ny.SOURCES[ny.GREENWOOD][0] else payload)
    assert len(result['events'])==1 and result['events'][0]['event_url']==event['url']
    for bad in ['https://unapproved.invalid/event/',None]:
        wrong=payload.replace(f'href="{alias}"',f'href="{bad}"' if bad else '')
        with pytest.raises(ValueError,match='identity_changed'):
            finish(ny.GREENWOOD,lambda u,a:gw_month([event]) if u==ny.SOURCES[ny.GREENWOOD][0] else wrong)


def test_estimated_after_hours_checkin_is_exact_url_body_bound_and_marked():
    from bs4 import BeautifulSoup
    event=gw_event('green-wood-after-hours-60',title='Green-Wood After Hours')
    payload=gw_detail(event,meeting='Check-in is not specified in this program body.')
    soup=BeautifulSoup(payload,'html.parser')
    container=soup.select_one('#tribe-events-content > div[id^=post-].tribe_events')
    for x in container.select('.tribe-events-series-relationship-single-marker, .tribe-events-schedule, .tribe-block__events-link'):x.decompose()
    digest=sha256(ny._body(str(container)).encode()).hexdigest()
    with patch.object(ny,'AFTER_HOURS_ESTIMATES',{event['url']:digest}):
        result=finish(ny.GREENWOOD,lambda u,a:gw_month([event]) if u==ny.SOURCES[ny.GREENWOOD][0] else payload)
        row,=result['events']
        assert row['location_is_approximate'] is True
        assert row['location_provenance']=='reviewed_same_tour_series_estimated_checkin_and_PAD_address_point'
        assert 'approximate meeting point' in row['venue_name']
        changed=payload.replace('Final weather condition.','New meeting instructions.')
        result=finish(ny.GREENWOOD,lambda u,a:gw_month([event]) if u==ny.SOURCES[ny.GREENWOOD][0] else changed)
        assert result['events']==[] and result['checkpoint']['diagnostics'][0]['reason']=='venue_unreviewed'


def test_snapshot_keeps_partial_rows_private_and_revalidates_manifest_before_success():
    fetch=Mock(side_effect=astor_fetch(('wine-tasting','another-class')))
    first=ny.collect_chunk(source(ny.ASTOR),fetch,now=NOW,max_details=1)
    assert first['events']==[] and not first['complete']
    assert first['checkpoint']['cursor']==1 and len(first['checkpoint']['events'])==1
    second=ny.collect_chunk(source(ny.ASTOR),fetch,checkpoint=first['checkpoint'],now=NOW,max_details=1)
    assert second['complete'] and len(second['events'])==2
    before=fetch.call_count
    assert ny.collect_chunk(source(ny.ASTOR),fetch,checkpoint=second['checkpoint'],now=NOW)['complete']
    assert fetch.call_count==before


def test_manifest_change_discards_stale_hydrated_prefix():
    fetch=astor_fetch(('wine-tasting','another-class'))
    first=ny.collect_chunk(source(ny.ASTOR),fetch,now=NOW,max_details=1)
    def changed(url,accept):
        if url==ny.ASTOR_CATALOG: return astor_catalog(('wine-tasting','another-class','new-class'))
        return fetch(url,accept)
    result=ny.collect_chunk(source(ny.ASTOR),changed,checkpoint=first['checkpoint'],now=NOW,max_details=1)
    assert not result['complete'] and result['events']==[]
    assert result['checkpoint']['cursor']==0 and result['checkpoint']['manifest_count']==3


@pytest.mark.parametrize('mutation',['hash','source','cursor','venue','body','short_body','row_hash','missing_row_hash','extra_row_hash','diagnostic','date','version'])
def test_checkpoint_tampering_is_rejected(mutation):
    fetch=astor_fetch(('wine-tasting','another-class'))
    state=ny.collect_chunk(source(ny.ASTOR),fetch,now=NOW,max_details=1)['checkpoint']
    if mutation=='hash':state['manifest_hash']='0'*64
    if mutation=='source':state['source_key']=ny.GREENWOOD
    if mutation=='cursor':state['cursor']=True
    if mutation=='venue':state['events'][0]['venue_address']='999 Unknown Street, New York, NY 10003'
    if mutation=='body':state['events'][0]['description']=''
    if mutation=='short_body':state['events'][0]['description']='Taste wine.'
    if mutation=='row_hash':state['row_hashes'][ny._row_key(state['events'][0])]='0'*64
    if mutation=='missing_row_hash':state['row_hashes']={}
    if mutation=='extra_row_hash':state['row_hashes']['unrelated']='0'*64
    if mutation=='diagnostic':state['diagnostics'][0]['event_count']=5
    if mutation=='date':state['events'][0]['starts_at']='2026-11-18T19:30:00-05:00'
    if mutation=='version':state['version']=True
    with pytest.raises(ValueError,match='checkpoint_invalid'):
        ny.collect_chunk(source(ny.ASTOR),fetch,checkpoint=state,now=NOW)


def test_row_hash_preserves_full_body_on_complete_checkpoint_resume():
    fetch=Mock(side_effect=astor_fetch())
    result=finish(ny.ASTOR,fetch)
    state=result['checkpoint']
    assert state['row_hashes']=={ny._row_key(row):ny._digest(row) for row in result['events']}
    state['events'][0]['description']=state['events'][0]['description'][:-5]
    before=fetch.call_count
    with pytest.raises(ValueError,match='checkpoint_invalid'):
        ny.collect_chunk(source(ny.ASTOR),fetch,checkpoint=state,now=NOW)
    assert fetch.call_count==before


def test_permission_failure_propagates_without_partial_success_or_retry():
    event=gw_event()
    denied=PreviewError('robots_denied')
    fetch=Mock(side_effect=[gw_month([event]),denied])
    with pytest.raises(PreviewError) as caught:
        ny.collect_chunk(source(ny.GREENWOOD),fetch,now=NOW)
    assert caught.value is denied and fetch.call_count==2


def test_bounded_pacing_pause_retains_private_checkpoint():
    event=gw_event()
    fetch=Mock(side_effect=[gw_month([event]),PreviewError('publisher_pacing_deferred')])
    result=ny.collect_chunk(source(ny.GREENWOOD),fetch,now=NOW)
    assert not result['complete'] and result['events']==[] and result['checkpoint']['cursor']==0


@pytest.mark.parametrize('field,value',[('feed_url','https://other.invalid/'),('kind','json'),('platform_adapter','wordpress'),('timezone','UTC')])
def test_source_contract_is_exact(field,value):
    invalid=source(ny.ASTOR);invalid[field]=value
    fetch=Mock()
    with pytest.raises(ValueError,match='source_unregistered'):
        ny.collect_chunk(invalid,fetch,now=NOW)
    fetch.assert_not_called()


def test_expired_checkpoint_starts_new_snapshot_and_source_requires_checkpoint():
    fetch=Mock(side_effect=astor_fetch(('wine-tasting','another-class')))
    state=ny.collect_chunk(source(ny.ASTOR),fetch,now=NOW,max_details=1)['checkpoint']
    result=ny.collect_chunk(source(ny.ASTOR),fetch,checkpoint=state,now=NOW+timedelta(hours=5),max_details=1)
    assert result['checkpoint']['started_at']==(NOW+timedelta(hours=5)).isoformat()
    with pytest.raises(ValueError,match='publisher_checkpoint_required'):
        ny.collect(source(ny.ASTOR),fetch,now=NOW)
