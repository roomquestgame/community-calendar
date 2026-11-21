import json

from roomquest.event_description import description
from roomquest.jsonld_adapter import collect
from roomquest.registration_formats import source_key
from roomquest.registered_native_content import validate_record


def test_encoded_publisher_markup_is_removed_before_native_validation():
    url = 'https://publisher.example/events/'
    source = {'source_key': source_key(url), 'feed_url': url, 'kind': 'json',
              'platform_adapter': 'jsonld', 'registered_native_content_version': 1}
    event = {'@type': 'Event', 'name': 'Public race',
             'url': 'https://publisher.example/event/race/',
             'startDate': '2027-01-02T08:00:00-05:00',
             'location': {'@type': 'Place', 'name': 'Race field',
                          'address': {'streetAddress': '12 Main St', 'addressLocality': 'Lynchburg'}},
             'description': '&lt;p&gt;Run &amp; give thanks.&lt;/p&gt;'
                            '&lt;script&gt;untrusted()&lt;/script&gt;'}
    rows = collect(source, lambda *_: json.dumps(event))
    assert len(rows) == 1
    assert rows[0]['description'] == 'Run & give thanks.'
    validate_record(rows[0], source)


def test_double_encoding_is_bounded_and_prose_and_limits_survive():
    assert description('&amp;lt;p&amp;gt;Family fun&amp;lt;/p&amp;gt;') == 'Family fun'
    assert description('Children aged < 5 welcome & families too') == 'Children aged < 5 welcome & families too'
    assert description('&lt;div&gt;abcdef&lt;/div&gt;', limit=3) == 'abc'
    assert description('&lt;style&gt;hidden&lt;/style&gt;&lt;p&gt;Visible&lt;/p&gt;') == 'Visible'
