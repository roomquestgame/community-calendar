"""Full native bodies, exact reviewed venues, complete scopes and durable chunks."""
from datetime import datetime, timedelta, timezone
import json
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo
import pytest
from roomquest import new_york_outdoors_final as ny

NOW = datetime.now(timezone.utc).replace(microsecond=0)
START = (NOW + timedelta(days=3)).astimezone(ZoneInfo(ny.ZONE)).replace(hour=10, minute=0, second=0)


def source(key):
    url, kind, adapter = ny.SOURCES[key]
    return dict(source_key=key, feed_url=url, kind=kind, platform_adapter=adapter, timezone=ny.ZONE)


def bk_page(url, body='Complete participation rules.', venue='Brooklyn Uprising', address=None, title='Community Climbing', access=True):
    address = address or dict(streetAddress='20 John St', addressLocality='Brooklyn', addressRegion='NY', postalCode='11201')
    native = dict(**{'@type': 'Event'}, name=title, url=url, description='Truncated excerpt...',
                  startDate=START.isoformat(), endDate=(START + timedelta(hours=1)).isoformat(),
                  eventAttendanceMode='https://schema.org/OfflineEventAttendanceMode',
                  eventStatus='https://schema.org/EventScheduled', location=dict(name=venue, address=address))
    location = '<div><h2>Location: Ritual Moves - Yoga Room</h2><p>Check in at 20 John Street first.</p></div>' if venue.startswith('Ritual') else ''
    return ('<script type="application/ld+json">' + json.dumps(native) + '</script>'
            '<article class="marketing-public-detail-card"><h1>' + title + '</h1><div class="mb-3">Fitness</div>'
            '<div class="event-description-rich"><p>' + body + '</p></div>' + location +
            '<div><h2>Instructor</h2><p>Complete coach biography.</p></div>'
            '<div class="event-fee-policy-callout">Late cancellations cost $10.</div>' +
            ('<p>Access to the gym via a pass or membership is required.</p>' if access else '') +
            '</article><div class="marketing-news-footer-top"><div>Important Information. Ages 13+, waiver required.</div></div>')


def bk_fetch(count=4):
    urls = ['https://www.bkup.nyc/events/' + f'{i:08d}-0000-0000-0000-000000000000' for i in range(count)]
    listing = ''.join('<div class="public-event-card"><h2><a href="' + u.split('www.bkup.nyc')[1] + '">Climb</a></h2></div>' for u in urls)
    calls = []
    def fetch(url, accept):
        calls.append(url)
        return listing if url == ny.SOURCES[ny.BKUP][0] else bk_page(url)
    return fetch, calls, urls


def park_event(**overrides):
    place = next(p for p in ny.PLACES if p['source_key'] == ny.PARKS and p.get('native_name', '').startswith('Seth Low Playground'))
    e = dict(guid='999', title='Nature Scavenger Hunt', description='<p>Follow every clue.</p><p>Bring water and a notebook.</p>',
             location=place['native_name'], coordinates=','.join(str(x) for x in place['native_point']), parkids=place['native_park_id'],
             categories='Nature | Urban Park Rangers', link={'url':f'http://www.nycgovparks.org/events/{START:%Y/%m/%d}/nature-walk'},
             starttime=START.replace(tzinfo=None).isoformat(), endtime=(START+timedelta(hours=1)).replace(tzinfo=None).isoformat())
    e.update(overrides)
    return e


def tribe_event(**overrides):
    p = ny._place(ny.CB6, '2513')
    e = dict(id=101, title='Neighborhood Meeting', status='publish', all_day=False, timezone=ny.ZONE,
             start_date=START.replace(tzinfo=None).isoformat(), end_date=(START+timedelta(hours=1)).replace(tzinfo=None).isoformat(),
             description='<p>Complete neighborhood agenda, admission and participation instructions.</p>',
             venue={'id':2513,'venue':p['native_venue']}, url='https://brooklyncb6.cityofnewyork.us/event/neighborhood-meeting/', categories=[])
    e.update(overrides)
    return e


def test_complete_rich_body_replaces_truncated_jsonld_and_preserves_all_terms():
    body = 'Complete safety, admission, accessibility and group participation instructions. ' * 50
    url = 'https://www.bkup.nyc/events/11111111-0000-0000-0000-000000000000'
    row = ny._bkup_detail({'url':url}, bk_page(url,body), NOW)[0]
    assert body.strip() in row['description'] and len(row['description'])>2000
    assert 'Truncated excerpt' not in row['description']
    assert all(x in row['description'] for x in ('Complete coach biography.','Late cancellations cost $10.','pass or membership','Ages 13+, waiver required.'))


