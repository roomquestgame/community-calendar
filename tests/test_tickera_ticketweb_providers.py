from datetime import datetime, timedelta, timezone
import html
import json
from unittest.mock import Mock, patch

import pytest

from roomquest import (feed_registration, preview_worker, provider_registration,
                       tickera_provider, ticketweb_event_discovery)
from roomquest.registration_formats import source_key


DAY = (datetime.now(timezone.utc) + timedelta(days=7)).date()
START = DAY.isoformat() + ' 19:00'


def tickera_page():
    return f'''<html><link href="/wp-content/plugins/tickera-event-calendar/includes/fullcalendar/lib/main.css">
    <div id="tc_calendar"></div><script>document.addEventListener('DOMContentLoaded', function() {{
    var calendar = new FullCalendar.Calendar(document.getElementById('tc_calendar'), {{
    events: [{{title: 'Public show', start: '{START}', end: '{DAY.isoformat()} 20:00',
    url: 'https://venue.example.org/event/public-show/', classNames: 'tcec-event-',
    backgroundImage: 'https://venue.example.org/show.jpg'}}], eventDidMount: function() {{}} }}); }});</script></html>'''


def event_discovery_page():
    settings = {'type': 'calendar3', 'current_datetime': {
        'date': DAY.isoformat() + ' 09:00:00', 'timezone_type': 3, 'timezone': 'America/Boise'}}
    return f'''<html><link href="/wp-content/plugins/event-discovery/css/tw-default.css">
    <script>jQuery.ajax({{url: 'https://venue.example.org/wp-admin/admin-ajax.php', data: {{
    action: 'get_events_artist_calendar', nonce: '123456789a', start: start_date, end: end_date,
    params: '{html.escape(json.dumps(settings))}',
    monthview: 'standard'}}}});</script></html>'''


def event_discovery_payload():
    return json.dumps({'events': [{
        'id': 'Public show', 'start': DAY.isoformat(), 'title': 'Public show',
        'sortkey': START + ':00', 'url': 'https://venue.example.org/tm-event/public-show/',
        'imageUrl': '<img src="https://i.ticketweb.com/show.jpg">',
        'venue': '<div>Fixture Hall<br>Boise, ID</div>'}]})



def event_discovery_provider_payload():
    payload = json.loads(event_discovery_payload())
    payload['events'][0]['url'] = 'https://www.ticketweb.com/event/public-show/'
    payload['events'].extend([
        {'title': 'Malformed row', 'url': 'https://www.ticketweb.com/event/bad/', 'sortkey': 'not-a-date'},
        {'title': 'Untrusted row', 'url': 'https://unrelated.example/event/', 'sortkey': START + ':00'},
    ])
    return json.dumps(payload)

def test_tickera_contract_uses_calendar_array_and_wordpress_timezone():
    page = tickera_page()
    assert tickera_provider.supports_listing('https://venue.example.org/calendar/', page)
    fetch = lambda url, accept, **kwargs: json.dumps({'timezone_string': 'America/New_York'})
    [row] = tickera_provider.collect({
        'feed_url': 'https://venue.example.org/calendar/', 'source_key': 'fixture',
        'platform_adapter': 'tickera', 'kind': 'json'}, fetch, body=page)
    assert row['title'] == 'Public show'
    assert row['event_url'].endswith('/event/public-show/')
    assert row['image_url'].endswith('/show.jpg')


def test_tickera_unions_multiple_configured_calendars_and_deduplicates_overlap():
    first = tickera_page()
    second = tickera_page().replace('Public show', 'Second show').replace(
        '/event/public-show/', '/event/second-show/').replace('/show.jpg', '/second.jpg')
    overlap = tickera_page()
    page = first.replace('</html>', '') + second.replace('<html>', '').replace('</html>', '') \
        + overlap.replace('<html>', '')
    rows = tickera_provider.parse(
        page, url='https://venue.example.org/calendar/', zone='America/New_York')
    assert [row['title'] for row in rows] == ['Public show', 'Second show']


