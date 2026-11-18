from datetime import datetime,timezone
import pytest
from roomquest import santa_cruz_reindeer as rr
SOURCE={'source_key':rr.KEY,'feed_url':rr.URL,'kind':'html','platform_adapter':'html','timezone':rr.ZONE}
NOW=datetime(2026,11,18,22,tzinfo=timezone.utc)
PAGE="""<body>2026 Reindeer Run Registration is Open NOW! Watch out, Boulder Creek! Reindeer will be congregating in herds on Christmas Eve! Be careful - they'll be dressed in disguises and costumes to participate in the 10th Annual Reindeer Run 5k run/walk. Between 9am and Noon, on December 24th, reindeer will be running, jogging, strolling, walking and rolling along Highway 9 and Irwin Way. They'll meet at Junction Park and celebrate the holidays by running through our beautiful town. Come out and cheer for the reindeer going through town on Christmas Eve! Or join the herd by registering for the event. Proceeds benefit the Boulder Creek Recreation and Park District Foundation. Interested in Volunteering? We need many volunteers to make this event work smoothly and safely. © 2026 Boulder Creek Reindeer Run</body>"""
PARK='<body>Junction Park 13264 Middleton Ave. Welcome to Boulder Creek Recreation and Park District</body>'
PAGES={rr.URL:PAGE,rr.PARK_URL:PARK}
def run(p=None,now=NOW):
 return rr.collect(SOURCE,lambda url,accept:(p or PAGES)[url],now=now)
def test_one_real_occurrence_not_repeating_daily_and_official_park_street():
 rows=run()
 assert len(rows)==1 and rows[0]['venue_address']==rr.ADDRESS
 assert rows[0]['starts_at'].startswith('2026-12-24T17:00')
 assert rows[0]['ends_at'].startswith('2026-12-24T20:00')
 assert rows[0]['lat'] is None and rows[0]['lng'] is None
 assert 'Boulder Creek Recreation and Park District' in rows[0]['description']
 assert rows[0]['event_url']==rr.URL
def test_publisher_and_park_changes_are_rejected():
 with pytest.raises(ValueError,match='reindeer_unregistered_source'):
  rr.collect(SOURCE|{'source_key':'different'},lambda url,accept:PAGES[url],now=NOW)
 with pytest.raises(ValueError,match='reindeer_date_or_location_changed'):
  run(PAGES|{rr.URL:PAGE.replace('9am and Noon','8am and Noon')})
 with pytest.raises(ValueError,match='reindeer_park_street_changed'):
  run(PAGES|{rr.PARK_URL:'<body>Junction Park (unknown address)</body>'})
def test_cancelled_or_expired_not_published():
 assert run(PAGES|{rr.URL:PAGE.replace('Interested in Volunteering?', 'Cancelled. Interested in Volunteering?')})==[]
 assert run(now=datetime(2027,1,1,tzinfo=timezone.utc))==[]
def test_source_link_identity():
 assert rr.event_url(rr.URL) and not rr.event_url('https://other.test/')
