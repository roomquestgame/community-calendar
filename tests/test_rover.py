import json

from roomquest.rover import candidates, select_candidate


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
