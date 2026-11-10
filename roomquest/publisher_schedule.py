"""Resolve corroborated publisher clocks without inventing calendar facts."""
from datetime import datetime


def earliest_published_time(*values):
    """Prefer the earlier explicit time for one already-matched event/date.

    Callers must independently match occurrence identity and parse each actual
    published date/time in its verified timezone. Missing/naive times and dates
    on different publisher-local days stay unresolved. Start/end ordering is a
    separate caller check; this function does not infer meridiems or years.
    """
    if (not values or any(not isinstance(value, datetime) or value.tzinfo is None
                          or value.utcoffset() is None for value in values)):
        raise ValueError('publisher_time_unverified')
    zone, day = values[0].tzinfo, values[0].date()
    if any(value.astimezone(zone).date() != day for value in values):
        raise ValueError('publisher_date_conflict')
    return min(values)
