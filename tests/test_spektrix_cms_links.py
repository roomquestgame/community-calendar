"""First-party CMS page matching must be grounded in exact instance times."""
import pytest
from roomquest import spektrix_cms_links as cms

ORIGIN = 'https://www.thealbany.org.uk/events'
EVENT_ID = '347737AVNHRBKMRLMQKLLCMGLMCVVMMVC'
INSTANCE_ID = '299937ANMNMKPVNLKBKDNJVSDQGSDMHRC'
PAGE = ORIGIN + '/christmas-2026-the-gingerbread-man'


def event(**overrides):
    return {'id': EVENT_ID, 'name': 'Christmas 2026: The Gingerbread Man', **overrides}


def performance(**overrides):
    return {
        'id': INSTANCE_ID, 'event': {'id': EVENT_ID},
        'startUtc': '2026-12-05T14:00:00', 'cancelled': False, 'isOnSale': True,
        **overrides,
    }


def page(**overrides):
    return {
        'url': PAGE, 'title': 'Christmas 2026: The Gingerbread Man',
        'instances': ['2026-12-05T14:00:00+00:00'],
        **overrides,
    }


def test_exact_title_and_instant_resolve_first_party_craft_page():
    assert cms.resolve(ORIGIN, [event()], [performance()], [page()]) == {
        EVENT_ID: PAGE,
    }
    assert cms.resolve(ORIGIN, [event()], [performance()],
                       [page(instances=['2026-12-05T14:00:00Z'])]) == {
        EVENT_ID: PAGE,
    }


def test_match_requires_true_instance_overlap_and_title():
    assert cms.resolve(ORIGIN, [event()], [performance()],
                       [page(instances=['2026-12-06T14:00:00Z'])]) == {}
    assert cms.resolve(ORIGIN, [event()], [performance()],
                       [page(title='A completely different performance')]) == {}
    # Matching show titles alone never create event URLs.
    assert cms.resolve(ORIGIN, [event()], [], [page()]) == {}


def test_two_publisher_urls_for_one_performance_is_held():
    pages = [page(), page(url=ORIGIN + '/another-url')]
    with pytest.raises(ValueError, match='spektrix_page_link_ambiguous'):
        cms.resolve(ORIGIN, [event()], [performance()], pages)


def test_two_events_on_one_page_are_held_even_if_their_clocks_agree():
    second = {'id': '2' * 32, 'name': event()['name']}
    other_instance = performance(event={'id': second['id']}, id='3' * 32)
    with pytest.raises(ValueError, match='spektrix_page_event_identity_conflict'):
        cms.resolve(ORIGIN, [event(), second], [performance(), other_instance],
                    [page()])


@pytest.mark.parametrize('bad', [
    page(url='https://tickets.other-venue.com/website/ChooseSeats.aspx'),
    page(url='http://www.thealbany.org.uk/events/show'),
    page(url='https://www.thealbany.org.uk/events/show#fragment'),
    page(instances=['2026-12-05T14:00:00']),
])
def test_unverified_page_identity_and_naive_clocks_are_rejected(bad):
    with pytest.raises(ValueError, match='spektrix_page_(source_conflict|identity_invalid)'):
        cms.resolve(ORIGIN, [event()], [performance()], [bad])


def test_cancelled_or_unsold_instances_never_support_event_link():
    for entry in (performance(cancelled=True), performance(isOnSale=False)):
        assert cms.resolve(ORIGIN, [event()], [entry], [page()]) == {}


def test_duplicate_cms_page_claims_with_conflicting_schedule_are_rejected():
    with pytest.raises(ValueError, match='spektrix_page_identity_conflict'):
        cms.resolve(ORIGIN, [event()], [performance()],
                    [page(), page(instances=['2026-12-05T15:00:00Z'])])


def test_invalid_instance_and_event_data_fail_closed():
    with pytest.raises(ValueError, match='spektrix_page_instance_invalid'):
        cms.resolve(ORIGIN, [event()], ['wrong type'], [page()])
    with pytest.raises(ValueError, match='spektrix_page_event_invalid'):
        cms.resolve(ORIGIN, [{'name': 'No API ID'}], [performance()], [page()])
