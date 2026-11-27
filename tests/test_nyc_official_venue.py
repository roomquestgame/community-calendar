import json
from unittest.mock import Mock
import pytest
from roomquest import nyc_official_venue as n

NAME = "Gymnasium in Highbridge Recreation Center"
URL = "https://www.nycgovparks.org/events/2026/12/02/zumba1"
SCOPE = {"scope_version": n.VERSION, "venue": NAME, "evidence_venue": "Highbridge Recreation Center",
         "locality": "Manhattan", "region": "NY", "country": "US", "hosts": list(n.HOSTS)}
CLAIM = {"provider": "nyc_event_calendar", "venue_name": NAME, "raw_address": NAME,
         "publisher_name": "NYC Gov", "event_url": URL, "research_scope": SCOPE,
         "location_identity": {"adapter": "nyc_event_calendar", "source_key": "nyc_event_calendar_public",
                               "name": NAME, "address": NAME, "event_url": URL, "borough": "Mn"}}
ROW = {"uid": "fixture-id", "facname": "HIGHBRIDGE RECREATION CENTER", "addressnum": "2301",
       "streetname": "Amsterdam Ave", "boro": "Manhattan", "city": "New York", "zipcode": "10033"}


def test_official_scope_binds_named_indoor_parent():
    assert n.valid_scope(CLAIM, SCOPE)
    assert not n.valid_scope(CLAIM, {**SCOPE, "evidence_venue": "Central Park"})
    assert not n.valid_scope(CLAIM, {**SCOPE, "locality": "Queens"})
    assert not n.valid_scope(CLAIM, {**SCOPE, "hosts": ["www.nycgovparks.org"]})
    assert not n.valid_scope({**CLAIM, "event_url": "https://evil.example/events/1"}, SCOPE)
    assert n.facility_name({"venue_name": "Nature Center in Crotona Park",
                            "raw_address": "Nature Center in Crotona Park"}) == "Nature Center in Crotona Park"


def test_exact_directory_record_uses_existing_address_contract():
    fetch = Mock(return_value=json.dumps([ROW]))
    result = n.resolve_official(CLAIM, fetch=fetch, deadline_at=10)
    assert result["address"] == "2301 Amsterdam Ave, New York, NY 10033"
    assert result["directory_record"] == ROW and result["evidence_name"] == NAME
    assert result["evidence_url"] == n.API + "?uid=fixture-id"
    args, kw = fetch.call_args
    assert args[0].startswith(n.API + "?") and args[1] == "application/json"
    assert kw == {"respect_robots": True, "deadline_at": 10, "allowed_hosts": (n.HOST,), "follow_redirects": False}


@pytest.mark.parametrize("row", [{**ROW, "boro": "Queens"}, {**ROW, "facname": "Another Center"},
    {**ROW, "addressnum": ""}, {**ROW, "uid": "../invalid"}, {**ROW, "zipcode": "nozip"}])
def test_wrong_or_incomplete_identity_does_not_submit(row):
    assert n.address_candidate(CLAIM, SCOPE, [row]) is None


def test_duplicate_same_address_is_reusable_but_conflicting_address_is_held():
    assert n.address_candidate(CLAIM, SCOPE, [ROW, {**ROW, "uid": "other-id"}])["address"] == "2301 Amsterdam Ave, New York, NY 10033"
    with pytest.raises(n.DirectoryConflict):
        n.address_candidate(CLAIM, SCOPE, [ROW, {**ROW, "addressnum": "9999"}])
    with pytest.raises(n.DirectoryConflict):
        n.address_candidate(CLAIM, SCOPE, [ROW] * 21)


def test_cached_exact_address_does_not_fetch():
    fetch = Mock(side_effect=AssertionError("cache should win"))
    candidate = {"name": NAME, "address": "2301 Amsterdam Ave, New York, NY",
                 "evidence_url": "https://www.nyc.gov/fixture"}
    assert n.resolve_official({**CLAIM, "verified_candidate": candidate}, fetch=fetch, deadline_at=10)["address"] == candidate["address"]
    fetch.assert_not_called()


def test_fixed_query_escapes_name():
    from urllib.parse import parse_qs, urlparse
    query = parse_qs(urlparse(n.directory_url("St. John's Center")).query)
    assert query["$where"] == ["upper(facname)='ST. JOHN''S CENTER'"]


def test_ai_research_uses_exact_room_parent_and_independent_semantic_row():
    from roomquest.venue_research import research
    url = "https://comptroller.nyc.gov/fixture"
    page = "<main><h1>Recreation directory</h1><table><tr><td>Highbridge Recreation Center</td><td>Manhattan</td><td>2301 Amsterdam Ave</td><td>10033</td></tr><tr><td>Another Recreation Center</td><td>Manhattan</td><td>999 Other St</td></tr></table></main>"
    def model(payload):
        assert payload["identity"]["venue"] == "Highbridge Recreation Center"
        assert len(payload["passages"]) == 1
        p = payload["passages"][0]
        return json.dumps({"passage_id": p["id"], "street": "2301 Amsterdam Ave", "locality": "Manhattan",
                           "postal_code": "10033", "quote": p["text"]})
    search = Mock(return_value=[url])
    answer = research(CLAIM, admit=lambda _: {**SCOPE, "permit_id": "fixture-permit"},
                      search=search, fetch=Mock(return_value=page), complete=model,
                      model="fixture-model", deadline=30, clock=lambda: 0)
    assert answer["status"] == "proposed"
    assert answer["candidate"]["evidence_name"] == NAME
    assert "Highbridge Recreation Center" in answer["evidence_quote"]
    assert "www.nycgovparks.org" not in search.call_args.args[1]
