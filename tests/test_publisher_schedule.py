from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from roomquest.publisher_schedule import earliest_published_time


def test_earlier_explicit_time_wins_independently_of_source_order():
    early = datetime(2026, 11, 15, 11, tzinfo=ZoneInfo('America/New_York'))
    late = datetime(2026, 11, 15, 12, tzinfo=ZoneInfo('America/New_York'))
    assert earliest_published_time(late, early) == early
    assert earliest_published_time(early, late.astimezone(timezone.utc)) == early


@pytest.mark.parametrize('other', [
    None, '11:00', datetime(2026, 11, 15, 11),
    datetime(2026, 11, 14, 11, tzinfo=ZoneInfo('America/New_York')),
    datetime(2027, 11, 15, 11, tzinfo=ZoneInfo('America/New_York')),
])
def test_missing_timezone_or_different_occurrence_day_remains_unresolved(other):
    first = datetime(2026, 11, 15, 11, tzinfo=ZoneInfo('America/New_York'))
    with pytest.raises(ValueError):
        earliest_published_time(first, other)
