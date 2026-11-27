from datetime import datetime, timezone

from bs4 import BeautifulSoup

from roomquest import maryland_park_programs as parks, maryland_public_calendars as calendars
from roomquest import preview_worker


NOW = datetime(2026, 11, 8, 10, tzinfo=timezone.utc)


def test_bowie_uses_local_showtimes_and_distinct_occurrences(monkeypatch):
    monkeypatch.setattr(preview_worker, '_future_datetime', lambda value: value.astimezone(timezone.utc))
    page = BeautifulSoup("""
        <script type="application/ld+json">
        {"@type":"Event","name":"The Nutcracker","startDate":"2026-12-05T12:00:00-04:00",
         "eventStatus":"https://schema.org/EventScheduled"}
        </script>
        <div class="gt-item gt-address">15200 Annapolis Rd Bowie, MD 20715 USA</div>
        <div class="gt-content"><span class="gt-date">December 5, 2026 1:00 PM</span> Doors open</div>
        <div class="gt-content"><span class="gt-date">December 5, 2026 2:00 PM</span> Matinee show</div>
        <div class="gt-content"><span class="gt-date">December 5, 2026 6:00 PM</span> Evening performance</div>
    """, 'html.parser')
    rows = calendars._bowie(page, 'https://bowiecenter.org/event/nutcracker/', NOW)
    assert [r['starts_at'] for r in rows] == [
        '2026-12-05T19:00:00+00:00', '2026-12-05T23:00:00+00:00']
    assert rows[0]['id'] != rows[1]['id']
    assert all(r['venue_address'] == '15200 Annapolis Rd, Bowie, MD 20715' and r['lat'] is None for r in rows)
    assert all(r['collector_event_content_v1']['event_id'] == r['id'] for r in rows)
    assert rows[0]['collector_event_content_v1']['facts']['starts_at_local'] == '2026-12-05T14:00:00'


def test_howard_reads_date_and_time_from_separate_sections(monkeypatch):
    monkeypatch.setattr(preview_worker, '_future_datetime', lambda value: value.astimezone(timezone.utc))
    page = BeautifulSoup("""
        <div class="hero--event"><h1>Resilient Earth</h1><span class="hero__date">11/14/2026</span></div>
        <div class="node-split--event"><div class="node-split__sidebar-item-content">
          <span class="time">04:00 PM - 07:00 PM</span>
        </div></div>
        <div class="node--location--department-header-component">
          <div class="title">Robinson Nature Center</div><span class="address-line1">6692 Cedar Ln</span>
          <span class="locality">Columbia</span><span class="administrative-area">MD</span>
          <span class="postal-code">21044</span>
        </div>
    """, 'html.parser')
    [row] = calendars._howard(page, 'https://www.howardcountymd.gov/robinson-nature-center/resilient-earth', NOW)
    assert row['starts_at'] == '2026-11-14T21:00:00+00:00'
    assert row['ends_at'] == '2026-11-15T00:00:00+00:00'
    assert row['venue_name'] == 'Robinson Nature Center'
    assert row['collector_event_content_v1']['facts']['venue_address'] == '6692 Cedar Ln, Columbia, MD 21044'


def _anne_page(title='Winter Nature Walk'):
    return f"""
      <div class="zn-event-w-date">
        <h2><a href="/recreation-parks/events/winter-nature-walk">{title}</a></h2>
        <div class="zn-event-location"><div>
          <span class="zn-location-name">Quiet Waters Park</span>
          <span>600 Quiet Waters Park Rd</span><span>Annapolis</span><span>MD 21403</span>
        </div></div>
        <div class="zn-event-time">
          <time datetime="2026-12-05T10:00:00-05:00"></time>
          <time datetime="2026-12-05T12:00:00-05:00"></time>
        </div>
      </div>
    """


