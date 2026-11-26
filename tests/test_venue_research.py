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


def test_model_input_byte_cap(monkeypatch):
    from roomquest.venue_research import anthropic_extract
    post = Mock()
    monkeypatch.setattr("roomquest.venue_research.requests.post", post)
    with pytest.raises(ValueError, match="model_input_bound"):
        anthropic_extract({"huge": "x" * 17000}, api_key="mock", model="test", deadline_at=20, clock=lambda: 0)
    post.assert_not_called()


from roomquest.venue_research import configured, claim_options, defer_miss, handle_claim

CONFIG = {"model": "test", "search_key": "search", "model_key": "model"}
IDENTITY = {"venue_key": "key", "lease_id": "lease"}
WORKER_CLAIM = {**IDENTITY, "provider": "nyc_event_calendar", "venue_name": "Wave Hill", "research_permit": SCOPE}
PROPOSAL = {"status": "proposed", "candidate": {"address": ADDRESS}}


def test_disabled_by_default_and_no_crawler_key_fallback():
    env = {"VENUE_RESEARCH_MODEL": "test", "TAVILY_API_KEY": "crawler", "VENUE_AI_ANTHROPIC_API_KEY": "model"}
    assert configured(env) is None
    env["VENUE_RESEARCH_ENABLED"] = "true"
    assert configured(env) is None
    env["VENUE_RESEARCH_TAVILY_API_KEY"] = "search"
    assert configured(env) == CONFIG
    assert claim_options(configured(env)) == {"limit": 1, "research_model": "test"}
    assert claim_options(None) == {"limit": 1}


def test_defer_only_on_eligible_miss():
    db = Mock(return_value={"deferred": True})
    assert not defer_miss(db, WORKER_CLAIM, IDENTITY, None)
    assert not defer_miss(db, {"provider": "ics"}, IDENTITY, CONFIG)
    db.assert_not_called()
    assert defer_miss(db, WORKER_CLAIM, IDENTITY, CONFIG)
    db.assert_called_once_with("research_defer", {**IDENTITY, "model": "test"})
    db.return_value = {"deferred": False}
    assert not defer_miss(db, WORKER_CLAIM, IDENTITY, CONFIG)


def test_ordinary_lease_untouched(monkeypatch):
    lookup = Mock()
    monkeypatch.setattr("roomquest.venue_research.research", lookup)
    db = Mock()
    assert handle_claim(db, IDENTITY, IDENTITY, CONFIG, fetch=Mock(), deadline=15, clock=lambda: 0) is None
    lookup.assert_not_called()
    db.assert_not_called()


@pytest.mark.parametrize("config,claim", [(None, WORKER_CLAIM), (CONFIG, {**WORKER_CLAIM, "research_permit": {"bad": True}})])
def test_unconfigured_or_invalid_permit_does_not_call_provider(monkeypatch, config, claim):
    lookup = Mock()
    monkeypatch.setattr("roomquest.venue_research.research", lookup)
    db = Mock()
    assert handle_claim(db, claim, IDENTITY, config, fetch=Mock(), deadline=15, clock=lambda: 0) == "review"
    lookup.assert_not_called()
    db.assert_called_once_with("fail", {**IDENTITY, "reason": "needs_review"})


def test_admitted_research_persists_proposal_before_submit(monkeypatch):
    lookup = Mock(return_value=PROPOSAL)
    monkeypatch.setattr("roomquest.venue_research.research", lookup)
    db = Mock(return_value={"recorded": True})
    assert handle_claim(db, WORKER_CLAIM, IDENTITY, CONFIG, fetch=Mock(), deadline=15, clock=lambda: 0) == "resolved"
    assert [c.args for c in db.call_args_list] == [("research_propose", {**IDENTITY, "proposal": PROPOSAL}),
        ("submit", {**IDENTITY, **PROPOSAL["candidate"]})]
    assert lookup.call_args.kwargs["admit"](WORKER_CLAIM) == WORKER_CLAIM["research_permit"]


@pytest.mark.parametrize("answer,receipt", [({"status": "held"}, {}), (PROPOSAL, {"recorded": False})])
def test_no_submit_on_held_or_rejected_proposal(monkeypatch, answer, receipt):
    monkeypatch.setattr("roomquest.venue_research.research", Mock(return_value=answer))
    db = Mock(return_value=receipt)
    assert handle_claim(db, WORKER_CLAIM, IDENTITY, CONFIG, fetch=Mock(), deadline=15, clock=lambda: 0) == "review"
    assert all(c.args[0] != "submit" for c in db.call_args_list)
    assert db.call_args.args == ("fail", {**IDENTITY, "reason": "needs_review"})


