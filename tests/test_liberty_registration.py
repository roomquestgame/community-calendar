"""Real Liberty registration/preview dispatch; only network and RPC are stubbed."""
from contextlib import ExitStack
from datetime import datetime, timezone
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from roomquest import feed_registration as registration
from roomquest import liberty_calendar as liberty
from roomquest import preview_worker as worker
from roomquest import registered_listings as listings

FIXTURE = Path(__file__).parent / 'fixtures/liberty/public-events.json'
TOKEN = 'eyJhbGciOiJIUzI1NiJ9.eyJndWVzdCI6dHJ1ZX0.' + 's' * 43
CHUNKS = tuple('/_next/static/chunks/' + char * 16 + '.js' for char in 'abc')
SCRIPT_URL = liberty.ORIGINAL.rstrip('/') + CHUNKS[1]
SCRIPT = ';'.join(
    '(0,p.createServerReference)("00' + char * 40
    + '",p.callServer,void 0,p.findSourceMapURL,"' + getter + '")'
    for getter, char in (('getApiUrl', '6'), ('getApiToken', '7')))
LISTING = ''.join('<script src="' + path + '"></script>' for path in CHUNKS) + (
    '<script>self.__next_f.push(' + json.dumps([1, '5:I' + json.dumps([27232, list(CHUNKS), 'AuthProvider']) + '\n'])
    + ')</script>')


class FrozenMeta(type):
    def __instancecheck__(cls, value):
        return isinstance(value, datetime)


class FrozenDateTime(datetime, metaclass=FrozenMeta):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 11, 22, 12, tzinfo=timezone.utc)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def freeze_clock(monkeypatch):
    # Keep the actual shared normalizer and future-date checks running against
    # the fixture's reviewed date, without replacing record() or description().
    monkeypatch.setattr(liberty, 'datetime', FrozenDateTime)
    monkeypatch.setattr(worker, 'datetime', FrozenDateTime)
    monkeypatch.setattr(listings, 'datetime', FrozenDateTime)


def source():
    return dict(source_key=liberty.SOURCE_KEY, feed_url=liberty.ORIGINAL,
                kind='html', platform_adapter='html', timezone=liberty.ZONE)


def public_action(**options):
    assert options['script_url'] == SCRIPT_URL and options['script'] == SCRIPT
    assert options['getter'] in liberty.GETTERS
    head = '0:{"a":"$@1","b":"synthetic-public-build"}\n'
    if options['getter'] == 'getApiUrl':
        return head + '1:' + json.dumps(liberty.API_ORIGIN) + '\n'
    return head + '2:T' + format(len(TOKEN), 'x') + ',' + TOKEN + '1:"$2"\n'


def network_stubs(*, payload=None):
    def fetch(url, accept, **options):
        if url == liberty.ORIGINAL:
            return LISTING
        if url == SCRIPT_URL:
            assert accept == 'application/javascript'
            return SCRIPT
        if url == liberty.ORIGINAL.rstrip('/') + CHUNKS[2]:
            assert accept == 'application/javascript'
            return '/* another referenced public app chunk */'
        pytest.fail('Unexpected network target: ' + url)
    return (Mock(side_effect=fetch), Mock(side_effect=public_action),
            Mock(return_value=payload or FIXTURE.read_text()))


def enter_network(stack, module, stubs):
    fetch, action, events = stubs
    stack.enter_context(patch.object(module, 'fetch_publisher', fetch))
    stack.enter_context(patch.object(worker, 'read_liberty_public_action', action))
    stack.enter_context(patch.object(worker, 'read_liberty_events', events))
    return stubs


