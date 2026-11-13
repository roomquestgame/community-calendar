"""Capture prose on the exact linked event pages in complete, resumable batches.

Only a finished manifest can enter staging. A skipped or failed detail request
therefore cannot erase old prose or certify a partially visited calendar.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import partial
from hashlib import sha256
import json
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

PROFILES = {
    "omaha_reverb_lounge_events": (
        "https://reverblounge.com/events/", "America/Chicago", "reverblounge.com"),
    "municipal_175e7cdf657e22645f5d5ef6": (
        "https://www.downtownnorfolk.org/explore/calendar?d=next30", "America/New_York",
        "www.downtownnorfolk.org"),
    "municipal_12c58b8068db81adc4284433": (
        "https://www.sandlercenter.org/events", "America/New_York", "www.sandlercenter.org"),
}
CONTRACT = "linked_event_descriptions_v1"
MAX_ROWS = 200
MAX_DETAILS_PER_CHUNK = 6
MIN_DETAIL_SECONDS = 18
MAX_BYTES = 900_000
MAX_AGE = timedelta(hours=4)


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _key(row):
    return row["id"], row["starts_at"]


def _facts(row):
    return {key: value for key, value in row.items() if key != "description"}


def _adapter(key):
    if key == "omaha_reverb_lounge_events":
        from roomquest import rockhouse
        return rockhouse.collect, rockhouse.description_from_detail
    if key == "municipal_175e7cdf657e22645f5d5ef6":
        from roomquest import downtown_norfolk
        return downtown_norfolk.collect, downtown_norfolk.description_from_detail
    from roomquest import hampton_roads_public_events
    return partial(hampton_roads_public_events.collect, listing_only=True), hampton_roads_public_events.description_from_detail


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None,
                  max_details=MAX_DETAILS_PER_CHUNK):
    key = source.get("source_key")
    profile = PROFILES.get(key)
    if (profile is None or source.get("feed_url") != profile[0]
            or source.get("timezone") != profile[1]
            or source.get("kind") != "html" or source.get("platform_adapter") != "html"):
        raise ValueError("unregistered_linked_description_source")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("linked_description_checkpoint_invalid")
    current = current.astimezone(timezone.utc)
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError("collection_deadline")

    # Some Sandler showtimes already require their exact detail page. Reuse
    # those responses within this invocation instead of requesting them twice.
    fetched = {}

    def cached_fetch(url, accept):
        if (url, accept) not in fetched:
            fetched[url, accept] = fetch(url, accept)
        return fetched[url, accept]

    collect, extract = _adapter(key)
    rows = sorted(collect(source, cached_fetch, deadline_at=deadline_at, now=current), key=_key)
    if len(rows) > MAX_ROWS or len({_key(row) for row in rows}) != len(rows):
        raise ValueError("linked_description_manifest_invalid")
    grouped = {}
    for row in rows:
        parsed = urlsplit(row["event_url"])
        if (parsed.scheme != "https" or parsed.netloc != profile[2]
                or parsed.query or parsed.fragment or parsed.username or parsed.password):
            raise ValueError("linked_description_manifest_invalid")
        grouped.setdefault(row["event_url"], []).append(row)
    urls = sorted(grouped)
    digest = sha256(_encoded([_facts(row) for row in rows]).encode()).hexdigest()
    state = None
    if checkpoint is not None:
        if (not isinstance(checkpoint, dict) or checkpoint.get("contract") != CONTRACT
                or type(checkpoint.get("version")) is not int or checkpoint["version"] != 1
                or checkpoint.get("source_key") != key
                or type(checkpoint.get("cursor")) is not int
                or type(checkpoint.get("manifest_count")) is not int
                or not 0 <= checkpoint["cursor"] <= checkpoint["manifest_count"] <= MAX_ROWS
                or not isinstance(checkpoint.get("events"), list)
                or len(checkpoint["events"]) > MAX_ROWS
                or checkpoint.get("diagnostics") != []
                or len(_encoded(checkpoint).encode()) > MAX_BYTES):
            raise ValueError("linked_description_checkpoint_invalid")
        try:
            started = datetime.fromisoformat(checkpoint["started_at"])
            if (started.tzinfo is None or started.utcoffset() is None
                    or checkpoint["window_start"] != started.astimezone(ZoneInfo(profile[1])).date().isoformat()):
                raise ValueError
        except (TypeError, ValueError, KeyError):
            raise ValueError("linked_description_checkpoint_invalid") from None
        if (started <= current <= started + MAX_AGE
                and checkpoint.get("manifest_hash") == digest
                and checkpoint["manifest_count"] == len(urls)):
            state = deepcopy(checkpoint)
            expected = {_key(row): _facts(row) for url in urls[:state["cursor"]] for row in grouped[url]}
            actual = {}
            for row in state["events"]:
                if (not isinstance(row, dict) or not isinstance(row.get("id"), str)
                        or not isinstance(row.get("starts_at"), str)
                        or not isinstance(row.get("description"), str)
                        or len(row["description"]) > 2000):
                    raise ValueError("linked_description_checkpoint_invalid")
                try:
                    identity = _key(row)
                except (KeyError, TypeError):
                    raise ValueError("linked_description_checkpoint_invalid") from None
                if identity in actual:
                    raise ValueError("linked_description_checkpoint_invalid")
                actual[identity] = _facts(row)
            if actual != expected:
                raise ValueError("linked_description_checkpoint_invalid")
    if state is None:
        state = {"version": 1, "contract": CONTRACT, "source_key": key,
                 "started_at": current.isoformat(),
                 "window_start": current.astimezone(ZoneInfo(profile[1])).date().isoformat(),
                 "manifest_hash": digest, "manifest_count": len(urls), "cursor": 0,
                 "events": [], "diagnostics": []}
    limit = min(MAX_DETAILS_PER_CHUNK, max(1, int(max_details)))
    previous_cursor = state["cursor"]
    stop = min(len(urls), state["cursor"] + limit)
    for offset in range(state["cursor"], stop):
        url = urls[offset]
        if ((url, "text/html") not in fetched and deadline_at is not None
                and deadline_at - monotonic() < MIN_DETAIL_SECONDS):
            break
        payload = cached_fetch(url, "text/html")
        for row in grouped[url]:
            narrative = extract(payload, row)
            if not isinstance(narrative, str) or len(narrative) > 2000:
                raise ValueError("linked_description_manifest_invalid")
            if " ".join(narrative.split()).casefold() == " ".join(row["title"].split()).casefold():
                narrative = ""
            state["events"].append({**row, "description": narrative})
        state["cursor"] = offset + 1
    if len(_encoded(state).encode()) > MAX_BYTES:
        raise ValueError("linked_description_checkpoint_size_limit")
    complete = state["cursor"] == state["manifest_count"]
    if not complete and state["cursor"] == previous_cursor:
        raise ValueError("collection_deadline")
    return {"checkpoint": state, "complete": complete,
            "events": sorted(state["events"], key=lambda row: (row["starts_at"], row["id"])) if complete else []}