def test_tickera_rejects_conflicting_duplicate_event_identity():
    page = tickera_page().replace('</html>', '') + tickera_page().replace(
        '<html>', '').replace('Public show', 'Changed show')
    with pytest.raises(ValueError, match='^conflicting_tickera_event$'):
        tickera_provider.parse(
            page, url='https://venue.example.org/calendar/', zone='America/New_York')


def test_ticketweb_event_discovery_contract_uses_public_display_action():
    page = event_discovery_page()
    spec = ticketweb_event_discovery.contract('https://venue.example.org/calendar/', page)
    calls = []
    def fetch(url, accept, **kwargs):
        calls.append((url, kwargs))
        return event_discovery_payload()
    [row] = ticketweb_event_discovery.collect({
        'feed_url': 'https://venue.example.org/calendar/', 'source_key': 'fixture',
        'platform_adapter': 'event_discovery', 'kind': 'json'}, fetch, body=page)
    assert row['title'] == 'Public show'
    assert row['venue_name'] == 'Fixture Hall Boise, ID'
    assert calls[0][0] == spec['endpoint']
    assert calls[0][1]['calendar_form']['action'] == 'get_events_artist_calendar'


def test_standard_ticketweb_calendar_uses_its_advertised_display_action():
    page = event_discovery_page().replace('calendar3', 'calendar').replace(
        'get_events_artist_calendar', 'get_events_for_calendar')
    spec = ticketweb_event_discovery.contract('https://venue.example.org/calendar/', page)
    submitted = ticketweb_event_discovery.form(
        spec, DAY.isoformat(), (DAY + timedelta(days=61)).isoformat())
    assert submitted['action'] == 'get_events_for_calendar'
    assert ticketweb_event_discovery.valid_form(submitted)
    calls = []
    def fetch(url, accept, **kwargs):
        calls.append(kwargs['calendar_form'])
        return event_discovery_payload()
    source = {'feed_url': 'https://venue.example.org/calendar/',
              'platform_adapter': 'event_discovery', 'kind': 'json'}
    assert len(ticketweb_event_discovery.collect(source, fetch, body=page)) == 1
    assert len(calls) == 1 and calls[0]['action'] == submitted['action']
    assert ticketweb_event_discovery.valid_form(calls[0])
    # This is a specific public calendar variant, not arbitrary AJAX access.
    with pytest.raises(ValueError, match='invalid_event_discovery_calendar'):
        ticketweb_event_discovery.contract(source['feed_url'], page.replace('&quot;calendar&quot;', '&quot;calendar3&quot;'))
    submitted['action'] = 'delete_event'
    assert not ticketweb_event_discovery.valid_form(submitted)


def test_ambiguous_ticketweb_calendar_actions_are_held():
    page = event_discovery_page() + "<script>action: 'get_events_for_calendar'</script>"
    assert not ticketweb_event_discovery.supports_listing('https://venue.example.org/calendar/', page)


def test_standard_calendar_dialog_retains_exact_public_event_identity():
    payload = json.loads(event_discovery_payload())
    event = payload['events'][0]
    canonical = event['url']
    event.update(id=2827, url='#tw-event-dialog-2827')
    payload['popupdata'] = ('<div id="tw-event-dialog-2827"><div class="tw-name">'
                            f'<a href="{canonical}">Public show</a></div></div>')
    [row] = ticketweb_event_discovery.parse(json.dumps(payload), url='https://venue.example.org/calendar/', zone='UTC')
    assert row['event_url'] == canonical
    assert row['id'] == canonical + ':' + START + ':00'
    # A same-response dialog with another title cannot supply this event URL.
    payload['popupdata'] = payload['popupdata'].replace('Public show', 'Other show')
    with pytest.raises(ValueError):
        ticketweb_event_discovery.parse(json.dumps(payload), url='https://venue.example.org/calendar/', zone='UTC')


def test_grouped_artist_performances_cannot_seal_a_partial_snapshot():
    payload = json.loads(event_discovery_payload())
    payload['events'][0]['times'] = ('<a href="https://venue.example.org/tm-event/public-show/">7PM</a>'
                                    '<a href="https://venue.example.org/tm-event/second-show/">9PM</a>')
    with pytest.raises(ValueError):
        ticketweb_event_discovery.parse(json.dumps(payload), url='https://venue.example.org/calendar/', zone='UTC')