def assert_transport_contract(stubs, *, first_accept):
    fetch, action, events = stubs
    assert [call.args[0] for call in fetch.call_args_list] == [
        liberty.ORIGINAL, liberty.ORIGINAL.rstrip('/') + CHUNKS[2], SCRIPT_URL]
    assert fetch.call_args_list[0].args[1] == first_accept
    deadline = fetch.call_args_list[0].kwargs['deadline_at']
    assert deadline > 0
    for call in fetch.call_args_list:
        assert call.kwargs == dict(respect_robots=True, deadline_at=deadline,
                                  allowed_hosts=('events.liberty.edu',), follow_redirects=False)
    assert [call.kwargs['getter'] for call in action.call_args_list] == ['getApiUrl', 'getApiToken']
    assert all(call.kwargs['deadline_at'] == deadline for call in action.call_args_list)
    events.assert_called_once_with(page=1, window_start=FrozenDateTime.now().date(),
                                   public_token=TOKEN, deadline_at=deadline)


@pytest.mark.parametrize('hint', [None, 'ical'])
def test_normal_registration_automatically_uses_html_for_original_receipt_and_legacy_hint(hint):
    stubs = network_stubs()
    with ExitStack() as stack:
        enter_network(stack, registration, stubs)
        rpc = stack.enter_context(patch.object(registration, 'supabase_rpc', side_effect=[
            {'id': 227, 'url': liberty.ORIGINAL, 'type_hint': hint}, True]))
        assert registration.register('existing-receipt-ticket') == {'outcome': 'verified'}
    assert_transport_contract(stubs, first_accept=registration.ACCEPT)
    assert [call.args[0] for call in rpc.call_args_list] == [
        'community_collector_claim_registration', 'community_collector_finish_registration']
    assert rpc.call_args_list[0].args[1] == {'p_ticket': 'existing-receipt-ticket'}
    assert rpc.call_args_list[-1].args[1] == {
        'p_ticket': 'existing-receipt-ticket', 'p_outcome': 'verified',
        'p_type': 'html', 'p_endpoint': liberty.ORIGINAL,
    }
    assert TOKEN not in repr(rpc.call_args_list)


def test_recurring_html_preview_reuses_exact_guarded_dispatch_and_real_normalizer():
    stubs = network_stubs()
    with ExitStack() as stack:
        enter_network(stack, worker, stubs)
        rpc = stack.enter_context(patch.object(worker, 'supabase_rpc'))
        result = worker.preview_source(source(), deadline_at=worker.monotonic() + 45)
    assert_transport_contract(stubs, first_accept='text/html')
    rpc.assert_not_called()
    assert result['p_source_key'] == liberty.SOURCE_KEY
    assert result['p_future_count'] == 4 and result['p_venue_count'] == 0 and result['p_error'] is None
    rows = result['p_events']
    assert [row['id'] for row in rows] == [
        'liberty-occurrence:33920', 'liberty-occurrence:34926',
        'liberty-occurrence:34143', 'liberty-occurrence:33507']
    assert rows[0]['starts_at'] == '2026-11-29T23:00:00+00:00'
    assert rows[0]['ends_at'] == '2026-11-30T04:00:00+00:00'
    assert all(row['timezone'] == 'America/New_York' and row['lat'] is None and row['lng'] is None for row in rows)
    assert all(row['reason'] == 'missing_verified_venue_geo' for row in rows)
    assert all(row['event_url'].startswith(liberty.ORIGINAL + 'event/') for row in rows)
    assert all(row['description'] and '<' not in row['description'] for row in rows)
    assert not any('Hockey' in row['title'] or row['title'] == 'Thanksgiving' for row in rows)
    assert TOKEN not in json.dumps(result)


