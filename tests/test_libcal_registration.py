from unittest.mock import patch

import pytest

from roomquest.feed_registration import classify, register
from roomquest.libcal_registration import subscription

URL = 'https://publisher.libcal.com/calendar/public'
BASE = 'https://publisher.libcal.com/ical_subscribe.php?src=p'
HTML = '''<script>var springyPage = {baseCalendarId: 8406,
iCalUrlBase: 'https\\u003A\\/\\/publisher.libcal.com\\/ical_subscribe.php\\u003Fsrc\\u003Dp'};</script>
<select id="cal-dd" multiple><option value="-1">All</option><option value="8406" selected>Public</option></select>
<select id="cat-dd" multiple></select>'''


def test_declared_export_uses_selected_calendar_and_filters():
    assert subscription(URL, HTML) == BASE + '&cid=8406'
    assert subscription(URL, HTML.replace('</select>', '</select>', 1) +
        '<select id="audience-dd"><option value="515" selected>Public</option></select>') == BASE + '&cid=8406&aud=515'
    assert classify(URL, HTML)['p_endpoint'] == BASE + '&cid=8406'
    assert classify(URL, HTML, endpoint_only=True)['p_outcome'] == 'review'


@pytest.mark.parametrize('url,html', [
    (URL+'?cid=2', HTML), (URL+'#filter', HTML),
    (URL.replace('.libcal.com', '.example.com'), HTML),
    (URL, HTML.replace('baseCalendarId: 8406', 'baseCalendarId: 5')),
    (URL, HTML.replace('value="8406" selected', 'value="-1" selected')),
    (URL, HTML.replace('value="8406" selected', 'value="8406"')),
    (URL, HTML.replace('publisher.libcal.com\\/', 'other.libcal.com\\/')),
    (URL, HTML.replace('src\\u003Dp', 'src\\u003De')),
    (URL, HTML+HTML),
])
def test_ambiguous_or_unverified_scope_is_not_invented(url, html):
    assert subscription(url, html) is None


def test_admin_registration_discovers_then_existing_endpoint_validation_runs():
    with patch('roomquest.feed_registration.supabase_rpc', side_effect=[{'url':URL}, True]) as rpc, \
         patch('roomquest.feed_registration.fetch_publisher', return_value=HTML) as fetch:
        assert register('ticket')['outcome'] == 'discovered'
        assert rpc.call_args.args[1]['p_endpoint'] == BASE + '&cid=8406'
        assert fetch.call_count == 1
        assert fetch.call_args.kwargs['respect_robots']
