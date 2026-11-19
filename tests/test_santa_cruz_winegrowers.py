from datetime import datetime,timezone
from roomquest import santa_cruz_winegrowers as s
NOW=datetime(2026,11,18,20,tzinfo=timezone.utc)
SOURCE={'source_key':s.KEY,'feed_url':s.URL,'kind':'html','platform_adapter':'html','timezone':s.ZONE}
def listing(link=s.STROLL,title='Surf City Stroll',day='November 21, 2026'):
    return '<article class="grid-card events"><a class="main-link" href="'+link+'"></a><div class="info"><h2>'+title+'</h2><h3>'+day+'</h3></div></article>'
def detail(day='November 21, 2026',clock='1:00 pm - 4:00 pm',body=None):
    body=body if body is not None else 'Join the Westside wine walk. Check-in & Registration: Swift Street Courtyard at 334 Ingalls St Suite A. Experience tastings from local wineries.'
    return '<main class="site-main events"><section class="event-header"><h1>Surf City Stroll</h1><div class="event-meta"><h3>'+day+'</h3><h3>'+clock+'</h3></div></section><section class="events-body"><div class="event-body-text">'+body+'</div></section></main>'
def run(c=None,d=None):
    return s.collect(SOURCE,lambda url,accept: c if url==s.URL and c is not None else listing() if url==s.URL else d if d is not None else detail(),now=NOW)
def test_publisher_narrative_and_correct_checkin_not_fake_coordinates():
    rows=run()
    assert len(rows)==1 and rows[0]['venue_address']==s.STREET
    assert rows[0]['lat'] is None and rows[0]['lng'] is None
    assert 'Experience tastings' in rows[0]['description']
def test_no_offsite_or_unapproved_event_identity():
    assert run(c=listing(link='https://attacker.test/events/surfcitystroll/'))==[]
    assert run(c=listing(link='https://winesofthesantacruzmountains.com/events/passport/'))==[]
    assert run(d=detail(body='Join our wine tasting, streets unknown.'))==[]
def test_reject_mismatched_detail_date_and_unauthorized_source():
    try:run(d=detail(day='November 22, 2026'))
    except ValueError as e:assert str(e)=='scmwa_detail_date_drift'
    else:assert False
    try:s.collect(SOURCE|{'feed_url':'https://winesofthesantacruzmountains.com/other'},lambda *_:'',now=NOW)
    except ValueError as e:assert str(e)=='unregistered_scmwa_source'
    else:assert False
def test_exact_future_time_and_recurrence_not_inferred():
    assert s._parse('November 21, 2026','1:00 pm - 4:00 pm')
    assert s._parse('November 21, 2026','5:00 pm - 4:00 pm') is None
    assert s.event_url(s.STROLL)
    assert not s.event_url(s.STROLL+'?redirect=1')
    assert not s.event_url('https://winesofthesantacruzmountains.com/events/other/')

