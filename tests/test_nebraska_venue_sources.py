from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from roomquest import hurrdat_calendar as hurrdat
from roomquest import nebraska_venues as venues
from roomquest import preview_worker
from roomquest.preview_worker import preview_source


def source(key, *, publisher_name='Original provider label'):
    html = key in venues.SOURCES
    return dict(source_key=key, feed_url=venues.SOURCES.get(key, hurrdat.URL),
                kind='html' if html else 'json', platform_adapter='html' if html else 'wordpress',
                timezone=venues.ZONE, publisher_name=publisher_name)


def page(url, html):
    return f'<link rel="canonical" href="{url}">{html}'


def test_pint_uses_visible_time_and_verified_suite():
    day = datetime.now(ZoneInfo(venues.ZONE)).date() + timedelta(days=3)
    payload = page(venues.SOURCES[venues.PINT], f"""
    <article class="eventlist-event--upcoming">
      <a class="eventlist-title-link" href="/events/opaque-bingo-slug">Brewery Bingo</a>
      <time class="event-date" datetime="{day}"></time>
      <time class="event-time-localized-start" datetime="{day}">7:00 PM</time>
      <time class="event-time-localized-end" datetime="{day}">8:00 PM</time>
      <li class="eventlist-meta-address">Pint Nine Brewing Company
        <a href="http://maps.google.com?q=10411 Portal Road Ste 104 La Vista, Nebraska, 68128">(map)</a>
      </li>
      <div class="eventlist-description">Play music bingo with friends.</div>
    </article>""")
    with patch('roomquest.preview_worker.fetch_publisher', return_value=payload) as fetch:
        result = preview_source(source(venues.PINT))
    assert fetch.call_args.args[0] == venues.SOURCES[venues.PINT]
    assert fetch.call_args.kwargs['respect_robots']
    row, = result['p_events']
    assert row['venue_address'] == venues.VENUES[venues.PINT][1]
    assert row['lat'] is row['lng'] is None
    assert datetime.fromisoformat(row['starts_at']).astimezone(ZoneInfo(venues.ZONE)).hour == 19
    facts = row['collector_event_content_v1']['facts']
    assert facts['description'] == 'Play music bingo with friends.'
    assert facts['venue_address'] == venues.VENUES[venues.PINT][1]


def test_kros_filters_omaha_and_checks_la_vista_detail():
    day = datetime.now(ZoneInfo(venues.ZONE)).date() + timedelta(days=3)
    root = venues.SOURCES[venues.KROS]
    detail = root + 'run-club/'
    cards = ''.join(f"""<div class="section_home_upcoming_event_item">
      <a href="{detail}"><h4>Run Club</h4></a>
      <p class="date">{day:%A, %B %d, %Y}</p><p class="time">5:00 pm</p>
      <h5 class="location">{location}</h5></div>""" for location in ('La Vista', 'Downtown'))
    pages = {
        root: page(root, f'<div class="section_events_archive_wrapper"><div class="section_home_upcoming_events">{cards}</div></div>'),
        detail: page(detail, f"""<div class="single_event_wrapper"><h2>Run Club</h2>
          <h5 class="date">{day:%B %d, %Y}</h5><h5 class="time">5:00 pm - 7:00 pm</h5>
          <h5 class="location">La Vista</h5><div class="rte">Join a group run.</div></div>"""),
    }
    result = venues.collect(source(venues.KROS), lambda url, accept: pages[url])
    row, = result
    assert row['description'] == 'Join a group run.'
    assert row['venue_address'] == venues.VENUES[venues.KROS][1]
    facts = row['collector_event_content_v1']['facts']
    assert facts['venue_city'] == 'La Vista'
    assert 'venue_name' not in facts and 'venue_address' not in facts


def test_frosty_uses_explicit_open_nights_and_skips_closed_ones():
    day = datetime.now(ZoneInfo(venues.ZONE)).date() + timedelta(days=3)
    following = day + timedelta(days=1)
    url = venues.SOURCES[venues.FROSTY]
    payload = page(url, f"""<h1>Falconwood Frosty Nights {day.year} Hours &amp; Dates</h1>
      <p>905 Allied Road</p><h2>All 2 nights</h2><div class="fn-nights"><div class="month"><ul>
      <li><span>{day:%a, %b %d}</span><b>5 PM to 10 PM</b></li>
      <li><span>{following:%a, %b %d}<span class="note">Closed</span></span><b>5 PM to 9 PM</b></li>
      </ul></div></div>""")
    row, = venues.collect(source(venues.FROSTY), lambda *_: payload)
    assert row['id'] == day.isoformat()
    assert row['venue_address'] == venues.VENUES[venues.FROSTY][1]
    assert row['collector_event_content_v1']['facts']['venue_address'] == venues.VENUES[venues.FROSTY][1]


