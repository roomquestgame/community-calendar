from datetime import date
from unittest.mock import patch
import pytest
from bs4 import BeautifulSoup
from roomquest import registered_listings as x
from roomquest.feed_registration import register

BODY = '<footer>Located at The AMP 1220 Waterway Blvd, Indianapolis, IN 46202 FREE PARKING EVERY SATURDAY November 14, 2026 - April 24, 2027 Closed on December 26 9 a.m. — 12:30 p.m.</footer>'

def test_actual_season_omits_closure_and_bounds_horizon():
    rows=list(x.indy(BeautifulSoup(BODY,'html.parser'),date(2026,11,22)))
    assert len(rows)==7
    assert rows[0]['starts_at']=='2026-11-28T14:00:00+00:00'
    assert rows[0]['ends_at']=='2026-11-28T17:30:00+00:00'
    assert not any(r['starts_at'].startswith('2026-12-26') for r in rows)
    assert all(r['venue_address']=='1220 Waterway Blvd, Indianapolis, IN 46202' and r['lat'] is None for r in rows)

@pytest.mark.parametrize('old,new', [('footer','main'),('Closed on December 26',''),('1220 Waterway','999 Waterway'),('9 a.m.','10 a.m.'),('EVERY SATURDAY','EVERY SUNDAY'),('April 24, 2027','April 24, 2029')])
def test_changed_or_incomplete_evidence_stays_review(old,new):
    with pytest.raises(ValueError):list(x.indy(BeautifulSoup(BODY.replace(old,new),'html.parser'),date(2026,11,22)))

def test_shared_expansion_season_bounds():
    assert list(x.seasonal_weekly_dates(date(2027,4,3),date(2027,4,24),5,{date(2027,4,10)},date(2027,4,1)))==[date(2027,4,3),date(2027,4,17),date(2027,4,24)]
    assert list(x.seasonal_weekly_dates(date(2027,4,3),date(2027,4,24),5,set(),date(2027,4,25)))==[]

def test_registration_uses_normal_html_path_and_robots():
    with patch('roomquest.feed_registration.supabase_rpc',side_effect=[{'url':x.INDY},True]) as rpc, patch('roomquest.feed_registration.fetch_publisher',return_value=BODY) as fetch:
        assert register('ticket')['outcome']=='verified'
        assert rpc.call_args.args[1]['p_type']=='html'
        assert rpc.call_args.args[1]['p_endpoint']==x.INDY
        assert fetch.call_count==1 and fetch.call_args.kwargs['respect_robots'] is True
