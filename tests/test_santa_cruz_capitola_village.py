"""Capitola Village direct TEC REST publisher adapter: event-specific evidence only."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import json
import pytest

from roomquest import santa_cruz_sources as s
from roomquest import preview_worker

NOW = datetime(2026, 11, 18, 21, tzinfo=timezone.utc)
ZONE = ZoneInfo(s.ZONE)


def source(**changes):
    url, kind, adapter = s.SOURCES[s.CAPITOLA_VILLAGE]
    return dict(source_key=s.CAPITOLA_VILLAGE, feed_url=url, kind=kind,
                platform_adapter=adapter, timezone=s.ZONE, **changes)


def occurrence(*, day=0, **changes):
    start = datetime(2026, 11, 19, 19, 0, tzinfo=ZONE) + timedelta(days=day)
    end = start + timedelta(hours=2)
    item = dict(id=10003472, status='publish',
                title='Thursday Night Wine Down With DJ Ryan James',
                start_date=start.strftime('%Y-%m-%d %H:%M:%S'),
                utc_start_date=start.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                end_date=end.strftime('%Y-%m-%d %H:%M:%S'),
                utc_end_date=end.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                timezone=s.ZONE,
                description='<p>Enjoy live music at Cocoa Vino in Capitola. DJ Ryan James spins ' +
                            'classic tracks for the local Thursday wine-down gathering.</p>',
                url='https://capitolavillage.com/event/thursday-night-wine-down-with-dj-ryan-james/2026-11-19/',
     ¶»§q«^