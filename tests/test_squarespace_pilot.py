import copy
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch

import pytest
from roomquest.squarespace import SOURCES, parse
from roomquest.preview_worker import PreviewError, preview_source

FRAZIER, MISSION = SOURCES


def payload(url=FRAZIER):
    start = datetime.now(timezone.utc) + timedelta(days=2)
    start = start.replace(hour=18, minute=0, second=0, microsecond=0)
    location = ({'addressTitle': 'Fixture Hall', 'addressLine1': '829 West Main Street',
                 'addressLine2': 'Louisville, KY, 40202', 'markerLat': 38.2579, 'markerLng': -85.7645}
                if url == FRAZIER else
                {'addressTitle': 'Fixture Garden', 'addressLine1': '946 W Mission Ln',
                 'addressLine2': 'Tucson, AZ, 85745', 'markerLat': 32.2142, 'markerLng': -110.9864})
    event = {'id': 'fixture1', 'title': 'Fixture &amp; Event', 'workflowState': 1,
             'startDate': start.timestamp()*1000, 'endDate': (start+timedelta(hours=1)).timestamp()*1000,
             'fullUrl': url.split('?')[0].split('.org')[-1]+'/fixture' if url == FRAZIER else '/events/fixture',
             'location': location, 'categories': []}
    return {'website': {'timeZone': SOURCES[url]['timezone']}, 'upcoming': [event], 'past': []}


@pytest.mark.parametrize('url', SOURCES)
def test_selected_sources_preserve_factual_fields(url):
    data=payload(url)
    [row]=parse(json.dumps(data), {'feed_url':url})
    assert row['id']=='fixture1' and row['title']=='Fixture & Event'
    assert row['lat']==data['upcoming'][0]['location']['markerLat']
    assert row['starts_at'].endswith('+00:00') and row['ends_at']>row['starts_at']
    assert 'image_url' not in row and 'description' not in row


def test_offsite_venue_full_state_name_is_not_replaced_by_museum():
    data=payload();data['upcoming'][0]['location'].update(addressTitle='Offsite Hall',
        addressLine1='1121 East Washington Street',addressLine2='Louisville, Kentucky, 40206',markerLng=-85.7305)
    [row]=parse(json.dumps(data),{'feed_url':FRAZIER})
    assert row['venue_name']=='Offsite Hall' and row['lng']==-85.7305


def test_conflicting_and_missing_geo_are_held_without_default_pin():
    data=payload();data['upcoming'][0]['location'].update(markerLat=40.7207559,markerLng=-74.0007613)
    [row]=parse(json.dumps(data),{'feed_url':FRAZIER})
    assert row['lat'] is row['lng'] is None and '829 West Main Street' in row['venue_address']


def test_past_archive_cursor_is_checked_but_not_fetched():
    data=payload();past=copy.deepcopy(data['upcoming'][0])
    past.update(publishOn=1000,endDate=2000);data['past']=[past]
    data['pagination']={'nextPage':True,'nextPageOffset':1000}
    assert len(parse(json.dumps(data),{'feed_url':FRAZIER}))==1
    data['pagination']['nextPageOffset']=3000
    with pytest.raises(ValueError,match='pagination_requires_review'):
        parse(json.dumps(data),{'feed_url':FRAZIER})


def test_changed_timezone_or_unknown_source_fails():
    data=payload();data['website']['timeZone']='UTC'
    with pytest.raises(ValueError,match='publisher_timezone_changed'):parse(json.dumps(data),{'feed_url':FRAZIER})
    with pytest.raises(ValueError,match='unregistered'):parse(json.dumps(data),{'feed_url':'https://waimeavalley.net/events?format=json'})


def test_unapproved_source_is_rejected_before_network():
    with patch('roomquest.preview_worker.fetch_publisher') as fetch:
        with pytest.raises(PreviewError,match='unregistered_squarespace_source'):
            preview_source({'platform_adapter':'squarespace','feed_url':'https://avondalebrewing.com/calendar-tickets?format=json'})
        fetch.assert_not_called()


def test_existing_protected_transport_and_private_staging_shape():
    with patch('roomquest.preview_worker.fetch_publisher',return_value=json.dumps(payload())) as fetch:
        result=preview_source({'source_key':'municipal_fixture','platform_adapter':'squarespace','feed_url':FRAZIER},deadline_at=9999999999)
    assert fetch.call_args.kwargs=={'respect_robots':True,'deadline_at':9999999999}
    assert result['p_future_count']==result['p_venue_count']==len(result['p_events'])==1


def test_cancelled_unpublished_all_day_and_outside_window_are_excluded():
    data=payload();e=data['upcoming'][0]
    for change in [{'cancelled':True},{'workflowState':0},{'allDay':True},
                   {'startDate':1000,'endDate':2000},
                   {'startDate':(datetime.now(timezone.utc)+timedelta(days=90)).timestamp()*1000,
                    'endDate':(datetime.now(timezone.utc)+timedelta(days=91)).timestamp()*1000}]:
        data['upcoming']=[{**e,**change}]
        assert parse(json.dumps(data),{'feed_url':FRAZIER})==[]


def test_bad_identity_time_link_and_conflicting_occurrences_fail():
    for change,reason in [({'id':''},'identity'),({'endDate':0},'end'),
                          ({'startDate':True},'time'),({'fullUrl':'//evil.example/event'},'link')]:
        data=payload();data['upcoming'][0].update(change)
        with pytest.raises(ValueError,match=reason):parse(json.dumps(data),{'feed_url':FRAZIER})
    data=payload();data['upcoming'].append({**data['upcoming'][0],'title':'Conflicting title'})
    with pytest.raises(ValueError,match='conflicting'):parse(json.dumps(data),{'feed_url':FRAZIER})
    data=payload();data['upcoming']*=101
    with pytest.raises(ValueError,match='source_record_limit'):parse(json.dumps(data),{'feed_url':FRAZIER})