@pytest.mark.parametrize('body,reason', [('', 'description_missing'), ('x'*12001, 'description_limit')])
def test_native_missing_or_oversize_description_is_never_invented_or_truncated(body,reason):
    with pytest.raises(ValueError, match=reason): ny._body(body)


def test_yoga_room_is_actual_attendance_site_and_checkin_is_preserved():
    url='https://www.bkup.nyc/events/11111111-0000-0000-0000-000000000000'
    row=ny._bkup_detail({'url':url},bk_page(url,venue='Ritual Moves - Yoga Room',address={'streetAddress':'32 Pearl St, Brooklyn, NY 11201'}),NOW)[0]
    assert row['venue_address']=='32 Pearl Street, Brooklyn, NY 11201'
    assert row['venue_name']=='Ritual Moves - Yoga Room' and 'Check in at 20 John Street first.' in row['description']


def test_public_social_event_without_membership_callout_stays_complete():
    url='https://www.bkup.nyc/events/11111111-0000-0000-0000-000000000000'
    assert ny._bkup_detail({'url':url},bk_page(url,title='Community Film Night',access=False),NOW)
    with pytest.raises(ValueError,match='event_not_public'):
        ny._bkup_detail({'url':url},bk_page(url,title='Climbing Rehab',access=False),NOW)


def test_unknown_changed_yoga_room_does_not_inherit_bkup_main_gym():
    url='https://www.bkup.nyc/events/11111111-0000-0000-0000-000000000000'
    with pytest.raises(ValueError,match='venue_conflict'):
        ny._bkup_detail({'url':url},bk_page(url,venue='Unrelated venue',address={'streetAddress':'99 Other Street'}),NOW)


def test_chunks_use_local_date_complete_wire_and_immutable_retry():
    fetch,calls,urls=bk_fetch()
    first=ny.collect_chunk(source(ny.BKUP),fetch,now=NOW,max_details=2)
    state=first['checkpoint'];assert not first['complete'] and first['events']==[]
    assert state['window_start']==NOW.astimezone(ZoneInfo(ny.ZONE)).date().isoformat()
    assert state['cursor']==2 and state['manifest_count']==4
    second=ny.collect_chunk(source(ny.BKUP),fetch,now=NOW+timedelta(minutes=1),checkpoint=state)
    assert second['complete'] and len(second['events'])==4
    assert second['checkpoint']['cursor']==second['checkpoint']['manifest_count']==4
    assert second['checkpoint']['started_at']==state['started_at']
    assert calls.count(ny.SOURCES[ny.BKUP][0])==1
    before=len(calls)
    assert ny.collect_chunk(source(ny.BKUP),fetch,now=NOW+timedelta(minutes=2),checkpoint=second['checkpoint'])==second
    assert len(calls)==before


@pytest.mark.parametrize('change', ['timestamp_window','altered_queue','altered_point','description_empty','wrong_id'])
def test_checkpoint_tampering_is_rejected_before_fetch(change):
    fetch,_,_=bk_fetch();state=ny.collect_chunk(source(ny.BKUP),fetch,now=NOW,max_details=1)['checkpoint']
    if change=='timestamp_window':state['window_start']=NOW.isoformat()
    elif change=='altered_queue':state['queue'][0]['url']='https://evil.example/events/a'
    elif change=='altered_point':state['events'][0]['lat']+=0.1
    elif change=='description_empty':state['events'][0]['description']=''
    elif change=='wrong_id':state['events'][0]['id']='not-the-native-occurrence'
    with pytest.raises(ValueError,match='checkpoint_invalid'):
        ny.collect_chunk(source(ny.BKUP),lambda *_:pytest.fail('invalid checkpoint fetched'),now=NOW,checkpoint=state)


def test_manifest_can_persist_before_details_when_budget_is_almost_spent(monkeypatch):
    fetch,_,_=bk_fetch();clock=iter([0,20]);monkeypatch.setattr(ny,'monotonic',lambda:next(clock,20))
    result=ny.collect_chunk(source(ny.BKUP),fetch,now=NOW,deadline_at=30)
    assert not result['complete'] and result['checkpoint']['cursor']==0 and result['checkpoint']['manifest_count']==4


def test_expired_checkpoint_refreshes_manifest_instead_of_reusing_old_anchor():
    fetch,calls,_=bk_fetch();state=ny.collect_chunk(source(ny.BKUP),fetch,now=NOW,max_details=1)['checkpoint']
    next_now=NOW+timedelta(hours=5)
    result=ny.collect_chunk(source(ny.BKUP),fetch,now=next_now,checkpoint=state,max_details=1)
    assert result['checkpoint']['started_at']==next_now.isoformat()
    assert calls.count(ny.SOURCES[ny.BKUP][0])==2


