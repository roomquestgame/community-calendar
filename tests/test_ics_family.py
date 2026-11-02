from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import pytest
from roomquest.preview_worker import preview_source,parse_ics_preview,PreviewError,_process_claimed_source
from roomquest.ics_adapter import parse
START=(datetime.now(timezone.utc)+timedelta(days=2)).strftime('%Y%m%dT%H%M%SZ')
def feed(count=1):
 return 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\n'+''.join(f'BEGIN:VEVENT\r\nUID:event-{i}\r\nSUMMARY:Community workshop\r\nDTSTART:{START}\r\nLOCATION:Actual Hall\\, 12 Main St\\, Raleigh\\, NC\r\nGEO:35.8;-78.6\r\nURL:https://venue.example.org/event/{i}\r\nCATEGORIES:Arts,Community\r\nEND:VEVENT\r\n' for i in range(count))+'END:VCALENDAR\r\n'
def source(key):return dict(source_key=key,platform_adapter='ical',kind='ical',feed_url='https://venue.example.org/calendar.ics')
@pytest.mark.parametrize('key',['municipal_mapsee_fixture','udell_fixture','metro_fixture'])
def test_shared_dispatch_preserves_identity_and_transport(key):
 s=source(key)
 with patch('roomquest.mapsee_adapter.profiles',return_value={key:dict(type='ics',url=s['feed_url'])}),patch('roomquest.preview_worker.fetch_publisher',return_value=feed()) as fetch:
  out=preview_source(s)
 assert out['p_events'][0]['id']=='event-0' and out['p_events'][0]['lat']==35.8
 assert out['p_source_key']==key and out['p_future_count']==1
 assert fetch.call_args.kwargs['respect_robots']==key.startswith('municipal_mapsee_')
@pytest.mark.parametrize('legacy',[False,True])
def test_large_feed_fails_instead_of_truncating(legacy):
 with pytest.raises(ValueError,match='source_record_limit'):parse(feed(501),{'url':'https://venue.example.org/calendar.ics'},legacy=legacy)
@pytest.mark.parametrize('legacy',[False,True])
def test_empty_and_invalid_are_distinct(legacy):
 assert parse('BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n',{},legacy=legacy)==[]
 with pytest.raises(ValueError):parse('<html>unavailable</html>',{},legacy=legacy)
def test_legacy_cache_media_and_category_fields_preserved():
 assert parse(feed(),{},legacy=True)==parse_ics_preview(feed(),allow_ongoing=True,include_images=True)
@pytest.mark.parametrize('legacy',[False,True])
def test_date_only_is_not_false_empty(legacy):
 raw=feed().replace('DTSTART:'+START,'DTSTART;VALUE=DATE:'+(datetime.now(timezone.utc)+timedelta(days=2)).strftime('%Y%m%d'))
 with pytest.raises(ValueError,match='unsupported_all_day_time'):parse(raw,{},legacy=legacy)
def test_failed_checkpoint_stays_failed():
 with patch('roomquest.preview_worker.fetch_publisher',return_value=feed(101)),patch('roomquest.preview_worker.supabase_rpc',side_effect=[100,PreviewError('database_unavailable'),None]) as rpc:
  result=_process_claimed_source(source('udell_fixture'))
 assert result['failed']==1 and result['complete']==0
 assert rpc.call_args.args[1]['p_error']=='database_unavailable'


def test_publisher_categories_are_preserved_as_individual_labels():
    events = parse(feed(), {}, legacy=False)
    assert len(events) == 1
    assert events[0]["publisher_categories"] == ["Arts", "Community"]
    assert events[0]["category"] == "Arts, Community"


def test_missing_publisher_categories_remain_empty_not_inferred():
    events = parse(feed().replace("CATEGORIES:Arts,Community\\r\\n", ""), {}, legacy=False)
    assert events[0]["publisher_categories"] == []
    assert events[0]["category"] == ""
