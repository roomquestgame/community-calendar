"""Branded Spektrix stays in the registered-HTML durable intake path."""
from datetime import date, datetime, timedelta, timezone
import json

import pytest

from roomquest import registered_html_calendar as calendar
from roomquest import registered_html_checkpoint as checkpoint
from roomquest import registered_html_spektrix as adapter
from roomquest import registered_native_content as native
from roomquest import spektrix_v3 as api
from roomquest.registration_formats import source_key

LISTING = 'https://www.beaconartscentre.co.uk/whats-on/'
BASE = 'https://tickets.beaconartscentre.co.uk/beaconartscentre/api/v3'
EVENT = '347737AVNHRBKMRLMQKLLCMGLMCVVMMVC'
INSTANCE = '1928802AGPJVJCHJVPHSNVRRBPHQBSJJQ'
PLAN = '1801APGQPRKNVLCHGSKJBCTJKDRMGPLNL'
VENUE = '201AGBHDRLQHNHPHKKMPKLGPMDRDTDMVL'
STAMP = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
HTML = ('<html><head><link rel="import" href="' + BASE
        + '/webcomponents/html"></head><body><h1>What’s On</h1></body></html>')
COMPONENT = ('<html><body><spektrix-donate client-name="beaconartscentre" '
             'custom-domain="tickets.beaconartscentre.co.uk"></spektrix-donate></body></html>')
DETAIL = LISTING + 'event/beacon-christmas-show/'
INDEX = ('<html><body><main><h1>What’s On</h1><article><a href="' + DETAIL
         + '">Book Now</a></article></main></body></html>')


def source():
    return {'source_key': source_key(LISTING), 'feed_url': LISTING,
            'kind': 'html', 'platform_adapter': 'html',
            native.CAPABILITY: 1, native.HTML_CAPABILITY: 1,
            checkpoint.CAPABILITY: 1}


def payloads(start):
    event = {'id': EVENT, 'name': 'Beacon Christmas Show', 'description': 'Family fun',
             'webUrl': LISTING + 'beacon-christmas-show/', 'imageUrl': '', 'duration': 90}
    instance = {'id': INSTANCE, 'event': {'id': EVENT}, 'planId': PLAN,
                'start': start.isoformat() + 'T19:30:00',
                'startUtc': start.isoformat() + 'T19:30:00Z',
                'isOnSale': True, 'cancelled': False}
    out = {}
    for first, last in api.windows(start, start + timedelta(days=59)):
        out[api.api_url('beaconartscentre', 'events', start=first, end=last,
                        base=BASE)] = [event] if first <= start <= last else []
        out[api.api_url('beaconartscentre', 'instances', start=first, end=last,
                        base=BASE)] = [instance] if first <= start <= last else []
    out[api.api_url('beaconartscentre', 'venues', base=BASE)] = [{
        'id': VENUE, 'name': 'Beacon Arts Centre',
        'address': 'Custom House Quay<br>Greenock<br>PA15 1HJ'}]
    out[api.api_url('beaconartscentre', 'plans', identity=PLAN, base=BASE)] = {
        'id': PLAN, 'name': 'Main Auditorium', 'venue': {'id': VENUE}}
    return out


def test_complete_branded_api_uses_original_html_source(monkeypatch):
    start = date(2026, 12, 5)
    monkeypatch.setattr(adapter, '_today', lambda: start)
    responses = payloads(start)
    visited = []

    def fetch(url, accept):
        visited.append((url, accept))
        return json.dumps(responses[url])

    rows = calendar.collect(source(), fetch, listing=HTML)
    assert len(rows) == 1
    row = rows[0]
    assert row['venue_city'] == 'Greenock'
    assert row['venue_address'] == 'Custom House Quay Greenock PA15 1HJ'
    assert row['registered_native_content']['extraction'] == adapter.VERSION
    assert row['registered_native_content']['evidence_url'] == BASE
    native.validate_record(row, source())
    assert all(accept == 'application/json' for _, accept in visited)
    assert all(url.startswith(BASE + '/') for url, _ in visited)


def test_checkpoint_expands_only_from_captured_listing_evidence(monkeypatch):
    start = date(2026, 12, 5)
    monkeypatch.setattr(adapter, '_today', lambda: start)
    responses = payloads(start)
    first = checkpoint.collect_chunk(source(), lambda *_: pytest.fail('listing supplied'),
                                     listing=HTML, max_requests=1, at=STAMP)
    assert first['complete'] is False
    assert first['checkpoint']['cursor'] == 1
    fetched = []

    def fetch(url, accept):
        fetched.append(url)
        return json.dumps(responses[url])

    chunk = first
    while not chunk['complete']:
        chunk = checkpoint.collect_chunk(source(), fetch,
                                         checkpoint=chunk['checkpoint'], at=STAMP)
    assert len(chunk['events']) == 1
    assert len(fetched) == len(set(fetched)) == len(responses)
    assert first['checkpoint']['cursor'] == 1