def test_gateway_oidc_explicit_model_and_search_opt_in(monkeypatch):
    env = {"VENUE_RESEARCH_ENABLED":"true", "VENUE_RESEARCH_MODEL_PROVIDER":"vercel_gateway",
           "VENUE_RESEARCH_MODEL":"anthropic/claude-haiku-5.5", "VERCEL_OIDC_TOKEN":"fake-oidc",
           "TAVILY_API_KEY":"fake-existing-search"}
    assert configured(env) is None
    env["VENUE_RESEARCH_USE_EXISTING_TAVILY_KEY"] = "true"
    assert configured(env) == {"model":"anthropic/claude-haiku-5.5", "provider":"vercel_gateway",
                               "model_key":"fake-oidc", "search_key":"fake-existing-search"}
    assert configured({**env, "VERCEL_OIDC_TOKEN":""}) is None
    assert configured({**env, "VENUE_RESEARCH_MODEL":"claude-haiku-5-5"}) is None
    from roomquest.venue_research import anthropic_extract
    call = Mock(return_value={"stop_reason":"end_turn", "content":[{"type":"text","text":"{}"}]})
    monkeypatch.setattr("roomquest.venue_research.bounded_json", call)
    assert anthropic_extract({"identity":"fixture"}, api_key="fake-oidc", model=env["VENUE_RESEARCH_MODEL"],
                             provider="vercel_gateway", deadline_at=30, clock=lambda:0) == "{}"
    args = call.call_args.args
    assert args[0] == "https://ai-gateway.vercel.sh/v1/messages"
    assert args[1]["Authorization"] == "Bearer fake-oidc" and "x-api-key" not in args[1]
    assert args[2]["max_tokens"] == 512 and args[2]["thinking"] == {"type":"disabled"}
    with pytest.raises(ValueError, match="model_provider_mismatch"):
        anthropic_extract({}, api_key="fake-oidc", model="wrong", provider="vercel_gateway", deadline_at=30, clock=lambda:0)
    assert call.call_count == 1


@pytest.mark.parametrize("adapter", ["ical", "wordpress", "html", "jsonld", "spektrix", "localist", "squarespace", "growthzone", "future_adapter"])
def test_server_permit_not_adapter_controls_research(monkeypatch, adapter):
    lookup = Mock(return_value=PROPOSAL)
    monkeypatch.setattr("roomquest.venue_research.research", lookup)
    claim = {**WORKER_CLAIM, "provider": adapter, "research_eligible": True}
    db = Mock(return_value={"recorded": True, "deferred": True})
    assert defer_miss(db, claim, IDENTITY, CONFIG)
    assert handle_claim(db, claim, IDENTITY, CONFIG, fetch=Mock(), deadline=30, clock=lambda: 0) == "resolved"
    lookup.assert_called_once()


def test_shared_gb_extraction_and_postcode():
    scope = {"permit_id": "permit", "venue": "Nottingham Playhouse",
             "locality": "Nottingham", "region": "GB", "country": "GB",
             "hosts": ["theatre.example"], "scope_version": "registered_venue_v1"}
    html = "<main><h1>Nottingham Playhouse</h1><address>Wellington Circus, Nottingham, NG1 5AL</address></main>"
    claim = {**CLAIM, "venue_name": "Nottingham Playhouse", "provider": "wordpress"}
    def complete(payload):
        p = payload["passages"][0]
        return json.dumps({"passage_id": p["id"], "street": "Wellington Circus",
            "locality": "Nottingham", "postal_code": "NG1 5AL", "quote": p["text"]})
    ans = research(claim, admit=lambda _: scope, search=lambda *a, **k: ["https://theatre.example/visit"],
                   fetch=lambda *a, **k: html, complete=complete, model="test", deadline=30, clock=lambda: 0)
    assert ans["status"] == "proposed"
    assert ans["candidate"]["address"] == "Wellington Circus, Nottingham, NG1 5AL"
    assert ans["candidate"]["country_code"] == "GB"


def test_registered_us_requires_region_proof():
    scope = {**SCOPE, "scope_version": "registered_venue_v1"}
    ans, _ = fixture(admit=Mock(return_value=scope))
    assert ans["status"] == "held"
