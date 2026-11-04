"""Per-collection, bounded publisher wait evidence for the existing DB queue.

No raw header or robots body crosses the RPC boundary. Waits beyond a day, or
unrepresentable Retry-After values, require explicit review rather than a
shorter invented wait. A ContextVar keeps concurrent legacy previews isolated.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from email.utils import parsedate_to_datetime
from math import ceil
import re
from urllib.robotparser import RobotFileParser

MAX_PUBLISHER_WAIT = 86400
_capture = ContextVar("publisher_pacing", default=None)


@contextmanager
def capture_publisher_pacing():
    state = {"crawl_delay_seconds": 0, "retry_after_seconds": 0, "wait_unbounded": False}
    token = _capture.set(state)
    try:
        yield state
    finally:
        _capture.reset(token)


def _bounded_number(value):
    try:
        number = Decimal(str(value).strip())
        if not number.is_finite() or number < 0 or number > MAX_PUBLISHER_WAIT:
            return 0, True
        return int(number.to_integral_value(rounding=ROUND_CEILING)), False
    except (InvalidOperation, ValueError, OverflowError):
        return 0, True


def _remember(field, seconds, unbounded):
    state = _capture.get()
    if state is not None:
        state[field] = max(state[field], seconds)
        state["wait_unbounded"] = state["wait_unbounded"] or unbounded
    return seconds, unbounded


def observe_crawl_delay(value):
    return _remember("crawl_delay_seconds", *_bounded_number(value))


def observe_retry_after(value, *, now=None):
    """Accept numeric seconds or an HTTP date; round up, never shorten a wait."""
    if value is None or str(value).strip() == "":
        return 0, False
    raw = str(value).strip()
    if isinstance(value, (int, float, Decimal)) or re.fullmatch(r"\d+(?:\.\d+)?", raw):
        seconds, unbounded = _bounded_number(raw)
    else:
        try:
            when = parsedate_to_datetime(raw)
            if when.tzinfo is None:
                raise ValueError
            current = now or datetime.now(timezone.utc)
            seconds, unbounded = _bounded_number(max(0, ceil((when - current).total_seconds())))
        except (TypeError, ValueError, OverflowError):
            seconds, unbounded = 0, True
    return _remember("retry_after_seconds", seconds, unbounded)


def robots_crawl_delay(lines, user_agent):
    """Use the same robots group selection, rounding fractional delays upward.

    This second parser supplies pacing only. The original parser remains the
    authority for path permissions. A sentinel above the RPC bound survives
    group selection so an oversized applicable wait becomes a review hold.
    """
    normalized = []
    for line in lines:
        field, separator, raw = line.partition(":")
        if separator and field.strip().casefold() == "crawl-delay":
            value = raw.split("#", 1)[0].strip()
            seconds, unbounded = _bounded_number(value)
            normalized.append("Crawl-delay: " + str(MAX_PUBLISHER_WAIT + 1 if unbounded else seconds))
        else:
            normalized.append(line)
    parser = RobotFileParser()
    parser.parse(normalized)
    selected = parser.crawl_delay(user_agent)
    if selected is None:
        selected = parser.crawl_delay("*")
    return max(1, selected if selected is not None else 1)


def pacing_rpc_fields(state):
    if state["wait_unbounded"]:
        return {"p_publisher_crawl_delay_seconds": 0, "p_publisher_retry_after_seconds": 0,
                "p_publisher_wait_unbounded": True}
    return {"p_publisher_crawl_delay_seconds": state["crawl_delay_seconds"],
            "p_publisher_retry_after_seconds": state["retry_after_seconds"],
            "p_publisher_wait_unbounded": False}