def test_ticketweb_provider_links_are_kept_and_bad_rows_do_not_drop_calendar():
    rows = ticketweb_event_discovery.parse(
        event_discovery_provider_payload(), url='https://venue.example.org/calendar/', zone='America/Boise')
    [row] = rows
    assert row['event_url'].startswith('https://www.ticketweb.com/event/')
    assert rows.complete is False
    assert rows.rejected == {'invalid_start': 1, 'untrusted_url': 1}


def test_ticketweb_incomplete_first_party_snapshot_is_not_accepted(caplog):
    page = event_discovery_page()
    def fetch(url, accept, **kwargs):
        return event_discovery_provider_payload()
    with pytest.raises(ValueError, match='^incomplete_event_discovery_snapshot$'):
        ticketweb_event_discovery.collect({
            'feed_url': 'https://venue.example.org/calendar/', 'source_key': 'fixture',
            'platform_adapter': 'event_discovery', 'kind': 'json'}, fetch, body=page)
    assert 'event_discovery_rows_rejected' in caplog.text
    assert 'invalid_start' in caplog.text


def test_ticketweb_untrusted_noise_does_not_make_snapshot_incomplete():
    payload = json.loads(event_discovery_payload())
    payload['events'].append({
        'title': 'Untrusted row', 'url': 'https://unrelated.example/event/',
        'sortkey': START + ':00'})
    rows = ticketweb_event_discovery.parse(
        json.dumps(payload), url='https://venue.example.org/calendar/', zone='America/Boise')
    assert len(rows) == 1 and rows.complete is True
    assert rows.rejected == {'untrusted_url': 1}

def test_ticketweb_event_discovery_transport_allows_only_reviewed_display_post():
    spec = ticketweb_event_discovery.contract('https://venue.example.org/calendar/', event_discovery_page())
    form = ticketweb_event_discovery.form(spec, DAY.isoformat(), (DAY + timedelta(days=61)).isoformat())
    response = Mock(status_code=200, encoding='utf-8')
    response.headers = {'Content-Type': 'application/json'}
    response.iter_content.return_value = [event_discovery_payload().encode()]
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.post.return_value = response
    with patch.object(preview_worker.requests, 'Session', return_value=session), patch.object(
            preview_worker, 'validate_public_dns'), patch.object(
            preview_worker, 'robots_allowed', return_value=True), patch.object(
            preview_worker, 'pace_publisher'):
        payload = preview_worker._fetch_publisher_request(
            spec['endpoint'], 'application/json', respect_robots=True,
            allowed_hosts=('venue.example.org',), calendar_form=form)
    assert json.loads(payload)['events'][0]['title'] == 'Public show'
    _, kwargs = session.post.call_args
    assert kwargs['headers']['Referer'] == 'https://venue.example.org/calendar/'
    assert kwargs['allow_redirects'] is False


@pytest.mark.parametrize('change', [
    {'action': 'register'}, {'end': '2099-01-01'}, {'showmobilelist': 'false'},
    {'unexpected': 'field'},
])
def test_ticketweb_event_discovery_transport_rejects_mutated_post(change):
    spec = ticketweb_event_discovery.contract('https://venue.example.org/calendar/', event_discovery_page())
    form = ticketweb_event_discovery.form(spec, DAY.isoformat(), (DAY + timedelta(days=61)).isoformat())
    form.update(change)
    with patch.object(preview_worker.requests, 'Session') as session:
        with pytest.raises(preview_worker.PreviewError, match='^invalid_calendar_render_parameters$'):
            preview_worker._fetch_publisher_request(
                spec['endpoint'], 'application/json', respect_robots=True,
                allowed_hosts=('venue.example.org',), calendar_form=form)
        session.assert_not_called()

