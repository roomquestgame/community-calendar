from datetime import datetime, timedelta, timezone
import json
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch
import pytest
from roomquest.community_formats import SOURCES, collect, parse_rss, parse_libnet, libnet_url, MEC, ICAL
from roomquest.preview_worker import preview_source, PreviewError, _process_claimed_source

START = (datetime.now(timezone.utc)+timedelta(days=2)).replace(microsecond=0).isoformat()
END = (datetime.now(timezone.utc)+timedelta(days=2,hours=2)).replace(microsecond=0).isoformat()
WP = next(k for k,v in SOURCES.items() if v[2]=='wordpress')
LIB = next(k for k,v in SOURCES.items() if v[1]=='json')
PIMA = next(k for k,v in SOURCES.items() if v[2]=='library' and v[1]=='rss')
def source(key):
 u,k,a,t=SOURCES[key]
 return dict(source_key=key,feed_url=u,kind=k,platform_adapter=a)
def rss(adapter='wordpress',start=START,extra='',identity='event-1',venue='Actual Hall',street='12 Main St, Raleigh, NC'):
 ns=MEC if adapter=='wordpress' else ICAL
 field='startDate' if adapter=='wordpress' else 'dtstart'
 return f'<rss xmlns:e="{ns}" xmlns:geo="http://www.w3.org/2003/01/geo/wgs84_pos#"><channel><item><guid>{identity}</guid><title>Community Workshop</title><link>https://venue.example.org/event/1</link><pubDate>Mon, 01 Jan 2001 00:00:00 GMT</pubDate><e:{field}>{start}</e:{field}><e:location>{venue}</e:location><e:address>{street}</e:address><geo:lat>35.8</geo:lat><geo:long>-78.6</geo:long>{extra}</item></channel></rss>'
def event():
 return dict(event_id=1,title='Library workshop',event_start=START,event_end=END,location='Actual Branch',address='12 Main St, Raleigh, NC',latitude=35.8,longitude=-78.6,url='https://library.example.org/events/1')
@pytest.mark.parametrize('key',list(SOURCES))
def test_exact_registered_families_dispatch_with_same_identity(key):
 s=source(key);payload=json.dumps([event()]) if s['kind']=='json' else rss(s['platform_adapter'])
 with patch('roomquest.preview_worker.fetch_publisher',return_value=payload) as fetch:
  result=preview_source(s)
 assert result['p_source_key']==key and result['p_future_count']==1
 assert result['p_events'][0]['lat']==35.8
 assert fetch.call_args.kwargs['respect_robots'] is True
 assert fetch.call_args.kwargs['deadline_at'] is not None

def test_libnet_updates_local_calendar_date_preserves_filters_window():
 u=libnet_url(SOURCES[LIB][0],'America/Denver',datetime(2026,11,2,1,tzinfo=timezone.utc))
 req=json.loads(parse_qs(urlsplit(u).query)['req'][0])
 assert req['date']=='2026-11-01' and req['days']==30 and req['private'] is False
 assert req['locations']==[] and parse_qs(urlsplit(u).query)['event_type']==['0']

@pytest.mark.parametrize('bad',['2026-11-02','','Mon, 02 Nov 2026 12:00:00 GMT'])
def test_rss_never_uses_pubdate_or_invents_time(bad):
 with pytest.raises(ValueError,match='event_time_unresolved'):parse_rss(rss(start=bad),source(WP),'America/Chicago')

def test_split_mec_date_time_is_explicit_local_time():
 d=(datetime.now(timezone.utc)+timedelta(days=2)).date().isoformat()
 rows=parse_rss(rss(start=d,extra='<e:startTime>12:30</e:startTime>'),source(WP),'America/Chicago')
 assert rows[0]['starts_at'].endswith('+00:00')

@pytest.mark.parametrize('payload',['<html>denied</html>','<!DOCTYPE rss [<!ENTITY x "boom">]><rss><channel/></rss>','<rss><channel><item/>'])
def test_bad_xml_not_successful_empty(payload):
 with pytest.raises(ValueError):parse_rss(payload,source(WP),'America/Chicago')

def test_explicit_empty_is_healthy():
 assert parse_rss('<rss><channel/></rss>',source(WP),'America/Chicago')==[]
 assert parse_libnet('[]',source(LIB),'America/Denver')==[]

def test_missing_location_is_retained_unlocated_not_headquarters():
 rows=parse_rss(rss(venue='',street=''),source(WP),'America/Chicago')
 assert rows[0]['lat'] is None and rows[0]['venue_address']==''

def test_duplicate_occurrence_conflict_is_not_overwritten():
 one=rss();other=rss(venue='Conflicting Hall').split('<item>')[1].split('</item>')[0]
 with pytest.raises(ValueError,match='conflicting_event_occurrence'):
  parse_rss(one.replace('</channel>',f'<item>{other}</item></channel>'),source(WP),'America/Chicago')

@pytest.mark.parametrize('change',[dict(feed_url='https://evil.example.org/feed'),dict(kind='json'),dict(source_key='unregistered')])
def test_registry_rejection_precedes_network(change):
 s=source(WP);s.update(change)
 with patch('roomquest.preview_worker.fetch_publisher') as fetch:
  with pytest.raises(PreviewError,match='unregistered_community_format_source'):preview_source(s)
  fetch.assert_not_called()

def test_bounded_large_library_snapshot_is_review_not_truncated():
 with pytest.raises(ValueError,match='source_record_limit'):
  parse_libnet(json.dumps([event()]*500),source(LIB),'America/Denver')

def test_library_invalid_record_cannot_be_healthy_empty():
 with pytest.raises(ValueError,match='event_time_unresolved'):
  parse_libnet('[{"event_id":1}]',source(LIB),'America/Denver')

def test_rss_explicit_next_page_requires_review():
 p=rss().replace('</channel>','<atom:link xmlns:atom="http://www.w3.org/2005/Atom" rel="next" href="https://evil.example.org"/></channel>')
 with pytest.raises(ValueError,match='rss_pagination_requires_review'):parse_rss(p,source(WP),'America/Chicago')

def test_failed_checkpoint_never_reports_complete():
 s=source(LIB)
 with patch('roomquest.preview_worker.fetch_publisher',return_value=json.dumps([event()])),patch('roomquest.preview_worker.supabase_rpc') as rpc:
  rpc.side_effect=[PreviewError('database_unavailable'),None]
  result=_process_claimed_source(s)
 assert result['failed']==1 and result['complete']==0
 assert rpc.call_args.args[1]['p_error']=='database_unavailable'


def test_event_rss_namespace_uses_event_time_not_publish_time():
 payload=rss('library').replace(ICAL,'http://purl.org/rss/1.0/modules/event/').replace('dtstart','startdate')
 assert parse_rss(payload,source(PIMA),'America/Phoenix')[0]['starts_at']==START

def test_ambiguous_library_wall_time_requires_review():
 e=event();e['event_start']='2027-11-07T01:30:00';e['event_end']=None
 with pytest.raises(ValueError,match='timezone_ambiguous'):parse_libnet(json.dumps([e]),source(LIB),'America/Denver')

def test_no_venue_enrichment_or_geocoder_calls():
 with patch('roomquest.preview_worker.fetch_publisher',return_value=rss(venue='Unknown Place',street='')) as fetch:
  out=preview_source(source(WP))
 assert fetch.call_count==1 and out['p_events'][0]['lat'] is None