def test_detail_advertised_api_expands_same_checkpoint_without_repeat(monkeypatch):
    start = date(2026, 12, 5)
    monkeypatch.setattr(adapter, '_today', lambda: start)
    responses = payloads(start)
    visited = []

    def fetch(url, accept):
        visited.append(url)
        if url == DETAIL:
            return COMPONENT
        return json.dumps(responses[url])

    first = checkpoint.collect_chunk(source(), fetch, listing=INDEX,
                                     max_requests=2, at=STAMP)
    assert first['complete'] is False
    assert first['checkpoint']['cursor'] == 2
    assert visited == [DETAIL]
    chunk = first
    while not chunk['complete']:
        chunk = checkpoint.collect_chunk(source(), fetch,
                                         checkpoint=chunk['checkpoint'], at=STAMP)
    assert len(chunk['events']) == 1
    assert visited[0] == DETAIL
    assert len(visited) == len(set(visited)) == len(responses) + 1


def test_blank_api_weburl_uses_exact_publisher_card_identity(monkeypatch):
    start = date(2026, 12, 5)
    monkeypatch.setattr(adapter, '_today', lambda: start)
    responses = payloads(start)
    for value in responses.values():
        if isinstance(value, list):
            for item in value:
                if item.get('id') == EVENT:
                    item['webUrl'] = ''
    page = HTML.replace(
        '</body>',
        '<article class="card"><h4>Beacon Christmas Show</h4>'
        '<a href="/event/beacon-christmas-show-347737/">Book Now</a>'
        '</article></body>')
    [row] = calendar.collect(source(), lambda url, accept: json.dumps(responses[url]),
                             listing=page)
    assert row['event_url'] == (
        'https://www.beaconartscentre.co.uk/event/beacon-christmas-show-347737/')


def test_listing_link_requires_prefix_and_exact_nearest_heading(monkeypatch):
    start = date(2026, 12, 5)
    monkeypatch.setattr(adapter, '_today', lambda: start)
    responses = payloads(start)
    for value in responses.values():
        if isinstance(value, list):
            for item in value:
                if item.get('id') == EVENT:
                    item['webUrl'] = ''
    wrong_title = HTML.replace(
        '</body>',
        '<article><h4>Different Show</h4>'
        '<a href="/event/beacon-christmas-show-347737/">Book Now</a>'
        '</article></body>')
    with pytest.raises(ValueError, match='spektrix_event_link_missing'):
        calendar.collect(source(), lambda url, accept: json.dumps(responses[url]),
                         listing=wrong_title)
    ambiguous = HTML.replace(
        '</body>',
        '<article><h4>Beacon Christmas Show</h4>'
        '<a href="/event/beacon-christmas-show-347737/">Book Now</a></article>'
        '<article><h4>Beacon Christmas Show</h4>'
        '<a href="/event/alternate-show-347737/">Book Now</a></article></body>')
    with pytest.raises(ValueError, match='html_spektrix_event_link_conflict'):
        calendar.collect(source(), lambda url, accept: json.dumps(responses[url]),
                         listing=ambiguous)


def test_detail_central_or_foreign_api_does_not_expand(monkeypatch):
    for host in ('system.spektrix.com', 'tickets.attacker.org.uk'):
        body = HTML.replace('tickets.beaconartscentre.co.uk', host)
        with pytest.raises(ValueError, match='html_calendar_event_jsonld_missing'):
            calendar.collect(source(), lambda *_: body, listing=INDEX)


def test_foreign_or_central_api_cannot_expand_html_transport():
    foreign = HTML.replace('tickets.beaconartscentre.co.uk', 'tickets.attacker.org.uk')
    assert not adapter.supports_listing(LISTING, foreign)
    assert adapter.verified_api_host(LISTING, foreign, BASE + '/venues') is None
    with pytest.raises(ValueError, match='html_spektrix_request_scope_invalid'):
        adapter.transport_hosts(source(), 'https://system.spektrix.com/beaconartscentre/api/v3/venues')


def test_spektrix_native_proof_is_not_jsonld_and_is_tamper_evident(monkeypatch):
    start = date(2026, 12, 5)
    monkeypatch.setattr(adapter, '_today', lambda: start)
    responses = payloads(start)
    [row] = calendar.collect(source(), lambda url, accept: json.dumps(responses[url]),
                             listing=HTML)
    row['registered_native_content']['client'] = 'otherclient'
    with pytest.raises(ValueError, match='registered_native_evidence_invalid'):
        native.validate_record(row, source())