@pytest.mark.parametrize(('adapter','marker','page','extra'), [
    ('tickera', '/wp-content/plugins/tickera/', tickera_page(),
     {'https://venue.example.org/wp-json/': json.dumps({'timezone_string':'America/New_York'})}),
    ('event_discovery', '/wp-content/plugins/event-discovery/', event_discovery_page(),
     {'https://venue.example.org/wp-admin/admin-ajax.php': event_discovery_payload()}),
])
def test_feedzilla_registration_and_recurring_collection_share_provider(adapter, marker, page, extra):
    home = f'<html><link href="{marker}front.css"><a href="/calendar/">Calendar</a></html>'
    url = 'https://venue.example.org/'
    calendar = url + 'calendar/'
    receipts = []
    def rpc(method, args, **kwargs):
        if method.endswith('claim_registration'):
            return {'url': url}
        if method.endswith('feed_profile'):
            return {}
        receipts.append(args)
        return True
    def fetch(target, accept, **kwargs):
        if target == url:
            return home
        if target == calendar:
            return page
        if target in extra:
            return extra[target]
        raise AssertionError(target)
    with patch.object(feed_registration, 'supabase_rpc', rpc), patch.object(
            feed_registration, 'fetch_publisher', fetch):
        assert feed_registration.register('ticket')['outcome'] == 'discovered'
    assert (receipts[0]['p_endpoint'], receipts[0]['p_type']) == (calendar, adapter)

    source = {'feed_url': calendar, 'source_key': source_key(calendar),
              'platform_adapter': adapter, 'kind': 'json'}
    with patch.object(preview_worker, 'supabase_rpc', rpc), patch.object(
            preview_worker, 'fetch_publisher', fetch):
        result = preview_worker.preview_source(source)
    assert result['p_future_count'] == 1


def test_provider_identity_is_not_generic_fullcalendar():
    assert provider_registration.family('https://venue.example.org/calendar/', tickera_page()) == 'tickera'
    assert provider_registration.family(
        'https://venue.example.org/calendar/', event_discovery_page()) == 'event_discovery'


def test_verified_single_venue_default_is_handed_to_shared_staging_policy():
    records = [{'title': 'Show', 'venue_name': '', 'venue_address': '',
                'venue_city': '', 'lat': None, 'lng': None}]
    source = {'platform_adapter': 'tickera',
              'publisher_default_venue': 'Motorco Music Hall',
              'publisher_default_lat': 36.0035821,
              'publisher_default_lng': -78.9002707,
              'publisher_default_evidence': 'Verified venue website and reviewed street point.'}
    [row] = provider_registration.apply_verified_default_venue(source, records)
    assert row['venue_name'] == 'Motorco Music Hall'
    assert row['lat'] is None and row['lng'] is None


def test_provider_default_profile_uses_collector_authorized_rpc():
    calls = []
    profile = {'publisher_default_venue': 'Motorco Music Hall'}
    assert provider_registration.read_profile(
        'https://venue.example.org/calendar/', 'tickera',
        lambda name, args: calls.append((name, args)) or profile) is profile
    assert calls == [('community_collector_feed_profile', {
        'p_url': 'https://venue.example.org/calendar/', 'p_adapter': 'tickera'})]


@pytest.mark.parametrize('change', [
    {'platform_adapter': 'wordpress'},
    {'publisher_default_evidence': ''},
])
def test_unverified_or_non_provider_default_is_not_inferred(change):
    records = [{'title': 'Show', 'venue_name': '', 'venue_address': '',
                'venue_city': '', 'lat': None, 'lng': None}]
    source = {'platform_adapter': 'tickera',
              'publisher_default_venue': 'Venue', 'publisher_default_lat': 1.0,
              'publisher_default_lng': 2.0,
              'publisher_default_evidence': 'Reviewed publisher evidence.', **change}
    assert provider_registration.apply_verified_default_venue(source, records) is records


def test_multi_venue_provider_snapshot_keeps_publisher_locations():
    records = [
        {'title': 'Main room', 'venue_name': 'Main Room', 'lat': None, 'lng': None},
        {'title': 'Second room', 'venue_name': 'Second Room', 'lat': None, 'lng': None},
    ]
    source = {'platform_adapter': 'event_discovery',
              'publisher_default_venue': 'Main Room', 'publisher_default_lat': 1.0,
              'publisher_default_lng': 2.0,
              'publisher_default_evidence': 'Reviewed publisher evidence.'}
    assert provider_registration.apply_verified_default_venue(source, records) is records


