from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import pytest
from roomquest.preview_worker import preview_source,parse_ics_preview,PreviewError,_process_claimed_source
from roomquest.ics_adapter import parse
START=(datetime.now(timezone.utc)+timedelta(days=2)).strftime('%Y%m%dT%H%M%SZ')
def feed(count=1):
 return 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\n'+''.join(f'BEGIN:VEVENT\r\nUID:event-{i}\r\nSUMMARY:Community workshop\r\nDTSTART:{START}\r\nLOCATION:Actual Hall\\, 12 Main St\\, Raleigh\\, NC\r\nGEO:35.8;-78.6\r\nURL:https://venue.example.org/event/{i}\r\nCATEGORIES:Arts,Community\r\nEND:VEVENT\r\n' for i in range(count))+'END:VCALENDAR\r\n'
def source(key):return dict(source_key=key,platform_adapter='ical',kind='ical',feed_url='https://venue.example.org/calendar.ics')
@pytest.mark.parametrize('key',['municipal_mapsee_fixture','udell_fixture','metro_fixture'])
def test_shared_dispatch_preserves_identity_and_transport(key):
 s=source(key)
 with patch('roomquest.mapsee_adapter.profiles',return_value={key:dict(type='ics',url=s['feed_url'])}),patch('roomquest.preview_worker.fetch_publisher',return_value=feed()) as fetch:
  out=preview_source(s)
 assert out['p_events'][0]['id']=='event-0' and out['p_events'][0]['lat']==35.8
 assert out['p_source_key']==key and out['p_future_count']==1
 assert fetch.call_args.kwargs['respect_robots']==key.startswith('municipal_mapsee_')


def test_reviewed_raleigh_legacy_ics_checks_publisher_and_keeps_description():
    key = "municipal_78278a6e98fb935c1bade8f8"
    reviewed = {**source(key), "feed_url": "https://unitedarts.org/events/?ical=1"}
    raw = feed().replace("SUMMARY:", "DESCRIPTION:Make a creation.\r\nSUMMARY:")
    with patch("roomquest.preview_worker.fetch_publisher", return_value=raw) as fetch:
        out = preview_source(reviewed)
        with pytest.raises(PreviewError, match="unregistered_raleigh_catalog_ics"):
            preview_source(source(key))
    fetch.assert_called_once()
    assert fetch.call_args.kwargs["respect_robots"] is True
    assert fetch.call_args.kwargs["allowed_hosts"] == ("unitedarts.org",)
    assert out["p_events"][0]["description"] == "Make a creation."


def test_raleigh_udell_catalog_uses_bounded_publisher_transport():
    key = "municipal_3eaa90140971d6aa8fd09832"
    reviewed = {**source(key), "feed_url": "https://events.ackland.org/events/?ical=1"}
    with patch("roomquest.preview_worker.fetch_publisher", return_value=feed()) as fetch:
        assert preview_source(reviewed)["p_future_count"] == 1
        with pytest.raises(PreviewError, match="unregistered_raleigh_catalog_ics"):
            preview_source(source(key))
    fetch.assert_called_once()
    assert fetch.call_args.kwargs["respect_robots"] is True
    assert fetch.call_args.kwargs["allowed_hosts"] == ("events.ackland.org",)


DUKE_KEY = 'municipal_f8b341508884150709031005'
DUKE_FEED = 'https://calendar.duke.edu/events/index.ics?gf[]=Duke+Arts&future_days=90'


def legacy_url_feed(event_url=None):
    """Synthetic publisher fields; no live Duke feed request is needed."""
    url_property = '' if event_url is None else 'URL:' + event_url + '\r\n'
    return feed().replace('URL:https://venue.example.org/event/0\r\n', url_property).replace(
        'END:VEVENT', 'IMAGE:https://venue.example.org/fixture.jpg\r\n'
        'DESCRIPTION:Fixture narrative remains on the existing legacy path.\r\nEND:VEVENT')


