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
