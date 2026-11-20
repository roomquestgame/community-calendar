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
