from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
import xml.etree.ElementTree as ET
import pytest
from roomquest.reviewed_chambers import SOURCES, collect
from roomquest.chambermaster import collect as shared_collect

NOW=datetime(2026,11,6,12,tzinfo=timezone.utc)
ROOT=Path(__file__).parent/'fixtures/batch2'

def source(key):
    return {'source_key':key,'feed_url':SOURCES[key][0],'timezone':'America/Chicago',
            'kind':'xml','platform_adapter':'growthzone'}

@pytest.fixture(autouse=True)
def clock(monkeypatch):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr('roomquest.reviewed_chambers.datetime', FrozenDateTime)
    monkeypatch.setattr('roomquest.preview_worker._future_datetime',lambda value: value.astimezone(timezone.utc) if isinstance(value,datetime) and value.tzinfo else None)

@pytest.mark.parametrize('key,file',[(k,f) for k,f in zip(SOURCES,['bellevue','clear-lake'])])
def test_real_public_xml_uses_own_record_facts_without_inherited_occurrences(key,file):
    rows=collect(source(key),(ROOT/(file+'.xml')).read_text(),now=NOW)
    assert rows
    assert all(r['description'] and r['venue_address'] and r['lat'] is None for r in rows)
    assert all(r['image_extractor_version']=='publisher_event_candidates_v1' for r in rows)
    assert not any('Exhibition:' in r['title'] or 'Operation Holiday Cheer' in r['title'] for r in rows)
    assert all(not r['publisher_categories'] for r in rows)  # numeric IDs are not labels
    if file=='bellevue':
        thai=next(r for r in rows if r['id']=='2874')
        assert thai['starts_at']=='2026-11-11T16:30:00+00:00'
        assert not thai.get('image_url')  # Google search thumbnails are not event photos
        assert not any('Veterans Day Parade' in r['title'] for r in rows)  # locality missing
        assert next(r for r in rows if r['id']=='2873')['image_url'].startswith('https://cdn.firespring.com/')

def test_no_public_flag_or_missing_locality_never_inherits_city_or_venue():
    key=next(iter(SOURCES));root=ET.parse(ROOT/'bellevue.xml').getroot()
    event=next(e for e in root if e.findtext('EventID')=='2874')
    event.find('VisibilityFlags').text='ChamberInternal MemberOnly'
    isolated=ET.Element('ArrayOfEventDisplay');isolated.append(event)
    assert collect(source(key),ET.tostring(isolated),now=NOW)==[]
    event.find('VisibilityFlags').text='Public'
    event.find('LocationDesc').text='Jaruwan Thai Cuisine 11796 S 25th St'
    assert collect(source(key),ET.tostring(isolated),now=NOW)==[]
    with pytest.raises(ValueError,match='unregistered'):
        collect({**source(key),'feed_url':'https://unrelated.example/api/events'},ET.tostring(root),now=NOW)

def test_reviewed_shared_dispatch_does_not_fetch_per_record_ics(monkeypatch):
    key=next(iter(SOURCES))
    def nofetch(*args,**kwargs):raise AssertionError('unexpected detail network request')
    assert shared_collect(source(key),(ROOT/'bellevue.xml').read_text(),monotonic()+30,fetcher=nofetch)

def test_preview_stages_every_reviewed_occurrence_across_the_old_hundred_row_boundary(monkeypatch):
    import copy
    from roomquest.preview_worker import preview_source
    key=next(iter(SOURCES));root=ET.parse(ROOT/'bellevue.xml').getroot()
    event=next(e for e in root if e.findtext('EventID')=='2874')
    exported=ET.Element('ArrayOfEventDisplay')
    for n in range(120):
        item=copy.deepcopy(event);item.find('EventID').text=str(9000+n)
        item.find('Slug').text='public-event-'+str(9000+n);exported.append(item)
    monkeypatch.setattr('roomquest.preview_worker.fetch_publisher',lambda *a,**kw: ET.tostring(exported))
    output=preview_source(source(key),deadline_at=monotonic()+40)
    assert output['p_future_count']==120
    assert len(output['p_events'])==120
    assert output['p_parser_capability']=='publisher_event_candidates_v1'


def test_export_default_end_is_unknown_and_continuous_display_is_not_a_timed_session():
    key=next(iter(SOURCES));root=ET.parse(ROOT/'bellevue.xml').getroot()
    event=next(e for e in root if e.findtext('EventID')=='2874')
    isolated=ET.Element('ArrayOfEventDisplay');isolated.append(event)
    event.find('EndDate').text='2026-11-11T23:55:00'
    assert collect(source(key),ET.tostring(isolated),now=NOW)[0]['ends_at'] is None
    event.find('EndDate').text='2026-11-30T23:55:00'
    assert collect(source(key),ET.tostring(isolated),now=NOW)==[]


def test_actual_addresses_have_resolver_delimiters_and_keep_suite_in_publisher_evidence():
    key=next(iter(SOURCES))
    rows=collect(source(key),(ROOT/'bellevue.xml').read_text(),now=NOW)
    thai=next(r for r in rows if r['id']=='2874')
    assert thai['venue_address']=='11796 S 25th St, Bellevue, NE 68123'
    together=next(r for r in rows if r['id']=='2873')
    assert together['venue_address']=='1001 Ft Crook Rd. N., Bellevue, NE'
    assert 'Suite 248' in together['publisher_details']['meeting_location']
    assert '6805' not in together['venue_address']  # never invent the missing ZIP digit
    assert thai['venue_city']=='Bellevue'


def test_valid_but_shared_resolver_unsupported_plaza_address_is_held():
    key=next(iter(SOURCES))
    rows=collect(source(key),(ROOT/'bellevue.xml').read_text(),now=NOW)
    assert not any(r['id']=='2902' for r in rows)


def test_surf_label_requires_own_publisher_domain_and_complete_address():
    key='municipal_chambermaster_clear_lake_ia'
    root=ET.parse(ROOT/'clear-lake.xml').getroot()
    event=next(e for e in root if e.findtext('URL')=='http://surfballroom.com'
               and '460 N Shore Drive' in (e.findtext('LocationDesc') or ''))
    isolated=ET.Element('ArrayOfEventDisplay');isolated.append(event)
    row=collect(source(key),ET.tostring(isolated),now=NOW)[0]
    assert row['venue_name']=='Surf Ballroom & Museum'
    assert '460 N Shore Drive' in row['publisher_details']['meeting_location']
    identity=(row['id'],row['starts_at'],row['ends_at'],row['venue_address'])
    event.find('URL').text='https://surfballroom.com.unrelated.example/'
    other=collect(source(key),ET.tostring(isolated),now=NOW)[0]
    assert other['venue_name']==other['venue_address']
    assert identity==(other['id'],other['starts_at'],other['ends_at'],other['venue_address'])
    event.find('URL').text='http://surfballroom.com'
    event.find('LocationDesc').text='461 N Shore Drive, Clear Lake, Iowa, 50428'
    assert collect(source(key),ET.tostring(isolated),now=NOW)[0]['venue_name']!='Surf Ballroom & Museum'