def test_provider_label_does_not_change_pint_content_or_identity():
    day = datetime.now(ZoneInfo(venues.ZONE)).date() + timedelta(days=3)
    payload = page(venues.SOURCES[venues.PINT], f"""
    <article class="eventlist-event--upcoming">
      <a class="eventlist-title-link" href="/events/opaque-bingo-slug">Brewery Bingo</a>
      <time class="event-date" datetime="{day}"></time>
      <time class="event-time-localized-start" datetime="{day}">7:00 PM</time>
      <time class="event-time-localized-end" datetime="{day}">8:00 PM</time>
      <li class="eventlist-meta-address">Pint Nine Brewing Company
        <a href="http://maps.google.com?q=10411 Portal Road Ste 104 La Vista, Nebraska, 68128">(map)</a>
      </li><div class="eventlist-description">Play music bingo with friends.</div>
    </article>""")
    [first] = venues.collect(source(venues.PINT), lambda *_: payload)
    [renamed] = venues.collect(source(venues.PINT, publisher_name='Renamed provider label'),
                              lambda *_: payload)
    assert first['id'] == renamed['id']
    assert first['collector_event_content_v1'] == renamed['collector_event_content_v1']


def test_narrative_edit_changes_nebraska_venue_input_not_occurrence_id():
    start = datetime.now(ZoneInfo(venues.ZONE)).replace(microsecond=0) + timedelta(days=2)
    first = venues._row(venues.KROS, 'Run Club', start, None,
                        'https://krosstrainbrewing.com/events/run-club/', '/events/run-club/',
                        'Join a group run.', raw_city='La Vista')
    changed = venues._row(venues.KROS, 'Run Club', start, None,
                          'https://krosstrainbrewing.com/events/run-club/', '/events/run-club/',
                          'Bring reflective gear for the group run.', raw_city='La Vista')
    assert first['id'] == changed['id']
    assert first['collector_event_content_v1'] != changed['collector_event_content_v1']


def test_normal_path_keeps_nebraska_facts_and_admin_sample_strips(monkeypatch):
    start = datetime.now(ZoneInfo(venues.ZONE)).replace(microsecond=0) + timedelta(days=2)
    row = venues._row(venues.KROS, 'Run Club', start, None,
                      'https://krosstrainbrewing.com/events/run-club/', '/events/run-club/',
                      'Join a group run.', raw_city='La Vista')
    calls = {}
    monkeypatch.setattr(venues, 'collect', lambda *args, **kwargs: [row])
    monkeypatch.setattr(preview_worker, 'fetch_publisher', lambda *args, **kwargs: '')
    monkeypatch.setattr(preview_worker, 'supabase_rpc',
                        lambda name, payload: calls.setdefault(name, payload) and 0)
    preview_worker._process_claimed_source(source(venues.KROS))
    staged = calls['community_collector_record_staged_events']['p_events']
    samples = calls['community_collector_record_preview_v3']['p_samples']
    assert staged[0]['collector_event_content_v1']['event_id'] == staged[0]['id']
    assert 'collector_event_content_v1' not in samples[0]


def test_hurrdat_requires_la_vista_venue_and_publisher_time():
    start = datetime.now(ZoneInfo(venues.ZONE)).replace(microsecond=0) + timedelta(days=2)
    end = start + timedelta(hours=2)
    venue = dict(venue='Hurrdat Sports Bar & Grill – La Vista', address='12744 Westport Pkwy',
                 city='Omaha', state='NE', zip='68138', geo_lat=1, geo_lng=2)
    item = dict(id=1, title='Trivia Night', status='publish', timezone=venues.ZONE,
                url='https://hurrdatsportsbar.com/event/trivia-night/', venue=venue,
                start_date=start.replace(tzinfo=None).isoformat(),
                end_date=end.replace(tzinfo=None).isoformat(),
                utc_start_date=start.astimezone(timezone.utc).isoformat(),
                utc_end_date=end.astimezone(timezone.utc).isoformat())
    events = [item, dict(item, id=2, venue={**venue, 'city': 'Lincoln'}), dict(item, id=3, status='private')]
    row, = hurrdat.review({'events': events})['events']
    assert row['venue']['city'] == 'La Vista'
    assert row['venue']['geo_lat'] is None
