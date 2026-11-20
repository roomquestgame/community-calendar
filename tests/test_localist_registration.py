from datetime import datetime, timedelta, timezone
import json
import pytest
from roomquest.feed_registration import classify
from roomquest.localist_registration import collect, endpoint

BASE = 'https://example.edu/api/2/events'
URL = BASE + '?venue_id=24'
PAGE = '<script src="https://localist-images.azureedge.net/packs/js/application.js"></script>'
BADGE = '<ul id="share-buttons" class="em-list-buttons-business_24"></ul>'


def response(page=1, total=1, item=10, venue=24, private=False):
    start = (datetime.now(timezone.utc) + timedelta(days=item)).replace(microsecond=0)
    event = {'id': 2,'localist_url':'https://example.edu/event/dance','title':'Dance','venue_id':venue,
             'location_name':'Auditorium','room_number':'Hall A','private':private,'rejected':False,
             'publish_status':'published','status':'live','description_text':'Publisher description.',
             'geo':{'latitude':36.13,'longitude':-80.27},
             'event_instances':[{'event_instance':{'id':item,'event_id':2,'start':start.isoformat(),'all_day':False}}]}
    return json.dumps({'page':{'current':page,'total':total,'total_items':total},'events':[{'event':event}]})


def test_root_and_venue_are_distinct_and_scope_evidence_is_required():
    assert classify('https://example.edu/', PAGE)['p_endpoint'] == BASE
    assert classify('https://example.edu/auditorium', PAGE+BADGE)['p_endpoint'] == URL
    assert classify('https://example.edu/auditorium', PAGE)['p_outcome'] == 'review'
    assert classify('https://example.edu/?group=choir', PAGE)['p_reason'] == 'localist_filter_unverified'
    assert classify(BASE+'/2', response())['p_reason'] == 'single_event_page'
    assert classify(URL+'&page=2', response())['p_reason'] == 'localist_filter_unverified'
    assert endpoint(URL+'&page=1') == URL


def test_paging_and_occurrence_identity_preserve_scope():
    fetched=[]
    def fetch(url, accept):
        fetched.append(url)
        page=len(fetched)
        return response(page,2,10+page)
    rows=collect(URL,fetch)
    assert all(url.startswith(URL+'&days=60&pp=50&page=') for url in fetched)
    assert [r['id'] for r in rows] == ['11','12']
    assert rows[0]['description'] and rows[0]['lat'] == 36.13
    with pytest.raises(ValueError,match='localist_venue_filter_mismatch'):
        collect(URL,lambda *_: response(venue=9))
    with pytest.raises(ValueError,match='pagination_limit'):
        collect(URL,lambda *_: response(total=25))
    with pytest.raises(ValueError,match='invalid_localist_pagination'):
        collect(URL,lambda *_: response(total=2))
    assert collect(URL,lambda *_: response(private=True)) == []
