from datetime import datetime, timedelta, timezone
import json

from roomquest import eventon


def test_eventon_preserves_occurrence_times_and_maps_reedy_creek():
    start = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0)
    end = start + timedelta(hours=3)
    html = f'''<div class="eventon_list_event" data-event_id="117532" data-time="1-2">
        <meta itemprop="eventStatus" content="https://schema.org/EventScheduled">
        <link itemprop="url" href="{eventon.CALENDAR}invasive-plant-removal-at-reedy-creek/">
        <meta itemprop="startDate" content="{start.isoformat()}">
        <meta itemprop="endDate" content="{end.isoformat()}">
        <span class="evcal_event_title">Invasive Plant Removal at Reedy Creek</span>
        </div>'''
    payload = json.dumps({'cals': {eventon.CALENDAR_ID: {'json': [{}], 'html': html}}})
    [row] = eventon.parse(payload)
    assert row['starts_at'] == start.isoformat()
    assert row['venue_address'] == eventon.REEDY_CREEK
    assert row['id'].startswith('117532:')
