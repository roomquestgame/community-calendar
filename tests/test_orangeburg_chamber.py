"""Synthetic ChamberMaster pilot fixtures; no publisher/network dependency."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from xml.etree import ElementTree as ET

import pytest
from roomquest.preview_worker import parse_growthzone_preview, PreviewError
from scrapers.growthzone import KNOWN_SITES

SOURCE = {'feed_url': KNOWN_SITES['orangeburgchamber']['api_url'],
          'timezone': 'America/New_York'}


def payload(slug='farmers-market', status='APPROVED', all_day='false', event_id='7490'):
    start = (datetime.now(ZoneInfo(SOURCE['timezone'])) + timedelta(days=2)).replace(tzinfo=None, microsecond=0)
    root = ET.Element('ArrayOfEventDisplay')
    event = ET.SubElement(root, 'EventDisplay')
    for key, value in {'EventID': event_id, 'Name': 'Fixture Market', 'Slug': slug,
                       'Status': status, 'IsAllDayEvent': all_day,
                       'StartDate': start.isoformat(),
                       'EndDate': (start + timedelta(hours=2)).isoformat()}.items():
        ET.SubElement(event, key).text = value
    return ET.tostring(root, encoding='unicode'), start


def test_identity_link_timezone_and_no_fabricated_venue():
    xml, start = payload()
    [row] = parse_growthzone_preview(xml, SOURCE)
    assert row['id'] == '7490'
    assert row['event_url'] == 'https://business.orangeburgchamber.com/events/details/farmers-market-7490'
    assert datetime.fromisoformat(row['starts_at']) == start.replace(tzinfo=ZoneInfo(SOURCE['timezone']))
    assert row['venue_name'] == '' and row['venue_address'] == ''
    assert row['lat'] is None and row['lng'] is None
    assert row['reason'] == 'missing_verified_venue_geo'


@pytest.mark.parametrize('slug,ending', [('market-7490', 'market-7490'),
                                          ('market-11-05-2026', 'market-11-05-2026-7490')])
def test_numeric_suffix_does_not_confuse_year_and_event_id(slug, ending):
    xml, _ = payload(slug=slug)
    assert parse_growthzone_preview(xml, SOURCE)[0]['event_url'].endswith('/' + ending)


@pytest.mark.parametrize('fields', [{'status': 'CANCELLED'}, {'status': 'PENDING'},
                                    {'all_day': 'true'}, {'event_id': ''},
                                    {'event_id': '../secret'}, {'slug': ''}])
def test_unusable_event_is_not_published_as_timed_public_event(fields):
    xml, _ = payload(**fields)
    assert parse_growthzone_preview(xml, SOURCE) == []


def test_wrong_payload_is_failure_rather_than_successful_empty():
    with pytest.raises(PreviewError, match='not_growthzone_events_api'):
        parse_growthzone_preview('<html/>', SOURCE)


def test_invalid_xml_reports_safe_failure():
    with pytest.raises(PreviewError, match='invalid_calendar_payload'):
        parse_growthzone_preview('<ArrayOfEventDisplay>', SOURCE)


def test_explicit_offset_is_preserved():
    xml, _ = payload()
    root = ET.fromstring(xml)
    start = datetime.now(ZoneInfo('UTC')) + timedelta(days=2)
    root.find('EventDisplay/StartDate').text = start.isoformat()
    root.find('EventDisplay/EndDate').text = (start+timedelta(hours=2)).isoformat()
    [row] = parse_growthzone_preview(ET.tostring(root, encoding='unicode'), SOURCE)
    assert datetime.fromisoformat(row['starts_at']) == start


def test_ics_enrichment_keeps_precise_address_and_rejects_wrong_event():
    from roomquest.chambermaster import collect
    from time import monotonic
    xml, start = payload()
    source = {**SOURCE, 'source_key':'municipal_chambermaster_fixture'}
    stamp = start.replace(tzinfo=ZoneInfo(SOURCE['timezone'])).astimezone(ZoneInfo('UTC')).strftime('%Y%m%dT%H%M%SZ')
    ics = ('BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:e.3204.7490\n'
           'SUMMARY:Fixture Market\nDTSTART:'+stamp+'\n'
           'LOCATION:Fixture Center 1437 Example Street Orangeburg SC 29115\n'
           'END:VEVENT\nEND:VCALENDAR')
    calls=[]
    def fetcher(url, accept, **kwargs):
        calls.append(url)
        return ics
    [row] = collect(source, xml, monotonic()+10, fetcher)
    assert row['venue_address'] == 'Fixture Center 1437 Example Street Orangeburg SC 29115'
    assert row['lat'] is None and row['lng'] is None
    assert calls == ['https://business.orangeburgchamber.com/events/addtocalendar/farmers-market-7490?format=ICal']
    with pytest.raises(PreviewError,match='chambermaster_detail_identity'):
        collect(source, xml, monotonic()+10, lambda *a,**k:ics.replace('7490','9999'))


def test_collection_limits_fail_instead_of_silently_truncating():
    from roomquest.chambermaster import collect
    from time import monotonic
    from unittest.mock import patch
    source = {**SOURCE,'source_key':'municipal_chambermaster_fixture'}
    with patch('roomquest.chambermaster.parse_growthzone_preview', return_value=[{}]*21):
        with pytest.raises(PreviewError, match='chambermaster_detail_limit'):
            collect(source,'',monotonic()+5)


def test_manual_endpoint_auth_and_no_public_url_input():
    from api.chambermaster import handler
    from unittest.mock import Mock, patch
    import os
    h=object.__new__(handler)
    h.path='/api/chambermaster';h.headers={};h.chambermaster_reply=Mock()
    with patch('api.chambermaster.collect_batch') as batch:
        handler.do_GET(h)
        batch.assert_not_called()
        h.chambermaster_reply.assert_called_with(200,{'service':'chambermaster','mode':'registered_sources_only'})
        handler.do_POST(h)
        batch.assert_not_called()
        h.chambermaster_reply.assert_called_with(401,{'error':'unauthorized'})
        with patch.dict(os.environ,{'ROOMQUEST_PREVIEW_SECRET':'secret'}):
            h.headers={'Authorization':'Bearer secret','Content-Length':'20'}
            handler.do_POST(h)
            batch.assert_not_called()
            h.chambermaster_reply.assert_called_with(400,{'error':'unexpected_body'})
            h.headers={'Authorization':'Bearer secret','Content-Length':'0'}
            batch.return_value={'claimed':0}
            handler.do_POST(h)
            batch.assert_called_once_with()
            h.chambermaster_reply.assert_called_with(200,{'claimed':0})