def test_every_maryland_public_parser_attaches_event_owned_original_facts(monkeypatch):
    monkeypatch.setattr(preview_worker, '_future_datetime', lambda value: value.astimezone(timezone.utc))
    anne = calendars._anne(BeautifulSoup(_anne_page(), 'html.parser'),
                           calendars.SOURCES[calendars.ANNE], NOW)
    assert anne[0]['collector_event_content_v1']['facts']['venue_address'] == (
        '600 Quiet Waters Park Rd Annapolis MD 21403')

    umd = BeautifulSoup("""
      <script type="application/ld+json">{
        "@type":"Event", "name":"Community Concert",
        "startDate":"2026-12-06T18:00:00-05:00", "endDate":"2026-12-06T20:00:00-05:00",
        "eventStatus":"https://schema.org/EventScheduled",
        "eventAttendanceMode":"https://schema.org/OfflineEventAttendanceMode",
        "description":"The complete publisher concert narrative.",
        "image":"https://calendar.umd.edu/images/concert.jpg"
      }</script>
      <umd-event-tags><a href="/audience/public">General Public</a></umd-event-tags>
      <umd-event-location><span class="address-title">The Clarice</span><address>
        <span>8270 Alumni Dr</span><span>College Park</span><span>MD 20742</span>
      </address></umd-event-location>
    """, 'html.parser')
    [umd_row] = calendars._umd(umd, 'https://calendar.umd.edu/community-concert', NOW)
    umd_facts = umd_row['collector_event_content_v1']['facts']
    assert umd_facts['description'] == 'The complete publisher concert narrative.'
    assert umd_facts['publisher_categories'] == ['General Public']
    assert umd_facts['source_image_url'] == 'https://calendar.umd.edu/images/concert.jpg'

    montgomery = BeautifulSoup("""
      <script type="application/ld+json">{
        "@type":"Event", "description":"Publisher-owned park program details.",
        "keywords":["Nature", "Family"]
      }</script>
      <main><h1>Owl Prowl</h1>
        <div class="content"><span class="date">Saturday, December 05, 2026</span>
          <span class="time">6:00 PM - 8:00 PM</span></div>
        <div class="content"><strong>Location:</strong>
          <span>Brookside Nature Center</span><span>1400 Glenallan Ave</span>
          <span>Wheaton</span><span>MD 20902</span></div>
      </main>
    """, 'html.parser')
    [montgomery_row] = calendars._montgomery(
        montgomery, 'https://montgomeryparks.org/events/owl-prowl/', NOW)
    montgomery_facts = montgomery_row['collector_event_content_v1']['facts']
    assert montgomery_facts['description'] == 'Publisher-owned park program details.'
    assert montgomery_facts['publisher_categories'] == ['Family', 'Nature']


def test_provider_label_is_not_event_content_or_identity(monkeypatch):
    monkeypatch.setattr(preview_worker, '_future_datetime', lambda value: value.astimezone(timezone.utc))
    source = {'source_key': calendars.ANNE, 'feed_url': calendars.SOURCES[calendars.ANNE],
              'kind': 'html', 'platform_adapter': 'html', 'timezone': calendars.ZONE,
              'publisher_name': 'Original provider label'}
    first = calendars.collect(source, lambda *_: _anne_page(), now=NOW)
    renamed = calendars.collect({**source, 'publisher_name': 'Renamed provider label'},
                                lambda *_: _anne_page(), now=NOW)
    assert first[0]['collector_event_content_v1'] == renamed[0]['collector_event_content_v1']
    assert first[0]['id'] == renamed[0]['id']


def test_event_narrative_change_changes_fingerprint_input_not_occurrence_id(monkeypatch):
    monkeypatch.setattr(preview_worker, '_future_datetime', lambda value: value.astimezone(timezone.utc))

    def bowie(description):
        return BeautifulSoup(f"""
          <script type="application/ld+json">{{"@type":"Event","name":"The Nutcracker",
            "description":"{description}","eventStatus":"https://schema.org/EventScheduled"}}</script>
          <div class="gt-item gt-address">15200 Annapolis Rd Bowie, MD 20715 USA</div>
          <div class="gt-content"><span class="gt-date">December 5, 2026 2:00 PM</span> Matinee show</div>
        """, 'html.parser')

    [original] = calendars._bowie(bowie('Original narrative.'),
                                  'https://bowiecenter.org/event/nutcracker/', NOW)
    [changed] = calendars._bowie(bowie('Corrected narrative.'),
                                 'https://bowiecenter.org/event/nutcracker/', NOW)
    assert original['id'] == changed['id']
    assert original['collector_event_content_v1'] != changed['collector_event_content_v1']


