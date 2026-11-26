from copy import deepcopy
from datetime import date
import json

import pytest

from roomquest import provider_registration
from roomquest import venuepilot_provider as venuepilot


URL = venuepilot.API + '#accounts=2535'
PAGE = '''
<div id="venuepilot-app"></div>
<script>window.venuepilotSettings = {"general":{"accountIds":[2535],
"server":"https://www.venuepilot.co/"}};</script>
<script src="https://widget.staging.venuepilot.com/2.0.0/widget-loader.js"></script>
'''


def event(**changes):
    value = {
        'id': 205906, 'name': 'Friday House Show', 'date': '2026-12-04',
        'doorTime': '20:30', 'startTime': '21:00', 'endTime': '00:30',
        'minimumAge': 18, 'promoter': None, 'support': None,
        'description': '<p>A full comedy show.</p>', 'websiteUrl': None,
        'twitterUrl': None, 'instagramUrl': None,
        'images': ['https://venuepilot-production.s3.amazonaws.com/show.jpg'],
        'status': 'Tickets', 'venue': {'name': 'Stand Up NY at Bond 45'},
        'footerContent': None, 'highlightedImage': None,
        'ticketsUrl': 'https://square.link/u/example',
    }
    value.update(changes)
    return value


def payload(rows=None):
    return json.dumps({'data': {'publicEvents': [event()] if rows is None else rows}})


def test_standard_embed_discovers_exact_provider_identity():
    assert venuepilot.subscription(PAGE) == URL
    assert provider_registration.family(URL) == 'venuepilot'
    assert provider_registration.family(venuepilot.API) is None
    assert venuepilot.subscription(PAGE.replace('https://www.venuepilot.co/', 'https://evil.example/')) is None
    assert venuepilot.subscription(PAGE.replace('[2535]', '[2535,2535]')) is None
    assert venuepilot.subscription(PAGE.replace('widget.staging.venuepilot.com/', 'evil.example/')) is None


def test_request_is_read_only_bounded_and_exact():
    request = venuepilot.request((2535,), date(2026, 11, 26), date(2027, 1, 26))
    assert venuepilot.valid_request(request)
    for mutate in (
        lambda body: body.update(query=body['query'] + ' mutation'),
        lambda body: body['variables'].update(limit=501),
        lambda body: body['variables'].update(search='comedy'),
        lambda body: body['variables'].update(accountIds=[2535, 2535]),
        lambda body: body['variables'].update(endDate='2027-01-27'),
        lambda body: body.update(extra=True),
    ):
        changed = deepcopy(request)
        mutate(changed)
        assert not venuepilot.valid_request(changed)


def test_complete_public_collection_becomes_stage_records():
    rows = venuepilot.parse(payload(), url=URL, config=venuepilot.profile(URL))
    assert len(rows) == 1
    assert rows[0]['title'] == 'Friday House Show'
    assert rows[0]['starts_at'] == '2026-12-05T02:00:00+00:00'
    assert rows[0]['ends_at'] == '2026-12-05T05:30:00+00:00'
    assert rows[0]['venue_name'] == 'Stand Up NY at Bond 45'
    assert rows[0]['venue_address'] == '221 W 46th St, New York, NY 10036'
    assert rows[0]['description'] == 'A full comedy show.'
    assert rows[0]['event_url'] == 'https://standupny.com/upcoming-shows/#/events/205906'
    assert rows[0]['image_url'].endswith('/show.jpg')


@pytest.mark.parametrize('rows,reason', [
    ([event(id=205906), event(id=205906)], 'venuepilot_event_invalid'),
    ([event(venue={'name': 'Unknown Room'})], 'venuepilot_venue_unreviewed'),
    ([event(startTime='9pm')], 'venuepilot_event_invalid'),
    ([event(images={})], 'venuepilot_event_invalid'),
])
def test_incomplete_or_ambiguous_collection_is_held(rows, reason):
    with pytest.raises(ValueError, match='^' + reason + '$'):
        venuepilot.parse(payload(rows), url=URL, config=venuepilot.profile(URL))


def test_collector_uses_exact_api_request_and_profile():
    calls = []
    def fetch(url, accept, **options):
        calls.append((url, accept, options))
        return payload()
    source = {'feed_url': URL, 'source_key': 'unused', 'kind': 'json',
              'platform_adapter': 'venuepilot'}
    rows = venuepilot.collect(source, fetch, today=date(2026, 11, 26))
    assert len(rows) == 1
    assert calls[0][0:2] == (venuepilot.API, 'application/json')
    assert venuepilot.valid_request(calls[0][2]['calendar_json'])
