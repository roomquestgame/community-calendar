from urllib.parse import urlencode

import pytest

from roomquest.event_calendar_export import evidence
from roomquest.venue_resolver import extract_candidates, next_links

URL = 'https://venue.example/tm-event/show/'
IDENTITY = {'adapter': 'event_discovery', 'event_url': URL, 'event_title': 'Public show',
            'starts_at': '2026-12-01T03:00:00+00:00', 'original_venue_name': ''}


def page(**changes):
    query = {'action': 'TEMPLATE', 'text': 'Public show',
             'dates': '20261130T210000/20261130T210000', 'ctz': 'America/Chicago',
             'location': '1135 Decatur St,New Orleans,LA,US'}
    query.update(changes)
    return ('<html><link rel="canonical" href="' + URL + '"><h1>Public show</h1>'
            '<a href="https://www.google.com/calendar/event?' + urlencode(query) + '">Calendar</a></html>')


def test_exact_event_export_supplies_address_without_inventing_end_or_venue():
    answer = evidence(page(), URL, IDENTITY)
    assert answer == {'address': '1135 Decatur St, New Orleans, LA', 'evidence_url': URL,
                      'evidence_name': '1135 Decatur St, New Orleans, LA',
                      'method': 'event_calendar_export', 'calendar_start': '2026-12-01T03:00:00+00:00'}
    claim = {'provider': 'event_discovery', 'location_identity': IDENTITY}
    assert extract_candidates(page(), URL, claim) == [answer]
    assert next_links(page(), URL, claim) == []


@pytest.mark.parametrize('changes', [
    {'text': 'Other show'}, {'dates': '20261130T220000/20261130T220000'},
    {'ctz': 'America/Denver'}, {'location': 'Online'},
    {'location': '1135 Decatur St,New Orleans,LA,CA'}, {'action': 'DELETE'},
])
def test_other_occurrence_clock_or_nonphysical_location_cannot_resolve(changes):
    assert evidence(page(**changes), URL, IDENTITY) is None


def test_ambiguous_or_other_canonical_page_cannot_supply_location():
    assert evidence(page().replace('rel="canonical"', 'rel="alternate"'), URL, IDENTITY) is None
    assert evidence(page(), URL + '?other', IDENTITY) is None
    assert evidence(page() + page(location='1 Other St,New Orleans,LA,US'), URL, IDENTITY) is None
    # A second location in the same correctly canonicalized page is ambiguous too.
    second = page(location='1 Other St,New Orleans,LA,US').split('<a href=')[1].split('</a>')[0]
    assert evidence(page() + '<a href=' + second + '</a>', URL, IDENTITY) is None


def test_event_calendar_resolver_fetches_only_exact_event_inside_existing_claim_deadline():
    from unittest.mock import patch
    from roomquest import venue_resolver
    claim = {'provider': 'event_discovery', 'location_identity': IDENTITY,
             'event_url': URL, 'publisher_url': 'https://venue.example/',
             'evidence_hint': 'https://venue.example/footer/'}
    with patch.object(venue_resolver, 'fetch_page', return_value=page()) as fetch:
        answer = venue_resolver.resolve(claim, clock=lambda: 1, deadline=16)
        assert answer['method'] == 'event_calendar_export'
        fetch.assert_called_once_with(URL, deadline_at=16)
    with patch.object(venue_resolver, 'fetch_page', return_value='<html>Other page</html>') as fetch:
        assert venue_resolver.resolve(claim, clock=lambda: 1, deadline=16) is None
        fetch.assert_called_once_with(URL, deadline_at=16)
    with patch.object(venue_resolver, 'fetch_page') as fetch:
        assert venue_resolver.resolve(claim, clock=lambda: 12, deadline=16) is None
        fetch.assert_not_called()


def test_event_export_accepts_exact_publisher_open_graph_identity_without_canonical():
    og = page().replace('<link rel="canonical" href="' + URL + '">',
                        '<meta property="og:url" content="' + URL + '">')
    assert evidence(og, URL, IDENTITY)['method'] == 'event_calendar_export'
    assert evidence(og.replace('content="' + URL, 'content="https://venue.example/other'), URL, IDENTITY) is None
    assert evidence(og + '<link rel="canonical" href="https://venue.example/other">', URL, IDENTITY) is None
