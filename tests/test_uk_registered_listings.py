from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from roomquest import preview_worker
from roomquest import uk_registered_listings as uk


class FrozenMeta(type):
    def __instancecheck__(cls, value):
        return isinstance(value, datetime)


class FrozenDateTime(datetime, metaclass=FrozenMeta):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 11, 22, 10, tzinfo=timezone.utc)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(uk, 'datetime', FrozenDateTime)
    monkeypatch.setattr(preview_worker, 'datetime', FrozenDateTime)


def source(url):
    return {'feed_url': url, 'source_key': uk.source_key(url)}


WIX = '''<li data-hook="event-list-item">
  <span data-hook="ev-list-item-title">Run Bike Run November</span>
  <a data-hook="ev-rsvp-button" href="https://www.miltoncountrypark.org/event-details/run-bike-run-november">Details</a>
  <div data-hook="ev-full-date-location"><div data-hook="date">28 Nov 2026, 10:30 – 12:30</div>
  <div data-hook="location">Milton, Cambridge Rd, Milton, Cambridge CB24 6AZ, UK</div></div>
  <div data-hook="ev-list-item-description">Come and try Run Bike Run.</div>
</li>'''
WINE_URL = uk.WINE + 'napa/napa/25-11-2026/'
WINE_CARD = '''<div class="upcoming-event"><h3>Napa</h3><h4>Napa</h4>
  <p class="when">November 26<sup>th</sup> - 7:00pm<div><p class="price">£40
  <p class="button"><a href="/wine-tastings/napa/napa/25-11-2026/">Book</a></div></div>'''
WINE_PAGE = '''<html><head><title>26-11-2026 | The Cambridge Wine Academy</title></head>
<body><div class="split-right"><div class="split-right-event"><h1>Napa<br>Napa</h1><ul>
  <li><span><i class="fa-clock"></i></span><span>November 26<sup>th</sup> - 7:00pm</span></li>
  <li><span><i class="fa-map-marker-alt"></i></span><span>The Wine Rooms Cambridge, 57 Hills Rd, Cambridge CB2 1NT</span></li>
</ul></div><div class="content-styling"><p>Published tasting description.</p>
<div class="quantity"><form>Enter quantity<input></form></div></div></div></body></html>'''


def test_wix_visible_full_date_address_without_detail_requests():
    fetch = Mock(side_effect=AssertionError('No extra request permitted'))
    rows = uk.collect(source(uk.MILTON), fetch, listing=WIX)
    assert len(rows) == 1
    assert rows[0]['starts_at'] == '2026-11-28T10:30:00+00:00'
    assert rows[0]['ends_at'] == '2026-11-28T12:30:00+00:00'
    assert rows[0]['venue_address'].endswith('CB24 6AZ, UK')
    assert rows[0]['venue_name'] == 'Milton Country Park'
    assert rows[0]['lat'] is None and rows[0]['lng'] is None
    assert rows[0]['timezone'] == 'Europe/London'
    fetch.assert_not_called()


def test_wix_duplicate_cards_and_recurring_ribbon_do_not_invent_dates():
    rows = uk.collect(source(uk.MILTON), Mock(), listing=WIX * 2 +
                      WIX.replace('28 Nov 2026', '21 Jan 2024').replace('</li>', '<span>Multiple Dates</span></li>'))
    assert len(rows) == 1


def test_wix_explicit_end_date_is_retained():
    rows = uk.collect(source(uk.MILTON), Mock(), listing=WIX.replace('10:30 – 12:30', '10:30 – 29 Nov 2026, 12:30'))
    assert rows[0]['ends_at'] == '2026-11-29T12:30:00+00:00'


@pytest.mark.parametrize('old,new,reason', [
    ('12:30', '09:30', 'schedule_unverified'),
    ('CB24 6AZ', 'CB23 7PY', 'venue_unverified'),
    ('https://www.miltoncountrypark.org/event-details/', 'https://evil.test/event-details/', 'identity_unverified'),
    ('run-bike-run-november"', 'run-bike-run-november?lightbox=test"', 'identity_unverified'),
])
def test_wix_changed_evidence_holds(old, new, reason):
    with pytest.raises(ValueError, match=reason):
        uk.collect(source(uk.MILTON), Mock(), listing=WIX.replace(old, new))


def test_wix_pagination_does_not_silently_truncate():
    with pytest.raises(ValueError, match='pagination_requires_review'):
        uk.collect(source(uk.MILTON), Mock(), listing=WIX + '<button data-hook="load-more-button">More</button>')