def test_registry_dispatch_retains_public_description_without_admin_metadata():
    payload = json.loads(FIXTURE.read_text())
    event = next(item for item in payload['events'] if item['eventId'] == 17107)
    event['eventDescription'] = '<nav>Navigation only</nav><p>Public bowling &amp; shoe rental.</p><script>privateMarker()</script>'
    event['creatorUser'] = {'email': 'never-copy@example.test'}
    event['metadata'] = [{'metadataName': 'admin_note', 'metadataValue': 'never persist this'}]
    stubs = network_stubs(payload=json.dumps(payload))
    with ExitStack() as stack:
        enter_network(stack, worker, stubs)
        result = worker.preview_source(source())
    row = next(item for item in result['p_events'] if item['id'] == 'liberty-occurrence:33920')
    assert row['description'] == 'Public bowling & shoe rental.'
    assert row['venue_name'] == 'Montview Student Union'
    assert row['venue_address'] == '1410 Regents Pkwy, Lynchburg, VA 24515'
    output = json.dumps(result)
    assert all(value not in output for value in ('Navigation only', 'privateMarker', 'never-copy', 'never persist', TOKEN))


@pytest.mark.parametrize('changed', [
    {'source_key': 'municipal_' + '0' * 24},
    {'feed_url': liberty.ORIGINAL.rstrip('/')},
    {'feed_url': liberty.ORIGINAL + '?private=true'},
    {'feed_url': liberty.API_ORIGIN + '/events'},
])
def test_registry_and_recurring_preview_reject_changed_source_or_original_url_before_network(changed):
    claim = {**source(), **changed}
    stubs = network_stubs()
    with ExitStack() as stack:
        enter_network(stack, worker, stubs)
        with pytest.raises(ValueError, match='^unregistered_html_source$'):
            listings.collect(claim, stubs[0], listing=LISTING)
        with pytest.raises(worker.PreviewError, match='^unregistered_html_source$'):
            worker.preview_source(claim)
    for stub in stubs:
        stub.assert_not_called()


@pytest.mark.parametrize('where', ['root', 'script', 'bootstrap', 'events'])
def test_normal_registration_preserves_access_denial_at_each_public_read(where):
    stubs = network_stubs()
    fetch, action, events = stubs
    if where in ('root', 'script'):
        real_side_effect = fetch.side_effect
        def denied(url, accept, **options):
            if (where == 'root' and url == liberty.ORIGINAL) or (where == 'script' and url == SCRIPT_URL):
                raise worker.PreviewError('publisher_http_403')
            return real_side_effect(url, accept, **options)
        fetch.side_effect = denied
    elif where == 'bootstrap':
        action.side_effect = worker.PreviewError('publisher_http_403')
    else:
        events.side_effect = worker.PreviewError('publisher_http_403')
    with ExitStack() as stack:
        enter_network(stack, registration, stubs)
        rpc = stack.enter_context(patch.object(registration, 'supabase_rpc', side_effect=[
            {'id': 227, 'url': liberty.ORIGINAL, 'type_hint': None}, True]))
        assert registration.register('same-ticket') == {'outcome': 'disabled'}
    assert rpc.call_args.args[1] == {'p_ticket': 'same-ticket', 'p_outcome': 'disabled', 'p_reason': 'publisher_http_403'}
    if where in ('root', 'script'):
        action.assert_not_called()
    if where != 'events':
        events.assert_not_called()


def test_incomplete_public_page_cannot_verify_registration_or_complete_recurring_preview():
    data = json.loads(FIXTURE.read_text())
    data['queryInfo']['totalResults'] = 101
    data['queryInfo']['totalPages'] = 2
    stubs = network_stubs(payload=json.dumps(data))
    with ExitStack() as stack:
        enter_network(stack, registration, stubs)
        rpc = stack.enter_context(patch.object(registration, 'supabase_rpc', side_effect=[
            {'id': 227, 'url': liberty.ORIGINAL}, True]))
        assert registration.register('same-ticket') == {'outcome': 'review'}
    assert rpc.call_args.args[1]['p_reason'] == 'liberty_calendar_limit'
    stubs = network_stubs(payload=json.dumps(data))
    with ExitStack() as stack:
        enter_network(stack, worker, stubs)
        with pytest.raises(worker.PreviewError, match='^liberty_calendar_limit$'):
            worker.preview_source(source())
    stubs[2].assert_called_once()
