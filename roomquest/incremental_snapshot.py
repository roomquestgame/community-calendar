"""Optional, lease-fenced reuse of complete normalized collector snapshots.

The database advertises this protocol in a category claim. No response bodies
or credentials are retained. Ordinary feeds still parse their moving window;
only a complete event manifest may suppress repeated staging. A ChamberMaster
detail has a narrower, independently revalidated identity and can reuse its
bounded normalized evidence after an exact-request 304 or identical body.
"""
from contextlib import contextmanager
import ast
from contextvars import ContextVar
import codecs
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import re
from threading import Lock
from uuid import UUID

VERSION = 1
MAX_EVENTS = 500
MAX_REQUESTS = 32
MAX_REQUEST_BYTES = 32_000
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_CATEGORIES = frozenset(("ical", "wordpress", "localist", "chambermate", "chambermaster"))
_capture = ContextVar("collector_incremental_snapshot", default=None)
_detail = ContextVar("collector_incremental_detail", default=None)


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def fingerprint(value):
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def utc_start(value):
    if not isinstance(value, str):
        raise ValueError("invalid_incremental_start")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("invalid_incremental_start")
    return parsed.astimezone(timezone.utc).isoformat()


def _identity(item):
    identity = item.get("id")
    if not isinstance(identity, str) or not identity.strip() or len(identity) > 180:
        raise ValueError("invalid_incremental_identity")
    return identity, utc_start(item.get("starts_at"))


@lru_cache(maxsize=1)
def _global_parser_context():
    """Invalidate normalized evidence when any deployed adapter/config changes.

    Reading the small source package once avoids an error-prone manually bumped
    parser version. Catalog inventories are not parser configuration. The source
    URL and all claim configuration are independently included below.
    """
    package = Path(__file__).resolve().parent
    root = package.parent
    paths = [p for p in package.rglob("*")
             if p.is_file() and p.suffix in (".py", ".json")
             and "catalogs" not in p.relative_to(package).parts]
    paths.extend(p for p in (root / "scripts/combine_ics.py",
                             root / "scrapers/growthzone.py",
                             root / "scrapers/lib/jsonld.py",
                             root / "scrapers/lib/base.py",
                             root / "scrapers/lib/utils.py",
                             root / "scrapers/lib/tribe_events.py",
                             root / "source_priority.json",
                             root / "requirements.txt") if p.is_file())
    digest = sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(root)).encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    for dependency in ("icalendar", "recurring-ical-events", "python-dateutil", "beautifulsoup4",
                       "feedparser", "lxml", "tzdata", "x-wr-timezone"):
        try:
            installed = version(dependency)
        except PackageNotFoundError:
            installed = "absent"
        digest.update((dependency + "=" + installed + "\0").encode("utf-8"))
    return digest.hexdigest()



# Exactly the same approved five-source pilot as the bounded HTTP cache.
# Leave non-pilot and source-specific parser routes on the existing broad
# fallback until their dependencies can be reviewed independently.
_SCOPED_ICAL_KEYS = frozenset({
    "municipal_mapsee_48489e8f5c906f7610d30197",
    "municipal_df6fb09e5e9df3f197946372",
    "municipal_mapsee_c3384b4db5c0226f2d7dc0bb",
    "municipal_mapsee_a4d675992e7b41375e3f0672",
    "municipal_mapsee_ed3b97dd2d6526767fe2da5f",
})

# The shared/normal iCalendar path invokes ics_adapter.parse, which in turn
# calls the preview normalizer, recurrence expander, address, event URL and
# description helpers. Hash whole relevant modules for conservative
# dependency coverage. The large multi-provider preview_worker is captured
# by the exact generic-ICS control-flow tail and its normalization functions.
_SCOPED_ICAL_FILES = (
    "roomquest/ics_adapter.py",
    "roomquest/event_description.py",
    "roomquest/reviewed_venue_addresses.py",
    "roomquest/communico_links.py",
    "roomquest/mapsee_adapter.py",
    "roomquest/odu_campusgroups.py",
    "roomquest/registered_native_content.py",
    "roomquest/incremental_snapshot.py",
    "scripts/combine_ics.py",
)
_SCOPED_ICAL_PREVIEW_FUNCTIONS = (
    "_future_datetime", "_location", "_preview", "public_source_url",
    "parse_ics_preview", "calendar_image", "event_image",
    "calendar_categories",
)
_SCOPED_ICAL_DEPENDENCIES = (
    "icalendar", "recurring-ical-events", "python-dateutil",
    "tzdata", "x-wr-timezone", "beautifulsoup4",
    "pytz", "timezonefinder", "timezonefinder-data",
)


