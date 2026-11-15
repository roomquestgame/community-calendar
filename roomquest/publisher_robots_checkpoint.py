"""Authenticated, short-lived transport cache for selected leased HTML sources.

This is a cache of the complete robots response, never a cached path decision.
Only the publisher transport may create it. The existing private collector token
authenticates the cache across the already lease-fenced checkpoint RPC; publisher
JSON cannot mint policy authority. A token rotation merely causes a normal fetch.
"""
from __future__ import annotations

import base64
import binascii
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re

FIELD = "transport_robots_v1"
TTL_SECONDS = 300
MAX_ROBOTS_BYTES = 128_000
MAX_CHECKPOINT_BYTES = 900_000
ROBOTS_USER_AGENT = "RoomQuestCommunityCalendar/0.1 (community-event research)"
PERMISSION_USER_AGENT = "RoomQuestCommunityCalendar"
PUBLISHER_USER_AGENT = "RoomQuestCommunityCalendar/0.2 (+https://roomquestapp.vercel.app/)"
PROFILES = {
    "radegast_hall_brooklyn_ny": ("https://radegasthall.com/", "radegasthall.com"),
    "ny_transit_museum_ny": ("https://www.nytransitmuseum.org/programs/", "www.nytransitmuseum.org"),
    "flushing_town_hall_ny": ("https://www.flushingtownhall.org/events", "www.flushingtownhall.org"),
    "visit_raleigh_nc": ("https://www.visitraleigh.com/events/", "www.visitraleigh.com"),
}
HOSTS = frozenset(value[1] for value in PROFILES.values())
_DOMAIN = b"RoomQuest/transport-robots-checkpoint/v1\x00"
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)")
_FIELDS = frozenset(("version", "source_key", "feed_url", "host", "robots_url",
    "robots_user_agent", "permission_user_agent", "publisher_user_agent", "response_status",
    "body_b64", "fetched_at", "expires_at", "sealed_at", "not_before", "retry_after_until"))


def profile(source, allowed_hosts=None):
    if not isinstance(source, dict):
        return None
    expected = PROFILES.get(source.get("source_key"))
    if (expected is None or (source.get("feed_url"), source.get("kind"),
            source.get("platform_adapter"), source.get("timezone")) !=
            (expected[0], "html", "html", "America/New_York")
            or (allowed_hosts is not None and tuple(allowed_hosts) != (expected[1],))):
        return None
    return expected[1]


