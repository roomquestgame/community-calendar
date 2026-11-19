"""Source-specific fail-closed original Santa Cruz Mountains Art Center 2026 holiday events."""
from datetime import datetime,timezone
from bs4 import BeautifulSoup
import pytest
from roomquest import santa_cruz_local_venues as mod

NOW=datetime(2026,11,19,19,tzinfo=timezone.utc)
SRC=dict(source_key=mod.SCMAC,feed_url=mod.SOURCES[mod.SCMAC][0],
         kind='html',platform_adapter='html',timezone=mod.ZONE)
def page():
 return """<html><main><h1>Call for Artists: The Gift of Art</h1>
 <p>Exhibit Dates: November 5 – December 22, 2026</p>
 <p>Once again we will have our popular holiday gift exhibit. For this show we ask artists to submit work that is suitable for gift giving. Framed paintings, crafty wall hangings, functional ceramics, sculpture, jewelry, cards, glass, woodwork, etc! All mediums are welcome. But all submissions must be for sale . Open to artists 18 years and older.</p>
 <h3>Related Events for this exhibit:</h3><p>Opening Reception, November 6 | 5 – 7 pm First Friday Open House, December 4 | 5 – 7 pm Annual Holiday Sale, December 19 | 12 – 5 pm</p>
 <p>9341 Mill Street, Ben Lomond, CA 95005</p></main></html>"""
def test_exact_two_true_dated_original_events():
 rows=mod.collect(SRC,lambda *_: page(),now=NOW)
 assert len(rows)==2
 assert [r['id'] for r in rows]==['scmac-2026-12-04-first-friday','scmac-2026-12-19-holiday-sale']
 assert [r['starts_at'] for r in rows]==['2026-12-05T01:00:00+00:00','2026-12-19T20:00:00+00:00']
 assert [r['ends_at'] for r in rows]==['2026-12-05T03:00:00+00:00','2026-12-20T01:00:00+00:00']
 assert all('9341 Mill Street' in r['venue_address'] for r in rows)
 assert all('functional ceramics' in r['description'] for r in rows)
 assert all(r['timezone']=='America/Los_Angeles' for r in rows)
 assert all(not r.get('lat') and not r.get('lng') for r in rows)
@pytest.mark.parametrize('old,new',[
 ('December 4','December 3'),
 ('December 19','December 18'),
 ('5 – 7 pm','5 – 8 pm'),
 ('12 – 5 pm','12 – 4 pm'),
 ('2026','2025'),
 ('9341 Mill Street','9300 Mill Street'),
 ('functional ceramics','unverified merchandise'),
 ('Related Events for this exhibit:','Applications only:'),
])
def test_identity_schedule_street_and_prose_fail_closed(old,new):
 with pytest.raises(ValueError):
  mod.collect(SRC,lambda *_: page().replace(old,new),now=NOW)
def test_exact_owner_feed_tuple_only():
 assert mod.event_url(mod.SCMAC,mod.SOURCES[mod.SCMAC][0])
 assert not mod.event_url(mod.SCMAC,'https://other.example/call-for-artists-gift-of-art-2026/')
 with pytest.raises(ValueError):mod.collect({**SRC,'feed_url':'https://other.example/'},lambda *_:page(),now=NOW)
def test_no_invented_future_recurring_events():
 assert mod.collect(SRC,lambda *_:page(),now=datetime(2027,2,1,tzinfo=timezone.utc))==[]