def test_complete_socrata_window_uses_typed_native_url_and_overflow_sentinel():
    calls=[]
    def fetch(url,accept):calls.append(url);return json.dumps([park_event()])
    rows,held=ny.collect_with_diagnostics(source(ny.PARKS),fetch,now=NOW)
    assert len(rows)==1 and not held
    assert rows[0]['description']=='Follow every clue.\nBring water and a notebook.'
    assert rows[0]['event_url'].startswith('https://www.nycgovparks.org/events/')
    q=parse_qs(urlsplit(calls[0]).query)
    assert q['$limit']==['501'] and q['$order']==['starttime,guid']
    assert (NOW.astimezone(ZoneInfo(ny.ZONE)).date()+timedelta(days=14)).isoformat() in q['$where'][0]
    with pytest.raises(ValueError,match='record_limit'):
        ny.collect(source(ny.PARKS),lambda *_:json.dumps([park_event()]*501),now=NOW)


def test_citywide_ownership_is_per_event_not_entire_shared_park():
    assert ny._parks_rows(park_event(),NOW)
    for changes in ({'title':"It's My Park at Seth Low Playground"},{'title':'NYRR Open Run: Set Place'},
                    {'guid':'2282507','registration_url':{'url':'https://www.eventbrite.com/e/2003425962986?aff=oddtdtcreator'}}):
        with pytest.raises(ValueError,match='other_source_owns_event'):ny._parks_rows(park_event(**changes),NOW)
    assert ny._parks_rows(park_event(guid='another',registration_url={'url':'https://www.eventbrite.com/e/2003425962986'}),NOW)


def test_missing_foster_point_is_resolved_only_for_reviewed_id_and_exact_entrance_prose():
    item=park_event(guid='2315505',title='Show Rev. T. Wendell Foster Park Your Love!',location='',coordinates='',
                    description='Join the cleanup near the E.164 St. park entrance.')
    row=ny._parks_rows(item,NOW)[0]
    assert row['venue_address']=='40 East 164th Street, Bronx, NY 10452'
    assert 'approximate meeting point' in row['venue_name'] and row['lat']==40.830809
    with pytest.raises(ValueError,match='point_unresolved'):ny._parks_rows({**item,'guid':'different'},NOW)


def test_unknown_private_or_conflicting_park_meeting_is_not_guessed():
    for changes,reason in [({'location':"Randall's Island Park",'description':'Location notified after registration.'},'street_unresolved'),
                           ({'location':'Oak Ridge (in Forest Park)'},'venue_conflict'),
                           ({'coordinates':'40.1,-73.0'},'point_unresolved'),
                           ({'link':{'url':'http://evil.example/events/a'}},'event_link_unresolved')]:
        with pytest.raises(ValueError,match=reason):ny._parks_rows(park_event(**changes),NOW)


def test_cb6_equal_start_end_is_unknown_end_not_fake_duration():
    item=tribe_event(end_date=START.replace(tzinfo=None).isoformat())
    row=ny._tribe_rows(item,NOW)[0]
    assert row['ends_at'] is None
    explicit=ny._tribe_rows({**item,'description':'Complete participation details. Ends 1:00 PM.'},NOW)[0]
    assert datetime.fromisoformat(explicit['ends_at']).astimezone(ZoneInfo(ny.ZONE)).hour==13


def test_cb6_named_venue_without_structured_address_uses_reviewed_place_only():
    row=ny._tribe_rows(tribe_event(title='Old Stone House: Community Workshop',venue=[]),NOW)[0]
    assert row['venue_address']=='336 3rd Street, Brooklyn, NY 11215'
    with pytest.raises(ValueError,match='venue_not_reviewed'):ny._tribe_rows(tribe_event(venue=[]),NOW)
    with pytest.raises(ValueError,match='event_not_public'):ny._tribe_rows(tribe_event(venue={'venue':'Zoom'}),NOW)
    with pytest.raises(ValueError,match='description_missing'):ny._tribe_rows(tribe_event(description=''),NOW)


def test_localist_pagination_must_account_for_complete_declared_total():
    calls=[]
    def fetch(url,accept):
        page=int(parse_qs(urlsplit(url).query)['page'][0]);calls.append(page)
        return json.dumps({'page':{'current':page,'total':2,'total_items':2},'events':[{'event':{'id':page}}]})
    assert len(ny._fordham_manifest(fetch,NOW,None))==2 and calls==[1,2]
    with pytest.raises(ValueError,match='pagination_incomplete'):
        ny._fordham_manifest(lambda *_:json.dumps({'page':{'current':1,'total':1,'total_items':2},'events':[]}),NOW,None)


