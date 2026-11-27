"""Evidence-bound calendar research primitives; no network, model or DB calls.

This module is intentionally not wired to production. Its caller must hold an
appropriate research lease and budget and must independently probe any result
through the normal robots-aware registration pipeline.
"""
import hashlib
import json
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlsplit

from roomquest.preview_worker import public_source_url
from roomquest.preview_worker import PreviewError
from roomquest.feed_registration import classify
from roomquest.venue_calendar_locator import find_calendar

MAX_HTML = 750_000
MAX_LINKS = 80
MAX_LABEL = 160
MAX_RESPONSE = 4096


class _Links(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.links = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag != "a" or len(self.links) >= MAX_LINKS:
            return
        href = dict(attrs).get("href")
        if not href or len(href) > 1500:
            return
        try:
            url = urldefrag(urljoin(self.base, href)).url
            parts = urlsplit(url)
            if (not public_source_url(url) or parts.username or parts.password
                    or parts.hostname != urlsplit(self.base).hostname):
                return
        except (TypeError, ValueError):
            return
        self.current = [url, ""]

    def handle_data(self, text):
        if self.current is not None:
            self.current[1] = (self.current[1] + " " + text)[:MAX_LABEL]

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            url, label = self.current
            self.current = None
            label = " ".join(label.split())
            if not label or any(x["url"] == url for x in self.links):
                return
            identity = hashlib.sha256(url.encode()).hexdigest()[:24]
            self.links.append({"id": identity, "url": url, "label": label})


def candidates(html, website_url):
    """List publisher-linked same-host candidates; page must already be verified."""
    if (not isinstance(html, str) or len(html.encode("utf-8")) > MAX_HTML
            or not public_source_url(website_url)):
        return []
    parser = _Links(website_url)
    parser.feed(html)
    return parser.links


def select_candidate(links, model_response):
    """Accept only a returned candidate ID; output remains unverified evidence."""
    if (not isinstance(model_response, str)
            or len(model_response.encode("utf-8")) > MAX_RESPONSE):
        return None
    try:
        obj = json.loads(model_response)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict) or set(obj) != {"candidate_id"}:
        return None
    if not isinstance(obj["candidate_id"], str):
        return None
    matches = [entry for entry in links if entry.get("id") == obj["candidate_id"]]
    if len(matches) != 1:
        return None
    return {"url": matches[0]["url"], "status": "needs_independent_validation"}


def inspect_selection(website_url, event_url, selected, *, fetch, deadline):
    """Probe a chosen publisher link through existing collector checks.

    The caller must verify venue identity, hold an active research lease, and
    establish that ``selected`` came from candidates on that venue's page.
    This function never registers a URL or treats model selection as proof.
    """
    if not isinstance(selected, dict) or selected.get("status") != "needs_independent_validation":
        return {"status": "review", "reason": "invalid_selection"}
    url = selected.get("url")
    try:
        if (not isinstance(url, str) or not public_source_url(url)
                or urlsplit(url).hostname != urlsplit(website_url).hostname):
            return {"status": "review", "reason": "invalid_selection"}
        content = fetch(url, "text/calendar,application/json,text/html",
                        respect_robots=True, allowed_hosts=(urlsplit(website_url).hostname,),
                        deadline_at=deadline)
        result = classify(url, content, endpoint_only=True)
        if result.get("p_outcome") == "verified" and result.get("p_type") in ("ical", "wordpress"):
            return {"status": "candidate", "url": url, "kind": result["p_type"]}
        if not isinstance(content, str) or not content.lstrip().startswith("<"):
            return {"status": "review", "reason": "not_calendar"}
        feed, kind = find_calendar(content, url, event_url, fetch, deadline,
                                   require_unique_calendar_page=True)
        if (feed and kind in ("ical", "wordpress", "squarespace", "html_listing")
                and urlsplit(feed).hostname == urlsplit(website_url).hostname):
            return {"status": "candidate", "url": feed, "kind": kind}
        return {"status": "review", "reason": "calendar_not_verified"}
    except PreviewError as exc:
        reason = str(exc)
        if reason in ("robots_denied", "publisher_http_401", "publisher_http_403"):
            return {"status": "denied", "reason": reason}
        return {"status": "retry", "reason": "publisher_unavailable"}
    except (TypeError, ValueError):
        return {"status": "review", "reason": "invalid_selection"}
