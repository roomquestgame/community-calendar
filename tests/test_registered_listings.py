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
