from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from roomquest import feed_registration, preview_worker, provider_registration
from roomquest.registration_formats import source_key

NOW = datetime.now(timezone.utc)
DAY = (NOW + timedelta(days=5)).date()
STAMP = DAY.isoformat() + 'T12:00:00'
ZONE = {'timezone':'America/Chicago'}
FIXTURES = Path(__file__).parent / 'fixtures'


def calendars():
    parks = 'https://southcarolinaparks.com/api/events#park=1234'
    park = {'productID':1234, 'name':'Test park','address1':'25 Park Rd','cityName':'Columbia','state':'SC'}
    event = {'parkId':1234,'id':7,'name':'Guided walk','dates':[DAY.strftime('%m/%d/%Y')]}
    def park_response(url):
        if url.endswith('/parks'):
            return json.dumps([park])
        if url.endswith('/events'):
            return json.dumps([event])
        return '<h3>DETAILS</h3><li>' + DAY.strftime('%B %d, %Y') + ', 12:00 PM - 1:00 PM</li><h3>End</h3>'
    yield 'south_carolina_parks', parks, {}, park_response
    cm = json.loads((FIXTURES / 'chambermate_clarksville_public.json').read_text())
    item = cm['data']['events'][0]
    item.update(startDateTime=STAMP,endDateTime=STAMP.replace('12:', '13:'))
    cm['data'].update(events=[item], eventsCount=1)
    tenant = 'clarksvillelakecountrychamber'
    url = ('https://api.chambermate.com/core/biz/webPresence/getEventsInfo?websiteShorthand=' +
           tenant + '&websiteDomain=' + tenant + '.chambermate.com')
    yield 'chambermate', url, {}, lambda _: json.dumps(cm)
    meeting = json.loads((FIXTURES / 'civic/richmondva_legistar.json').read_text())[0]
    meeting.update(EventDate=DAY.isoformat()+'T00:00:00', EventTime='12:00 PM',
                   EventInSiteURL='https://fixture.legistar.com/MeetingDetail.aspx?ID=1')
    yield 'legistar', 'https://webapi.legistar.com/v1/fixture/events', ZONE, lambda _:json.dumps([meeting])
    cfg = dict(ZONE, map={'title':'name','start':'starts','venue':'venue','id':'id'}, order='starts, id')
    yield 'socrata', 'https://data.example.org/resource/abcd-1234.json', cfg, lambda _:json.dumps([
        {'name':'Museum night','starts':STAMP,'venue':'Gallery','id':'1'}])
    rev = 'https://city.example.org/_assets_/plugins/revizeCalendar/calendar_data_handler.php?webspace=example'
    yield 'revize', rev, dict(ZONE, calendar_url='https://city.example.org/calendar.php'), lambda _:json.dumps([
        {'id':'1','rid':'1','title':'Public concert','start':STAMP,'end':STAMP.replace('12:', '13:'),
         'allDay':False,'location':'123 Center Street, Chicago, IL 60601'}])
    xml = ('<ArrayOfEventDisplay><EventDisplay><Name>Business lunch</Name><StartDate>'+STAMP+
           '</StartDate><EventID>7</EventID><Slug>lunch</Slug><Status>APPROVED</Status>'
           '<VisibilityFlags>Public</VisibilityFlags><IsAllDayEvent>false</IsAllDayEvent></EventDisplay></ArrayOfEventDisplay>')
    ics = ('BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:meeting.7\r\nDTSTART:' +
           DAY.strftime('%Y%m%d')+'T180000Z\r\nLOCATION:City Hall\r\nEND:VEVENT\r\nEND:VCALENDAR')
    # Construct ICS in the same reviewed zone year-round.
    from zoneinfo import ZoneInfo
    start = datetime.fromisoformat(STAMP).replace(tzinfo=ZoneInfo(ZONE['timezone'])).astimezone(timezone.utc)
    ics = ics.replace(DAY.strftime('%Y%m%d')+'T180000Z', start.strftime('%Y%m%dT%H%M%SZ'))
    yield 'growthzone','https://chamber.example.org/api/events',ZONE,lambda url:xml if url.endswith('/api/events') else ics


@pytest.mark.parametrize('adapter,url,profile,respond',list(calendars()),ids=lambda x:x if isinstance(x,str) and '://' not in x else None)
def test_registration_and_recurring_import_use_same_provider(adapter,url,profile,respond):
    receipts = []
    def rpc(method,args,**kwargs):
        if method.endswith('claim_registration'):
            return {'url':url}
        if method.endswith('feed_profile'):
            return profile
        receipts.append(args)
        return True

    def fetch(target,accept,**kwargs):
        assert kwargs['respect_robots'] and kwargs.get('deadline_at')
        return respond(target)

    with patch.object(feed_registration, 'fetch_publisher', fetch), patch.object(feed_registration, 'supabase_rpc', rpc):
        assert feed_registration.register('test')['outcome']=='verified', receipts
    assert receipts[0]['p_endpoint']==url and receipts[0]['p_type']==adapter
    source={'feed_url':url,'source_key':source_key(url),'platform_adapter':adapter,'kind':'xml' if adapter=='growthzone' else 'json'}
    if adapter == "south_carolina_parks":
        source["source_key"] = "south_carolina_parks_1234"
    with patch.object(preview_worker,'fetch_publisher',fetch), patch.object(preview_worker,'supabase_rpc',rpc):
        result=preview_worker.preview_source(source)
    assert result['p_future_count']==1 and result['p_events'][0]['event_url'].startswith('https://')


def test_unknown_dataset_is_held_and_denials_remain_disabled():
    url='https://data.example.org/resource/abcd-1234.json'
    with patch.object(feed_registration,'supabase_rpc',side_effect=[{'url':url},{},True]) as rpc:
        assert feed_registration.register('t')['outcome']=='review'
        assert rpc.call_args.args[1]['p_reason']=='socrata_field_mapping_required'
    with patch.object(feed_registration,'supabase_rpc',side_effect=[{'url':url},{'map':{'title':'a','start':'b'},
              'order':'b','timezone':'UTC'},True]), patch.object(feed_registration,'fetch_publisher',
              side_effect=preview_worker.PreviewError('robots_denied')):
        assert feed_registration.register('t')['outcome']=='disabled'


def test_scope_is_exact():
    assert provider_registration.family('https://southcarolinaparks.com/api/events') is None
    assert provider_registration.family('https://webapi.legistar.com/v1/example/events?$top=1') is None
    assert provider_registration.family('https://data.example.org/resource/abcd-1234.json?$limit=2') is None