def test_wine_rescheduled_url_uses_current_complete_publisher_date():
    fetch = Mock(return_value=WINE_PAGE)
    rows = uk.collect(source(uk.WINE), fetch, listing=WINE_CARD * 2)
    assert len(rows) == 1
    assert rows[0]['starts_at'] == '2026-11-26T19:00:00+00:00'
    assert rows[0]['ends_at'] is None
    assert rows[0]['event_url'] == WINE_URL
    assert rows[0]['venue_address'] == '57 Hills Rd, Cambridge CB2 1NT, United Kingdom'
    assert rows[0]['description'] == 'Published tasting description.'
    assert rows[0]['timezone'] == 'Europe/London'
    fetch.assert_called_once_with(WINE_URL, 'text/html')


def test_wine_explicit_arrival_and_duration():
    page = WINE_PAGE.replace('Published tasting description.',
                            'The tasting lasts two hours, and nibbles are included. Please arrive at 7pm for a 7.15pm start.')
    row = uk.collect(source(uk.WINE), Mock(return_value=page), listing=WINE_CARD)[0]
    assert row['starts_at'] == '2026-11-26T19:15:00+00:00'
    assert row['ends_at'] == '2026-11-26T21:15:00+00:00'


def test_wine_exact_branch_address_completion():
    page = WINE_PAGE.replace('The Wine Rooms Cambridge, 57 Hills Rd, Cambridge CB2 1NT',
                            'Cambridge Wine Merchants, Cherry Hinton Road, CB1 7BX')
    row = uk.collect(source(uk.WINE), Mock(return_value=page), listing=WINE_CARD)[0]
    assert row['venue_address'] == '163 Cherry Hinton Road, Cambridge CB1 7BX, United Kingdom'


@pytest.mark.parametrize('old,new,reason', [
    ('26-11-2026 |', '25-11-2026 |', 'schedule_conflict'),
    ('<h1>Napa<br>Napa</h1>', '<h1>Different event</h1>', 'identity_unverified'),
    ('November 26', 'November 25', 'schedule_conflict'),
    ('7:00pm', '8:00pm', 'schedule_conflict'),
    ('57 Hills Rd', '99 Hills Rd', 'venue_unverified'),
    ('26-11-2026 |', 'Unknown date |', 'identity_unverified'),
])
def test_wine_changed_evidence_holds(old, new, reason):
    with pytest.raises(ValueError, match=reason):
        uk.collect(source(uk.WINE), Mock(return_value=WINE_PAGE.replace(old, new)), listing=WINE_CARD)


def test_wine_courses_and_far_future_details_are_not_requested():
    fetch = Mock(return_value=WINE_PAGE)
    other = WINE_CARD.replace('/wine-tastings/', '/wine-courses/')
    later = WINE_CARD.replace('November 26', 'February 3').replace(' - 7:00pm', ', 2027 - 7:00pm')
    assert len(uk.collect(source(uk.WINE), fetch, listing=WINE_CARD + other + later)) == 1
    fetch.assert_called_once()


def test_wine_detail_budget_fails_before_fetch():
    fetch = Mock()
    cards = ''.join(WINE_CARD.replace('/napa/napa/', f'/napa-{i}/napa/') for i in range(uk.MAX_DETAILS + 1))
    with pytest.raises(ValueError, match='wine_calendar_detail_limit'):
        uk.collect(source(uk.WINE), fetch, listing=cards)
    fetch.assert_not_called()


@pytest.mark.parametrize('url', [uk.MILTON + '?lightbox=anything', uk.WINE + '?all=1', 'https://evil.test/whats-on'])
def test_unknown_source_url_is_not_accepted(url):
    fetch = Mock()
    with pytest.raises(ValueError, match='unregistered_html_source'):
        uk.collect(source(url), fetch, listing=WIX)
    fetch.assert_not_called()


def test_source_identity_and_deadline_are_preserved():
    fetch = Mock()
    with pytest.raises(ValueError, match='unregistered_html_source'):
        uk.collect({'feed_url': uk.MILTON, 'source_key': 'wrong'}, fetch, listing=WIX)
    with pytest.raises(ValueError, match='collection_deadline'):
        uk.collect(source(uk.MILTON), fetch, deadline_at=0, listing=WIX)
    fetch.assert_not_called()