def test_reviewed_intersections_require_exact_source_name_street_tuple():
    for p in ny.REVIEWED_INTERSECTIONS:
        assert ny.reviewed_venue_location(p['source_key'],p['venue_name'],p['venue_address'])=={'lat':p['lat'],'lng':p['lng']}
        assert ny.reviewed_venue_location('different',p['venue_name'],p['venue_address']) is None
        assert ny.reviewed_venue_location(p['source_key'],p['venue_name'],p['venue_address']+' wrong') is None


def test_profile_and_hosts_are_exact():
    bad=source(ny.PARKS);bad['platform_adapter']='socrata'
    with pytest.raises(ValueError,match='source_unregistered'):ny.collect(bad,lambda *_:pytest.fail('mismatched profile fetched'))
    for url in ['http://www.bkup.nyc/events/a','https://user@www.bkup.nyc/events/a','https://www.bkup.nyc.evil.test/events/a']:
        assert ny.event_url(ny.BKUP,url) is None


def nyrr_page(*, wrong_weekday=False, wrong_point=False):
    p=ny._place(ny.NYRR,'Astoria Park')
    first=(START+timedelta(days=(5-START.weekday())%7)).replace(hour=9)
    last=first+timedelta(days=28)
    native={'@type':'SportsEvent','name':'Astoria Park','eventStatus':'https://schema.org/EventScheduled',
            'startDate':first.isoformat(),'endDate':last.isoformat(),
            'location':{'name':p['native_meeting'],'address':{'addressRegion':'New York'}}}
    direction=p['native_direction'] if not wrong_point else '40.7,-73.7'
    weekday='Sunday' if wrong_weekday else 'Saturday'
    return ('<script type="application/ld+json">'+json.dumps(native)+'</script><main><section>'
            '<p class="_1jjn27a6">Free all-abilities run or walk.</p><p class="_1jjn27a4">'+weekday+'s at 09:00 AM, '
            '<a href="https://www.google.com/maps/dir/Current+Location/'+direction+'">Meeting directions</a></p>'
            '<div class="x2jflr1"><p>Check in with the volunteers and keep all course safety instructions.</p></div>'
            '</section><section><h2>FAQ</h2><p>Children must be accompanied by an adult. Complete waiver requirements.</p></section></main>'),first,last


def test_native_weekly_schedule_is_bounded_and_has_no_invented_end():
    payload,first,last=nyrr_page();url='https://prod.nyrr.org/races-and-events/2026/astoria-park'
    rows=ny._nyrr_detail({'url':url},payload,NOW)
    assert len(rows)==5 and all(r['ends_at'] is None for r in rows)
    assert {datetime.fromisoformat(r['starts_at']).astimezone(ZoneInfo(ny.ZONE)).weekday() for r in rows}=={5}
    assert max(datetime.fromisoformat(r['starts_at']) for r in rows)==last
    assert all('Complete waiver requirements.' in r['description'] for r in rows)


@pytest.mark.parametrize('change,reason',[('wrong_weekday','schedule_conflict'),('wrong_point','venue_conflict')])
def test_recurring_schedule_or_meeting_pin_changes_are_held(change,reason):
    payload,_,_=nyrr_page(**{change:True})
    with pytest.raises(ValueError,match=reason):
        ny._nyrr_detail({'url':'https://prod.nyrr.org/races-and-events/2026/astoria-park'},payload,NOW)


def test_bike_bus_estimate_requires_exact_publisher_link_body_and_clock():
    start=START+timedelta(days=(3-START.weekday())%7);start=start.replace(hour=8)
    item=tribe_event(title='Grown-Up Bike Bus',venue=[],website='https://principlesbk.nyc/upcoming-events',
        description='Weekly group ride from Gowanus to the Upper East Side. Thursdays 8:00 AM.',
        start_date=start.replace(tzinfo=None).isoformat(),end_date=start.replace(tzinfo=None).isoformat())
    row=ny._tribe_rows(item,NOW)[0]
    assert row['venue_address']=='139 9th Street, Brooklyn, NY 11215' and 'approximate meeting point' in row['venue_name']
    assert row['ends_at'] is None
    with pytest.raises(ValueError,match='venue_not_reviewed'):
        ny._tribe_rows({**item,'website':'https://unrelated.example/'},NOW)
    with pytest.raises(ValueError,match='schedule_conflict'):
        ny._tribe_rows({**item,'start_date':start.replace(hour=9,tzinfo=None).isoformat(),'end_date':start.replace(hour=9,tzinfo=None).isoformat()},NOW)


def test_transalt_private_address_cannot_use_reviewed_previous_public_point():
    with pytest.raises(ValueError,match='event_not_public'):
        ny._transalt_rows({'id':783377,'sponsor':{'id':35772},'is_virtual':False,'visibility':'PUBLIC','address_visibility':'PRIVATE','approval_status':'APPROVED'},NOW)
