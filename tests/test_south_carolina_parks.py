import json
from unittest.mock import patch
import pytest
from roomquest import south_carolina_parks as sc
from roomquest import preview_worker as worker


def page(*items):
    return '<h3>DETAILS</h3>' + ''.join('<li>'+i+'</li>' for i in items) + '<h3>Event Hours</h3>'


def test_two_sessions_same_date_are_preserved():
    result = sc.occurrences(page('November 16, 2026, 10:00 AM - 11:00 AM', 'November 16, 2026, 2:00 PM - 3:00 PM'))
    assert result == [('2026-11-16T10:00:00', '2026-11-16T11:00:00'), ('2026-11-16T14:00:00', '2026-11-16T15:00:00')]


def test_explicit_weekly_recurrence():
    result = sc.occurrences(page('November 2, 2026 - November 9, 2026, 12:00 PM - 1:00 PM<br>Every Week on Monday, Friday'))
    assert [r[0][:10] for r in result] == ['2026-11-02', '2026-11-06', '2026-11-09']


@pytest.mark.parametrize('schedule', ['November 2, 2026 - November 9, 2026, 12:00 PM - 1:00 PM', 'November 2, 2026, 10:00 PM - 1:00 AM', 'Hours vary'])
def test_ambiguous_times_are_not_invented(schedule):
    with pytest.raises(ValueError): sc.occurrences(page(schedule))


def test_unregistered_source_cannot_choose_url():
    with pytest.raises(ValueError, match='unregistered'):
        sc.collect({'source_key':'south_carolina_parks_1831', 'feed_url':'https://example.org'}, lambda *_: pytest.fail('must not fetch'))


def test_park_join_and_missing_session_fail_closed():
    event = {'id':1, 'parkId':1831, 'name':'Walk', 'dates':['11/16/2026', '11/16/2026']}
    park = {'productID':1831, 'name':'Aiken', 'address1':'1145 State Park RD', 'cityName':'Windsor', 'state':'SC','zip':'29856'}
    with pytest.raises(ValueError, match='occurrence_mismatch'):
        sc.normalize(event, park, page('November 16, 2026, 10:00 AM - 11:00 AM'))
    with pytest.raises(ValueError, match='identity_mismatch'):
        sc.normalize(event, {**park, 'productID':2}, '')


def test_custom_family_preserves_transport_error_and_never_uses_wordpress():
    source = {'source_key':'south_carolina_parks_1831', 'kind':'json', 'platform_adapter':'south_carolina_parks', 'feed_url':sc.ROOT+'/api/events#park=1831'}
    with patch.object(worker, 'fetch_publisher', side_effect=worker.PreviewError('publisher_http_403')), patch('roomquest.wordpress_adapter.collect') as wp:
        with pytest.raises(worker.PreviewError, match='publisher_http_403'): worker.preview_source(source)
        wp.assert_not_called()
