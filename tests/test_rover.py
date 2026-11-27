import json

from roomquest.rover import candidates, select_candidate, inspect_selection, propose
from roomquest.preview_worker import PreviewError


def test_only_same_host_publisher_links_are_selectable():
    links = candidates('<a href="/whats-on?site=west">What’s on</a>'
                       '<a href="https://other.example/events">Events</a>'
                       '<a href="http://127.0.0.1/">Internal</a>',
                       'https://venue.example/')
    assert len(links) == 1
    selected = select_candidate(links, json.dumps({'candidate_id': links[0]['id']}))
    assert selected == {'url': 'https://venue.example/whats-on?site=west',
                        'status': 'needs_independent_validation'}


def test_model_cannot_invent_a_url_or_include_extra_instructions():
    links = candidates('<a href="/events">Events</a>', 'https://venue.example/')
    assert select_candidate(links, '{"candidate_id":"made-up"}') is None
    assert select_candidate(links, json.dumps({'candidate_id': links[0]['id'],
                                                'url': 'https://evil.example'})) is None
    assert select_candidate(links, 'not json') is None


def test_model_only_receives_bounded_publisher_link_labels():
    links = candidates('<a href="/whats-on?venue=west">What’s on</a>',
                       'https://venue.example/')
    def complete(system, payload):
        assert 'untrusted' in system
        assert payload == {'venue': 'West Venue', 'links': [
            {'id': links[0]['id'], 'label': 'What’s on'}]}
        return json.dumps({'candidate_id': links[0]['id']})
    assert propose('West Venue', links, complete=complete)['url'] == links[0]['url']


def test_model_miss_and_failure_remain_unresolved():
    links = candidates('<a href="/about">About</a>', 'https://venue.example/')
    assert propose('Venue', links, complete=lambda *a: '{"candidate_id":null}') is None
    assert propose('Venue', links, complete=lambda *a: (_ for _ in ()).throw(TimeoutError())) is None


def test_selected_non_calendar_does_not_register():
    selected = {'url': 'https://venue.example/about', 'status': 'needs_independent_validation'}
    result = inspect_selection('https://venue.example/', '', selected,
                               fetch=lambda *a, **k: '<h1>About</h1>', deadline=999999999)
    assert result == {'status': 'review', 'reason': 'calendar_not_verified'}


def test_selected_real_calendar_is_probed_before_handoff():
    selected = {'url': 'https://venue.example/calendar.ics', 'status': 'needs_independent_validation'}
    calls = []
    def fetch(url, accept, **kwargs):
        calls.append((url, kwargs))
        return ('BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:event-1\n'
                'DTSTART:20271201T190000Z\nSUMMARY:Concert\nEND:VEVENT\nEND:VCALENDAR')
    result = inspect_selection('https://venue.example/', '', selected,
                               fetch=fetch, deadline=999999999)
    assert result == {'status': 'candidate', 'url': selected['url'], 'kind': 'ical'}
    assert calls[0][1]['respect_robots'] is True
    assert calls[0][1]['allowed_hosts'] == ('venue.example',)


def test_selected_calendar_denial_is_preserved():
    selected = {'url': 'https://venue.example/events', 'status': 'needs_independent_validation'}
    def blocked(*args, **kwargs):
        raise PreviewError('robots_denied')
    result = inspect_selection('https://venue.example/', '', selected,
                               fetch=blocked, deadline=999999999)
    assert result == {'status': 'denied', 'reason': 'robots_denied'}


def test_selected_foreign_host_is_never_fetched():
    selected = {'url': 'https://other.example/events', 'status': 'needs_independent_validation'}
    result = inspect_selection('https://venue.example/', '', selected,
                               fetch=lambda *a, **k: (_ for _ in ()).throw(AssertionError()),
                               deadline=999999999)
    assert result == {'status': 'review', 'reason': 'invalid_selection'}