@pytest.fixture
def offline_ics_transport(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError('ICS regression attempted live network access')
    monkeypatch.setattr('socket.getaddrinfo', forbidden)
    monkeypatch.setattr('urllib.request.urlopen', forbidden)
    monkeypatch.setattr('requests.sessions.Session.request', forbidden)


@pytest.mark.usefixtures('offline_ics_transport')
@pytest.mark.parametrize('event_url', [None, '', '   ', 'http://venue.example.org/event/0',
                                      'https://calendar.duke.edu/show?fq=id:fixture'])
def test_duke_dispatch_falls_back_only_for_missing_or_rejected_event_url(event_url):
    raw = legacy_url_feed(event_url)
    expected = parse_ics_preview(raw, allow_ongoing=True, include_images=True)
    expected[0]['event_url'] = expected[0]['event_url'] or DUKE_FEED
    reviewed = {**source(DUKE_KEY), 'feed_url': DUKE_FEED}
    with patch('roomquest.preview_worker.fetch_publisher', return_value=raw) as fetch:
        out = preview_source(reviewed)
    # Equality preserves identity, times, venue, category and image; it also
    # catches accidentally enabling the legacy description/address rewrites.
    assert out['p_events'] == out['p_samples'] == expected
    assert out['p_error'] is None and out['p_future_count'] == 1
    assert expected[0]['image_url'] == 'https://venue.example.org/fixture.jpg'
    assert 'description' not in out['p_events'][0]
    fetch.assert_called_once()
    assert fetch.call_args.args == (DUKE_FEED, 'text/calendar')
    assert fetch.call_args.kwargs['respect_robots'] is True
    assert fetch.call_args.kwargs['allowed_hosts'] == ('calendar.duke.edu',)
    assert fetch.call_args.kwargs['deadline_at'] is not None


@pytest.mark.usefixtures('offline_ics_transport')
@pytest.mark.parametrize('legacy', [False, True])
def test_shared_ics_url_fallback_uses_the_actual_feed_for_both_paths(legacy):
    result = parse(legacy_url_feed(), {'url': DUKE_FEED}, legacy=legacy)
    assert result[0]['event_url'] == DUKE_FEED
    assert result[0]['id'] == 'event-0'


@pytest.mark.usefixtures('offline_ics_transport')
@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('fallback', [None, '', '   ', 42,
    'http://calendar.duke.edu/events/index.ics', 'https://127.0.0.1/events.ics',
    'https://fixture@calendar.duke.edu/events/index.ics'])
def test_missing_event_url_rejects_an_unusable_feed_fallback(legacy, fallback):
    with pytest.raises(ValueError, match='^invalid_source_url$'):
        parse(legacy_url_feed(), {'url': fallback}, legacy=legacy)


@pytest.mark.usefixtures('offline_ics_transport')
@pytest.mark.parametrize('event_url', [None, ''])
def test_duke_stages_the_feed_fallback_before_recording_success_and_pacing(event_url):
    from roomquest.publisher_pacing import observe_crawl_delay, observe_retry_after
    raw = legacy_url_feed(event_url)
    calls = []
    def fetch(*_args, **_kwargs):
        observe_crawl_delay(2.1)
        observe_retry_after('60')
        return raw
    def rpc(name, payload):
        calls.append((name, payload))
        return len(payload.get('p_events', []))
    with patch('roomquest.preview_worker.fetch_publisher', side_effect=fetch), \
            patch('roomquest.preview_worker.supabase_rpc', side_effect=rpc):
        result = _process_claimed_source({**source(DUKE_KEY), 'feed_url': DUKE_FEED})
    assert result == {'complete': 1, 'failed': 0, 'staged': 1}
    assert [name for name, _ in calls] == [
        'community_collector_record_staged_events', 'community_collector_record_preview_v2']
    assert calls[0][1]['p_events'][0]['event_url'] == DUKE_FEED
    recorded = calls[1][1]
    assert recorded['p_error'] is None and recorded['p_future_count'] == 1
    assert recorded['p_publisher_crawl_delay_seconds'] == 3
    assert recorded['p_publisher_retry_after_seconds'] == 60
    assert recorded['p_publisher_wait_unbounded'] is False


@pytest.mark.usefixtures('offline_ics_transport')
@pytest.mark.parametrize('fallback', ['', 'https://127.0.0.1/events.ics'])
def test_invalid_feed_fallback_cannot_stage_or_record_success(fallback):
    # Isolate parser validation even when a transport fixture returns a body.
    # The production transport independently rejects this URL before fetching.
    with patch('roomquest.preview_worker.fetch_publisher', return_value=legacy_url_feed()), \
            patch('roomquest.preview_worker.supabase_rpc') as rpc:
        result = _process_claimed_source({**source('udell_fixture'), 'feed_url': fallback})
    assert result['complete'] == 0 and result['failed'] == 1 and result['staged'] == 0
    assert result['error_code'] == 'invalid_source_url'
    rpc.assert_called_once()
    assert rpc.call_args.args[0] == 'community_collector_record_preview_v2'
    assert rpc.call_args.args[1]['p_error'] == 'invalid_source_url'


@pytest.mark.parametrize('legacy',[False,True])
def test_large_feed_fails_instead_of_truncating(legacy):
 with pytest.raises(ValueError,match='source_record_limit'):parse(feed(501),{'url':'https://venue.example.org/calendar.ics'},legacy=legacy)
@pytest.mark.parametrize('legacy',[False,True])
def test_empty_and_invalid_are_distinct(legacy):
 assert parse('BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n',{},legacy=legacy)==[]
 with pytest.raises(ValueError):parse('<html>unavailable</html>',{},legacy=legacy)
def test_legacy_cache_media_and_category_fields_preserved():
 assert parse(feed(),{},legacy=True)==parse_ics_preview(feed(),allow_ongoing=True,include_images=True)
@pytest.mark.parametrize('legacy',[False,True])
def test_date_only_is_not_false_empty(legacy):
 raw=feed().replace('DTSTART:'+START,'DTSTART;VALUE=DATE:'+(datetime.now(timezone.utc)+timedelta(days=2)).strftime('%Y%m%d'))
 with pytest.raises(ValueError,match='unsupported_all_day_time'):parse(raw,{},legacy=legacy)
def test_failed_checkpoint_stays_failed():
 with patch('roomquest.preview_worker.fetch_publisher',return_value=feed(101)),patch('roomquest.preview_worker.supabase_rpc',side_effect=[100,PreviewError('database_unavailable'),None]) as rpc:
  result=_process_claimed_source(source('udell_fixture'))
 assert result['failed']==1 and result['complete']==0
 assert rpc.call_args.args[1]['p_error']=='database_unavailable'


def test_publisher_categories_are_preserved_as_individual_labels():
    events = parse(feed(), {}, legacy=False)
    assert len(events) == 1
    assert events[0]["publisher_categories"] == ["Arts", "Community"]
    assert events[0]["category"] == "Arts, Community"


def test_missing_publisher_categories_remain_empty_not_inferred():
    events = parse(feed().replace('CATEGORIES:Arts,Community' + chr(13) + chr(10), ''), {}, legacy=False)
    assert events[0]["publisher_categories"] == []
    assert events[0]["category"] == ""


def test_ics_description_survives_normalization():
    raw = feed().replace('SUMMARY:Community workshop',
                         'DESCRIPTION:Make a creation\\nBring your family.\r\nSUMMARY:Community workshop')
    event = parse(raw, {}, legacy=False, include_description=True)[0]
    assert event['description'] == 'Make a creation\nBring your family.'
    assert event['id'] == 'event-0'
    assert event['event_url'] == 'https://venue.example.org/event/0'


def test_ics_missing_description_is_not_fabricated():
    assert parse(feed(), {}, legacy=False, include_description=True)[0]['description'] == ''


def test_independence_dispatch_retains_publisher_description():
    s = source('independence_ia_library_family')
    raw = feed().replace('SUMMARY:Community workshop',
                         'DESCRIPTION:Build with library bricks. https://venue.example.org/calendar.aspx?EID=event-0\r\nSUMMARY:Community workshop')
    with patch('roomquest.preview_worker.fetch_publisher', return_value=raw), patch('roomquest.iowa_civicplus.enrich', side_effect=lambda r,*args:r):
        out = preview_source(s)
    assert out['p_events'][0]['description'].startswith('Build with library bricks.')


def test_civicplus_detail_links_require_same_publisher_explicit_matching_id():
    from roomquest.ics_adapter import civicplus_detail_url
    origin = 'https://independenceia.gov/calendar.ics'
    good = 'https://independenceia.gov/calendar.aspx?EID=5975'
    assert civicplus_detail_url('Summary ' + good, '5975', origin) == good
    for bad in [good.replace('5975', '12'), good.replace('independenceia.gov', 'elsewhere.gov'),
                good.replace('/calendar.aspx', '/other'), good + '&tracking=1']:
        assert civicplus_detail_url(bad, '5975', origin) is None


def test_independence_actual_capture_full_details_and_explicit_all_day_exclusion(caplog):
    from pathlib import Path
    from roomquest.iowa_civicplus import KEY, FEED
    from zoneinfo import ZoneInfo
    path = Path(__file__).parent / 'fixtures' / 'iowa'
    local = (datetime.now(timezone.utc) + timedelta(days=2)).astimezone(ZoneInfo('America/Chicago')).replace(hour=18,minute=0,second=0,microsecond=0)
    raw = (path/'independence-library.ics').read_text().replace('20261116',local.strftime('%Y%m%d'))
    raw = raw.replace('20261019',(local-timedelta(days=10)).strftime('%Y%m%d')).replace('20261106',(local+timedelta(days=1)).strftime('%Y%m%d'))
    detail = (path/'independence-lego.html').read_text().replace('2026-11-16T18:00:00',local.replace(tzinfo=None).isoformat())
    with patch('roomquest.preview_worker.fetch_publisher', side_effect=[
            raw, detail]):
        result = preview_source(dict(source_key=KEY, feed_url=FEED, kind='ical', platform_adapter='ical'))
    assert result['p_future_count'] == 1
    event = result['p_events'][0]
    assert event['event_url'] == 'https://independenceia.gov/calendar.aspx?EID=5975'
    assert event['starts_at'] == local.astimezone(timezone.utc).isoformat()
    assert event['ends_at'] == (local+timedelta(hours=1)).astimezone(timezone.utc).isoformat()
    assert event['venue_address'] == '805 1st St East, Independence, IA 50644'
    assert event['venue_name'] == 'Public Library > Community Room'
    assert 'No registration needed.' in event['description']
    assert event['lat'] is None and event['lng'] is None
    assert 'uid=5956 reason=unsupported_all_day_time' in caplog.text


def test_independence_detail_cancellation_is_withheld():
    from pathlib import Path
    from roomquest.iowa_civicplus import enrich, KEY, FEED
    path = Path(__file__).parent/'fixtures'/'iowa'
    detail = (path/'independence-lego.html').read_text().replace('Join us in the Community Room', 'This event is cancelled. Join us in the Community Room')
    records = [{'id':'5975','title':'Legos @ the Library','description':'Lego activity.',
                'starts_at':'2026-11-17T00:00:00+00:00',
                'event_url':'https://independenceia.gov/calendar.aspx?EID=5975'}]
    with patch('roomquest.preview_worker.fetch_publisher', return_value=detail) as fetch:
        assert enrich(records, {'source_key':KEY,'feed_url':FEED}, fetch, float('inf')) == []


def test_independence_keeps_feed_summary_if_detail_has_no_description(caplog):
    from pathlib import Path
    from bs4 import BeautifulSoup
    from roomquest.iowa_civicplus import enrich, KEY, FEED

    path = Path(__file__).parent / 'fixtures' / 'iowa'
    detail = BeautifulSoup((path/'independence-lego.html').read_text(), 'html.parser')
    detail.select_one('[itemprop="description"]').decompose()
    record = {'id': '5975', 'title': 'Legos @ the Library', 'description': 'Lego activity.',
              'starts_at': '2026-11-17T00:00:00+00:00',
              'event_url': 'https://independenceia.gov/calendar.aspx?EID=5975'}
    event, = enrich([record], {'source_key': KEY, 'feed_url': FEED},
                    lambda *args, **kwargs: str(detail), float('inf'))
    assert event['description'] == 'Lego activity.'
    assert event['venue_address'] == '805 1st St East, Independence, IA 50644'
    assert 'field=description reason=missing' in caplog.text
