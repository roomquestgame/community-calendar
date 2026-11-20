"""Original Felton Fire Santa's Shelves dates, venue and complete narrative."""
from datetime import datetime,timezone
import pytest
from roomquest import santa_cruz_felton_fire as m

NOW=datetime(2026,11,19,23,tzinfo=timezone.utc)
SOURCE={'source_key':m.KEY,'feed_url':m.EVENT,'kind':'html','platform_adapter':'html','timezone':m.ZONE}
HTML='''<section class="bde-section-1657-104">
<h2>Santa's Shelves Craft Faire</h2>
<p>November 21 &amp; 22, 2026 · 10 AM – 4 PM</p>
<p>Come to the Felton Fire Station, corner of Kirby &amp; Gushee St to visit the Santa's Shelves Craft Faire. Handmade gifts, hometown treats, raffle baskets and community celebrations with local vendors.</p>
<p>Both days free admission. Saturday, November 21 and Sunday, November 22, 2026 · 10 AM – 4 PM · Free admission.</p>
<p>Santa's Shelves is presented by the Felton Fire Auxiliary. Silent auction and Bake sale supported by local volunteers. Santa visits from 1pm until 3pm each day; shop for handcrafted art and support the community!</p>
</section>'''
CONTACT='<p>131 Kirby Street, Felton, CA 95018</p>'
def fetch(url,accept):
    assert accept=='text/html'
    return {m.EVENT:HTML,m.CONTACT:CONTACT}[url]

def test_exact_two_original_future_rows():
    records=m.collect(SOURCE,fetch,now=NOW)
    assert len(records)==2
    for i,row in enumerate(records):
        day=21+i
        assert row['id']==f'felton-fire-santas-shelves-2026-11-{day:02d}'
        assert row['venue_address']==m.STREET
        assert row['lat'] is None and row['lng'] is None
        assert row['event_url']==m.EVENT
        assert row['starts_at']==f'2026-11-{day:02d}T18:00:00+00:00'
        assert row['ends_at']==f'2026-11-{day+1:02d}T00:00:00+00:00'
        assert row['description'].startswith("Santa's Shelves Craft Faire")
        assert len(row['description'])>300

@pytest.mark.parametrize('old,new',[
 ('November 21 &amp; 22, 2026','November 21 &amp; 23, 2026'),
 ('10 AM – 4 PM','10 AM',),
 ('Felton Fire Station','Unknown Site'),
 ('Kirby &amp; Gushee St','123 Other Street'),
 ('Felton Fire Auxiliary','Someone Else'),
 ('Silent auction','Other auction'),
 ('Bake sale','Some food'),
])
def test_original_event_evidence_fail_closed(old,new):
    with pytest.raises(ValueError):
        m.collect(SOURCE,lambda u,a:fetch(u,a).replace(old,new),now=NOW)

def test_contact_street_and_source_identity():
    with pytest.raises(ValueError,match='station_street'):
        m.collect(SOURCE,lambda u,a:CONTACT.replace('131','999') if u==m.CONTACT else fetch(u,a),now=NOW)
    with pytest.raises(ValueError,match='wrong_source'):
        m.collect({**SOURCE,'feed_url':'https://other.test/announcements'},fetch,now=NOW)
    assert m.event_url(m.EVENT) and not m.event_url(m.EVENT+'?track=1')
    assert not m.event_url('https://fake.test/santasshelves/')

def test_expired_occurrences_not_regenerated():
    assert m.collect(SOURCE,fetch,now=datetime(2027,1,1,tzinfo=timezone.utc))==[]
