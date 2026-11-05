import json,unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs
from roomquest.wordpress_adapter import collect
from roomquest.preview_worker import preview_source,PreviewError

def event(i=1):
 start=datetime.now(timezone.utc)+timedelta(days=2)
 return {'id':i,'title':'Public concert','utc_start_date':start.isoformat(),'utc_end_date':(start+timedelta(hours=2)).isoformat(),
 'url':'https://venue.example.org/event/'+str(i),'venue':{'venue':'Hall','address':'12 Main St','city':'Raleigh','state':'NC','geo_lat':35.8,'geo_lng':-78.6},'categories':[{'name':'Music'}]}

class WordPressTests(unittest.TestCase):
 def test_endpoint_preserves_filters_and_does_not_duplicate_path(self):
  calls=[]
  def fetch(url,accept):
   calls.append(url);return json.dumps({'events':[event()], 'total_pages':1})
  rows=collect({'feed_url':'https://venue.example.org/wp-json/tribe/events/v1/events/?organizer=12&per_page=50'},fetch)
  u=urlsplit(calls[0]);q=parse_qs(u.query)
  self.assertEqual(u.path.count('/wp-json/'),1);self.assertEqual(q['organizer'],['12']);self.assertEqual(q['per_page'],['100'])
  self.assertEqual(rows[0]['id'],'1');self.assertEqual(rows[0]['lat'],35.8)
 def test_root_and_complete_pagination(self):
  calls=[]
  def fetch(url,accept):
   calls.append(url);p=int(parse_qs(urlsplit(url).query)['page'][0]);return json.dumps({'events':[event(p)],'total_pages':2,'next_rest_url':'http://127.0.0.1/' if p==1 else None})
  rows=collect({'feed_url':'https://venue.example.org'},fetch)
  self.assertEqual(len(rows),2);self.assertEqual(len(calls),2);self.assertTrue(all(urlsplit(u).hostname=='venue.example.org' for u in calls))
 def test_over_budget_is_failure(self):
  with self.assertRaisesRegex(ValueError,'pagination_limit'):
   collect({'feed_url':'https://venue.example.org'},lambda *_:json.dumps({'events':[event()],'total_pages':6}))
 def test_successful_empty_remains_healthy(self):
  self.assertEqual(collect({'feed_url':'https://venue.example.org'},lambda *_:json.dumps({'events':[],'total_pages':0})),[])
 def test_invalid_event_is_not_confirmed_empty(self):
  e=event();e['utc_end_date']='2001-01-01T00:00:00Z'
  with self.assertRaisesRegex(ValueError,'invalid_event_end'):
   collect({'feed_url':'https://venue.example.org'},lambda *_:json.dumps({'events':[e]}))
 def test_missing_geometry_keeps_actual_venue_for_shared_cache(self):
  e=event();e['venue'].pop('geo_lat');e['venue'].pop('geo_lng')
  rows=collect({'feed_url':'https://venue.example.org'},lambda *_:json.dumps({'events':[e]}))
  self.assertIsNone(rows[0]['lat']);self.assertIn('Raleigh',rows[0]['venue_address'])
 def test_registered_mapsee_dispatch_uses_wordpress_family(self):
  source={'source_key':'municipal_mapsee_fixture','feed_url':'https://venue.example.org','kind':'json','platform_adapter':'wordpress'}
  with patch('roomquest.mapsee_adapter.profiles',return_value={source['source_key']:{'url':source['feed_url'],'type':'tribe'}}),patch('roomquest.preview_worker.fetch_publisher',return_value=json.dumps({'events':[event()],'total_pages':1})) as fetch:
   result=preview_source(source);self.assertEqual(result['p_source_key'],source['source_key']);self.assertEqual(len(result['p_events']),1);self.assertTrue(fetch.call_args.kwargs['respect_robots'])
 def test_unregistered_mapsee_cannot_fetch(self):
  with patch('roomquest.mapsee_adapter.profiles',return_value={}),patch('roomquest.preview_worker.fetch_publisher') as fetch:
   with self.assertRaisesRegex(PreviewError,'unregistered_mapsee_source'):preview_source({'source_key':'municipal_mapsee_bad','feed_url':'https://venue.example.org','kind':'json','platform_adapter':'wordpress'})
   fetch.assert_not_called()
 def test_all_checkpoints_precede_success(self):
  from roomquest.preview_worker import _process_claimed_source
  source={'source_key':'municipal_mapsee_fixture','feed_url':'https://venue.example.org','kind':'json','platform_adapter':'wordpress'}
  def fetch(url,*args,**kwargs):
   page=int(parse_qs(urlsplit(url).query)['page'][0])
   return json.dumps({'events':[event(i) for i in range((page-1)*100,page*100)],'total_pages':2})
  def rpc(name,payload):
   return len(payload['p_events']) if name.endswith('record_staged_events') else None
  with patch('roomquest.mapsee_adapter.profiles',return_value={source['source_key']:{'url':source['feed_url'],'type':'tribe'}}),patch('roomquest.preview_worker.fetch_publisher',side_effect=fetch),patch('roomquest.preview_worker.supabase_rpc',side_effect=rpc) as db:
   result=_process_claimed_source(source)
   self.assertEqual(result,{'complete':1,'failed':0,'staged':200})
   self.assertEqual([c.args[0] for c in db.call_args_list],['community_collector_record_staged_events']*10+['community_collector_record_preview'])
   self.assertEqual(db.call_args_list[-1].args[1]['p_future_count'],200)
 def test_failed_checkpoint_never_reports_complete(self):
  from roomquest.preview_worker import _process_claimed_source
  source={'source_key':'municipal_mapsee_fixture'}
  output={'p_source_key':source['source_key'],'p_events':[{'title':str(i)} for i in range(101)],'p_error':None}
  with patch('roomquest.preview_worker.preview_source',return_value=output),patch('roomquest.preview_worker.supabase_rpc',side_effect=[100,PreviewError('database_unavailable'),None]) as db:
   result=_process_claimed_source(source)
   self.assertEqual(result['failed'],1);self.assertEqual(result['complete'],0)
   self.assertEqual(db.call_args_list[-1].args[1]['p_error'],'database_unavailable')

