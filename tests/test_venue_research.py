import json
from unittest.mock import Mock

import pytest
from roomquest.venue_research import research, search_urls

CLAIM = {"venue_name": "Wave Hill", "venue_key": "example", "lease_id": "lease"}
SCOPE = {"permit_id": "permit", "venue": "Wave Hill", "locality": "Bronx",
         "region": "NY", "country": "US", "hosts": ["www.nyc.gov"]}
URL = "https://www.nyc.gov/wavehill"
QUOTE = "Wave Hill Visitor entrance 4900 Independence Avenue Bronx 10471"
HTML = "<main><h1>Wave Hill</h1><p>Visitor entrance 4900 Independence Avenue Bronx 10471</p></main>"
ADDRESS = "4900 Independence Avenue, Bronx, NY 10471"


def model(payload, **patch):
    return json.dumps({"passage_id": payload["passages"][0]["id"],
                       "street": "4900 Independence Avenue", "locality": "Bronx",
                       "postal_code": "10471", "quote": QUOTE, **patch})


def fixture(**overrides):
    deps = {"admit": Mock(return_value=SCOPE), "search": Mock(return_value=[URL]),
            "fetch": Mock(return_value=HTML), "complete": Mock(side_effect=model),
            "model": "fixture-model", "deadline": 30, "clock": lambda: 0}
    deps.update(overrides)
    return research(CLAIM, **deps), deps


def test_unstructured_page_produces_evidence_bound_proposal():
    r, d = fixture()
    assert r["status"] == "proposed" and r["candidate"]["address"] == ADDRESS
    assert r["permit_id"] == "permit" and r["evidence_quote"] == QUOTE
    assert r["selection_method"] == "model_evidence_extraction_v1"
    assert "latitude" not in r["candidate"]
    assert d["admit"].call_count == d["search"].call_count == d["complete"].call_count == 1


def test_no_permit_no_external_work():
    r, d = fixture(admit=Mock(return_value=None))
    assert r["reason"] == "budget_or_scope_not_admitted"
    for k in ("search", "fetch", "complete"):
        d[k].assert_not_called()


@pytest.mark.parametrize("change", [{"venue": "other venue"}, {"locality": ""},
    {"hosts": ["*.nyc.gov"]}, {"country": "GB"}, {"region": ""}])
def test_wrong_scope_rejected(change):
    r, d = fixture(admit=Mock(return_value={**SCOPE, **change}))
    assert r["status"] == "held"
    d["search"].assert_not_called()


@pytest.mark.parametrize("lead", [{"url": URL, "address": ADDRESS},
    "https://www.nyc.gov.evil.example/wavehill", URL+"?secret=x", "http://www.nyc.gov/wavehill"])
def test_search_snippet_and_foreign_host_are_not_evidence(lead):
    r, d = fixture(search=Mock(return_value=[lead]))
    assert r["reason"] == "no_scoped_passage"
    d["fetch"].assert_not_called()
    d["complete"].assert_not_called()


@pytest.mark.parametrize("html", [HTML.replace("Bronx", "Brooklyn"),
    HTML.replace("<h1>Wave Hill</h1>", "<h1>Wave Hill Annex</h1>"),
    "<main><h1>Wave Hill</h1>Bronx</main><footer>4900 Independence Avenue</footer>",
    "<main><h1>Wave Hill</h1>Bronx<script>4900 Independence Avenue</script></main>"])
def test_wrong_identity_or_footer_not_evidence(html):
    r, d = fixture(fetch=Mock(return_value=html))
    assert r["reason"] == "no_scoped_passage"
    d["complete"].assert_not_called()


def test_conflicting_streets_are_held_without_model():
    r, d = fixture(fetch=Mock(return_value=HTML.replace("</p>", " and 1 Other Road Bronx</p>")))
    assert r["reason"] == "conflicting_evidence"
    d["complete"].assert_not_called()


def test_incomplete_evidence_set_not_used():
    r, d = fixture(search=Mock(return_value=[URL, URL+"/two", URL+"/three"]))
    assert r["reason"] == "incomplete_evidence_set"
    d["complete"].assert_not_called()


@pytest.mark.parametrize("patch", [{"street": "1 Other Road"}, {"quote": "invented quote"},
    {"locality": "Queens"}, {"postal_code": "10001"}, {"passage_id": "invented"},
    {"latitude": 40.0}])
def test_invalid_model_output_held(patch):
    r, _ = fixture(complete=Mock(side_effect=lambda p: model(p, **patch)))
    assert r["status"] == "held"


def test_null_model_answer_held():
    r, _ = fixture(complete=Mock(return_value='{"passage_id":null}'))
    assert r["reason"] == "ambiguous"


def test_no_remaining_deadline_no_admission():
    r, d = fixture(deadline=12)
    assert r["reason"] == "configuration_or_deadline"
    d["admit"].assert_not_called()


def test_no_second_host_after_transport_denial():
    fetch = Mock(side_effect=RuntimeError("robots_denied"))
    with pytest.raises(RuntimeError, match="robots_denied"):
        fixture(search=Mock(return_value=[URL, URL+"/other"]), fetch=fetch)
    fetch.assert_called_once()


def test_search_without_separate_key_never_calls_network(monkeypatch):
    post = Mock()
    monkeypatch.setattr("roomquest.venue_research.requests.post", post)
    with pytest.raises(ValueError, match="search_not_configured"):
        search_urls("Wave Hill", SCOPE["hosts"], api_key="", deadline_at=20, clock=lambda: 0)
    post.assert_not_called()