def grouped_payload():
    payload = json.loads(event_discovery_payload())
    event = payload['events'][0]
    event['times'] = (f'<span><a href="{event["url"]}">7:00PM</a></span>'
                      '<span><a href="https://venue.example.org/tm-event/second-performance/">9:30PM</a></span>')
    return payload


def test_artist_card_expands_published_performance_urls_without_changing_primary_identity():
    payload = grouped_payload()
    rows = ticketweb_event_discovery.parse(json.dumps(payload), url='https://venue.example.org/calendar/', zone='America/Boise')
    assert rows.complete and not rows.rejected
    assert len(rows) == 2
    assert rows[0]['id'] == payload['events'][0]['url'] + ':' + START + ':00'
    assert rows[1]['id'] == 'https://venue.example.org/tm-event/second-performance/:' + DAY.isoformat() + ' 21:30:00'
    assert rows[0]['starts_at'].endswith('+00:00')
    assert rows[0]['venue_name'] == rows[1]['venue_name']


@pytest.mark.parametrize('change', ['date', 'primary_clock', 'other_host', 'ambiguous_clock', 'same_url_two_clocks'])
def test_artist_card_ambiguous_performance_preserves_prior_snapshot(change):
    payload = grouped_payload()
    event = payload['events'][0]
    if change == 'date':
        event['start'] = (DAY + timedelta(days=1)).isoformat()
    elif change == 'primary_clock':
        event['times'] = event['times'].replace('7:00PM', '8:00PM')
    elif change == 'other_host':
        event['times'] = event['times'].replace('venue.example.org/tm-event/second', 'other.example.org/tm-event/second')
    elif change == 'ambiguous_clock':
        event['times'] = event['times'].replace('9:30PM', '9:30')
    else:
        event['times'] = event['times'].replace('https://venue.example.org/tm-event/second-performance/', event['url'])
    payload['events'].append(json.loads(event_discovery_payload())['events'][0])
    rows = ticketweb_event_discovery.parse(json.dumps(payload), url='https://venue.example.org/calendar/', zone='UTC')
    assert not rows.complete and rows.rejected['grouped_performances_unverified'] == 1


def test_explicit_reviewed_publisher_timezone_overrides_bad_widget_without_identity_changes():
    source = {'feed_url': 'https://venue.example.org/calendar/', 'platform_adapter': 'event_discovery', 'kind': 'json'}
    fetch = lambda *args, **kwargs: event_discovery_payload()
    [original] = ticketweb_event_discovery.collect(source, fetch, body=event_discovery_page())
    source['publisher_event_timezone'] = {'timezone': 'America/New_York',
        'evidence_url': 'https://venue.example.org/tm-event/public-show/'}
    [reviewed] = ticketweb_event_discovery.collect(source, fetch, body=event_discovery_page())
    assert original['id'] == reviewed['id']
    assert datetime.fromisoformat(original['starts_at']) - datetime.fromisoformat(reviewed['starts_at']) == timedelta(hours=2)
    source['publisher_event_timezone']['evidence_url'] = 'https://other.example.org/show/'
    with pytest.raises(ValueError, match='invalid_reviewed_event_timezone'):
        ticketweb_event_discovery.collect(source, fetch, body=event_discovery_page())


@pytest.mark.parametrize('adapter,page', [('event_discovery', event_discovery_page()), ('tickera', tickera_page())])
@pytest.mark.parametrize('reason,outcome', [('source_network_error','retry'),('publisher_http_503','retry'),
                                           ('robots_denied','disabled'),('publisher_http_403','disabled')])
def test_native_provider_identity_survives_collection_failure_without_changing_access_or_retry(adapter,page,reason,outcome):
    url = 'https://venue.example.org/calendar/'
    with patch.object(feed_registration,'supabase_rpc',side_effect=[{'url':url},{},True]) as rpc, \
         patch.object(feed_registration,'fetch_publisher',return_value=page), \
         patch.object(provider_registration,'collect',side_effect=preview_worker.PreviewError(reason)):
        assert feed_registration.register('ticket') == {'outcome':outcome}
    result = rpc.call_args.args[1]
    assert result['p_outcome'] == outcome and result['p_reason'] == reason
    assert result['p_type'] == adapter and result['p_endpoint'] == url
    assert not any('source_id' in key or 'approval' in key for key in result)