class ParksTests(unittest.TestCase):
 def test_madison_zone_fallback_requires_matching_official_detail(self):
  import copy
  e=event();e.update(status='publish',timezone='UTC+0',url='https://venue.example.org/calendar/event/',
   start_date='2026-11-17 18:00:00',end_date='2026-11-17 19:00:00',
   utc_start_date='2026-11-17 18:00:00',utc_end_date='2026-11-17 19:00:00')
  source={'source_key':'madison_county_parks_ia','feed_url':'https://venue.example.org','timezone':'America/Chicago'}
  page='<h1 class="tribe-events-single-event-title">Public concert</h1><div class="tribe-events-schedule"><span class="tribe-event-date-start">November 17 @ 6:00 pm</span><span class="tribe-event-time">7:00 pm</span></div><div class="tribe-events-start-time" title="2026-11-17"></div>'
  calls=[]
  def fetch(url,accept):
   calls.append((url,accept));return page if accept=='text/html' else json.dumps({'events':[copy.deepcopy(e)]})
  row=collect(source,fetch)[0]
  self.assertEqual(datetime.fromisoformat(row['starts_at']).astimezone(timezone.utc).isoformat(),'2026-11-18T00:00:00+00:00')
  self.assertEqual(row['timezone'],'America/Chicago');self.assertEqual(len(calls),2)
  for bad in (page.replace('Public concert','Wrong event'),page.replace('2026-11-17','2026-11-03'),page.replace('6:00 pm','5:00 pm'),page.replace('7:00 pm','8:00 pm')):
   with self.subTest(page=bad),self.assertRaisesRegex(ValueError,'publisher_timezone_review_required'):
    collect(source,lambda u,a:bad if a=='text/html' else json.dumps({'events':[e]}))
  e['url']='https://other.example.org/calendar/event/'
  with self.assertRaisesRegex(ValueError,'publisher_timezone_review_required'):
   collect(source,fetch)
 def test_actual_madison_api_timezone_requires_review(self):
  # Factual fields captured from live API Nov 5; no prose/coordinate fixture.
  e=event();e.update(status='publish',timezone='UTC+0',
   start_date='2026-11-17 18:00:00',end_date='2026-11-17 19:00:00',
   utc_start_date='2026-11-17 18:00:00',utc_end_date='2026-11-17 19:00:00')
  source={'source_key':'madison_county_parks_ia','feed_url':'https://venue.example.org','timezone':'America/Chicago'}
  with self.assertRaisesRegex(ValueError,'publisher_timezone_review_required'):
   collect(source,lambda *_:json.dumps({'events':[e]}))
  # Its UTC+0 representations are internally consistent, but disagree with
  # the reviewed Iowa source timezone. No six-hour correction is invented.
  del source['timezone']
  self.assertEqual(len(collect(source,lambda *_:json.dumps({'events':[e]}))),1)
 def test_madison_conflicting_local_and_utc_times_fail_without_guessing(self):
  from zoneinfo import ZoneInfo
  source={'source_key':'madison_county_parks_ia','feed_url':'https://venue.example.org'}
  e=event();e.update(status='publish',timezone='America/Chicago')
  for field in ('start_date','end_date'):
   instant=datetime.fromisoformat(e['utc_'+field])
   e[field]=instant.astimezone(ZoneInfo('America/Chicago')).replace(tzinfo=None).isoformat()
  self.assertEqual(len(collect(source,lambda *_:json.dumps({'events':[e]}))),1)
  for field in ('start_date','end_date'):
   bad=dict(e);bad[field]=datetime.fromisoformat(e['utc_'+field]).replace(tzinfo=None).isoformat()
   with self.subTest(field=field),self.assertRaisesRegex(ValueError,'publisher_schedule_conflict'):
    collect(source,lambda *_:json.dumps({'events':[bad]}))
 def test_madison_narrative_is_clean_bounded_and_source_scoped(self):
  e=event();e.update(status='publish',description='<p>Learn &amp; build.</p><script>bad()</script><p>Bring tools.</p>')
  for key in ('madison_county_parks_ia','nebraska_game_parks','municipal_mapsee_fixture'):
   rows=collect({'source_key':key,'feed_url':'https://venue.example.org'},lambda *_:json.dumps({'events':[e]}))
   if key=='madison_county_parks_ia':self.assertEqual(rows[0]['description'],'Learn & build.\nBring tools.')
   else:self.assertNotIn('description',rows[0])
  e['description']='x'*2100
  rows=collect({'source_key':'madison_county_parks_ia','feed_url':'https://venue.example.org'},lambda *_:json.dumps({'events':[e]}))
  self.assertEqual(len(rows[0]['description']),2000)
 def test_madison_missing_or_malformed_prose_is_not_invented(self):
  source={'source_key':'madison_county_parks_ia','feed_url':'https://venue.example.org'}
  for value in (None,''):
   e=event();e.update(status='publish',description=value)
   self.assertEqual(collect(source,lambda *_:json.dumps({'events':[e]}))[0]['description'],'')
  e['description']={'rendered':'wrong API shape'}
  with self.assertRaisesRegex(ValueError,'invalid_wordpress_description'):
   collect(source,lambda *_:json.dumps({'events':[e]}))
 def test_madison_worker_carries_narrative_to_staging_without_extra_fetch(self):
  source={'source_key':'madison_county_parks_ia','feed_url':'https://venue.example.org','kind':'json','platform_adapter':'wordpress'}
  e=event();e.update(status='publish',description='<p>Learn basket weaving.</p>')
  with patch('roomquest.preview_worker.fetch_publisher',return_value=json.dumps({'events':[e]})) as fetch:
   result=preview_source(source)
  self.assertEqual(result['p_events'][0]['description'],'Learn basket weaving.')
  self.assertEqual(result['p_events'][0]['venue_address'],'12 Main St, Raleigh, NC')
  self.assertEqual(fetch.call_count,1)
 def test_parks_preserve_timezone_and_address_but_reject_nonpublic_records(self):
  source={'source_key':'nebraska_game_parks','feed_url':'https://calendar.outdoornebraska.gov/wp-json/tribe/events/v1/events'}
  good=event();good.update(status='publish',timezone='America/Denver')
  good['venue']['stateprovince']=good['venue'].pop('state')
  bad=[dict(good,**patch) for patch in ({'status':'draft'},{'is_virtual':True},{'hide_from_listings':True},{'event_status':'cancelled'},{'all_day':True})]
  rows=collect(source,lambda *_:json.dumps({'events':[good]+bad,'total_pages':1}))
  self.assertEqual(len(rows),1);self.assertEqual(rows[0]['timezone'],'America/Denver')
  self.assertIn('NC',rows[0]['venue_address']);self.assertEqual(rows[0]['lat'],35.8)
 def test_custom_json_source_receives_worker_deadline(self):
  from roomquest.preview_worker import _process_claimed_source
  source={'source_key':'madison_county_parks_ia','kind':'json','platform_adapter':'wordpress'}
  with patch('roomquest.preview_worker.preview_source',return_value={'p_source_key':source['source_key'],'p_events':[],'p_error':None}) as preview,patch('roomquest.preview_worker.supabase_rpc'):
   _process_claimed_source(source)
   self.assertIn('deadline_at',preview.call_args.kwargs)

if __name__=='__main__':unittest.main()


class WordPressOffsetTests(unittest.TestCase):
 def test_fixed_offset_timezone_with_utc_dates(self):
  for zone,expected in [('UTC+0','UTC'),('UTC-6','Etc/GMT+6'),('UTC+5.5','UTC')]:
   with self.subTest(zone=zone):
    e=event();e.update(status='publish',timezone=zone)
    rows=collect({'source_key':'madison_county_parks_ia','feed_url':'https://venue.example.org'},lambda *_:json.dumps({'events':[e]}))
    self.assertEqual(rows[0]['timezone'],expected)
    self.assertEqual(rows[0]['starts_at'],e['utc_start_date'])

 def test_park_publisher_gps_survives_highway_address(self):
  e=event();e.update(status='publish',timezone='America/Denver')
  e['venue'].update(address='210615 NE-71',city='Gering',state='Nebraska')
  rows=collect({'source_key':'nebraska_game_parks','feed_url':'https://venue.example.org'},lambda *_:json.dumps({'events':[e]}))
  self.assertEqual(rows[0]['lat'],35.8)
