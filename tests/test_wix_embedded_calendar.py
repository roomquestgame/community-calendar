"""Public captured Wix listing facts, privacy exclusions and drift guards."""
from copy import deepcopy
from datetime import date, datetime, timezone
import json
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup
import pytest

from roomquest import preview_worker, wix_embedded_calendar as wix


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    # Keep the already-tested shared preview clock deterministic for this
    # publisher snapshot, while exercising the adapter's own 60-day bound.
    monkeypatch.setattr(preview_worker, '_future_datetime',
        lambda value: value.astimezone(timezone.utc) if value >= datetime(2026, 11, 22, 12, tzinfo=timezone.utc) else None)


def soup():
    return BeautifulSoup((Path(__file__).parent / 'fixtures/registered/mythic.html').read_text(), 'html.parser')


def edit(change):
    page = soup()
    script = page.find('script', id='wix-warmup-data')
    state = json.loads(script.string)
    events = state['appsWarmupData'][wix.WIX_EVENTS]['widgetPublicList']['events']['events']
    change(events)
    script.string = json.dumps(state)
    return page


def collect(page):
    return list(wix.rows(page, wix.MYTHIC, date(2026, 11, 22)))


def test_publisher_times_street_and_sold_out_evidence_without_private_event():
    result = collect(soup())
    assert [r['title'] for r in result] == ['The Gilded Shepard', 'The Book of Cylinders']
    assert result[0]['starts_at'] == '2026-11-28T22:00:00+00:00'
    assert result[0]['ends_at'] == '2026-11-29T01:00:00+00:00'
    assert all(r['timezone'] == 'America/New_York' for r in result)
    assert all(r['venue_address'] == '918 Commerce Street (3rd Floor), Lynchburg, VA 24504, USA' for r in result)
    assert all(r['lat'] is None and r['lng'] is None for r in result)
    assert 'Tickets sold out.' in result[1]['description']
    assert 'Tickets sold out.' not in result[0]['description']


@pytest.mark.parametrize('change', [
    lambda e: e[0].update(status=2),
    lambda e: e[0].pop('publishedDate'),
    lambda e: e[0]['registration'].update(restrictedTo=2),
    lambda e: e[0].update(description='Private invitation-only event'),
    lambda e: e[0]['location'].update(tbd=True),
    lambda e: e[0]['location']['fullAddress'].update(country='CA'),
    lambda e: e[0]['location'].update(address='Venue to be announced'),
    lambda e: e[0]['scheduling']['config'].update(scheduleTbd=True),
    lambda e: e[0]['scheduling']['config'].update(timeZoneId='Mars/Base'),
    lambda e: e[0]['scheduling']['config'].update(startDate='2026-11-28T22:00:00'),
    lambda e: e[0]['scheduling']['config'].update(startDate='2027-12-01T22:00:00Z'),
    lambda e: e[0]['calendarLinks'].update(google='https://calendar.google.com.evil.example/calendar/render?action=TEMPLATE'),
    lambda e: e[0]['calendarLinks'].update(google=e[0]['calendarLinks']['google'].replace('20261128T220000Z', '20261128T230000Z')),
])
def test_unpublished_private_incomplete_or_conflicting_facts_are_held(change):
    result = collect(edit(change))
    assert [r['title'] for r in result] == ['The Book of Cylinders']


def test_hidden_record_and_cross_host_link_are_not_published():
    page = soup()
    anchor = page.find('a', string='The Gilded Shepard')
    anchor['href'] = anchor['href'].replace('www.mythichall.com', 'evil.example')
    assert [r['title'] for r in collect(page)] == ['The Book of Cylinders']


def test_duplicate_widgets_deduplicate_and_conflicts_fail_closed():
    assert len(collect(edit(lambda e: e.append(deepcopy(e[0]))))) == 2
    def conflict(events):
        duplicate = deepcopy(events[0])
        duplicate['description'] = 'Changed publisher description'
        events.append(duplicate)
    with pytest.raises(ValueError, match='conflicting_event_occurrence'):
        collect(edit(conflict))


def test_oversized_widget_and_missing_public_state_fail_closed():
    with pytest.raises(ValueError, match='wix_schedule_limit_exceeded'):
        collect(edit(lambda e: e.extend([deepcopy(e[0])] * 251)))
    with pytest.raises(ValueError, match='wix_public_schedule_unverified'):
        collect(BeautifulSoup('<main>No events</main>', 'html.parser'))


def test_publisher_hidden_end_is_not_invented():
    result = collect(edit(lambda e: e[0]['scheduling']['config'].update(endDateHidden=True)))
    assert result[0]['ends_at'] is None


def test_normal_registration_uses_reviewed_html_despite_legacy_ical_hint():
    from roomquest.feed_registration import register
    with patch('roomquest.feed_registration.supabase_rpc',
               side_effect=[{'id': 198, 'url': wix.MYTHIC, 'type_hint': 'ical'}, True]) as rpc, \
         patch('roomquest.feed_registration.fetch_publisher', return_value=str(soup())) as fetch, \
         patch('roomquest.registered_listings.datetime') as listing_clock:
        listing_clock.now.return_value = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
        assert register('one-time-ticket') == {'outcome': 'verified'}
    assert rpc.call_args.args[1] == {'p_ticket': 'one-time-ticket', 'p_outcome': 'verified',
                                   'p_type': 'html', 'p_endpoint': wix.MYTHIC}
    fetch.assert_called_once()
    assert fetch.call_args.kwargs['respect_robots'] is True
    assert fetch.call_args.kwargs['deadline_at'] > 0


def test_exact_source_identity_is_required_before_loading_html():
    from roomquest import registered_listings
    with pytest.raises(ValueError, match='unregistered_html_source'):
        registered_listings.collect({'feed_url': wix.MYTHIC, 'source_key': 'wrong'},
                                    lambda *_: pytest.fail('fetch before identity check'))
    with pytest.raises(ValueError, match='unregistered_html_source'):
        registered_listings.allowed_hosts(wix.MYTHIC + '?private=true')
