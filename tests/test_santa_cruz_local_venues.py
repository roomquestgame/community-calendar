"""Santa Cruz local venue contracts: identity, venue, full prose and clocks."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import json
import pytest

from roomquest import santa_cruz_local_venues as sc
from roomquest import preview_worker
from roomquest.preview_worker import PreviewError

NOW=datetime(2026,11,18,15,0,tzinfo=timezone.utc)

@pytest.fixture(autouse=True)
def fixed_preview(monkeypatch):
    monkeypatch.setattr(preview_worker,'_future_datetime',
                        lambda value:value.astimezone(timezone.utc))

def source(key=sc.WOODHOUSE):
    url,kind,adapter=sc.SOURCES[key]
    return {'source_key':key,'feed_url':url,'kind':kind,
            'platform_adapter':adapter,'timezone':sc.ZONE}

def woodhouse_item(**changes):
    start=datetime(2026,11,28,19,0,tzinfo=ZoneInfo(sc.ZONE))
    item={'title':'China Cats','start':int(start.timestamp()*1000),
        'end':int((start+timedelta(hours=3)).timestamp()*1000),
        'url':'https://minnow-cowbell-xynk.squarespace.com/events/2025/11/29/china-cats-2plsr',
        'body':'The China Cats are a popular live Grateful Dead tribute band with regular shows.',
        'excerpt':'A brief teaser',
        'categories':[],
        'image':'https://images.squarespace-cdn.com/content/v1/5b823724f93fd456200b626e/1793212187742-VDQSBZJWP1SA7IOY4OBD/Foster.jpg?format=750w'}
    item.update(changes)
    return item

def discretion_html():
    return """<div class="event-detail" id="loop-item-detail-9314">
    <img class="gallery-main" src="https://www.discretionbrewing.com/wp-content/uploads/2026/10/neil-bradley.jpg"/>
    <h3>Neil Bradley</h3><p class="event-date">Thurs. 11/19/26</p>
    <div class="detail-description"><p>5:30-7:30pm</p>
    <p>The band plays blues and country originals live, with audience dancing.</p></div></div>
    <div class="event-detail" id="loop-item-detail-9315">
    <h3>Taproom Closed</h3><p class="event-date">11/23/26</p>
    <div class="detail-description"><p>5:30-7:30pm</p><p>Closed for staff training</p></div></div>
    <div class="event-detail" id="loop-item-detail-9316">
    <h3>A Taste of Soquel</h3><p class="event-date">11/22/26</p>
    <div class="detail-description"><p>12:00-4:00pm</p>
    <p>Find us at 4951 Soquel Drive for this offsite event.</p></div></div>"""

def test_registration_requires_exact_publisher():
    for change in ({'feed_url':'https://example.com/events'},
                   {'timezone':'America/New_York'},
                   {'kind':'ical'}):
        with pytest.raises(ValueError,match='unregistered_santa_cruz_local_source'):
            sc.collect(dict(source(),**change),lambda *args:'{}',now=NOW)
    assert sc.event_url(sc.WOODHOUSE,woodhouse_item()['url'])
    assert not sc.event_url(sc.WOODHOUSE,'https://example.com/events/2026/11/29/other')
    assert sc.event_url(sc.DISCRETION,'https://www.discretionbrewing.com/events/#loop-item-detail-9314')

def test_woodhouse_keeps_full_body_and_unresized_image_candidate():
    item=woodhouse_item(body='An evening of original musicians playing together. '*70)
    rows=sc.collect(source(),lambda url,accept:json.dumps({'events':[item]}),now=NOW)
    assert len(rows)==1
    row=rows[0]
    assert len(row['description'])>2000
    assert '<' not in row['description']
    assert row['venue_address']=='119 Madrone St, Santa Cruz, CA 95060'
    assert row['image_url'].endswith('/Foster.jpg')
    assert row['image_provenance']=='publisher_event_candidates_v1'

def test_woodhouse_skips_empty_excerpt_only_and_other_venues():
    result=sc.collect(source(),lambda u,a:json.dumps({'events':[
      woodhouse_item(body='',excerpt='Read more for description'),
      woodhouse_item(title='Offsite Event',body='Offsite at a second venue',
                     url='https://minnow-cowbell-xynk.squarespace.com/events/2026/11/19/offsite-event')
    ]}),now=NOW)
    assert result==[]

def test_discretion_card_date_and_detailed_prose():
    rows=sc.collect(source(sc.DISCRETION),
        lambda url,accept:discretion_html(),now=NOW)
    assert len(rows)==1
    row=rows[0]
    assert row['title']=='Neil Bradley'
    assert row['venue_address']=='2703 41st Ave Ste A, Soquel, CA 95073'
    assert 'The band plays blues' in row['description']
    assert '5:30-7:30pm' not in row['description']
    assert row['event_url'].endswith('#loop-item-detail-9314')
    assert row['image_url'].endswith('/neil-bradley.jpg')

def test_time_parsing_uses_venue_timezone_no_guessed_dates():
    start,end=sc.schedule('Thurs. 11/19/26','5:30-7:30pm')
    assert (start.astimezone(ZoneInfo(sc.ZONE)).hour,
            end.astimezone(ZoneInfo(sc.ZONE)).hour)==(17,19)
    start,end=sc.schedule('Sat. 11/21/26','11:00am-1:00pm')
    assert (start.astimezone(ZoneInfo(sc.ZONE)).hour,
            end.astimezone(ZoneInfo(sc.ZONE)).hour)==(11,13)
    assert sc.schedule('Date TBC','tba') is None
    assert sc.schedule('11/22/26','music sometime') is None

def test_photo_rejects_unknown_host_and_tiny_source():
    good='https://www.discretionbrewing.com/wp-content/uploads/2026/10/neil-bradley.jpg'
    assert sc.photo_url(sc.DISCRETION,good)==good
    assert sc.photo_url(sc.DISCRETION,good+'?resize=100') is None
    assert sc.photo_url(sc.WOODHOUSE,'https://other.example.com/something.jpg') is None

def test_worker_completeness_and_source_dispatch(monkeypatch):
    def fake(url,accept,**kw):
        assert kw['respect_robots'] is True
        assert kw['allowed_hosts']==('www.woodhousebrews.com',)
        return json.dumps({'events':[woodhouse_item()]})
    monkeypatch.setattr(preview_worker,'fetch_publisher',fake)
    result=preview_worker.preview_source(source())
    assert result['p_future_count']==1 and result['p_events'][0]['description']
    monkeypatch.setattr(sc,'collect',
                        lambda *args,**kwargs:[{'description':'','venue_address':'x'}])
    with pytest.raises(PreviewError,match='santa_cruz_local_incomplete_event'):
        preview_worker.preview_source(source())
