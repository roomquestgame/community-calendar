from copy import deepcopy
import pytest
from roomquest import registered_native_content as native
from roomquest.registration_formats import source_key

FEEDS = ['https://www.punchlinecomedyclub.com/', 'https://www.theechodallas.com/']
URL = 'https://www.ticketmaster.com/publisher-show/event/1C00634ABCD12345'

def source(feed):
    return {'feed_url': feed, 'source_key': source_key(feed), 'kind': 'json',
            'platform_adapter': 'jsonld', native.CAPABILITY: 1}

@pytest.mark.parametrize('feed', FEEDS)
def test_official_ticket_identity_retains_native_proof(feed):
    claim = source(feed)
    row = native.attach({'id': URL, 'event_url': URL}, claim,
                        description_value='Publisher event description')
    native.validate_record(row, claim)
    assert row['event_url'] == URL
    assert row['registered_native_content']['feed_url'] == feed
    wrong = deepcopy(row)
    wrong['registered_native_content']['feed_url'] = FEEDS[1] if feed == FEEDS[0] else FEEDS[0]
    with pytest.raises(ValueError, match='registered_native_evidence_invalid'):
        native.validate_record(wrong, claim)

@pytest.mark.parametrize('url', [
    URL.replace('www.ticketmaster.com', 'ticketmaster.com'),
    URL.replace('www.ticketmaster.com', 'www.ticketmaster.com.evil.example'),
    URL.replace('https:', 'http:'), URL + '?redirect=evil', URL + '#fragment',
    URL.replace('/event/', '/artist/'), URL.lower(), URL + '/',
    URL.replace('www.ticketmaster.com', 'u:p@www.ticketmaster.com'),
    URL.replace('www.ticketmaster.com', 'www.ticketmaster.com:443'),
    None, 'https://www.ticketmaster.com/',
])
def test_ticket_shape_near_misses_fail(url):
    assert not native.event_url_matches(source(FEEDS[0]), url)

@pytest.mark.parametrize('feed', ['https://www.punchlinecomedyclub.com/calendar/',
    'https://punchlinecomedyclub.com/', 'https://www.theechodallas.com/?filter=1',
    'https://unreviewed.example.org/'])
def test_unreviewed_calendar_cannot_use_exception(feed):
    assert not native.event_url_matches(source(feed), URL)

def test_capability_and_adapter_required():
    for change in [{native.CAPABILITY: 0}, {'platform_adapter': 'wordpress'}]:
        assert not native.event_url_matches({**source(FEEDS[0]), **change}, URL)