def _stamp(value):
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        raise ValueError("invalid cache timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def response_evidence(host, raw, status, *, now):
    """Called only after an ordinary guarded robots response completed."""
    if (host not in HOSTS or type(raw) is not bytes or len(raw) > MAX_ROBOTS_BYTES
            or type(status) is not int or status not in (200, 404, 410)
            or (status != 200 and raw) or now.tzinfo is None):
        return None
    at = now.astimezone(timezone.utc)
    return dict(response_status=status, body_b64=base64.b64encode(raw).decode("ascii"),
                fetched_at=at.isoformat(), expires_at=(at + timedelta(seconds=TTL_SECONDS)).isoformat())


def evidence_fetched_at(evidence):
    """Read the transport-owned local timestamp when comparing fresh policies."""
    try:
        return _stamp(evidence["fetched_at"])
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return None


def _validate(source, value, *, now):
    host = profile(source)
    if (host is None or not isinstance(value, dict) or set(value) != _FIELDS
            or type(value["version"]) is not int or value["version"] != 1
            or value["source_key"] != source["source_key"] or value["feed_url"] != source["feed_url"]
            or value["host"] != host or value["robots_url"] != "https://" + host + "/robots.txt"
            or value["robots_user_agent"] != ROBOTS_USER_AGENT
            or value["permission_user_agent"] != PERMISSION_USER_AGENT
            or value["publisher_user_agent"] != PUBLISHER_USER_AGENT
            or type(value["response_status"]) is not int or value["response_status"] not in (200, 404, 410)
            or not isinstance(value["body_b64"], str)
            or len(value["body_b64"]) > 4 * ((MAX_ROBOTS_BYTES + 2) // 3)
            or now.tzinfo is None):
        raise ValueError("invalid cache envelope")
    raw = base64.b64decode(value["body_b64"], validate=True)
    if (len(raw) > MAX_ROBOTS_BYTES or base64.b64encode(raw).decode("ascii") != value["body_b64"]
            or (value["response_status"] != 200 and raw)):
        raise ValueError("invalid cache body")
    fetched, expires, sealed = (_stamp(value[field]) for field in ("fetched_at", "expires_at", "sealed_at"))
    not_before = _stamp(value["not_before"])
    retry = _stamp(value["retry_after_until"]) if value["retry_after_until"] is not None else None
    if (expires - fetched != timedelta(seconds=TTL_SECONDS)
            or not fetched <= sealed <= now < expires
            or not sealed <= not_before <= sealed + timedelta(seconds=86400)
            or (retry is not None and not sealed <= retry <= not_before)):
        raise ValueError("expired or invalid cache clock")
    return dict(raw=raw, status=value["response_status"], fetched_at=fetched,
                expires_at=expires, not_before=not_before, retry_after_until=retry)


def seal(source, evidence, *, not_before, retry_after_until, secret, now):
    """Sign only response evidence and waits read from transport-owned state."""
    host = profile(source)
    if host is None or not isinstance(evidence, dict) or not isinstance(secret, str) or len(secret) != 64:
        return None
    try:
        value = dict(version=1, source_key=source["source_key"], feed_url=source["feed_url"],
            host=host, robots_url="https://" + host + "/robots.txt", robots_user_agent=ROBOTS_USER_AGENT,
            permission_user_agent=PERMISSION_USER_AGENT, publisher_user_agent=PUBLISHER_USER_AGENT,
            **deepcopy(evidence), sealed_at=now.astimezone(timezone.utc).isoformat(),
            not_before=not_before.astimezone(timezone.utc).isoformat(),
            retry_after_until=retry_after_until.astimezone(timezone.utc).isoformat() if retry_after_until else None)
        _validate(source, value, now=now)
        signature = hmac.new(secret.encode(), _DOMAIN + _encoded(value), hashlib.sha256).hexdigest()
        return dict(value, signature=signature)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, binascii.Error):
        return None


def restore(source, snapshot, *, secret, now):
    """Invalid, expired, foreign, or unsigned metadata grants no authority."""
    if (not isinstance(snapshot, dict) or set(snapshot) != _FIELDS | {"signature"}
            or not isinstance(secret, str) or len(secret) != 64
            or not isinstance(snapshot.get("signature"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", snapshot["signature"])):
        return None
    try:
        value = {key: item for key, item in snapshot.items() if key != "signature"}
        # Bound and validate the payload before hashing or parsing its policy.
        restored = _validate(source, value, now=now)
        expected = hmac.new(secret.encode(), _DOMAIN + _encoded(value), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(snapshot["signature"], expected):
            return None
        return restored
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, binascii.Error):
        return None


def detach(checkpoint):
    """Adapters receive calendar state only, never transport cache authority."""
    if checkpoint is None:
        return None, None
    state = deepcopy(checkpoint)
    return state, state.pop(FIELD, None)


def attach(checkpoint, snapshot):
    """Ignore adapter-supplied cache fields; only the transport snapshot survives."""
    state = deepcopy(checkpoint)
    state.pop(FIELD, None)
    if snapshot is not None:
        candidate = dict(state, **{FIELD: deepcopy(snapshot)})
        # Cache metadata is optional. Never expand the existing RPC byte cap.
        if len(json.dumps(candidate, ensure_ascii=False).encode()) <= MAX_CHECKPOINT_BYTES:
            return candidate
    return state
