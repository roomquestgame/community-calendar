from datetime import datetime, timedelta

from roomquest import registered_listings as listings
from roomquest.jsonld_adapter import parse
import json


def test_rooms_and_duplicate_cards():
    date = (datetime.now(listings.EASTERN) + timedelta(days=2)).strftime('%B %d, %Y')
    card = ('<div class="tessera-show-card" data-fulldate="' + date + '" data-venue="Broadway Comedy Club">'
            '<a href="' + listings.BROADWAY + 'shows/one/"><h3 class="card-title">Matinee</h3></a>'
            '<div class="tessera-venue">Red Room</div><div class="tessera-showTimes">Show 2PM</div></div>')
    body = '<footer><span>318 W. 53rd St<br>New York, NY 10019</span></footer>' + card * 2
    rows = listings.collect({'feed_url':listings.BROADWAY,'source_key':listings.source_key(listings.BROADWAY)},
                            lambda *_: body)
    assert len(rows) == 1 and rows[0]['venue_name'].endswith('Red Room')


def test_full_postal_address_in_street_field():
    event = {'@type':'Event','name':'Workshop','url':'https://example.org/studio/class',
             'startDate':(datetime.now(listings.EASTERN)+timedelta(days=3)).isoformat(),
             'location':{'name':'Studio','address':{'streetAddress':'101 Masons Ln, Leesburg, VA 20175, USA',
                'addressLocality':'Leesburg','addressRegion':'VA','postalCode':'20175'}}}
    assert parse(json.dumps(event))[0]['venue_address'] == '101 Masons Ln, Leesburg, VA 20175'


def test_lynchburg_uses_first_party_activity_cards_not_webtrac_checkout():
    day = (datetime.now(listings.EASTERN) + timedelta(days=2)).strftime('%m/%d/%Y')
    body = f'''<body class="archive post-type-archive post-type-archive-cl_and_activ">
      <div class="pna-item"><h6 class="pna-title"><a href="{listings.LYNCHBURG}class-one/">Class One</a></h6>
        <div class="pna-location">Miller Center</div><span class="pna-dates">{day} -</span>
        <span class="pna-times">Start: 11:00 AM</span>
        <a href="https://cityweb.myvscloud.com/webtrac/web/search.html?keyword=class">Register</a></div>
      <div class="pna-item"><h6 class="pna-title"><a href="{listings.LYNCHBURG}unknown/">No Clock</a></h6>
        <div class="pna-location">City Armory</div><span class="pna-dates">{day} -</span>
        <span class="pna-times">Start: Varies</span></div></body>'''
    rows = listings.collect(
        {'feed_url': listings.LYNCHBURG, 'source_key': listings.source_key(listings.LYNCHBURG)},
        lambda *_: body)
    assert len(rows) == 1
    assert rows[0]['title'] == 'Class One'
    assert rows[0]['venue_name'] == 'Miller Center'
    assert rows[0]['venue_address'] == '301 Grove Street, Lynchburg, VA 24501'
    assert rows[0]['event_url'] == listings.LYNCHBURG + 'class-one/'


def test_lynchburg_requires_exact_publisher_template():
    body = '<body><div class="pna-item"></div></body>'
    try:
        listings.collect(
            {'feed_url': listings.LYNCHBURG, 'source_key': listings.source_key(listings.LYNCHBURG)},
            lambda *_: body)
    except ValueError as exc:
        assert str(exc) == 'lynchburg_activity_archive_changed'
    else:
        raise AssertionError('unproved template was accepted')


def test_state_theatre_uses_real_calendar_and_detail_show_time(monkeypatch):
    day = (datetime.now(listings.EASTERN) + timedelta(days=2)).date()
    month = day.strftime('%B %Y')
    calendar = f'''<body class="page-calendar"><div class="goo_calendar_container goo_calendar_active" data-post_id="19186">
      <table class="goo_table_scheduler"><tr><th class="goo_month_name">{month}</th></tr><tr>
      <td class="goo_TD"><span class="scheduler_heading">{day.day:02d}</span>
        <div class="cal-entry-headliner"><a href="https://statetheatreportland.com/events/show-one/">
          <span class="goo_cal_link" data-post_id="20858" data-calendar_id="19186">Show One</span></a></div>
      </td></tr></table></div></body>'''
    detail = f'''<article class="tm_event type-tm_event"><div class="edp-view-details vevent">
      <h1 class="headliners summary">Show One</h1><h2 class="edp-dates">{day.strftime('%a, %B')} {day.day}, {day.year}</h2>
      <h2 class="venue location">State Theatre</h2><h2 class="edp-times">Doors: 7:00pm - Show: 8:00pm - all ages</h2></div>
      <img class="wp-post-image" src="https://statetheatreportland.com/media/show.jpg"></article>
      <div class="edp-bio-content">A complete first-party event description.</div>'''

    rows = listings.collect(
        {'feed_url': listings.STATE_THEATRE, 'source_key': listings.source_key(listings.STATE_THEATRE)},
        lambda url, _accept: calendar if url == listings.STATE_THEATRE else detail)
    assert len(rows) == 1
    assert rows[0]['title'] == 'Show One'
    assert rows[0]['venue_address'] == '609 Congress Street, Portland, ME 04101'
    assert datetime.fromisoformat(rows[0]['starts_at']).astimezone(listings.EASTERN).hour == 20
    assert rows[0]['image_url'] == 'https://statetheatreportland.com/media/show.jpg'


def test_state_theatre_refuses_partial_snapshot_when_detail_changes():
    day = (datetime.now(listings.EASTERN) + timedelta(days=2)).date()
    calendar = f'''<body class="page-calendar"><div class="goo_calendar_container goo_calendar_active" data-post_id="19186">
      <table class="goo_table_scheduler"><th class="goo_month_name">{day.strftime('%B %Y')}</th>
      <td class="goo_TD"><span class="scheduler_heading">{day.day}</span><div class="cal-entry-headliner">
      <a href="https://statetheatreportland.com/events/changed/"><span class="goo_cal_link" data-post_id="1" data-calendar_id="19186">Changed</span></a>
      </div></td></table></div></body>'''
    try:
        listings.collect(
            {'feed_url': listings.STATE_THEATRE, 'source_key': listings.source_key(listings.STATE_THEATRE)},
            lambda url, _accept: calendar if url == listings.STATE_THEATRE else '<article class="tm_event type-tm_event"></article>')
    except ValueError as exc:
        assert str(exc) == 'state_theatre_event_detail_changed'
    else:
        raise AssertionError('partial snapshot was accepted')
