"""A bounded search interval, independent of collection/freshness wall clocks.

Only the private collector claim supplies this contract. Context-local storage
keeps concurrent source workers isolated; the default remains the rolling window.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

DURATION = timedelta(days=60)
_window = ContextVar("community_collection_window", default=None)


@dataclass(frozen=True)
class CollectionWindow:
    start: datetime
    end: datetime


def _instant(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("invalid_collection_window")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid_collection_window") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("invalid_collection_window")
    return parsed.astimezone(timezone.utc)


def claimed_window(source):
    value = source.get("collection_window")
    if value is None:
        return None
    if (not isinstance(value, dict) or type(value.get("version")) is not int
            or value["version"] != 1 or set(value) != {"version", "start", "end"}):
        raise ValueError("invalid_collection_window")
    start, end = _instant(value["start"]), _instant(value["end"])
    if end - start != DURATION:
        raise ValueError("invalid_collection_window")
    return CollectionWindow(start, end)


@contextmanager
def collection_scope(source):
    token = _window.set(claimed_window(source))
    try:
        yield _window.get()
    finally:
        _window.reset(token)


def explicit_window():
    return _window.get()


def collection_window(now=None):
    explicit = explicit_window()
    if explicit is not None:
        return explicit
    now = now or datetime.now(timezone.utc)
    return CollectionWindow(now, now + DURATION)


def recurrence_start():
    """None preserves the upstream expander's ordinary local-date behavior."""
    explicit = explicit_window()
    return explicit.start if explicit is not None else None


def localist_dates():
    explicit = explicit_window()
    return {"start": explicit.start.date().isoformat(), "days": 60} if explicit else {"days": 60}
