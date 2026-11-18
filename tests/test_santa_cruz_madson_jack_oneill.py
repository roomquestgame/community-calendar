"""Santa Cruz batch 3: Madson Wines and Jack O'Neill guarded publisher fixtures."""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
import json
import pytest
from roomquest import santa_cruz_square_venues as sc, santa_cruz_jack_oneill as jack
from roomquest import preview_worker

NOW=datetime(2026,11,18,17,0,tzinfo=timezone.utc)

def profile(key,module):
    u,kind,adapter=module.SOURCES[key]
    return {'source_key':key,'feed_url':u,'kind':kind,'platform_adapter':adapter,'timezone':module.ZONE}

def madson_event(**kw):
    local=datetime(2026,11,21,17,0,tzinfo=ZoneInfo(sc.ZONE))
    row={
       'id':'628f9dccb18aa0fdf9999999','workflowState':1,
       'title':'SIDEPIECE Sushi Night',
       'startDate':int(local.timestamp()*1000),
       'endDate':int((local+timedelta(hours=2)).timestamp()*1000),
       'body':'<p>Featuring hand rolls from Chefs Adam David and Jeffrey Wall at our tasting room.</p>',
       'excerpt':'Tonight only!',
       'fullUrl':'/events-2/sidepiece-sushi-night-2026',
       'location':{'addressLine1':'328 Ingalls Street, Suite G','markerLat':40.7207559,'markerLng':-74.0007613},
       'assetUrl':'https://images.squarespace-cdn.com/content/v1/60627269ce92a3553c16edf1/1789072676658-V9DDFYDY0IGWKZPJHTY8/sidepiece-flyer-orange-5.5x8.5.png?format=750w',
       'categories':[],
    }
    row.update(kw)
    return row

def madson_payload(events):
    return json.dumps({'upcoming':events,'website':{'timeZone':sc.ZONE},'pagination':{'nextPage':False}})

def jack_card(title='Mark Creech - November 19',link='/live-music/mark-creech',
              text='Mark Creech is a local Santa Cruz guitarist playing classic rock music.'):
    return f'''<div class="card event" data-hash="mark-creech" data-date="11/19/2026 12:00:00 AM">
        <figure class="event-img"><img src="/images/events/images/mark-creech-photo.jpg?01722947296367987"></figure>
        <div class="event-details"><div class="description">
          <h3>{title}</h3><div class="event-info"><p>Nov 19, 2026 | 3:00 PM - 6:00 PM</p></div>
          <div class="toggle-content excerpt"><div class="inner"><p>{text}</p></div></div></div></div>
        <div><a class="btn-lm" href="{link}">Learn More</a></div>
        </div>'''

def jack_detail(title='Mark Creech - November 19',
                text='Mark Creech is a Santa Cruz guitarist with a lively original rock set.'):
    return f'''<div class="event active"><div class="event-details"><div class="description">
     <h3>{title}</h3><div class="event-info"><p>November 19 | 3:00 PM - 6:00 PM</p></div>
     <p>{text}</p></div></div></div>'''

def test_madson_keeps_full_text_and_correct_suite():
    rows=sc.collect(profile(sc.MADSON,sc),lambda u,a:madson_payload([madson_event()]),now=NOW)
    assert len(rows)==1
    assert rows[0]['venue_address']=='328 Ingalls Street, Suite G, Santa Cruz, CA 95060'
    assert 'Featuring hand rolls' in rows[0]['description']
    assert rows[0]['image_url'].endswith('.png')
    assert rows[0]['image_provenance']=='publisher_event_candidates_v1'
    assert rows[0]['lat'] is None  # Squarespace's default NYC pin is untrusted.

def test_madson_holds_offsite_unverified_suite_and_teasers():
    entries=[
      madson_event(location={'addressLine1':'328 Ingalls Street'},id='offsite'),
      madson_event(title='Surf City Stroll',body='Meet us offsite at a local arena',id='other',fullUrl='/events-2/surf-city-stroll'),
      madson_event(title='Private Show',body='',id='empty',fullUrl='/events-2/private-show')
    ]
    assert sc.collect(profile(sc.MADSON,sc),lambda u,a:madson_payload(entries),now=NOW)==[]

def test_madson_enforces_exact_source_host():
    bad=dict(profile(sc.MADSON,sc),feed_url='https://attacker.example.com/api/events')
    with pytest.raises(ValueError,match='unregistered_santa_cruz_square_source'):
        sc.collect(bad,lambda u,a:madson_payload([]),now=NOW)
    assert not sc.event_url(sc.MADSON,'https://other.test/events-2/sushi')
    assert sc.photo_url(sc.MADSON,'https://other.test/image.png') is None

def test_jack_publisher_only_event_identity_and_full_description():
    def fetch(url,accept):
        if url==jack.URL:return jack_card()
        if url=='https://www.jackoneillrestaurant.com/live-music/mark-creech':
            return jack_detail()
        raise AssertionError(url)
    rows=jack.collect(profile(jack.KEY,jack),fetch,now=NOW)
    assert len(rows)==1
    r=rows[0]
    assert r['venue_address']=='175 W Cliff Drive, Santa Cruz, CA 95060'
    assert 'lively original rock set' in r['description']
    assert r['event_url']=='https://www.jackoneillrestaurant.com/live-music/mark-creech'
    assert r['image_url'].endswith('/mark-creech-photo.jpg')
    assert r['timezone']==jack.ZONE

def test_jack_holds_missing_publisher_narrative():
    def fetch(url,accept):
        return jack_card() if url==jack.URL else jack_detail(text='')
    assert jack.collect(profile(jack.KEY,jack),fetch,now=NOW)==[]

def test_jack_does_not_follow_cross_site_detail_links():
    def fetch(url,accept):
        assert url==jack.URL
        return jack_card(link='https://another-domain.test/events/poison')
    assert jack.collect(profile(jack.KEY,jack),fetch,now=NOW)==[]
    assert not jack.event_url('https://another-domain.test/events/poison')