def test_joint_park_pdf_uses_calendar_columns_and_keeps_sites_separate(monkeypatch):
    monkeypatch.setattr(preview_worker, '_future_datetime', lambda value: value.astimezone(timezone.utc))

    def line(*fields, align='left'):
        return ''.join(f'{value:>29}' if align == 'right' else f'{value:29}' for value in fields)

    layout = '\n'.join([
        'November 2026  23222 Georgia Avenue | Brookeville, Maryland 20833',
        line('Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'),
        line('8', '9', '10', '11', '12', '13', '14', align='right'),
        line('Freedman’s State Park', 'Nature Center (10-2):', '', '', '', 'Nature Center Open:'),
        line('Heritage Trail Tour 1 pm', 'Fall Suncatchers', '', '', '', '9am-1pm'),
    ])
    [row] = parks._patuxent(layout, datetime(2026, 11, 1), next(iter(parks.PDFS[parks.PATUXENT])), NOW)
    assert row['starts_at'] == '2026-11-09T15:00:00+00:00'
    assert row['ends_at'] == '2026-11-09T19:00:00+00:00'
    assert row['venue_address'] == '23222 Georgia Avenue, Brookeville, MD 20833'
    assert row['collector_event_content_v1']['event_id'] == row['id']
    assert row['collector_event_content_v1']['facts']['venue_address'] == (
        '23222 Georgia Avenue, Brookeville, Maryland 20833')


def test_patapsco_pdf_retains_publisher_address_before_normalization(monkeypatch):
    monkeypatch.setattr(preview_worker, '_future_datetime', lambda value: value.astimezone(timezone.utc))

    class Page:
        def __init__(self, text):
            self.text = text

        def extract_text(self):
            return self.text

    pages = [Page('cover'), Page("""
      November 9: Nature Hike
      10 a.m. - 12 p.m. at Soldiers Delight Visitor Center
      5100 Deer Park Road, Owings Mills, MD 21117
    """)]
    [row] = parks._patapsco(pages, datetime(2026, 11, 1),
                             next(iter(parks.PDFS[parks.PATAPSCO])), NOW)
    facts = row['collector_event_content_v1']['facts']
    assert facts['venue_name'] == 'Soldiers Delight Visitor Center'
    assert facts['venue_address'] == '5100 Deer Park Road, Owings Mills, MD 21117'
    assert facts['starts_at_local'] == '2026-11-09T10:00:00'


def test_maryland_public_facts_use_v2_preview_contract(monkeypatch):
    source_key = calendars.ANNE
    source = {'source_key': source_key, 'feed_url': calendars.SOURCES[source_key],
              'kind': 'html', 'platform_adapter': 'html', 'timezone': calendars.ZONE}
    calls = {}

    def record_rpc(name, payload):
        calls[name] = payload
        return 0

    monkeypatch.setattr(preview_worker, 'fetch_publisher',
                        lambda *args, **kwargs: '<div class="zn-event-w-date"></div>')
    monkeypatch.setattr(preview_worker, 'supabase_rpc', record_rpc)
    result = preview_worker._process_claimed_source(source)
    assert result['complete'] == 1
    assert calls['community_collector_record_staged_events']['p_events'] == []
    assert set(calls['community_collector_record_preview_v2']) == {
        'p_source_key', 'p_samples', 'p_future_count', 'p_venue_count', 'p_error',
        'p_publisher_crawl_delay_seconds', 'p_publisher_retry_after_seconds', 'p_publisher_wait_unbounded',
    }


def test_normal_path_keeps_original_facts_and_admin_samples_strip_them(monkeypatch):
    source_key = calendars.ANNE
    source = {'source_key': source_key, 'feed_url': calendars.SOURCES[source_key],
              'kind': 'html', 'platform_adapter': 'html', 'timezone': calendars.ZONE}
    calls = {}
    monkeypatch.setattr(preview_worker, '_future_datetime', lambda value: value.astimezone(timezone.utc))
    [row] = calendars._anne(BeautifulSoup(_anne_page(), 'html.parser'),
                            calendars.SOURCES[calendars.ANNE], NOW)
    monkeypatch.setattr(calendars, 'collect', lambda *args, **kwargs: [row])
    monkeypatch.setattr(preview_worker, 'fetch_publisher', lambda *args, **kwargs: _anne_page())
    monkeypatch.setattr(preview_worker, 'supabase_rpc',
                        lambda name, payload: calls.setdefault(name, payload) and 0)
    preview_worker._process_claimed_source(source)
    staged = calls['community_collector_record_staged_events']['p_events']
    samples = calls['community_collector_record_preview_v2']['p_samples']
    assert staged[0]['collector_event_content_v1']['event_id'] == staged[0]['id']
    assert 'collector_event_content_v1' not in samples[0]
