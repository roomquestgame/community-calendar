"""Guard first-party Little Giant event JSON, venue streets, and recurring-range holds."""
import json
from datetime import datetime, timezone
import pytest
from roomquest import santa_cruz_little_giant as m
from roomquest.publisher_evidence import family

NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)
SOURCE = {"source_key":m.KEY, "feed_url":m.URL, "kind":"json", "platform_adapter":"squarespace", "timezone":m.ZONE}
CONTACT = "<html><body><h1>Where we are</h1><p>115 RIVER ST SOUTH</p><p>SANTA CRUZ, CA 95060</p></body></html>"
BODY = "<div><p>Come play with us! Bring your art, your craft, your crossword puzzle, and your friends. We have tunes, snacks, sips and tea. You do not need to be good at art. This is a space for community to connect, people to laugh, and doodles to be made. We will play some games and generally have fun!</p></div>"
def evt(dt="2026-11-25T02:00:00Z"):
    start = int(datetime.fromisoformat(dt.replace("Z","+00:00")).timestamp()*1000)
    return {"id":"6af155b52f132f1815046b3c", "recordType":12, "workflowState":1,
            "fullUrl":"/calendar/2026/6/24/sipnsketch-7aajr-yfx4h",
            "title":"Sip 'N' Sketch (Copy)", "startDate":start, "endDate":start+7200000, "body":BODY,
            "location":{"addressTitle":"Little Giant Collective","addressLine1":"115 River St. South",
                        "addressLine2":"Santa Cruz, Ca", "addressCountry":"USA",
                        "markerLat":36.9752849,"markerLng":-122.0243303}}
def payload(rows=None):
    return json.dumps({"upcoming":rows if rows is not None else [evt()]})
def fetch(url, accept):
    assert (url,accept) in ((m.CONTACT,"text/html"),(m.URL,"application/json"))
    return CONTACT if url == m.CONTACT else payload()

def test_structured_owner_event_with_street_and_no_guessed_geocode():
    row = m.collect(SOURCE, fetch, now=NOW)[0]
    assert row["venue_address"] == m.STREET
    assert row["starts_at"] == "2026-11-25T02:00:00+00:00"
    assert row["ends_at"] == "2026-11-25T04:00:00+00:00"
    assert row.get("latitude") is None and row.get("longitude") is None
    assert "We have tunes" in row["description"]
    assert family(m.KEY, row["event_url"]) == "santa_cruz_little_giant"

def test_no_monthly_range_synthesized_or_venue_opening_hours():
    assert m.collect(SOURCE, lambda u,a: CONTACT if u==m.CONTACT else payload([
        {"title":"Women's Art Club Monthly", "startDate":1795141800997,
         "endDate":1806636600997}]),now=NOW) == []

@pytest.mark.parametrize("field,changed",[
    ("title","Private Party"),("fullUrl","/blog/sipnsketch"),("startDate",1795575600184),
    ("location",{"addressLine1":"115 Broadway", "addressLine2":"Santa Cruz, Ca", "addressCountry":"USA"}),
    ("body","generic")])
def test_bad_event_proof_rejected_or_not_promoted(field,changed):
    e=evt();e[field]=changed
    if field=="title":assert m.collect(SOURCE,lambda u,a:CONTACT if u==m.CONTACT else payload([e]),now=NOW)==[]
    else:
        with pytest.raises(ValueError):
            m.collect(SOURCE,lambda u,a:CONTACT if u==m.CONTACT else payload([e]),now=NOW)

def test_official_contact_and_source_identity_required():
    with pytest.raises(ValueError,match="little_giant_official_street"):
        m.collect(SOURCE,lambda u,a:CONTACT.replace("115","999") if u==m.CONTACT else payload(),now=NOW)
    with pytest.raises(ValueError,match="little_giant_source_identity"):
        m.collect({**SOURCE,"feed_url":"https://evil.example/calendar"},fetch,now=NOW)
