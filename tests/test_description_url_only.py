"""Links to another page do not count as publisher event narrative."""
from datetime import datetime, timedelta, timezone

import pytest

from roomquest.event_description import description


@pytest.mark.parametrize('value', [
    'https://www.sarpy.gov/calendar.aspx?EID=1071',
    '  http://publisher.example/event/1  ',
    'HTTPS://publisher.example/event/1#details',
    'https://publisher.example/one https://publisher.example/two',
    '\nhttps://publisher.example/one\n\thttp://publisher.example/two\n',
    '<p>https://publisher.example/one</p><p>https://publisher.example/two</p>',
    '<a href="https://publisher.example/event">https://publisher.example/event</a>',
    '<p>https://publisher.example/event?a=1&amp;b=2</p><nav>All events</nav><script>tracking()</script>',
])
def test_one_or_multiple_bare_http_links_are_not_descriptions(value):
    assert description(value) == ''


@pytest.mark.parametrize('value,expected', [
    ('No cover.', 'No cover.'),
    ('Ages 8+. Materials provided.', 'Ages 8+. Materials provided.'),
    ('Bring a board game. https://publisher.example/info', 'Bring a board game. https://publisher.example/info'),
    ('https://publisher.example/info\nBring a board game.', 'https://publisher.example/info\nBring a board game.'),
    ('<p>Guided garden walk.</p><a href="https://publisher.example/info">https://publisher.example/info</a>',
     'Guided garden walk.\nhttps://publisher.example/info'),
    ('https://publisher.example/info<p>Welcome!</p>', 'https://publisher.example/info\nWelcome!'),
    ('<p>No cover.</p><nav>Calendar</nav>', 'No cover.'),
])
def test_useful_prose_and_short_actionable_text_are_preserved(value, expected):
    assert description(value) == expected


def test_url_only_detection_precedes_bounding_without_changing_prose_limit():
    assert description('https://publisher.example/a-long-event-link', limit=12) == ''
    assert description('Bring art supplies. https://publisher.example/info', limit=12) == 'Bring art su'


def test_sarpy_county_generic_ics_route_drops_bare_link_without_changing_event_url(monkeypatch):
    from roomquest import preview_worker

    feed = 'https://www.sarpy.gov/common/modules/iCalendar/iCalendar.aspx?catID=34&feed=calendar'
    start = (datetime.now(timezone.utc) + timedelta(days=2)).strftime('%Y%m%dT%H%M%SZ')
    payload = '\r\n'.join([
        'BEGIN:VCALENDAR', 'VERSION:2.0', 'BEGIN:VEVENT', 'UID:url-only-fixture',
        'SUMMARY:Community Program', 'DTSTART:' + start, 'LOCATION:Community Center',
        'GEO:41.28;-96.01', 'DESCRIPTION:https://www.sarpy.gov/calendar.aspx?EID=1071',
        'END:VEVENT', 'END:VCALENDAR', '',
    ])
    calls = []

    def fetch(url, accept, **kwargs):
        calls.append((url, accept))
        return payload

    monkeypatch.setattr(preview_worker, 'fetch_publisher', fetch)
    result = preview_worker.preview_source({
        'source_key': 'sarpy_county_tourism_ical_ne', 'feed_url': feed,
        'timezone': 'America/Chicago', 'kind': 'ical', 'platform_adapter': 'ical',
    })
    row, = result['p_events']
    assert row['description'] == ''
    assert row['event_url'] == feed
    assert row['id'] == 'url-only-fixture'
    assert calls == [(feed, 'text/calendar')]
