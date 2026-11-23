"""Small, approved-source HTTP 304 cache for complete iCalendar feeds.

The publisher request is still admitted by the existing robots/pacing/SSRF
transport. A 304 replays the exact prior HTTP body through the *current*
recurrence/parser pipeline: a moving 60-day window is never inferred from an
old occurrence manifest. Cache writes occur only after a successful lease-
fenced, complete incremental publication receipt. Optional cache failures
fall back to the ordinary full GET and cannot certify an empty feed.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
import logging

from roomquest.incremental_snapshot import _cacheable, _validator, request_hash

_LOG = logging.getLogger(__name__)
_current = ContextVar("eq_ical_conditional_cache", default=None)
_MAX_BYTES = 131072
# Mirror the five exact database pilot source keys to avoid adding a read RPC
# to every iCalendar worker. The database still validates source ID, lease,
# approval, rights and exact source_key before returning cached bytes.
_PILOT_SOURCE_KEYS = frozenset({
    "municipal_mapsee_48489e8f5c906f7610d30197",
    "municipal_df6fb09e5e9df3f197946372",
    "municipal_mapsee_c3384b4db5c0226f2d7dc0bb",
    "municipal_mapsee_a4d675992e7b41375e3f0672",
    "municipal_mapsee_ed3b97dd2d6526767fe2da5f",
})


def _valid_ical(text):
    return (isinstance(text, str)
            and 20 <= len(text.encode("utf-8")) <= _MAX_BYTES
            and text.lstrip(" \r\n\t").startswith("BEGIN:VCALENDAR")
            and "END:VCALENDAR" in text)


class ConditionalCache:
    def __init__(self, source, snapshot, collection_context, rpc):
        self.source = source
        self.snapshot = snapshot
        self.context = collection_context
        self.rpc = rpc
        self.url = source["feed_url"]
        self.request_hash = request_hash(self.url, "text/calendar")
        self.enabled = False
        self.cached = None
        self.candidate = None
        self._conditional_sent = False
        self._saw_200 = False
        self._invalid_304 = False
        self._reused_304 = False

    def initialize(self):
        try:
            result = self.rpc("community_collector_read_ical_cache", {
                **self.context,
                "p_source_key": self.source["source_key"],
                "p_policy_context": self.snapshot.policy_context,
                "p_context_hash": self.snapshot.context_hash,
                "p_request_hash": self.request_hash,
            }, timeout=4)
        except Exception:
            _LOG.warning("Optional iCalendar conditional cache read failed")
            return
        if not isinstance(result, dict) or result.get("enabled") is not True:
            return
        self.enabled = True
        body = result.get("body")
        if not _valid_ical(body):
            return
        body_hash = sha256(body.encode("utf-8")).hexdigest()
        if result.get("body_hash") != body_hash:
            return
        etag = _validator(result.get("etag"), etag=True)
        modified = _validator(result.get("last_modified"))
        content_type = result.get("content_type")
        if ((etag is None and modified is None)
                or not isinstance(content_type, str) or not (1 <= len(content_type) <= 180)):
            return
        self.cached = {
            "body": body, "body_hash": body_hash, "etag": etag,
            "last_modified": modified, "content_type": content_type,
        }

    def headers(self, url, accept):
        if not self.enabled or self.cached is None or (url, accept) != (self.url, "text/calendar"):
            return {}
        self._conditional_sent = True
        if self.cached["etag"] is not None:
            return {"If-None-Match": self.cached["etag"]}
        return {"If-Modified-Since": self.cached["last_modified"]}

    def not_modified(self, url, accept, headers):
        if not self.headers(url, accept):
            return None
        # The existing transport retries a full GET if this 304 cannot be
        # trusted. Record that fallback only if the resulting fetch succeeds.
        self._invalid_304 = True
        if not _cacheable(headers):
            return None
        prior = self.cached
        # If the server supplies a contradictory representation/validator,
        # never use a cache. The existing transport retries one full GET.
        content_type = headers.get("Content-Type")
        if content_type is not None and content_type.strip().lower() != prior["content_type"].strip().lower():
            return None
        for key, prior_name, validator in (
                ("ETag", "etag", True), ("Last-Modified", "last_modified", False)):
            observed = headers.get(key)
            if observed is not None and _validator(observed, etag=validator) != prior[prior_name]:
                return None
        body = prior["body"]
        receipt_headers = {"Content-Type": prior["content_type"]}
        if prior["etag"] is not None:
            receipt_headers["ETag"] = prior["etag"]
        if prior["last_modified"] is not None:
            receipt_headers["Last-Modified"] = prior["last_modified"]
        self.snapshot.record_body(url, accept, body.encode("utf-8"), receipt_headers,
                                  encoding="utf-8", errors="strict")
        self.candidate = dict(prior)
        self._invalid_304 = False
        self._reused_304 = True
        return body

    def record_body(self, url, accept, payload, headers, *, encoding):
        if not self.enabled or (url, accept) != (self.url, "text/calendar"):
            return
        # Only this exact pilot feed's successfully decoded HTTP 200 body
        # counts. A non-cacheable 200 is still a full download.
        self._saw_200 = True
        if not isinstance(payload, bytes) or len(payload) > _MAX_BYTES or not _cacheable(headers):
            return
        try:
            body = payload.decode("utf-8", errors="strict")
            # Only cache identical decoded bytes. Other encodings or BOM
            # normalization must use the ordinary body/fetch path.
            if body != payload.decode(encoding, errors="strict") or not _valid_ical(body):
                return
        except (UnicodeError, LookupError):
            return
        etag = _validator(headers.get("ETag"), etag=True)
        modified = _validator(headers.get("Last-Modified"))
        content_type = headers.get("Content-Type", "")
        if (etag is None and modified is None) or not (1 <= len(content_type) <= 180):
            return
        self.candidate = {
            "body": body, "body_hash": sha256(payload).hexdigest(),
            "etag": etag, "last_modified": modified,
            "content_type": content_type,
        }

    def _completed_outcome(self):
        # At most one source-scope observation per *successful* collection.
        # Do not call this from failed transport/parse/partial publication.
        if self._reused_304:
            return "reused_304"
        if not self._saw_200:
            return None
        if self._invalid_304:
            return "fallback_200"
        return "conditional_200" if self._conditional_sent else "full_200"

    def save_after_success(self, deadline_at=None):
        if not self.enabled:
            return
        # Optional telemetry must not delay completion or affect an accepted
        # source snapshot. Only pilot sources reach this method.
        if deadline_at is not None:
            from time import monotonic
            if monotonic() > deadline_at - 2:
                return
        if self.candidate is not None:
            try:
                self.rpc("community_collector_save_ical_cache", {
                    **self.context, "p_source_key": self.source["source_key"],
                    "p_policy_context": self.snapshot.policy_context,
                    "p_context_hash": self.snapshot.context_hash,
                    "p_request_hash": self.request_hash,
                    "p_body": self.candidate["body"],
                    "p_body_hash": self.candidate["body_hash"],
                    "p_content_type": self.candidate["content_type"],
                    "p_etag": self.candidate["etag"],
                    "p_last_modified": self.candidate["last_modified"],
                }, timeout=4)
            except Exception:
                _LOG.warning("Optional iCalendar conditional cache save failed")
        outcome = self._completed_outcome()
        if outcome is None:
            return
        if deadline_at is not None:
            from time import monotonic
            if monotonic() > deadline_at - 1:
                return
        try:
            self.rpc("community_collector_record_ical_http_metric", {
                **self.context, "p_source_key": self.source["source_key"],
                "p_outcome": outcome,
            }, timeout=3)
        except Exception:
            _LOG.warning("Optional iCalendar conditional outcome metric failed")


@contextmanager
def capture(source, snapshot, collection_context, rpc):
    cache = None
    if (snapshot is not None and isinstance(collection_context, dict)
            and collection_context.get("p_category") == "ical"
            and source.get("kind") == "ical" and source.get("platform_adapter") == "ical"
            and source.get("source_key") in _PILOT_SOURCE_KEYS
            and isinstance(source.get("feed_url"), str)):
        cache = ConditionalCache(source, snapshot, collection_context, rpc)
        cache.initialize()
    token = _current.set(cache)
    try:
        yield cache
    finally:
        _current.reset(token)


def conditional_headers(url, accept):
    cache = _current.get()
    return cache.headers(url, accept) if cache is not None else {}


def not_modified(url, accept, headers):
    cache = _current.get()
    return cache.not_modified(url, accept, headers) if cache is not None else None


def record_body(url, accept, payload, headers, *, encoding):
    cache = _current.get()
    if cache is not None:
        cache.record_body(url, accept, payload, headers, encoding=encoding)


def save_after_success(deadline_at=None):
    cache = _current.get()
    if cache is not None:
        cache.save_after_success(deadline_at=deadline_at)
