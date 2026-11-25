"""Publisher permission rules must block requests before registration or staging.

The Squarespace fixture was read from /robots.txt on 2026-11-21. All seven
publishers below advertised the same wildcard group and export restrictions.
No calendar/export requests are made by these tests.
"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

import pytest

from roomquest import feed_registration, preview_worker as worker
from roomquest.registration_formats import source_key


AGENT = "RoomQuestCommunityCalendar"
SQUARESPACE = (Path(__file__).parent / "fixtures/robots/squarespace.txt").read_bytes()
EXPORTS = [
    "https://www.amazementsquare.org/calendar?format=json",
    "https://palmerahouse.com/events?format=json",
    "https://www.hazy-mountain.com/calendar?format=json",
    "https://www.scrappyelephant.com/lyh-classes-2026?format=json",
    "https://www.riverviews.org/calendar?format=json",
    "https://www.pranayogaandfitness.com/events?format=json",
    "https://thevirginianhotel.com/events?format=json",
]


def policy(rules):
    return worker._parse_robots_policy("publisher.example", rules.encode())[0]


@pytest.mark.parametrize("path,allowed", [
    ("/events", True),
    ("/events?offset=1", True),
    ("/events?format=json", False),
    ("/events?offset=1&format=json", False),
    ("/events?format=json-pretty", False),
    ("/events?format=ical", False),
    ("/events?offset=1&format=ical", False),
    ("/events?%66ormat=json", False),
    ("/events?format=%6ason", False),
    ("/events?FORMAT=json", True),
    ("/events%3Fformat=json", True),
])
def test_shared_wildcard_group_prohibits_exports_but_not_listing(path, allowed):
    parser, _ = worker._parse_robots_policy("publisher.example", SQUARESPACE)
    assert parser.can_fetch(AGENT, "https://publisher.example" + path) is allowed


@pytest.mark.parametrize("pattern,path,allowed", [
    ("/account$", "/account", False),
    ("/account$", "/account/settings", True),
    ("/account$", "/account?next=/", True),
    ("/account$", "/account#local-fragment", False),
    ("/events/*/tickets$", "/events//tickets", False),
    ("/events/*/tickets$", "/events/a/b/tickets", False),
    ("/events/*/tickets$", "/events/a/tickets?day=1", True),
    ("/a*b*c$", "/a-one-b-two-b-three-c", False),
    ("/a*b*c$", "/a-b-c-trailing", True),
    ("/a*b$", "/abxb", False),
    ("/events*", "/events", False),
    ("/events*", "/events/next", False),
    ("/events", "/Events", True),
    ("/events", "/other/events", True),
    ("/event[1].html", "/event1Xhtml", True),
    ("/event[1].html", "/event[1].html", False),
    ("/event%5B1%5D", "/event[1]", False),
    ("/event[1]", "/event%5B1%5D", False),
    ("*.gif$", "/folder/image.gif", False),
    ("*.gif$", "/folder/image.gif?download=1", True),
    ("*", "/events", False),
    ("/~team", "/%7Eteam", False),
    ("/%65vents", "/events", False),
    ("/a%2Fb", "/a%2fb", False),
    ("/a%2Fb", "/a/b", True),
    ("/a/b", "/a%2Fb", True),
    ("/café", "/caf%C3%A9", False),
    ("/caf%c3%a9", "/café", False),
    ("/file-%2A.html", "/file-*.html", False),
    ("/file-%2A.html", "/file-other.html", True),
    ("/price-%24", "/price-$", False),
    ("/literal%23hash", "/literal%23hash", False),
])
def test_anchored_wildcards_and_uri_octets(pattern, path, allowed):
    parser = policy("User-agent: *\nDisallow: " + pattern + "\n")
    assert parser.can_fetch(AGENT, "https://publisher.example" + path) is allowed


@pytest.mark.parametrize("rules,path,allowed", [
    (["Allow: /", "Disallow: /private"], "/private/event", False),
    (["Disallow: /", "Allow: /public"], "/public/event", True),
    (["Disallow: /same", "Allow: /same"], "/same/event", True),
    (["Allow: /page", "Disallow: /*.htm"], "/page.htm", False),
    (["Allow: /page", "Disallow: /*.ph"], "/page.php5", True),
    (["Allow: /$", "Disallow: /"], "/", True),
    (["Allow: /$", "Disallow: /"], "/page.htm", False),
    (["Disallow: /api/", "Allow: /api/ui-extensions/"], "/api/ui-extensions/item", True),
    (["Disallow: /", "Allow: /p/*"], "/p/item", True),
    (["Disallow: /", "Allow: /p/*"], "/other", False),
])
def test_most_specific_rule_and_allow_ties_are_order_independent(rules, path, allowed):
    for ordered in (rules, list(reversed(rules))):
        parser = policy("User-agent: *\n" + "\n".join(ordered))
        assert parser.can_fetch(AGENT, "https://publisher.example" + path) is allowed


def test_same_specific_agent_groups_merge_without_global_or_other_bot_rules():
    parser = policy("""User-agent: *
