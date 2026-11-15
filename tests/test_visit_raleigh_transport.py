"""Raleigh's longer public query stays inside the ordinary transport guards."""
from datetime import date
from unittest.mock import MagicMock, Mock
from urllib.parse import urlencode, urlsplit

import pytest

from roomquest import preview_worker as worker, visit_raleigh as r

URL = r.api_url("public-fixture-token", [str(n) for n in range(1, 38)],
                date(2026, 11, 15), date(2027, 1, 13), 0)


def transport(monkeypatch, *, status=200, extra=None, body=b'{"docs":[],"total":0}'):
    response = MagicMock(status_code=status, encoding="utf-8",
                         headers={"Content-Type": "application/json", **(extra or {})})
    response.iter_content.return_value = [body]
    session = MagicMock()
    session.__enter__.return_value = session
    session.get.return_value = response
    monkeypatch.setattr(worker.requests, "Session", lambda: session)
    dns, robots, pacing = Mock(), Mock(return_value=True), Mock()
    monkeypatch.setattr(worker, "validate_public_dns", dns)
    monkeypatch.setattr(worker, "robots_allowed", robots)
    monkeypatch.setattr(worker, "pace_publisher", pacing)
    monkeypatch.setattr(worker, "_observe_retry_after", Mock())
    return session, response, dns, robots, pacing


def test_exact_long_query_keeps_full_robots_path_and_unchanged_transport(monkeypatch):
    assert 1000 < len(URL) < r.MAX_API_URL_LENGTH
    assert not worker.public_source_url(URL)
    assert r.valid_api_url(URL)
    session, response, dns, robots, pacing = transport(monkeypatch)
    assert worker.fetch_visit_raleigh_page(URL) == '{"docs":[],"total":0}'
    session.post.assert_not_called()
    args, kwargs = session.get.call_args
    assert args == (URL,)
    assert kwargs["allow_redirects"] is False and kwargs["stream"] is True
    assert kwargs["headers"] == {
        "User-Agent": worker.robots_checkpoint.PUBLISHER_USER_AGENT,
        "Accept": "application/json",
    }
    dns.assert_called_once_with(r.HOST)
    parsed = urlsplit(URL)
    assert robots.call_args.args == (r.HOST, parsed.path + "?" + parsed.query)
    pacing.assert_called_once()
    response.close.assert_called_once()


@pytest.mark.parametrize("change", [
    {"url": URL.replace(r.HOST, "other.example")},
    {"url": URL.replace("events_by_date", "events")},
    {"url": URL.replace("https://", "http://")},
    {"url": URL + "#fragment"},
    {"url": URL + "&extra=1"},
    {"url": URL + "&token=duplicate"},
    {"url": URL + "&" + urlencode({"options[limit]": 100})},
    {"url": URL.replace("options%5Blimit%5D=100", "options%5Blimit%5D=200")},
    {"url": URL.replace("options%5Bskip%5D=0", "options%5Bskip%5D=1")},
    {"url": URL.replace("options%5Bskip%5D=0", "options%5Bskip%5D=10000")},
    {"url": URL.replace("2027-01-14", "2027-01-15")},
    {"url": URL.replace("filter%5Bsites%5D=primary", "filter%5Bsites%5D=other")},
    {"url": URL.replace("public-fixture-token", "a" * r.MAX_API_URL_LENGTH)},
    {"accept": "text/html"}, {"respect_robots": False},
    {"allowed_hosts": (r.HOST, "other.example")},
    {"calendar_form": {}}, {"calendar_json": {}},
    {"localhop_app_id": "a" * 30}, {"cardboard_arena_calendar": True},
    {"visit_raleigh_api": 1},
])
def test_exact_api_scope_rejects_changes_before_network(monkeypatch, change):
    session, _, dns, *_ = transport(monkeypatch)
    request = dict(url=URL, accept="application/json", respect_robots=True,
                   allowed_hosts=(r.HOST,), visit_raleigh_api=True)
    request.update(change)
    with pytest.raises(worker.PreviewError, match="^invalid_visit_raleigh_request$"):
        worker._fetch_publisher_request(**request)
    session.get.assert_not_called()
    dns.assert_not_called()


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_scoped_api_query_is_not_replayed_on_redirect(monkeypatch, status):
    session, response, *_ = transport(monkeypatch, status=status, extra={"Location": r.CALENDAR})
    with pytest.raises(worker.PreviewError, match="^calendar_render_redirect_blocked$"):
        worker.fetch_visit_raleigh_page(URL)
    session.get.assert_called_once()
    response.close.assert_called_once()


@pytest.mark.parametrize("gate,code", [
    ("dns", "non_public_dns"), ("robots", "robots_denied"),
    ("pacing", "publisher_pacing_deferred"),
])
def test_existing_access_guards_still_precede_the_api_get(monkeypatch, gate, code):
    session, _, dns, robots, pacing = transport(monkeypatch)
    if gate == "robots":
        robots.return_value = False
    else:
        (dns if gate == "dns" else pacing).side_effect = worker.PreviewError(code)
    with pytest.raises(worker.PreviewError, match="^" + code + "$"):
        worker.fetch_visit_raleigh_page(URL)
    session.get.assert_not_called()


def test_http_denial_and_body_limit_are_unchanged(monkeypatch):
    session, response, *_ = transport(monkeypatch, status=403)
    with pytest.raises(worker.PreviewError, match="^publisher_http_403$"):
        worker.fetch_visit_raleigh_page(URL)
    session.get.assert_called_once()
    response.close.assert_called_once()
    _, response, *_ = transport(monkeypatch, extra={"Content-Length": str(worker.MAX_BODY + 1)})
    with pytest.raises(worker.PreviewError, match="^source_unavailable_or_oversized$"):
        worker.fetch_visit_raleigh_page(URL)
    response.close.assert_called_once()


def test_generic_url_limit_is_not_widened(monkeypatch):
    session, _, dns, *_ = transport(monkeypatch)
    with pytest.raises(worker.PreviewError, match="^invalid_source_url$"):
        worker.fetch_publisher(URL, "application/json", respect_robots=True, allowed_hosts=(r.HOST,))
    session.get.assert_not_called()
    dns.assert_not_called()
