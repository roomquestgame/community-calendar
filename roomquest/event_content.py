"""Collector-level canonical event facts for shared publication fingerprints.

This is deliberately source-agnostic.  Publisher/source labels and collection
metadata never enter the envelope, so only fields belonging to the event can
change its fingerprint.
"""
from __future__ import annotations

from datetime import datetime, timezone


_JSON_ADAPTERS = frozenset((
    "wordpress", "jsonld", "squarespace", "spektrix", "localist",
    "tickera", "event_discovery", "chambermate",
))


def captures_original_event_content(source: dict) -> bool:
    """Match the shared database staging writers that retain this envelope."""
    kind = source.get("kind")
    adapter = source.get("platform_adapter")
    return (
        (kind == "html" and adapter == "html")
        or (kind == "json" and adapter in _JSON_ADAPTERS)
        or (kind == "rss" and adapter == "wordpress")
        or (kind == "xml" and adapter == "growthzone"
            and source.get("catalog_origin") == "feed_registration")
    )


def _schedule(value):
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(raw.removesuffix("Z") + ("+00:00" if raw.endswith("Z") else ""))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return "local", parsed.replace(microsecond=0).isoformat(timespec="seconds")
    return "utc", parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z")


def _text(value):
    return value if isinstance(value, str) and value.strip() else None


def _categories(value):
    if not isinstance(value, (list, tuple, set)):
        return []
    return sorted({item.strip() for item in value if isinstance(item, str) and item.strip()})


def original_event_content(row: dict, source: dict):
    """Return a v1 envelope from parsed publisher facts, or None if unsafe."""
    event_id = _text(row.get("id"))
    title = _text(row.get("title"))
    start = _schedule(row.get("starts_at"))
    end = _schedule(row.get("ends_at"))
    if event_id is None or title is None or start is None:
        return None
    if end is not None and end[0] != start[0]:
        return None
    facts = {
        "title": title,
        "description": _text(row.get("description")),
        "is_all_day": False,
        "publisher_status": _text(row.get("publisher_status")) or "scheduled",
        "event_url": _text(row.get("event_url")),
        "venue_name": _text(row.get("venue_name")),
        "venue_address": _text(row.get("venue_address")),
        "source_timezone": _text(row.get("timezone")) or _text(source.get("timezone")),
        "publisher_categories": _categories(row.get("publisher_categories")),
        "source_image_url": _text(row.get("image_url")),
        f"starts_at_{start[0]}": start[1],
        f"ends_at_{start[0]}": end[1] if end is not None else None,
    }
    return {"version": 1, "event_id": event_id, "facts": facts}


def attach_original_event_content(rows: list[dict], source: dict) -> None:
    """Attach missing envelopes once at the shared collector boundary."""
    if not captures_original_event_content(source):
        return
    for row in rows:
        if "collector_event_content_v1" in row:
            continue
        envelope = original_event_content(row, source)
        if envelope is not None:
            row["collector_event_content_v1"] = envelope