Disallow: /
User-agent: OtherBot
Disallow: /
User-agent: RoomQuestCommunityCalendar
Disallow: /one
User-agent: roomquestcommunitycalendar
Disallow: /two
Allow: /one/public
""")
    assert not parser.can_fetch(AGENT, "https://publisher.example/one/private")
    assert not parser.can_fetch(AGENT, "https://publisher.example/two")
    assert parser.can_fetch(AGENT, "https://publisher.example/one/public")
    assert parser.can_fetch(AGENT, "https://publisher.example/events")


def test_most_specific_named_agent_wins_independently_of_group_order():
    groups = ["User-agent: RoomQuest\nDisallow: /",
              "User-agent: RoomQuestCommunityCalendar\nAllow: /public\nDisallow: /private"]
    for ordered in (groups, list(reversed(groups))):
        parser = policy("\n\n".join(ordered))
        assert parser.can_fetch(AGENT, "https://publisher.example/public")
        assert not parser.can_fetch(AGENT, "https://publisher.example/private")


def test_repeated_global_groups_merge_and_empty_rules_do_not_allow_other_denials():
    parser = policy("""Disallow: /orphan
User-agent: *
Disallow: /one
Allow:
User-agent: *
Disallow: /two
Disallow:
""")
    assert not parser.can_fetch(AGENT, "https://publisher.example/one")
    assert not parser.can_fetch(AGENT, "https://publisher.example/two")
    assert parser.can_fetch(AGENT, "https://publisher.example/orphan")


def test_comments_blank_lines_and_other_records_do_not_break_a_shared_group():
    parser = policy("""User-agent: OtherBot
Sitemap: https://publisher.example/sitemap.xml

