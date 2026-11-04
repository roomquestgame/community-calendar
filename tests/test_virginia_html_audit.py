"""The optional live diagnostic has fixed scope and preserves publisher guards."""
from scripts import capture_virginia_event_html as audit
from roomquest.preview_worker import PreviewError


def test_audit_captures_only_reviewed_pages_with_existing_guards(tmp_path, monkeypatch):
    calls = []
    def fetch(url, accept, **kwargs):
        calls.append((url, accept, kwargs))
        return '<html><body><main><h1>Example</h1><h2>When</h2><p>Details</p></main></body></html>'
    monkeypatch.setattr(audit, "fetch_publisher", fetch)
    report = audit.capture(tmp_path)
    assert [call[0] for call in calls] == [url for _, url in audit.PAGES]
    assert all(call[1] == "text/html" and call[2]["respect_robots"] is True
               and call[2]["allowed_hosts"] == ("www.dcr.virginia.gov",)
               and call[2]["deadline_at"] > 0 for call in calls)
    assert all(page["status"] == "complete" and page["sha256"] for page in report["pages"])
    assert len(list(tmp_path.glob("*.html"))) == 2
    assert (tmp_path / "audit.json").exists()


def test_audit_stops_on_publisher_denial_without_fallback(tmp_path, monkeypatch):
    calls = []
    def deny(url, *_args, **_kwargs):
        calls.append(url)
        raise PreviewError("publisher_http_403")
    monkeypatch.setattr(audit, "fetch_publisher", deny)
    report = audit.capture(tmp_path)
    assert len(calls) == 1
    assert [page["status"] for page in report["pages"]] == ["failed", "not_attempted"]
    assert report["pages"][0]["error"] == "publisher_http_403"
    assert not list(tmp_path.glob("*.html"))
