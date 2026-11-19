"""First-party Scotts Valley single-session Dec 2026 Crafts & Cocoa."""
from datetime import datetime,timezone
import pytest
from roomquest import scotts_valley_cocoa as m
NOW=datetime(2026,11,19,19,tzinfo=timezone.utc)
SRC=dict(source_key=m.KEY,feed_url=m.EVENT,kind='html',platform_adapter='html',timezone=m.ZONE)
EVENT='''<main><h1>Crafts &amp; Cocoa</h1>
<p><strong>Crafts &amp; Cocoa is Back!</strong></p>
<p>Get cozy and get crafty with Scotts Valley Recreation! Join us for a festive evening filled with holiday crafts, warm cocoa, and plenty of holiday cheer for the whole family. Bring the kids, sip on something sweet, and enjoy a fun night creating holiday memories together.</p>
<p>This year, the event starts and hour earlier and price includes cookie decorating &amp; crafts.</p>
<p>Friday, December 11, 5-8pm Scotts Valley Community Center</p>
<p>Space is limited, so be sure to register early!</p></main>'''
ADDR='<p>360 Kings Village Rd. Scotts Valley, Ca 95066</p>'

def feed(url,_):
    if url==m.EVENT:return EVENT
    if url==m.ADDRESS:return ADDR
    raise ValueError('unexpected_fetch')
def test_exact_original_event_venue_and_date():
    a=m.collect(SRC,feed,now=NOW)
    assert len(a)==1
    assert a[0]['starts_at']=='2026-12-12T01:00:00+00:00'
    assert a[0]['ends_at']=='2026-12-12T04:00:00+00:00'
    assert a[0]['venue_address']==m.STREET
    assert a[0]['lat'] is None and a[0]['lng'] is None
    assert 'cookie decorating' in a[0]['description']
    assert a[0]['id']=='scotts-valley-crafts-cocoa-2026-12-11'
@pytest.mark.parametrize('old,new',[
 ('Friday, December 11','Friday, December 10'),
 ('5-8pm','5-9pm'),
 ('Scotts Valley Community Center','Unknown Center'),
 ('price includes cookie decorating &amp; crafts','price not specified'),
 ('Space is limited','Spaces forever available'),
 ('holiday crafts, warm cocoa, and plenty of holiday cheer','no event details'),
])
def test_source_changes_fail_closed(old,new):
    with pytest.raises(ValueError):
        m.collect(SRC,lambda u,a:feed(u,a).replace(old,new),now=NOW)
def test_location_change_holds_and_url_identity():
    with pytest.raises(ValueError):m.collect(SRC,lambda u,a:feed(u,a).replace('360 Kings Village','123 False Street'),now=NOW)
    assert m.event_url(m.EVENT)
    assert not m.event_url('https://example.com/807/Crafts-Cocoa')
    with pytest.raises(ValueError):m.collect({**SRC,'feed_url':'https://wrong.test'},feed,now=NOW)
def test_no_synthetic_later_recurrences():
    assert m.collect(SRC,feed,now=datetime(2027,2,1,tzinfo=timezone.utc))==[]