def _scoped_ical_parser_digest(root):
    """Hash only the proven shared ICS processing route; fail closed to broad."""
    try:
        tree = ast.parse((root / "roomquest/preview_worker.py").read_text("utf-8"))
        functions = {node.name: node for node in tree.body
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        required = [functions[name] for name in _SCOPED_ICAL_PREVIEW_FUNCTIONS]
        source = functions["preview_source"]
        # Generic adapter dispatch sits at the very end of preview_source.
        # Missing/moved dispatch must invalidate rather than claim equivalence.
        tail_start = next(i for i, node in enumerate(source.body)
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "adapter"
                    for t in node.targets)
            and isinstance(node.value, ast.BoolOp)
            and "platform_adapter" in ast.dump(node.value))
        tail = source.body[tail_start:]
        if not any(isinstance(node, ast.Constant) and node.value == "ical"
                   for entry in tail for node in ast.walk(entry)):
            return None
        digest = sha256(b"eventquest-ical-parser-scope-v1\0")
        digest.update(b"LOOKAHEAD_DAYS=60\0MAX_PREVIEWS=10\0")
        for name, node in zip(_SCOPED_ICAL_PREVIEW_FUNCTIONS, required):
            digest.update(name.encode("utf-8") + b"\0")
            digest.update(ast.dump(node, include_attributes=False).encode("utf-8"))
            digest.update(b"\0")
        digest.update(b"preview_source.generic_ical_route\0")
        digest.update(ast.dump(ast.Module(body=tail, type_ignores=[]),
                               include_attributes=False).encode("utf-8"))
        for name in _SCOPED_ICAL_FILES:
            path = root / name
            digest.update(name.encode("utf-8") + b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        for name in _SCOPED_ICAL_DEPENDENCIES:
            try:
                installed = version(name)
            except PackageNotFoundError:
                installed = "absent"
            digest.update((name + "=" + installed + "\0").encode("utf-8"))
        return digest.hexdigest()
    except (OSError, ValueError, SyntaxError, KeyError, StopIteration, TypeError):
        return None


@lru_cache(maxsize=1)
def _scoped_ical_parser_context():
    return _scoped_ical_parser_digest(Path(__file__).resolve().parent.parent)


def parser_context(source=None):
    if (isinstance(source, dict)
            and source.get("source_key") in _SCOPED_ICAL_KEYS
            and source.get("kind") == "ical"
            and source.get("platform_adapter") == "ical"):
        scoped = _scoped_ical_parser_context()
        if scoped is not None:
            return scoped
    # The full prior fingerprint remains unchanged for every other source,
    # as well as when the scoped parser's imports/functions cannot be proven.
    return _global_parser_context()


def request_hash(url, accept):
    return fingerprint({"method": "GET", "url": url, "accept": accept})


def _validator(value, *, etag=False):
    if not isinstance(value, str) or not value or len(value) > 512:
        return None
    if any(ord(char) < 32 or ord(char) > 255 or ord(char) == 127 for char in value):
        return None
    if etag:
        return value if re.fullmatch(r'(?:W/)?"[\x21\x23-\x7e\x80-\xff]*"', value) else None
    try:
        return value if parsedate_to_datetime(value).tzinfo is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def _cacheable(headers):
    # No representation-dependent validator is reused for an unsupported Vary.
    vary = {value.strip().lower() for value in headers.get("Vary", "").split(",") if value.strip()}
    if vary - {"accept", "accept-encoding", "user-agent"}:
        return False
    if "no-store" in headers.get("Cache-Control", "").lower():
        return False
    return True


def _validators(headers):
    if not _cacheable(headers):
        return {}
    result = {}
    for source, dest, etag in (("ETag", "etag", True), ("Last-Modified", "last_modified", False)):
        value = _validator(headers.get(source), etag=etag)
        if value is not None:
            result[dest] = value
    return result


def representation_hash(headers, encoding, errors):
    return fingerprint({"content_type": headers.get("Content-Type", "").strip().lower(),
                        "encoding": codecs.lookup(encoding).name, "errors": errors})


def _valid_detail(detail):
    if not isinstance(detail, dict) or set(detail) != {
            "kind", "id", "starts_at", "status", "venue_address", "lat", "lng"}:
        return False
    if detail["kind"] != "chambermaster_ical_v1" or detail["status"] not in ("scheduled", "cancelled"):
        return False
    if not isinstance(detail["venue_address"], str) or len(detail["venue_address"]) > 400:
        return False
    try:
        _identity(detail)
        for name, bound in (("lat", 90), ("lng", 180)):
            value = detail[name]
            if value is not None and (type(value) not in (int, float) or not -bound <= value <= bound):
                return False
        return (detail["lat"] is None) == (detail["lng"] is None)
    except (ValueError, TypeError, OverflowError):
        return False


@dataclass(frozen=True)
class RevalidatedDetail:
    evidence: dict


class Snapshot:
    def __init__(self, source, collection_context, claim):
        self.source_key = source["source_key"]
        self.collection_context = dict(collection_context)
        self.policy_context = claim["policy_context"]
        self.context_hash = fingerprint({
            "version": VERSION, "parser": parser_context(source),
            "source": {key: value for key, value in source.items()
                       if key not in ("incremental_snapshot", "action")},
        })
        self.baseline_id = claim.get("baseline_id")
        if self.baseline_id is not None:
            try:
                UUID(self.baseline_id)
            except (ValueError, TypeError, AttributeError):
                self.baseline_id = None
        reusable = self.baseline_id is not None and claim.get("context_hash") == self.context_hash
        self._baseline = {}
        self._requests = {}
        self._observations = {}
        self._uncacheable = set()
        self._lock = Lock()
        if reusable:
            try:
                manifest = claim.get("events", [])
                if not isinstance(manifest, list) or len(manifest) > MAX_EVENTS:
                    raise ValueError
                for item in manifest:
                    identity = _identity(item)
                    if identity in self._baseline or not _HASH.fullmatch(item.get("hash", "")):
                        raise ValueError
                    self._baseline[identity] = item["hash"]
            except (ValueError, TypeError, AttributeError):
                self._baseline = {}
                reusable = False
        if reusable:
            requests = claim.get("requests", [])
            if isinstance(requests, list) and len(requests) <= MAX_REQUESTS:
                for item in requests:
                    if (isinstance(item, dict) and _HASH.fullmatch(item.get("request_hash", ""))
                            and _HASH.fullmatch(item.get("body_hash", ""))):
                        self._requests[item["request_hash"]] = item

    def plan(self, events, output):
        """Return complete membership plus changed bodies, or exact legacy mode."""
        if (not isinstance(events, list) or len(events) > MAX_EVENTS
                or output.get("p_error") is not None
                or type(output.get("p_future_count")) is not int
                or output["p_future_count"] != len(events)
                or type(output.get("p_venue_count")) is not int):
            return None
        manifest, changed, seen = [], [], set()
        try:
            if output["p_venue_count"] != sum(event.get("lat") is not None for event in events):
                return None
            for event in events:
                identity = _identity(event)
                if identity in seen:
                    return None
                seen.add(identity)
                hashed = fingerprint(event)
                manifest.append({"id": identity[0], "starts_at": identity[1], "hash": hashed})
                if self._baseline.get(identity) != hashed:
                    changed.append({"event": event, "hash": hashed})
        except (ValueError, TypeError, AttributeError, OverflowError):
            return None
        return {"events": sorted(manifest, key=lambda row: (row["id"], row["starts_at"])),
                "changed": changed}

    def receipt(self, plan):
        with self._lock:
            observations = [self._observations[key] for key in sorted(self._observations)]
        # Optional evidence can be dropped safely. It never proves complete event
        # membership, and raw feed 304 shortcuts are intentionally not enabled.
        # PostgreSQL's jsonb::text includes separator spaces. Budget that larger
        # representation, not compact canonical JSON, below its 32768-byte cap.
        encoded_size = len(json.dumps(observations, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        if len(observations) > MAX_REQUESTS or encoded_size > MAX_REQUEST_BYTES:
            observations = []
        return {
            "version": VERSION, "policy_context": self.policy_context,
            "baseline_id": self.baseline_id, "context_hash": self.context_hash,
            "request_context_hash": fingerprint({
                "context": self.context_hash, "requests": [r["request_hash"] for r in observations],
                "window_day": datetime.now(timezone.utc).date().isoformat(),
                "window_policy": "fully_parsed_moving_window_v1",
            }),
            "events": plan["events"], "requests": observations, "not_modified": False,
        }

    def detail_baseline(self, url, accept):
        context = _detail.get()
        key = request_hash(url, accept)
        prior = self._requests.get(key)
        if (context is None or context[0] != key or prior is None
                or prior.get("detail_context_hash") != context[1]
                or not isinstance(prior.get("representation_hash"), str)
                or not _HASH.fullmatch(prior["representation_hash"])
                or not _valid_detail(prior.get("detail"))):
            return None
        return prior

    def conditional_headers(self, url, accept):
        prior = self.detail_baseline(url, accept)
        if prior is None:
            return {}
        etag = _validator(prior.get("etag"), etag=True)
        modified = _validator(prior.get("last_modified"))
        if etag is not None:
            return {"If-None-Match": etag}
        return {"If-Modified-Since": modified} if modified is not None else {}

    def record_body(self, url, accept, payload, headers, *, encoding="utf-8", errors="strict"):
        key = request_hash(url, accept)
        observed = {"request_hash": key, "body_hash": sha256(payload).hexdigest(),
                    "representation_hash": representation_hash(headers, encoding, errors), **_validators(headers)}
        prior = self.detail_baseline(url, accept)
        eligible = _cacheable(headers)
        if (eligible and key not in self._uncacheable and prior is not None and prior["body_hash"] == observed["body_hash"]
                and prior["representation_hash"] == observed["representation_hash"]):
            observed.update(detail=prior["detail"], detail_context_hash=prior["detail_context_hash"])
        with self._lock:
            if not eligible:
                self._uncacheable.add(key)
            if key in self._observations or len(self._observations) < MAX_REQUESTS:
                self._observations[key] = observed
        if "detail" in observed:
            return RevalidatedDetail(dict(observed["detail"]))
        return None

    def revalidated(self, url, accept, headers, *, encoding="utf-8", errors="strict"):
        prior = self.detail_baseline(url, accept)
        if prior is None or not self.conditional_headers(url, accept):
            return None
        # 304 normally omits representation headers. An explicit changed header
        # cannot reuse a previously decoded body: request it unconditionally.
        if ("Content-Type" in headers
                and representation_hash(headers, encoding, errors) != prior["representation_hash"]):
            return None
        observed = {key: prior[key] for key in ("request_hash", "body_hash", "representation_hash")}
        eligible = _cacheable(headers)
        if eligible:
            observed.update(detail=prior["detail"], detail_context_hash=prior["detail_context_hash"])
            for name in ("etag", "last_modified"):
                value = _validator(prior.get(name), etag=name == "etag")
                if value is not None:
                    observed[name] = value
            observed.update(_validators(headers))
        with self._lock:
            if not eligible:
                self._uncacheable.add(observed["request_hash"])
            self._observations[observed["request_hash"]] = observed
        return RevalidatedDetail(dict(prior["detail"]))

    def remember_detail(self, url, accept, evidence):
        context = _detail.get()
        key = request_hash(url, accept)
        if context is None or context[0] != key or not _valid_detail(evidence):
            return
        with self._lock:
            observed = self._observations.get(key)
            if observed is not None and key not in self._uncacheable:
                observed.update(detail=dict(evidence), detail_context_hash=context[1])


def current_snapshot():
    return _capture.get()


@contextmanager
def capture_snapshot(source, collection_context):
    claim = source.get("incremental_snapshot")
    snapshot = None
    if (isinstance(collection_context, dict) and collection_context.get("p_category") in _CATEGORIES
            and isinstance(collection_context.get("p_ticket"), str) and collection_context["p_ticket"]
            and isinstance(claim, dict) and type(claim.get("version")) is int and claim["version"] == VERSION
            and isinstance(claim.get("policy_context"), str) and _HASH.fullmatch(claim["policy_context"])
            and not source.get("fetch_checkpoint_version") and not source.get("civic_contract_version")):
        try:
            snapshot = Snapshot(source, collection_context, claim)
        except (KeyError, ValueError, TypeError, OSError):
            snapshot = None
    token = _capture.set(snapshot)
    try:
        yield snapshot
    finally:
        _capture.reset(token)


@contextmanager
def detail_request(url, accept, event):
    snapshot = current_snapshot()
    context = None
    if snapshot is not None:
        identity = _identity(event)
        context = (request_hash(url, accept), fingerprint({
            "parser": snapshot.context_hash, "kind": "chambermaster_ical_v1",
            "id": identity[0], "starts_at": identity[1],
        }))
    token = _detail.set(context)
    try:
        yield snapshot
    finally:
        _detail.reset(token)
