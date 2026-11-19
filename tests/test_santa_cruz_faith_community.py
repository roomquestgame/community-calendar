"""Faith Community Santa Cruz guarded owner JSON and real program-specific street."""
from datetime import datetime,timezone
import json
import pytest
from roomquest import santa_cruz_faith_community as m
from roomquest.publisher_evidence import family

NOW=datetime(2026,11,19,7,40,tzinfo=timezone.utc)
SOURCE={"source_key":m.KEY,"feed_url":m.URL,"kind":"json","platform_adapter":"squarespace","timezone":m.ZONE}
OWNER="<html><footer>Connect Youth Community Groups Kids Community 115 S. Morrissey Ave, Santa Cruz, CA 95062 info@santacruzfaith.org</footer></html>"
BODY="<p>Help support H.O.M.E. - Homeless Outreach Missions &amp; Evangelism. For November we are collecting rain ponchos along with hats, scarves and gloves (and always men’s large and extra large clothing) to support this ministry at the Armory Shelter for those experiencing homelessness. Bring donations to the FCC office or the donation bin in the lobby.</p>"
def event():
    return {"id":"6aded281da0da518ca37d8e8","recordType":12,"workflowState":1,
      "title":"H.O.M.E. Donations","fullUrl":"/events-1/home-backpack-drive-7lz4j",
      "startDate":int(datetime(2026,11,21,16,30,tzinfo=timezone.utc).timestamp()*1000),
      "endDate":int(datetime(2026,11,21,20,0,tzinfo=timezone.utc).timestamp()*1000),
      "location":{"addressLine1":"115 S Morrissey Ave","addressLine2":"Santa Cruz, CA, 95062",
                  "addressCountry":"United States","addressTitle":"Midtown Community Center"},
      "body":BODY}
def fetch(u,accept):
    return OWNER if u==m.OWNER else json.dumps({"upcoming":[event()]})

def test_owner_local_community_date_duration_and_real_street():
    rows=m.collect(SOURCE,fetch,now=NOW)
    assert len(rows)==1
    r=rows[0]
    assert r["venue_address"]==m.STREET
    assert r["starts_at"]=="2026-11-21T16:30:00+00:00"
    assert r["ends_at"]=="2026-11-21T20:00:00+00:00"
    assert r.get("latitude") is None and r.get("longitude") is None
    assert "H.O.M.E." in r["description"]
    assert family(m.KEY,r["event_url"])=="santa_cruz_faith_community"

@pytest.mark.parametrize("field,value",[
 ("fullUrl","/other/home-event"),("startDate",None),
 ("endDate",int(datetime(2026,11,25,20,tzinfo=timezone.utc).timestamp()*1000)),
 ("location",{"addressLine1":"5 Park Ave","addressLine2":"Santa Cruz, CA, 95062","addressCountry":"United States"}),
 ("body","placeholder")])
def test_missing_event_identity_time_street_narrative_rejected(field,value):
    e=event();e[field]=value
    with pytest.raises(ValueError):
        m.collect(SOURCE,lambda u,a:OWNER if u==m.OWNER else json.dumps({"upcoming":[e]}),now=NOW)

def test_no_worship_default_or_offsite_camp_location():
    for title in ("Sunday Worship","Hume Lake Winter Camp"):
        e=event();e["title"]=title
        assert m.collect(SOURCE,lambda u,a:OWNER if u==m.OWNER else json.dumps({"upcoming":[e]}),now=NOW)==[]

def test_owner_street_and_identity_required():
    with pytest.raises(ValueError,match="faith_official_street"):
        m.collect(SOURCE,lambda u,a:OWNER.replace("115 S.","999 S.") if u==m.OWNER else json.dumps({"upcoming":[event()]}),now=NOW)
    with pytest.raises(ValueError,match="faith_source_identity"):
        m.collect({**SOURCE,"feed_url":"https://another.example/events"},fetch,now=NOW)