# This agent shares the following rules with OtherBot.
USER-AGENT: RoomQuestCommunityCalendar
Disallow: /private # comment
Allow: /private/public
""")
    assert not parser.can_fetch(AGENT, "https://publisher.example/private")
    assert parser.can_fetch(AGENT, "https://publisher.example/private/public")
    assert not parser.can_fetch("OtherBot", "https://publisher.example/private")


def test_no_matching_group_and_empty_final_group_allow_and_robots_is_implicit():
    assert policy("User-agent: OtherBot\nDisallow: /").can_fetch(AGENT, "https://publisher.example/")
    parser = policy("User-agent: *\nDisallow: /\nUser-agent: RoomQuestCommunityCalendar\n")
    assert parser.can_fetch(AGENT, "https://publisher.example/events")
    assert policy("User-agent: *\nDisallow: /").can_fetch(AGENT, "https://publisher.example/robots.txt")
    assert policy("User-agent: *\nDisallow: /").can_fetch(AGENT, "https://publisher.example/%72obots.txt")


def test_many_wildcards_do_not_require_regex_backtracking():
    parser = policy("User-agent: *\nDisallow: /" + "*a" * 1000 + "*b$")
    assert parser.can_fetch(AGENT, "https://publisher.example/" + "a" * 1500 + "c")


@pytest.fixture
def guarded_origin(monkeypatch):
    fields = ("_robots_cache", "_robots_delays", "_publisher_next", "_publisher_retry_after")
    previous = {field: getattr(worker, field).copy() for field in fields}
    for field in fields:
        getattr(worker, field).clear()
    calls = []

    def open_request(request, timeout):
        assert request.full_url.endswith("/robots.txt")
        calls.append(request.full_url)
        response = MagicMock(status=200, headers={})
        response.__enter__.return_value = response
        response.read.side_effect = lambda limit: SQUARESPACE[:limit]
        return response

    session = MagicMock()
    session.__enter__.return_value = session
    session.get.side_effect = AssertionError("A robots-disallowed export must never be requested")
    session.post.side_effect = AssertionError("No publisher POST is permitted")
    monkeypatch.setattr(worker, "build_opener", lambda *_: SimpleNamespace(open=open_request))
    monkeypatch.setattr(worker.requests, "Session", lambda: session)
    monkeypatch.setattr(worker, "validate_public_dns", Mock())
    monkeypatch.setattr(worker, "sleep", Mock())
    monkeypatch.setattr(worker, "monotonic", lambda: 100.0)
    yield calls, session
    for field in fields:
        getattr(worker, field).clear()
        getattr(worker, field).update(previous[field])


def _clear_robots_state():
    fields = ("_robots_cache", "_robots_delays", "_publisher_next", "_publisher_retry_after")
    previous = {field: getattr(worker, field).copy() for field in fields}
    for field in fields:
        getattr(worker, field).clear()
    return previous


def _restore_robots_state(previous):
    for field, value in previous.items():
        getattr(worker, field).clear()
        getattr(worker, field).update(value)


def test_transient_robots_network_failure_temporarily_allows_collection(monkeypatch):
    previous = _clear_robots_state()
    opened = Mock(side_effect=URLError("temporary robots timeout"))
    monkeypatch.setattr(worker, "build_opener", lambda *_: SimpleNamespace(open=opened))
    monkeypatch.setattr(worker, "validate_public_dns", Mock())
    monkeypatch.setattr(worker, "activity_before_request", Mock())
    try:
        assert worker.robots_allowed("publisher.example", "/events")
        assert worker.robots_allowed("publisher.example", "/events?page=2")
        assert opened.call_count == 1
        assert worker._checkpoint_robots_snapshot({"feed_url": "https://publisher.example/events"}) is None
    finally:
        _restore_robots_state(previous)


def test_soft_robots_response_temporarily_allows_collection(monkeypatch):
    previous = _clear_robots_state()
    response = MagicMock(status=200, headers={})
    response.__enter__.return_value = response
    response.read.return_value = b"<html><body>temporary application response</body></html>"
    monkeypatch.setattr(worker, "build_opener", lambda *_: SimpleNamespace(open=Mock(return_value=response)))
    monkeypatch.setattr(worker, "validate_public_dns", Mock())
    monkeypatch.setattr(worker, "activity_before_request", Mock())
    try:
        assert worker.robots_allowed("publisher.example", "/events")
        assert worker._checkpoint_robots_snapshot({"feed_url": "https://publisher.example/events"}) is None
    finally:
        _restore_robots_state(previous)


def test_robots_http_access_denial_still_blocks_collection(monkeypatch):
    previous = _clear_robots_state()
    url = "https://publisher.example/robots.txt"
    denied = HTTPError(url, 403, "Forbidden", {}, None)
    monkeypatch.setattr(worker, "build_opener", lambda *_: SimpleNamespace(open=Mock(side_effect=denied)))
    monkeypatch.setattr(worker, "validate_public_dns", Mock())
    monkeypatch.setattr(worker, "activity_before_request", Mock())
    try:
        with pytest.raises(worker.PreviewError, match="^robots_denied$"):
            worker.robots_allowed("publisher.example", "/events")
    finally:
        _restore_robots_state(previous)


@pytest.mark.parametrize("url", EXPORTS)
def test_cached_listing_permission_never_authorizes_export_get(guarded_origin, url):
    calls, session = guarded_origin
    parsed = urlsplit(url)
    assert worker.robots_allowed(parsed.netloc, parsed.path)
    with pytest.raises(worker.PreviewError, match="^robots_denied$"):
        worker.fetch_publisher(url, "application/json", respect_robots=True)
    assert calls == ["https://" + parsed.netloc + "/robots.txt"]
    session.get.assert_not_called()
    session.post.assert_not_called()


def test_registration_records_disabled_without_fetching_export(guarded_origin, monkeypatch):
    calls, session = guarded_origin
    rpc = Mock(side_effect=[{"url": EXPORTS[0]}, True])
    monkeypatch.setattr(feed_registration, "supabase_rpc", rpc)
    assert feed_registration.register("fixture-ticket") == {"outcome": "disabled"}
    assert rpc.call_args.args == ("community_collector_finish_registration", {
        "p_ticket": "fixture-ticket", "p_outcome": "disabled", "p_reason": "robots_denied"})
    assert calls == ["https://www.amazementsquare.org/robots.txt"]
    session.get.assert_not_called()


def test_preview_records_denial_without_staging_events(guarded_origin, monkeypatch):
    _, session = guarded_origin
    rpc = Mock()
    monkeypatch.setattr(worker, "supabase_rpc", rpc)
    source = {"source_key": source_key(EXPORTS[0]), "kind": "json",
              "platform_adapter": "squarespace", "feed_url": EXPORTS[0]}
    result = worker._process_claimed_source(source)
    assert result["complete"] == result["staged"] == 0
    assert result["error_code"] == "robots_denied"
    rpc.assert_called_once()
    assert rpc.call_args.args[0] == "community_collector_record_preview"
    assert rpc.call_args.args[1]["p_error"] == "robots_denied"
    session.get.assert_not_called()
