"""RCNV original public event, source-street and narrative evidence fixtures."""
from datetime import datetime, timezone
import pytest
from roomquest import santa_cruz_rcnv as m

NOW = datetime(2026,11,19,22,tzinfo=timezone.utc)
SOURCE = {'source_key':m.KEY,'feed_url':m.CALENDAR,'kind':'html',
          'platform_adapter':'html','timezone':m.ZONE}
CALENDAR = '<a href="' + m.EVENT + '">Korea Is Not a War Base</a>'
CONTACT = '<p>612 Ocean Street Santa Cruz, CA 95060</p>'
EVENT = ('''<article><h1 class="entry-title">''' + m.TITLE + '''</h1>
<div class="em-event-single">
<div class="em-event-date">Nov 22, 2026</div>
<div class="em-event-time">3:00 pm - 5:00 pm</div>
<div class="em-event-location">Resource Center for Nonviolence 612 Ocean St., Santa Cruz, CA, 95060</div>
<div class="em-event-categories">Antiracism Resisting Militarism</div>
<div class="em-event-content">
<p>Join organizers for a reportback on the Jaju Solidarity Brigade's travels across South Korea and the movement against U.S. occupation.</p>
<p>Doors open at 2:30 PM. Event begins at 3:00 PM. Please join us for a discussion of the movement against occupation and grassroots campaigns.</p>
<p>Organizers will provide a community discussion about experiences and local connections, with a detailed talk from invited participants.</p>
<p>Everyone is welcome.</p>
</div></div></article>''')
def fetch(url, accept):
    assert accept == 'text/html'
    return {m.CALENDAR:CALENDAR,m.CONTACT:CONTACT,m.EVENT:EVENT}[url]

def test_complete_owner_venue_dates_and_classification():
    rows=m.collect(SOURCE,fetch,now=NOW)
    assert len(rows)==1
    row=rows[0]
    assert row['starts_at']=='2026-11-22T23:00:00+00:00'
    assert row['ends_at']=='2026-11-23T01:00:00+00:00'
    assert row['venue_address']==m.STREET
    assert row['lat'] is None and row['lng'] is None
    assert len(row['description']) > 250
    assert row['id']=='rcnv-jaju-solidarity-brigade-2026-11-22'
    assert row['publisher_categories']==['Antiracism','Resisting Militarism']

@pytest.mark.parametrize('old,new',[
('Nov 22, 2026','Nov 23, 2026'),
('3:00 pm - 5:00 pm','3:00 pm'),
('Resource Center for Nonviolence 612 Ocean St.','Unknown Venue 912 Ocean St.'),
('Everyone is welcome.',''),
('Antiracism Resisting Militarism',''),
('Jaju Solidarity Brigade','Another Event'),
])
def test_changed_original_details_fail_closed(old,new):
    with pytest.raises(ValueError):
        m.collect(SOURCE,lambda u,a:fetch(u,a).replace(old,new),now=NOW)

def test_original_calendar_and_street_required():
    with pytest.raises(ValueError,match='owner_calendar'):
        m.collect(SOURCE,lambda u,a: CALENDAR.replace(m.EVENT,'https://other.org') if u==m.CALENDAR else fetch(u,a),now=NOW)
    with pytest.raises(ValueError,match='official_street'):
        m.collect(SOURCE,lambda u,a: CONTACT.replace('612 Ocean','900 Ocean') if u==m.CONTACT else fetch(u,a),now=NOW)

def test_source_url_identity_and_expiry():
    assert m.event_url(m.EVENT)
    assert not m.event_url(m.EVENT+'?tracking=1')
    assert not m.event_url('https://attacker.test/events/korea-is-not-a-war-base-dispatches-from-the-2026-jaju-solidarity-brigade/')
    assert m.collect(SOURCE,fetch,now=datetime(2027,1,1,tzinfo=timezone.utc)) == []
    with pytest.raises(ValueError):
        m.collect({**SOURCE,'feed_url':'https://attacker.test'},fetch,now=NOW)

