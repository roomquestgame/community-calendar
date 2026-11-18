from datetime import datetime,timezone
import pytest
from roomquest import santa_cruz_boardwalk as bw

SOURCE={'source_key':bw.KEY,'feed_url':bw.URL,'kind':'html','platform_adapter':'html','timezone':bw.ZONE}
NOW=datetime(2026,11,18,22,tzinfo=timezone.utc)
LIST='<html><body><article class="mec-event-article"><h3>Brunch with Santa</h3><p>Sunday, December 13, 2026 9am-11:30am</p><a href="'+bw.DETAIL+'">More Info</a></article></body></html>'
DETAIL='<html><body>Brunch with Santa Sunday, December 13, 2026 9am Grab your friends and family for a jolly morning in The Grove: Santa Cruz Event Center! Schedule: 9am Doors Open 9:30am Buffet Open 10am Cookie Decorating and Coloring Station 10:30am Santa arrives 11am Story time. Brunch Menu: Pancakes, scrambled eggs, fresh baked pastries and fruit display. Boardwalk Holiday Events Other events</body></html>'
GROVE='<html><body>The Grove: Santa Cruz Event Center at the Boardwalk 400 Beach Street Santa Cruz, CA 95060</body></html>'
PAGES={bw.URL:LIST,bw.DETAIL:DETAIL,bw.GROVE:GROVE}
def collect(p=None,now=NOW):
 return bw.collect(SOURCE,lambda url,accept:(p or PAGES)[url],now=now)

def test_street_and_full_original_detail_and_showtime():
 rows=collect()
 assert len(rows)==1
 assert rows[0]['venue_address']==bw.ADDRESS
 assert rows[0]['starts_at'].startswith('2026-12-13T17:00')
 assert rows[0]['ends_at'].startswith('2026-12-13T19:30')
 assert rows[0]['lat'] is None
 assert 'Brunch Menu' in rows[0]['description']
 assert rows[0]['event_url']==bw.DETAIL
def test_source_identity_and_address_drift_fail_closed():
 with pytest.raises(ValueError,match='boardwalk_unregistered_source'):
  bw.collect(SOURCE|{'source_key':'different'},lambda url,accept:PAGES[url],now=NOW)
 with pytest.raises(ValueError,match='boardwalk_venue_street_changed'):
  collect(PAGES|{bw.GROVE:'<body>The Grove: Santa Cruz Event Center, street unknown</body>'})
 with pytest.raises(ValueError,match='boardwalk_detail_identity_changed'):
  collect(PAGES|{bw.URL:LIST.replace(bw.DETAIL,'https://example.net/brunch/')})
def test_sold_out_and_stale_events_not_published():
 assert collect(PAGES|{bw.DETAIL:DETAIL.replace('Brunch Menu','SOLD OUT Brunch Menu')})==[]
 assert collect(now=datetime(2027,1,1,tzinfo=timezone.utc))==[]
def test_only_own_original_event_link():
 assert bw.event_url(bw.DETAIL)
 assert not bw.event_url('https://test1.beachboardwalk.com/brunch-with-santa/')
