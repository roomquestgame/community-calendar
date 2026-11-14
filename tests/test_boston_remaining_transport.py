"""Boston Cares display POST retains the common network and request boundary."""
from datetime import datetime, timedelta
from unittest.mock import patch, Mock
from zoneinfo import ZoneInfo
import pytest
from roomquest import preview_worker as worker

URL='https://www.bostoncares.org/search/getOpportunitiesCalendar'
HOST=('www.bostoncares.org',)

def window():
    today=datetime.now(ZoneInfo('America/New_York')).date()
    return today.isoformat(),(today+timedelta(days=14)).isoformat()

def response(status=200, **headers):
    result=Mock(status_code=status,encoding='utf-8')
    result.headers={'Content-Type':'application/json',**headers}
    result.iter_content.return_value=[b'{"events": []}']
    return result

def run_transport(reply, robots=True):
    session=Mock();session.__enter__=Mock(return_value=session);session.__exit__=Mock(return_value=False)
    session.post.return_value=reply
    patches=[patch.object(worker.requests,'Session',return_value=session),
             patch.object(worker,'validate_public_dns'),patch.object(worker,'robots_allowed',return_value=robots),
             patch.object(worker,'pace_publisher')]
    return session,patches

def test_public_calendar_display_uses_only_reviewed_form_and_network_guards():
    start,end=window();session,patches=run_transport(response())
    with patches[0],patches[1] as dns,patches[2] as robots,patches[3] as pace:
        assert worker.render_boston_cares_calendar(start_day=start,end_day=end)=='{"events": []}'
    dns.assert_called_once_with('www.bostoncares.org')
    robots.assert_called_once();pace.assert_called_once()
    args,kw=session.post.call_args
    assert args==(URL,)
    assert kw['data']=={'searchvo_startfrom':start,'searchvo_endfrom':end,'searchvo_searchresultblockid':'589'}
    assert kw['headers']['Referer']=='https://www.bostoncares.org/calendar'
    assert kw['allow_redirects'] is False and kw['stream'] is True
    session.get.assert_not_called()

@pytest.mark.parametrize('mutation',[
    {'action':'register'},{'searchvo_searchresultblockid':'590'},
    {'searchvo_endfrom':'2099-01-01'},{'searchvo_startfrom':'2020-01-01'},
])
def test_arbitrary_fields_routes_and_unbounded_dates_fail_before_transport(mutation):
    start,end=window();form={'searchvo_startfrom':start,'searchvo_endfrom':end,'searchvo_searchresultblockid':'589',**mutation}
    with patch.object(worker.requests,'Session') as session:
        with pytest.raises(worker.PreviewError,match='^invalid_calendar_render_parameters$'):
            worker._fetch_publisher_request(URL,'application/json',respect_robots=True,allowed_hosts=HOST,calendar_form=form)
        session.assert_not_called()

def test_calendar_robots_denial_is_not_bypassed_by_post_helper():
    start,end=window();session,patches=run_transport(response(),robots=False)
    with patches[0],patches[1],patches[2],patches[3]:
        with pytest.raises(worker.PreviewError,match='^robots_denied$'):
            worker.render_boston_cares_calendar(start_day=start,end_day=end)
    session.post.assert_not_called()

def test_calendar_post_redirect_is_never_replayed():
    start,end=window();session,patches=run_transport(response(status=302,Location='https://www.bostoncares.org/register'))
    with patches[0],patches[1],patches[2],patches[3]:
        with pytest.raises(worker.PreviewError,match='^calendar_render_redirect_blocked$'):
            worker.render_boston_cares_calendar(start_day=start,end_day=end)
    assert session.post.call_count==1
    session.get.assert_not_called()
