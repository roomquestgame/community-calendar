"""Native Boston narratives, explicit schedules and complete-only checkpoints."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from html import escape
import json
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event
import pytest

from roomquest import boston_community_additional as b, boston_sources

NOW = datetime.now(timezone.utc)
START = (NOW + timedelta(days=7)).astimezone(ZoneInfo(b.ZONE)).replace(hour=10, minute=0, second=0, microsecond=0)


def source(key):
    url, kind, adapter = b.SOURCES[key]
    return dict(source_key=key, feed_url=url, kind=kind, platform_adapter=adapter, timezone=b.ZONE)


def track(index=0, *, body=None, native_address='285 Newbury Street, Boston, MA',
          venue='The Trackhouse', summary='An inclusive community run.'):
    start = START + timedelta(days=index)
    title = f'Community morning run {index}'
    url = f'https://www.tracksmith.com/events/community-run-{index}'
    card = dict(url=url, title=title, day_label=start.strftime('%-d %b'), clock='10am')
    schema = {'@type': 'Event', 'name': title, 'startDate': str(start.date()), 'endDate': str(start.date()),
        'description': summary, 'location': {'name': venue, 'address': {'name': native_address}}}
    html = (f'<link rel="canonical" href="{url}"><h1 class="event-page__title">{title}</h1>'
        f'<script type="application/ld+json">{json.dumps(schema)}</script><div class="event-page__content">'
        + (body if body is not None else '<p>Join the friendly run leaders for a guided route around Boston.</p>') + '</div>')
    return card, html


def parkour(*, title='Community parkour jam', start=START, end=None, body=None,
            venue='The Dojo @ Somernova', street='15 Properzi Way, Somerville, MA 02143', url=None):
    end = end or start + timedelta(hours=2)
    url = url or 'https://pkgenboston.com/local-events/community-jam'
    utc_start, utc_end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    card = dict(url=url, title=title, start=utc_start.isoformat(), end=utc_end.isoformat(), venue=venue, location=street)
    google = 'https://www.google.com/calendar/event?' + urlencode(dict(action='TEMPLATE', ctz=b.ZONE, text=title,
        dates=f'{utc_start:%Y%m%dT%H%M%SZ}/{utc_end:%Y%m%dT%H%M%SZ}', location=street))
    html = (f'<meta property="og:url" content="{url}"><article class="eventitem">'
        f'<h1 class="eventitem-title">{title}</h1><a class="eventitem-meta-export-google" href="{escape(google)}">Calendar</a>'
        f'<span class="eventitem-meta-address-line--title">{venue}</span>'
        '<div class="eventitem-column-content"><div class="sqs-layout">'
        + (body if body is not None else '<p>Learn playful movement skills together with the local community.</p>')
        + '</div></div></article>')
    return card, html


def trustees(*, url='https://thetrustees.org/event/123456/', start=START, body=None):
    title = 'Community garden workshop'
    card = dict(url=url, title=title)
    end = start + timedelta(hours=1, minutes=30)
    html = (f'<div class="event-text__when"><p>{start:%A, %B %d, %Y}<br>'
        f'{start:%I:%M%p}–{end:%I:%M%p}</p></div>'
        '<div class="event-text__location"><p>City Natives<br>30 Edgewater Drive<br>Mattapan, MA 02126</p></div>'
        f'<div class="event-text__column-right wysiwyg"><h4>About {title}</h4>'
        + (body if body is not None else '<p>Prepare native seeds with the community gardeners and learn propagation.</p>')
        + '<div class="event-text__social">Share this event</div></div>')
    return card, html


def rock(*, title='Public climbing workshop', body=None, book=True, location='95', day=None):
    day = day or START.date()
    card = {'url': b.SOURCES[b.ROCKSPOT][0] + '?day=' + str(day), 'title': 'Public schedule', 'day': str(day)}
    html = (f'<select id="location-select"><option selected value="{location}">South Boston, MA</option></select>'
        f'<form method="get"><input name="day" value="{day}"></form>'
        f'<div class="card capitan-card"><div class="card-header">{day:%A, %B %d, %Y}</div>'
        f'<div class="card-body"><span class="d-block">{title}</span><span class="d-block">10am - 12pm</span>'
        '<a class="show-event-details" data-eventpartid="742">Details</a>'
        + ('<a href="/rockspot/schedule/event/42/select-num-participants/">Book</a>' if book else '')
        + '<div id="event-details-742"><div class="mt-2">'
        + (body if body is not None else '<p>Our instructor teaches climbing techniques to every ability level.</p>')
        + '</div></div></div></div>')
    return card, html


def harbor(*, body=None, basic=True):
    url = 'https://www.eventbrite.com/e/community-history-walk-tickets-123456789'
    card = {'url': url, 'title': 'Boston Harbor Now official calendar event'}
    point = (42.3686156, -71.0554974)
    schema = {'@type': 'Event', 'name': 'Community history walk', 'url': url,
        'startDate': START.isoformat(), 'endDate': (START + timedelta(hours=2)).isoformat(),
        'description': 'Short teaser.', 'organizer': {'url': 'https://www.eventbrite.com/o/harbor-11882374432'},
        'location': {'name': 'Bocce Ball Courts', 'address': {'streetAddress': '523 Commercial Street, Boston, MA 02109'}}}
    location = {'name': 'Bocce Ball Courts', 'address': {'latitude': point[0], 'longitude': point[1]}}
    context = {'basicInfo': {'venue': location, 'url': url, 'id': '123456789', 'isProtected': False, 'isListed': True, 'isOnline': False, 'status': 'live', 'hideStartDate': False, 'hideEndDate': False, 'isParentEvent': False, 'isSeries': False, 'startDate': {'utc': START.isoformat()}, 'endDate': {'utc': (START + timedelta(hours=2)).isoformat()}}} if basic else {'recommendations': [location]}
    html = (f'<script type="application/ld+json">{json.dumps(schema)}</script>'
        f'<script id="__NEXT_DATA__">{json.dumps({"props": {"pageProps": {"context": context}}})}</script>'
        f'<meta property="event:location:latitude" content="{point[0]}">'
        f'<meta property="event:location:longitude" content="{point[1]}">'
        '<div class="Overview-module__summary">'
        + (body if body is not None else '<p>Meet at 423 Commercial Street between Langone and Puopolo parks for the history tour.</p>') + '</div>')
    return card, html


def test_registered_source_contract_and_external_links_are_narrow():
    for key in b.SOURCES:
        assert boston_sources.validate_source(source(key)) is b
        with pytest.raises(ValueError, match='unregistered'):
            b.collect({**source(key), 'feed_url': b.SOURCES[key][0] + '/other'},
                      lambda *args: pytest.fail('profile must be rejected before fetch'))
    url = 'https://pkgenboston.sites.zenplanner.com/event.cfm?eventId=' + next(iter(b.HOLIDAY_SESSIONS))
    assert b.event_url(b.PARKOUR, url)
    assert not b.event_url(b.PARKOUR, url + '&other=1')
    assert not b.event_url(b.PARKOUR, url.replace('eventId=', 'eventId=unapproved-'))
    assert not b.event_url(b.HARBOR, url)


def test_full_body_limit_and_no_title_fallback():
    text = 'Native narrative and access instructions. ' * 100
    card, html = track(body=f'<p>{text}</p>')
    row = b._tracksmith_detail(card, html, NOW, [])[0]
    assert row['description'] == text.strip() and len(row['description']) > 2000
    assert 'Short teaser' not in row['description'] and row['ends_at'] is None
    with pytest.raises(ValueError, match='description_limit'):
        b._full('x' * 12001)
    card, html = track(body='<p>Community morning run 0</p>')
    with pytest.raises(ValueError, match='description_missing'):
        b._tracksmith_detail(card, html, NOW, [])


@pytest.mark.parametrize('body', ['', '<p> </p>', '<p>https://example.com/register</p>'])
def test_blank_description_is_held_without_teaser_fallback(body):
    card, html = track(body=body)
    holds = []
    assert b._tracksmith_detail(card, html, NOW, holds) == []
    assert holds[0]['reason'] == 'boston_additional_description_missing'


def test_tracksmith_combines_explicit_date_clock_and_actual_partner_venue():
    card, html = track(venue='The Newbury Boston', native_address='1 Newbury St, Boston, MA 02116',
        summary='The class runs from 10am–11am. Meet in the hotel lobby.')
    row = b._tracksmith_detail(card, html, NOW, [])[0]
    assert row['venue_address'] == '1 Newbury St, Boston, MA 02116'
    assert datetime.fromisoformat(row['starts_at']) == START
    assert datetime.fromisoformat(row['ends_at']) == START + timedelta(hours=1)
    with pytest.raises(ValueError, match='time_conflict'):
        b._tracksmith_detail({**card, 'day_label': '1 Jan'}, html, NOW, [])
    with pytest.raises(ValueError, match='detail_changed'):
        b._tracksmith_detail(card, html.replace(card['url'], card['url'] + '-wrong'), NOW, [])


def test_dojo_point_is_bound_to_exact_native_venue_and_street():
    card, html = parkour()
    row = b._parkour_detail(card, html, NOW, [])[0]
    assert (row['lat'], row['lng']) == b.DOJO_POINT
    assert row['location_evidence_url'] == b.DOJO_EVIDENCE
    assert row['location_provenance'] == b.DOJO_PROVENANCE
    assert b._row_valid(b.PARKOUR, row, card, NOW)
    for changed in ({'lat': 42.38161}, {'venue_address': '17 Properzi Way, Somerville, MA 02143'},
                    {'location_evidence_url': card['url']}, {'location_provenance': 'unreviewed'}):
        assert not b._row_valid(b.PARKOUR, {**row, **changed}, card, NOW)
    for changes in ({'venue': 'The Dojo Annex'}, {'street': '17 Properzi Way, Somerville, MA 02143'}):
        near_card, near_html = parkour(**changes)
        near = b._parkour_detail(near_card, near_html, NOW, [])[0]
        assert near['lat'] is None and near['lng'] is None


def test_parkour_expands_only_explicit_individual_day_clinic():
    end = START + timedelta(days=3, hours=5)
    text = (f'DATES {START:%a %m/%d} - {end:%a %m/%d}. '
        'TIME / LOCATION 10am - 3pm at The Dojo. 1-day and 4-day signup options.').upper()
    # The native parser accepts the publisher's exact label and mixed-case clock.
    text = text.replace('10AM - 3PM', '10am - 3pm').replace('AT THE DOJO', 'at The Dojo')
    card, html = parkour(title='Parkour Explorer School Break Clinic', end=end, body=f'<p>{text}</p>')
    rows = b._parkour_detail(card, html, NOW, [])
    assert len(rows) == 4 and len({r['id'] for r in rows}) == 4
    assert all(datetime.fromisoformat(r['ends_at']) - datetime.fromisoformat(r['starts_at']) == timedelta(hours=5) for r in rows)
    assert b._parkour_sessions(card, text.replace('1-DAY AND 4-DAY SIGNUP OPTIONS', 'Full course enrollment only')) == []
    assert b._parkour_sessions({**card, 'end': (end + timedelta(hours=1)).isoformat()}, text) == []


def test_holiday_manifest_uses_two_explicit_registration_sessions():
    day = datetime(2026, 12, 5, 9, 30, tzinfo=ZoneInfo(b.ZONE))
    body = ''.join(f'<a href="https://pkgenboston.sites.zenplanner.com/event.cfm?eventId={native}">{label}</a>'
        for native, (_, label) in b.HOLIDAY_SESSIONS.items())
    card, html = parkour(url=b.HOLIDAY_PARENT, title='PKGB Holiday Challenge 2026',
                        start=day, end=day.replace(hour=15, minute=0), body=body)
    children = b._parkour_linked_sessions(card, html)
    assert len(children) == 2
    assert [(b._offset(c['start']).hour, b._offset(c['end']).hour) for c in children] == [(9, 12), (13, 15)]
    assert all(b._card_valid(b.PARKOUR, c, NOW) for c in children)
    assert not b._card_valid(b.PARKOUR, {**children[0], 'start': children[1]['start']}, NOW)
    with pytest.raises(ValueError, match='schedule_changed'):
        b._parkour_linked_sessions(card, html.replace('Adult / Teen Signup', 'Old session'))


def test_zenplanner_retains_all_native_narrative_paragraphs_and_lists():
    native = next(iter(b.HOLIDAY_SESSIONS))
    title = b.HOLIDAY_SESSIONS[native][0]
    start, end = START.replace(hour=9), START.replace(hour=12)
    card = dict(kind='zenplanner', native_id=native, title=title,
        url='https://pkgenboston.sites.zenplanner.com/event.cfm?eventId=' + native,
        start=start.isoformat(), end=end.isoformat(), venue='The Dojo @ Somernova',
        location='15 Properzi Way, Somerville, MA 02143')
    first = 'This is the complete native adult program narrative. ' * 45
    html = (f'<fieldset><legend>{title}</legend><p>{first}</p>'
        '<p>Second native paragraph supplies important participant instructions.</p>'
        '<ul><li>Bring water and comfortable shoes.</li></ul>'
        f'<strong>Date:</strong>{start:%B %d, %Y}'
        '<div><strong>Time:</strong>9:00 AM to 12:00 PM</div>'
        '<div><strong>Location:</strong>The Dojo @ Somernova SOM</div>'
        '<div class="adr"><span class="street-address">15 Properzi Way</span>'
        '<span class="locality">Somerville</span><span class="region">MA</span>'
        '<span class="postal-code">02143</span></div></fieldset>')
    row = b._parkour_zen_detail(card, html, NOW, [])[0]
    assert row['description'] == (first.strip() + '\nSecond native paragraph supplies important participant instructions.'
                                 '\nBring water and comfortable shoes.')
    assert len(row['description']) > 2000 and 'Date:' not in row['description']
    assert (row['lat'], row['lng']) == b.DOJO_POINT


def test_trustees_full_body_and_exact_already_public_overlap():
    card, html = trustees(body='<p>Grow healthy seedlings through the complete hands-on workshop.</p>')
    row = b._trustees_detail(card, html, NOW, [])[0]
    assert row['description'] == 'Grow healthy seedlings through the complete hands-on workshop.'
    assert 'Share' not in row['description']
    assert (row['lat'], row['lng']) == (42.2660524, -71.0955048)
    assert row['location_evidence_url'] == 'https://thetrustees.org/place/city-natives/'
    assert b._row_valid(b.TRUSTEES, row, card, NOW)
    fixed = datetime(2026, 12, 19, 14, 30, tzinfo=ZoneInfo(b.ZONE))
    card, html = trustees(url='https://thetrustees.org/event/450287/', start=fixed)
    holds = []
    assert b._trustees_detail(card, html, fixed - timedelta(days=2), holds) == []
    assert holds[0]['reason'] == 'boston_additional_existing_public_overlap'


def test_central_rock_rule_is_explicit_and_fresh():
    day = next(START.date() + timedelta(days=i) for i in range(35)
        if (START.date() + timedelta(days=i)).weekday() == 3 and 15 <= (START.date() + timedelta(days=i)).day <= 21)
    reference = datetime.combine(day - timedelta(days=10), datetime.min.time(), ZoneInfo(b.ZONE))
    body = (f'We meet on the third Thursday of the month, officially from 7–9pm at our '
        f'Cambridge location at 170 Alewife Brook Pkwy, this time on Thursday, {day:%B} {day.day}th. '
        'Join the community for climbing together and welcoming new members.')
    html = '<h1>BIPOC Climbers Meetup</h1><div class="white-content">' + body + '</div><div class="white-content">Hosted by community climbers.</div>'
    post = {'id': 492, 'status': 'publish', 'link': b.SOURCES[b.CENTRAL][0],
            'modified_gmt': reference.astimezone(timezone.utc).replace(tzinfo=None).isoformat()}
    def fetch(url, accept):
        return json.dumps(post) if accept == 'application/json' else html
    rows = b._central(fetch, reference, None, [])
    assert 1 <= len(rows) <= 3 and all('Third Thursday' in r['publisher_schedule_rule'] for r in rows)
    assert all(datetime.fromisoformat(r['starts_at']).astimezone(ZoneInfo(b.ZONE)).weekday() == 3 for r in rows)
    assert all((r['lat'], r['lng']) == (42.390776, -71.142459) for r in rows)
    assert all(r['location_evidence_url'] == 'https://centralrockgym.com/cambridge/' for r in rows)
    assert all('maps?q=42.390776,-71.142459' in r['location_provenance'] for r in rows)
    post['modified_gmt'] = (reference - timedelta(days=91)).replace(tzinfo=None).isoformat()
    with pytest.raises(ValueError, match='schedule_changed'):
        b._central(fetch, reference, None, [])


@pytest.mark.parametrize('changes', [
    {'title': 'Private group visit'}, {'title': 'Birthday rental'},
    {'title': 'Youth course (Part 2 of 4)'}, {'book': False},
])
def test_rock_spot_skips_private_closed_and_later_course_installments(changes):
    card, html = rock(**changes)
    assert b._rock_page(card, html, NOW, []) == []


def test_rock_spot_keeps_full_bookable_first_session_and_exact_location():
    body = 'Native full class content, eligibility and required equipment. ' * 55
    card, html = rock(title='Climbing course (Part 1 of 4)', body=f'<p>{body}</p>')
    rows = b._rock_page(card, html, NOW, [])
    assert len(rows) == 1 and rows[0]['description'] == body.strip()
    assert rows[0]['id'] == 'rockspot:42:742' and len(rows[0]['description']) > 2000
    assert rows[0]['venue_address'] == '30 Old Colony Avenue, South Boston, MA 02127'
    assert (rows[0]['lat'], rows[0]['lng']) == (42.3372967, -71.0561203)
    assert rows[0]['location_evidence_url'] == 'https://rockspotclimbing.com/locations/ma/southboston/'
    assert 'Separate parking marker 1 is excluded.' in rows[0]['location_provenance']
    assert b._row_valid(b.ROCKSPOT, rows[0], card, NOW)
    assert not b._row_valid(b.ROCKSPOT, {**rows[0], 'lat': 42.34}, card, NOW)
    _, wrong = rock(location='96')
    with pytest.raises(ValueError, match='calendar_changed'):
        b._rock_page(card, wrong, NOW, [])


@pytest.mark.parametrize('key,venue,street', list(b.REVIEWED_VENUE_POINTS))
def test_reviewed_gym_points_do_not_transfer_to_nearby_or_other_source_venues(key, venue, street):
    url = {b.CENTRAL: b.SOURCES[b.CENTRAL][0],
           b.ROCKSPOT: 'https://climber.hellocapitan.com/rockspot/schedule/event/42/select-num-participants/',
           b.TRUSTEES: 'https://thetrustees.org/event/123456/'}[key]
    city = {b.CENTRAL: 'Cambridge', b.ROCKSPOT: 'South Boston', b.TRUSTEES: 'Mattapan'}[key]
    def make(k=key, v=venue, address=street, link=url):
        return b._row(k, 'Community activity', START, START + timedelta(hours=1), link, 'native-42',
                      'The complete native activity description and participant instructions.', v, address, city)
    row = make();reviewed = b.REVIEWED_VENUE_POINTS[key, venue, street]
    assert (row['lat'], row['lng']) == reviewed['point'] and row['location_provenance'] == reviewed['provenance']
    for near in (make(v=venue + ' Annex'), make(address='9 Different Street, Boston, MA 02127'),
                 make(k=b.PARKOUR, link='https://pkgenboston.com/local-events/other-activity')):
        assert near['lat'] is None and near['lng'] is None


def test_harbor_complete_overview_preserves_conflict_and_reviewed_meeting_point():
    card, html = harbor()
    row = b._harbor_detail(card, html, NOW, [])[0]
    assert '423 Commercial Street' in row['description'] and 'Short teaser' not in row['description']
    assert row['venue_address'] == '523 Commercial Street, Boston, MA 02109'
    assert row['location_evidence_url'] == b.HARBOR_BOCCE_EVIDENCE
    assert b._row_valid(b.HARBOR, row, card, NOW)
    assert not b._row_valid(b.HARBOR, {**row, 'venue_address': '423 Commercial Street, Boston, MA 02109'}, card, NOW)
    with pytest.raises(ValueError, match='detail_changed'):
        _, missing_own_context = harbor(basic=False)
        b._harbor_detail(card, missing_own_context, NOW, [])


@pytest.mark.parametrize('field,value', [('isProtected', True), ('isListed', False),
    ('isOnline', True), ('status', 'draft'), ('hideStartDate', True), ('isSeries', True)])
def test_deployed_harbor_public_occurrence_guards_are_preserved(field, value):
    from bs4 import BeautifulSoup
    card, html = harbor()
    soup = BeautifulSoup(html, 'html.parser')
    node = soup.select_one('#__NEXT_DATA__');payload = json.loads(node.string)
    payload['props']['pageProps']['context']['basicInfo'][field] = value
    node.string = json.dumps(payload)
    holds = []
    assert b._harbor_detail(card, str(soup), NOW, holds) == []
    assert holds[0]['reason'] == 'boston_additional_not_public'


def test_arboretum_native_ics_full_description_and_exact_gate():
    item = Event()
    url = 'https://arboretum.harvard.edu/event/community-walk/'
    item.add('uid', 'native-walk'); item.add('url', url); item.add('summary', 'Guided community walk')
    item.add('dtstart', START); item.add('dtend', START + timedelta(hours=1))
    text = 'Explore the collection with the full native route and access instructions. ' * 40
    item.add('description', text)
    item.add('location', 'Flora Way Gate (Formerly Bussey St Gate), Bussey Street Gate, Boston, MA, United States')
    item.add('geo', (42.2964125, -71.1280781))
    cal = Calendar(); cal.add('version', '2.0'); cal.add_component(item)
    listing = '<div class="tribe-events"></div><script type="application/ld+json">' + json.dumps(
        {'@type': 'Event', 'url': url, 'startDate': START.isoformat(), 'endDate': (START + timedelta(hours=1)).isoformat()}) + '</script>'
    def fetch(path, accept):
        assert 'wp-json' not in path
        return cal.to_ical().decode() if accept == 'text/calendar' else listing
    rows = b._arboretum(fetch, NOW, None, [])
    assert rows[0]['description'] == text.strip() and len(rows[0]['description']) > 2000
    assert rows[0]['venue_address'] == b.REVIEWED_INTERSECTIONS[0]['venue_address']
    boston_sources.validate_records(rows, source(b.ARBORETUM))
    with pytest.raises(ValueError, match='incomplete_event'):
        boston_sources.validate_records([{**rows[0], 'lat': 42.4}], source(b.ARBORETUM))
    listing += '<a class="tribe-events-c-nav__next" href="/events/page/2/">Next</a>'
    with pytest.raises(ValueError, match='pagination_incomplete'):
        b._arboretum(fetch, NOW, None, [])


def test_checkpoint_complete_only_hash_binding_and_ttl(monkeypatch):
    items = [track(i) for i in range(10)]
    monkeypatch.setattr(b, '_manifest', lambda *args: [c for c, _ in items])
    reads = []
    def fetch(url, accept):
        reads.append(url)
        return dict((c['url'], html) for c, html in items)[url]
    first = b.collect_chunk(source(b.TRACKSMITH), fetch, now=NOW)
    assert not first['complete'] and first['events'] == [] and first['checkpoint']['cursor'] == 8
    boston_sources.validate_checkpoint(source(b.TRACKSMITH), first['checkpoint'], now=NOW)
    for field, value in [('description', 'Replaced narrative.'), ('venue_address', '1 Wrong Street, Boston, MA 02115'),
                         ('starts_at', (START + timedelta(days=1)).isoformat())]:
        poison = deepcopy(first['checkpoint']); poison['events'][0][field] = value
        with pytest.raises(ValueError, match='checkpoint_invalid'):
            b.collect_chunk(source(b.TRACKSMITH), fetch, checkpoint=poison, now=NOW)
    original = deepcopy(first['checkpoint'])
    with pytest.raises(RuntimeError, match='publisher failure'):
        b.collect_chunk(source(b.TRACKSMITH), lambda *a: (_ for _ in ()).throw(RuntimeError('publisher failure')),
                        checkpoint=first['checkpoint'], now=NOW)
    assert first['checkpoint'] == original
    final = b.collect_chunk(source(b.TRACKSMITH), fetch, checkpoint=first['checkpoint'], now=NOW)
    assert final['complete'] and len(final['events']) == 10 and len(reads) == 10
    with pytest.raises(ValueError, match='checkpoint_invalid'):
        b.collect_chunk(source(b.TRACKSMITH), fetch, checkpoint=first['checkpoint'], now=NOW + timedelta(hours=5))


def test_rehashed_checkpoint_cannot_move_the_reviewed_dojo_point(monkeypatch):
    card, html = parkour()
    monkeypatch.setattr(b, '_manifest', lambda *args: [card])
    state = b.collect_chunk(source(b.PARKOUR), lambda *args: html, now=NOW)['checkpoint']
    poison = deepcopy(state)
    poison['events'][0]['lat'] = 42.38161
    poison['outcomes'][0]['rows_hash'] = b._digest(poison['events'])
    with pytest.raises(ValueError, match='checkpoint_invalid'):
        b.collect_chunk(source(b.PARKOUR), lambda *args: pytest.fail('complete checkpoint must not refetch'),
                        checkpoint=poison, now=NOW)


def test_checkpoint_with_no_detail_budget_can_save_manifest_without_partial_events(monkeypatch):
    card, _ = track()
    monkeypatch.setattr(b, '_manifest', lambda *args: [card])
    monkeypatch.setattr(b, 'monotonic', lambda: 19)
    result = b.collect_chunk(source(b.TRACKSMITH), lambda *args: pytest.fail('reserve prohibits publisher read'),
                             now=NOW, deadline_at=36)
    assert not result['complete'] and result['events'] == [] and result['checkpoint']['cursor'] == 0
    boston_sources.validate_checkpoint(source(b.TRACKSMITH), result['checkpoint'], now=NOW)


def test_old_holiday_aggregate_manifest_cannot_resume(monkeypatch):
    card, _ = parkour(url=b.HOLIDAY_PARENT, title='Holiday Challenge 2026')
    manifest = [card]
    state = dict(version=1, source_key=b.PARKOUR, started_at=NOW.isoformat(),
        window_start=NOW.astimezone(ZoneInfo(b.ZONE)).date().isoformat(),
        manifest=manifest, manifest_hash=b._digest(manifest), manifest_count=1,
        cursor=0, events=[], outcomes=[], diagnostics=[])
    with pytest.raises(ValueError, match='checkpoint_invalid'):
        b.collect_chunk(source(b.PARKOUR), lambda *args: pytest.fail('old aggregate cannot refetch or publish'),
                        checkpoint=state, now=NOW)


def test_old_bookable_later_installment_prefix_cannot_resume():
    manifest = b._rock_manifest(NOW)
    first = date.fromisoformat(manifest[0]['day'])
    day = first + timedelta(days=1)
    start, end = b._range(day, '10am-12pm')
    row = b._row(b.ROCKSPOT, 'Public course (Part 2 of 4)', start, end,
        'https://climber.hellocapitan.com/rockspot/schedule/event/42/select-num-participants/',
        'rockspot:42:742', 'Full native course narrative, originally bookable as a parent course.',
        'Rock Spot Climbing South Boston', '30 Old Colony Avenue, South Boston, MA 02127', 'South Boston')
    row['publisher_schedule_page'] = manifest[0]['url']
    state = dict(version=1, source_key=b.ROCKSPOT, started_at=NOW.isoformat(),
        window_start=first.isoformat(), manifest=manifest, manifest_hash=b._digest(manifest),
        manifest_count=len(manifest), cursor=1, events=[row], diagnostics=[],
        outcomes=[{'url':manifest[0]['url'], 'rows_hash':b._digest([row])}])
    with pytest.raises(ValueError, match='checkpoint_invalid'):
        b.collect_chunk(source(b.ROCKSPOT), lambda *args: pytest.fail('obsolete prefix cannot publish'),
                        checkpoint=state, now=NOW)


@pytest.mark.parametrize('response_seconds,expected_claims', [(0.25, 2), (5, 3), (17, 9)])
def test_actual_worker_slow_fetch_reserve_and_complete_only_staging(monkeypatch, response_seconds, expected_claims):
    from roomquest import preview_worker as worker
    items = [track(i) for i in range(9)]
    expected = [r for c, html in items for r in b._tracksmith_detail(c, html, NOW, [])]
    monkeypatch.setattr(b, '_manifest', lambda *args: [c for c, _ in items])
    clock, saved, revision, staged, previews, reads = [0.0], [None], [0], [], [], []
    monkeypatch.setattr(b, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(worker, 'monotonic', lambda: clock[0])
    src = {**source(b.TRACKSMITH), 'fetch_checkpoint_version': 1}
    bodies = dict((c['url'], html) for c, html in items)
    def fetch(url, accept, **kwargs):
        assert kwargs['respect_robots'] is True and urlsplit(url).hostname in kwargs['allowed_hosts']
        assert clock[0] + 18 < kwargs['deadline_at']
        clock[0] += response_seconds; reads.append(url)
        return bodies[url]
    def rpc(op, args):
        if op == 'community_collector_read_fetch_checkpoint':
            return {'revision': revision[0], 'checkpoint': saved[0]}
        if op == 'community_collector_write_fetch_checkpoint':
            saved[0] = args['p_checkpoint']; revision[0] += 1
            boston_sources.validate_checkpoint(src, saved[0])
            return {'checkpoint_saved': True, 'revision': revision[0]}
        if op == 'community_collector_record_staged_events':
            assert saved[0]['cursor'] == saved[0]['manifest_count']
            boston_sources.validate_records(args['p_events'], src); staged.extend(args['p_events'])
            return len(args['p_events'])
        if op == 'community_collector_record_preview_v2':
            assert args['p_error'] is None; previews.append(args); return {'ok': True}
        raise AssertionError(op)
    monkeypatch.setattr(worker, 'fetch_publisher', fetch)
    monkeypatch.setattr(worker, 'supabase_rpc', rpc)
    for claim in range(expected_claims):
        clock[0] = claim * 60
        result = worker._process_claimed_source_with_pacing(src,
            {'wait_unbounded': False, 'crawl_delay_seconds': 0, 'retry_after_seconds': 0},
            deadline_at=clock[0] + 60,
            collection_context={'p_category': 'html', 'p_ticket': 'test-native-boston-capture'})
        assert result['failed'] == 0
        if result.get('fetch_pending'):
            assert not staged and not previews
        else:
            assert result['complete'] == 1 and claim + 1 == expected_claims
    assert staged == expected and len(previews) == 1 and len(set(reads)) == len(reads) == 9


def test_city_natives_reviewed_destination_precedes_conflicting_event_pin():
    card, html = trustees()
    row = b._row(b.TRUSTEES, card['title'], START, START + timedelta(hours=1, minutes=30),
        card['url'], 'trustees:123456', 'Learn native seed propagation with the community gardeners.',
        'City Natives', '30 Edgewater Drive, Mattapan, MA 02126', 'Mattapan',
        point=(42.2660524, -71.096052), evidence=card['url'], provenance='Conflicting event pin.')
    assert (row['lat'], row['lng']) == (42.2660524, -71.0955048)
    assert row['location_evidence_url'] == 'https://thetrustees.org/place/city-natives/'
    assert b._row_valid(b.TRUSTEES, row, card, NOW)
    for changes in ({'lng': -71.096052}, {'location_evidence_url': card['url']},
                    {'location_provenance': 'Unreviewed replacement'}):
        assert not b._row_valid(b.TRUSTEES, {**row, **changes}, card, NOW)


def test_city_natives_checkpoint_rejects_rehashed_destination_change(monkeypatch):
    card, html = trustees()
    monkeypatch.setattr(b, '_manifest', lambda *args: [card])
    result = b.collect_chunk(source(b.TRUSTEES), lambda *args: html, now=NOW)
    assert result['complete'] and len(result['events']) == 1
    state = result['checkpoint']
    resumed = b.collect_chunk(source(b.TRUSTEES), lambda *args: pytest.fail('complete checkpoint must not refetch'),
                              checkpoint=state, now=NOW)
    assert resumed['events'] == result['events']
    poison = deepcopy(state)
    poison['events'][0]['lng'] = -71.096052
    poison['outcomes'][0]['rows_hash'] = b._digest(poison['events'])
    with pytest.raises(ValueError, match='checkpoint_invalid'):
        b.collect_chunk(source(b.TRUSTEES), lambda *args: pytest.fail('invalid checkpoint must not refetch'),
                        checkpoint=poison, now=NOW)
