"""Original Watsonville Taiko Squarespace structured feed, strict venue and clocks."""
from datetime import datetime, timezone
import json
import pytest
from roomquest import santa_cruz_watsonville_taiko as m
from roomquest.publisher_evidence import family

NOW = datetime(2026, 11, 19, 16, tzinfo=timezone.utc)
SOURCE = {"source_key":m.KEY,"feed_url":m.FEED,"kind":"json",
          "platform_adapter":"squarespace","timezone":m.ZONE}

def fixture(**updates):
    event = {
      "id":"6aa8a9c91f869b010d1bcf11", "recordType":12,"workflowState":1,
      "title":"Cookie Workshop","fullUrl":"/events/2026/12/5/cookie-workshop",
      "startDate":1796506200809, "endDate":1796513400809,
      "structuredContent":{"_type":"CalendarEvent","startDate":1796506200809,"endDate":1796513400809},
      "location":{"addressTitle":"Kizuka Hall","addressLine1":" 150 Blackburn Street",
                  "addressLine2":"Watsonville, CA, 95076","addressCountry":"United States"},
      "body":"<p>We will make cranberry pinwheel cookies, molasses, checkerboard, and two types of slice and bake refrigerator cookies. The $35 fee includes all ingredients for every participant.</p>"
    }
    event.update(updates)
    return json.dumps({"website":{"primaryDomain":"www.watsonvilletaiko.org","siteTitle":"Watsonville Taiko"},
                       "upcoming":[event]})

def run(payload=None):
    return m.collect(SOURCE, lambda url,accept: payload or fixture(),now=NOW)

def test_first_party_structured_event():
    a=run()
    assert len(a)==1
    e=a[0]
    assert "Cookie Workshop"==e["title"]
    assert e["venue_address"] == m.STREET
    assert "cranberry" in e["description"]
    assert e["lat"] is None and e["lng"] is None
    assert e["ends_at"] and e["starts_at"]
    assert m.event_url(e["event_url"])
    assert family(m.KEY,e["event_url"]) == "watsonville_taiko"

@pytest.mark.parametrize("mod",[
    {"fullUrl":"/events/2026/12/5/other","location":{"addressTitle":"Other","addressLine1":"150 Blackburn Street","addressLine2":"Watsonville, CA, 95076","addressCountry":"United States"}},
    {"endDate":1796506200809},
    {"body":"<p>short</p>"},
    {"fullUrl":"/events/2026/12/4/cookie-workshop"},
    {"id":"invented"}
])
def test_guardrails(mod):
    with pytest.raises(ValueError): run(fixture(**mod))

def test_source_identity_and_time_guard():
    with pytest.raises(ValueError): m.collect(dict(SOURCE,source_key="other"),lambda u,a:fixture(),now=NOW)
    assert not m.event_url("https://attacker.org/events/2026/12/5/cookie-workshop")
    assert not m.event_url("https://www.watsonvilletaiko.org/events/2026/12/5/cookie-workshop?bad=1")
    assert run(fixture(startDate=1796506200809))[0]["lat"] is None

