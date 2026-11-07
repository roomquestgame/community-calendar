import copy
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import pytest
from roomquest.waterloo import parse_hits, collect, KEY, FEED, API_HOST
from roomquest.publisher_evidence import family, image_url

NOW=datetime(2026,11,6,12,tzinfo=timezone.utc)
SOURCE={'source_key':KEY,'feed_url':FEED,'kind':'html','platform_adapter':'html','timezone':'America/Chicago'}

@pytest.fixture
def payload():
    return json.loads((Path(__file__).parent/'fixtures/batch2/waterloo-index.json').read_text())

@pytest.fixture(autouse=True)
def fixture_clock(monkeypatch):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr('roomquest.waterloo.datetime', FrozenDateTime)
    monkeypatch.setattr('roomquest.preview_worker._future_datetime',lambda value: value.astimezone(timezone.utc) if isinstance(value,datetime) and value.tzinfo else None)

def test_actual_snapshot_keeps_narrative_categories_streets_and_unverified_photo_candidates(payload):
    rows=parse_hits(payload['hits'],now=NOW)
    assert len(rows)==13
    story=next(r for r in rows if 'Storytime' in r['title'])
    assert datetime.fromisoformat(story['starts_at']) == datetime(2026,11,7,15,30,tzinfo=timezone.utc)
    assert all(r['description'] and r['venue_address'] and r['lat'] is None and r['lng'] is None for r in rows)
    assert all(family(KEY,r['event_url'])=='waterloo' for r in rows)
    assert not any('Lights the Night' in r['title'] or 'Frozen' in r['title'] for r in rows)
    assert all(r['publisher_categories'] for r in rows)
    assert all('?' not in r['image_url'] for r in rows if r.get('image_url'))
    assert any('Storytime' in r['title'] and '503 South Street' in r['venue_address'] for r in rows)

def test_unsafe_images_stay_absent_and_unsafe_identities_fail_closed(payload):
    assert image_url('https://unrelated.example/photo.jpg','waterloo') is None
    assert image_url('https://waterloo-ia.s3.amazonaws.com/images/a.jpg?redirect=https://evil.example','waterloo') is None
    assert image_url('https://waterloo-ia.s3.amazonaws.com/images/a.jpg?v=123','waterloo')=='https://waterloo-ia.s3.amazonaws.com/images/a.jpg'
    good=next(x for x in payload['hits'] if x['id']==1209841)
    broken=copy.deepcopy(good);broken['uri']='//unrelated.example/event/'
    with pytest.raises(ValueError,match='identity_changed'):parse_hits([broken],now=NOW)

def test_api_pagination_must_complete_and_rebuilds_only_reviewed_index(payload):
    calls=[]
    def fetch(url,accept):
        calls.append(url)
        if url==FEED:
            info={'appId':'EYQHJ2IY2M','index':'prod-experience-waterloo-listings','apiKey':'a'*32}
            return "<div data-listings data-info='"+json.dumps(info)+"' data-config='"+json.dumps({'filters':'calendarName:"Default Calendar"'})+"'></div>"
        assert urlsplit(url).hostname==API_HOST
        assert parse_qs(urlsplit(url).query)['page']==['0']
        return json.dumps(payload)
    assert collect(SOURCE,fetch)
    assert len(calls)==2
    with pytest.raises(ValueError,match='unregistered'):
        collect({**SOURCE,'feed_url':'https://unrelated.example/events/'},fetch)

def test_duplicate_conflicts_and_unbounded_result_sets_are_not_partial_success(payload):
    good=next(x for x in payload['hits'] if x['id']==1209841)
    modified={**good,'title':'Changed title'}
    with pytest.raises(ValueError,match='conflicting'):parse_hits([good,modified],now=NOW)
    with pytest.raises(ValueError,match='record_limit'):parse_hits([good]*501,now=NOW)


def test_publisher_address_padding_does_not_change_the_geocoder_identity(payload):
    padded=next(e for e in payload['hits'] if e['id']==1209841)
    clean=copy.deepcopy(padded)
    clean['address']=[value.strip() for value in clean['address']]
    a=parse_hits([padded],now=NOW)[0]
    b=parse_hits([clean],now=NOW)[0]
    assert a['venue_address']==b['venue_address']=='503 South Street, Waterloo, ia 50701'
    assert a['id']==b['id'] and a['starts_at']==b['starts_at']
