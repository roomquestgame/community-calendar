"""Links to another page do not count as publisher event narrative."""
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
