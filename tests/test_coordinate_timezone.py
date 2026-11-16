from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch
import pytest
from roomquest.coordinate_timezone import resolve, run_batch, RESOLVER_VERSION

@pytest.mark.parametrize('lat,lng,zone',[
 (35.7796,-78.6382,'America/New_York'),(36.7265,-78.1289,'America/New_York'),
 (41.8781,-87.6298,'America/Chicago'),(39.7392,-104.9903,'America/Denver'),
 (34.0522,-118.2437,'America/Los_Angeles'),(33.4484,-112.074,'America/Phoenix'),
 (61.2181,-149.9003,'America/Anchorage'),(21.3099,-157.8581,'Pacific/Honolulu'),
])
def test_nationwide(lat,lng,zone):
 assert resolve(lat,lng)==zone

@pytest.mark.parametrize('lat,lng',[(None,1),(True,1),(0,0),(91,0),(0,181),('nan',1),(1,'inf'),('bad',1),(0,-140)])
def test_unusable(lat,lng):
 assert resolve(lat,lng) is None

def test_dst_uses_event_date_not_lookup_date():
 zone=ZoneInfo(resolve(35.7796,-78.6382))
 assert datetime(2026,1,15,19,tzinfo=zone).utcoffset().total_seconds()==-18000
 assert datetime(2026,7,15,19,tzinfo=zone).utcoffset().total_seconds()==-14400

def test_claims_only_and_stores_results():
 calls=[]
 def rpc(path,payload):
  calls.append((path,payload))
  if payload['p_action']=='claim':
   return [{'lat':35.7796,'lng':-78.6382,'lease_id':'lease'}]
  return 1
 result=run_batch(rpc=rpc)
 assert result=={'resolved':1,'unresolved':0,'applied':1}
 assert calls[1][1]['p_payload']=={'lat':35.7796,'lng':-78.6382,'lease_id':'lease','zone':'America/New_York','version':RESOLVER_VERSION}
 assert [p['p_action'] for _,p in calls]==['claim','finish','apply']

def test_empty_claim_does_not_lookup():
 with patch('roomquest.coordinate_timezone.resolve') as lookup:
  run_batch(rpc=lambda path,p: [] if p['p_action']=='claim' else 0)
  lookup.assert_not_called()

def test_overlapping_boundaries_are_unresolved():
 with patch('roomquest.coordinate_timezone.finder') as f:
  f.return_value.timezone_at_land.return_value='America/Chicago'
  f.return_value.timezones_at.return_value=['America/Chicago','America/Denver']
  assert resolve(40,-100) is None

@pytest.mark.parametrize('secret,header,status',[
 ('','',401),('test','Bearer wrong',401),('test','Bearer test',200)])
def test_entrypoint_authorization(secret,header,status):
 from api import timezones
 from unittest.mock import Mock
 h=object.__new__(timezones.handler)
 h.path='/api/timezones';h.headers={'Authorization':header};h.reply=Mock()
 with patch.dict('os.environ',{'CRON_SECRET':secret}), patch.object(timezones,'run_batch',return_value={}) as run:
  h.do_GET()
  assert h.reply.call_args.args[0]==status
  assert run.call_count==(1 if status==200 else 0)

def test_unified_entrypoint_routes_with_timezone_auth_not_geocoder_auth():
 from api import index,timezones
 from unittest.mock import Mock
 h=object.__new__(index.handler)
 h.path='/api/timezones';h.headers={'Authorization':'Bearer test'};h.reply=Mock()
 with patch.dict('os.environ',{'CRON_SECRET':'test'}),patch.object(timezones,'run_batch',return_value={'applied':1}) as run:
  h.do_GET()
  run.assert_called_once_with()
  h.reply.assert_called_once_with(200,{'applied':1})
