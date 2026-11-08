"""Captured publisher replay and adversarial boundary tests; no network I/O."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock
from xml.etree import ElementTree

from bs4 import BeautifulSoup
import pytest

from roomquest import holly_hill_institution_recovery as parser
from roomquest import preview_worker

FIXTURES = Path(__file__).with_name('fixtures') / 'holly_hill_institution_recovery'
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


class ClockMeta(type):
    def __instancecheck__(cls, value):
        return isinstance(value, datetime)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    class FrozenDatetime(datetime, metaclass=ClockMeta):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(parser, 'datetime', FrozenDatetime)
    monkeypatch.setattr(preview_worker, 'datetime', FrozenDatetime)


def fixture(name):
    return (FIXTURES / name).read_text()


def source(key):
    return dict(source_key=key, feed_url=parser.SOURCES[key], kind='html',
                platform_adapter='html', timezone=parser.ZONE)


def listing(program_id=100):
    return next(x for x in parser.parse_program_listing(fixture('recdesk_programs.html'))
                if x['url'].endswith('=' + str(program_id)))


def program(program_id=100, payload=None):
    return parser.parse_program(payload or fixture(f'recdesk_{program_id}.html'), listing(program_id))


def feed(single=False):
    root = ElementTree.fromstring(fixture('ymca_branch_feed.xml'))
    if single:
        for item in root.findall('./channel/item')[1:]:
            root.find('channel').remove(item)
    return root


def article(root=None):
    payload = ElementTree.tostring(root if root is not None else feed(True), encoding='unicode')
    return parser._ymca_feed(payload)[0]


def ymca_collect(payload=None, details=None, diagnostics=None):
    responses = {parser.YMCA_RSS: payload if payload is not None else fixture('ymca_branch_feed.xml'),
                 article()['url']: details if details is not None else fixture('ymca_craft.html')}
    fetch = Mock(side_effect=lambda url, accept: responses[url])
    rows = parser.collect(source(parser.ORANGEBURG_YMCA), fetch, diagnostics=diagnostics)
    return rows, fetch


def test_capture_manifest_matches_sanitized_publisher_fixtures():
    manifest = json.loads(fixture('capture_manifest.json'))
    for entry in manifest['sanitized_fixtures']:
        payload = (FIXTURES / entry['name']).read_bytes()
        assert len(payload) == entry['bytes']
        assert hashlib.sha256(payload).hexdigest() == entry['sha256']


def test_complete_recdesk_replay_has_five_programs_and_no_cart_or_registration_fetches():
    fetch = Mock(side_effect=lambda url, accept: fixture('recdesk_' + url.split('=')[-1] + '.html'))
    display = Mock(return_value=fixture('recdesk_programs.html'))
    rows = parser.collect(source(parser.OLD_SANTEE), fetch, fetch_programs=display)
    assert len(rows) == 5
    display.assert_called_once_with()
    assert fetch.call_count == 5
    assert all(parser.event_url(parser.OLD_SANTEE, call.args[0]) and call.args[1] == 'text/html'
               for call in fetch.call_args_list)
    assert all(row['lat'] is row['lng'] is None for row in rows)
    assert all(row['timezone'] == parser.ZONE and 'image_url' not in row for row in rows)
    assert all(row['details_evidence_url'] == row['event_url'] for row in rows)
    assert all(set(row['publisher_details']) <= {'cost', 'registration', 'audience', 'meeting_location'}
               for row in rows)


def test_offsite_bird_walk_does_not_inherit_park_footer_address():
    row = program()[0]
    assert row['title'] == 'Camp Hall Guided Bird Walk'
    assert (row['starts_at'], row['ends_at']) == ('2026-12-05T14:00:00+00:00', '2026-12-05T16:00:00+00:00')
    assert (row['venue_name'], row['venue_address'], row['venue_city']) == (
        'Refuel gas station', '309 Avian Pavilion Ln, Ridgeville, SC 29472', 'Ridgeville')
    assert row['publisher_details']['cost'] == 'Individual Registration: $5.00'
    assert '3 places remaining' in row['publisher_details']['registration']
    assert 'No residency or membership restrictions' in row['publisher_details']['registration']
    assert 'Registration deadline: 12/4/2026 12:00 PM' in row['publisher_details']['registration']


def test_tinsel_uses_course_hours_not_packet_pickup_or_registration_deadline():
    row = program(95)[0]
    assert (row['starts_at'], row['ends_at']) == ('2026-11-21T22:30:00+00:00', '2026-11-22T01:00:00+00:00')
    assert row['venue_address'] == parser.PARK_ADDRESS
    assert row['publisher_details']['cost'] == 'Adult Registration: $20.00; Child (0-6 years old) no shirt: $0.00'
    assert 'Commemorative Ornament' not in row['publisher_details']['cost']
    assert 'Children under 6 years are FREE' in row['description']


def test_full_homeschool_program_keeps_waitlist_cost_and_age_evidence():
    row = program(99)[0]
    assert 'Full; waitlist available' in row['publisher_details']['registration']
    assert 'Full; waitlist available' in row['description']
    assert row['publisher_details']['cost'] == 'Adult Registration: $2.00; Child Registration: $2.00'
    assert row['publisher_details']['audience'] == 'All ages, under 13 accompanied by an adult. Registration ages: 3y'
    assert 'Canal Room' in row['venue_name']
    assert row['starts_at'] == '2026-11-11T15:00:00+00:00'


def test_tots_age_limits_and_adult_fee_exception_survive():
    row = program(101)[0]
    assert row['publisher_details']['audience'] == '2 – 5-year-olds (with an adult). Registration ages: 2y - 5y'
    assert '$5 per child (adults are free)' in row['description']
    assert row['ends_at'] == '2026-12-16T16:30:00+00:00'
    assert 'Oak Room' in row['venue_name']


@pytest.mark.parametrize('program_id,old,new,error', [
    (101, 'Time: 10 am – 11:30 am', 'Time: 9 am – 11:30 am', 'schedule_conflict'),
    (95, 'The course opens at 5:30pm', 'The course opens at 6:30pm', 'schedule_conflict'),
    (101, 'Program Fee: $5 per child', 'Program Fee: $8 per child', 'fee_conflict'),
])
def test_explicit_narrative_and_schedule_or_fee_conflicts_are_held(program_id, old, new, error):
    payload = fixture(f'recdesk_{program_id}.html')
    assert old in payload
    with pytest.raises(ValueError, match=error):
        program(program_id, payload.replace(old, new))


@pytest.mark.parametrize('old,new', [
    ('Displaying 1 - 5 of 5', 'Displaying 1 - 5 of 6'),
    ('Displaying 1 - 5 of 5', 'Displaying 1 - 25 of 26'),
    ('Displaying 1 - 5 of 5', 'Displaying 0 - 0 of 0'),
    ('programId=100', 'programId=99'),
    ('11/21/2026', '11/22/2026'),
    ('/Community/Program/Detail?programId=100', 'https://evil.example/Community/Program/Detail?programId=100'),
])
def test_partial_changed_duplicate_or_foreign_listing_is_not_a_success(old, new):
    with pytest.raises(ValueError):
        parser.parse_program_listing(fixture('recdesk_programs.html').replace(old, new))


def test_get_shell_is_not_mistaken_for_a_genuinely_empty_recdesk_response():
    with pytest.raises(ValueError, match='recdesk_listing_structure_changed'):
        parser.parse_program_listing(fixture('recdesk_index_shell.html'))


@pytest.mark.parametrize('selector,value,error', [
    ('#program-schedule [data-label="Day"]', 'Sunday', 'weekday_conflict'),
    ('#program-schedule [data-label="Date"]', '12/12/2026', 'listing_schedule_conflict'),
    ('#program-schedule [data-label="Start Time"]', 'TBA', 'time_unresolved'),
    ('#program-schedule [data-label="End Time"]', '8:00 AM', 'schedule_conflict'),
    ('#program-fees [data-label="Membership Restrictions"]', 'Members only', 'eligibility_unverified'),
    ('#program-fees [data-label="Amount"]', 'Call for pricing', 'fee_unresolved'),
])
def test_recdesk_conflicting_required_fields_fail_closed(selector, value, error):
    soup = BeautifulSoup(fixture('recdesk_100.html'), 'html.parser')
    soup.select_one(selector).string = value
    with pytest.raises(ValueError, match=error):
        program(payload=str(soup))


def test_missing_offsite_address_is_not_repaired_from_footer():
    payload = fixture('recdesk_100.html').replace('309 Avian Pavilion Ln, Ridgeville, SC 29472', 'Meeting point to be confirmed')
    with pytest.raises(ValueError, match='recdesk_venue_unverified'):
        program(payload=payload)


@pytest.mark.parametrize('old,new', [('facilityId=2', 'facilityId=99'), ('Oak Room', 'Another Room'),
                                    ('Meeting Place: Interpretive Center', 'Meeting Place: Offsite')])
def test_room_alias_requires_exact_occurrence_evidence(old, new):
    with pytest.raises(ValueError, match='recdesk_venue_unverified'):
        program(101, fixture('recdesk_101.html').replace(old, new))


def test_program_canonical_identity_conflict_fails_closed():
    with pytest.raises(ValueError, match='identity_conflict'):
        program(payload=fixture('recdesk_100.html').replace('programId=100', 'programId=101'))


@pytest.mark.parametrize('notice', ['This class is cancelled.', 'This is a private event.'])
def test_cancelled_or_private_notice_is_checked_before_narrative_truncation(notice):
    soup = BeautifulSoup(fixture('recdesk_100.html'), 'html.parser')
    soup.select_one('#program-detail .well').append('Background. ' * 350 + notice)
    assert program(payload=str(soup)) == []


def test_one_failed_program_detail_does_not_return_partial_source_success():
    fetch = Mock(side_effect=[fixture('recdesk_99.html'), TimeoutError('publisher unavailable')])
    with pytest.raises(TimeoutError):
        parser.collect(source(parser.OLD_SANTEE), fetch, fetch_programs=lambda: fixture('recdesk_programs.html'))
    assert fetch.call_count == 2


def test_ymca_full_feed_replay_keeps_craft_and_uses_only_two_requests():
    diagnostics = []
    rows, fetch = ymca_collect(diagnostics=diagnostics)
    assert len(rows) == 1
    row = rows[0]
    assert (row['starts_at'], row['ends_at']) == ('2026-12-05T15:00:00+00:00', '2026-12-05T17:00:00+00:00')
    assert row['venue_address'] == '2550 St Matthews Rd NE, Orangeburg, SC 29118'
    assert row['publisher_details']['cost'] == '$15 for Members, $20 for Non-Members'
    assert row['publisher_details']['audience'] == 'Members and non-members'
    assert row['image_url'].endswith('/2026/11/ChatGPT-Image-Aug-19-2026-01_44_15-PM-1024x541.png')
    assert row['image_evidence_url'] == row['details_evidence_url'] == row['event_url']
    assert row['lat'] is row['lng'] is None
    assert [call.args for call in fetch.call_args_list] == [(parser.YMCA_RSS, 'application/rss+xml'),
                                                          (article()['url'], 'text/html')]
    assert {x['reason'] for x in diagnostics} >= {'outside_orangeburg_scope', 'self_paced_without_occurrence_time'}
    assert all('prayer-breakfast' not in row['event_url'] for row in rows)


def test_ymca_event_body_image_avoids_detail_fetch():
    root = feed(True)
    body = root.find('./channel/item/' + parser.CONTENT + 'encoded')
    hero = BeautifulSoup(fixture('ymca_craft.html'), 'html.parser').select_one('meta[property="og:image"]')['content']
    body.text += '<img src="' + hero + '">'
    rows, fetch = ymca_collect(ElementTree.tostring(root, encoding='unicode'))
    assert len(rows) == 1 and rows[0]['image_url'] == hero
    fetch.assert_called_once_with(parser.YMCA_RSS, 'application/rss+xml')


def test_more_ymca_occurrences_do_not_expand_optional_detail_budget():
    root = feed(True)
    clone = deepcopy(root.find('./channel/item'))
    clone.find('title').text += ' Second Session'
    clone.find('link').text = clone.findtext('link').rstrip('/') + '-second-session/'
    root.find('channel').append(clone)
    rows, fetch = ymca_collect(ElementTree.tostring(root, encoding='unicode'))
    assert len(rows) == 2 and fetch.call_count == 2
    assert sum('image_url' in row for row in rows) == 1


@pytest.mark.parametrize('old,new,error', [
    ('Saturday, December 5th', 'Sunday, December 5th', 'date_conflict'),
    ('Saturday, December 5th', 'Saturday, December 5th, 2025', 'date_conflict'),
    ('10:00 AM – 12:00 PM', '10:00 AM – 9:00 AM', 'time_conflict'),
    ('10:00 AM – 12:00 PM', '10:00 AM', 'time_unresolved'),
    ('2550 St Matthews Rd NE', '99 Different Road', 'venue_changed'),
    ('$20 for Non-Members', 'Members only', None),
])
def test_ymca_occurrence_ambiguity_is_held(old, new, error):
    item = article()
    assert old in item['content']
    item['content'] = item['content'].replace(old, new)
    if error:
        with pytest.raises(ValueError, match=error):
            parser._ymca_occurrence(item)
    else:
        assert parser._ymca_occurrence(item) == (None, 'private_or_cancelled')


def test_ymca_old_post_is_not_rolled_into_current_year():
    item = article()
    item['published'] = datetime(2025, 11, 3, 10, 45, 52, tzinfo=timezone.utc)
    item['content'] = item['content'].replace('Saturday, December 5th', 'Friday, December 5th')
    result, reason = parser._ymca_occurrence(item)
    assert reason is None and result['starts'].year == 2025


@pytest.mark.parametrize('old,new,error', [
    ('2550 St Matthews Rd NE', '99 Different Road', 'venue_changed'),
    ('10:00 AM – 12:00 PM', '11:00 AM – 12:00 PM', 'feed_detail_conflict'),
    ('2026-11-03T10:45:52+00:00', '2026-11-02T10:45:52+00:00', 'publication_conflict'),
    ('create-with-us-holiday-craft-event-at-orangeburg-y/', 'another-event/', 'identity_conflict'),
])
def test_ymca_detail_must_agree_with_feed_before_attaching_artwork(old, new, error):
    with pytest.raises(ValueError, match=error):
        ymca_collect(details=fixture('ymca_craft.html').replace(old, new))


@pytest.mark.parametrize('change,error', [
    ('category', 'feed_identity_unverified'), ('duplicate', 'article_identity_unverified'),
    ('next', 'feed_identity_unverified'), ('publication', 'publication_date_conflict'),
    ('missing_content', 'article_identity_unverified'),
])
def test_ymca_feed_identity_and_complete_page_guards(change, error):
    root = feed(True)
    channel, item = root.find('channel'), root.find('./channel/item')
    if change == 'category':
        channel.find('link').text = 'https://columbiaymca.org/category/another-branch/'
    elif change == 'duplicate':
        channel.append(deepcopy(item))
    elif change == 'next':
        ElementTree.SubElement(channel, parser.ATOM + 'link', rel='next', href=parser.YMCA_RSS + '?paged=2')
    elif change == 'publication':
        item.find('pubDate').text = 'Mon, 02 Nov 2026 10:45:52 +0000'
    else:
        item.remove(item.find(parser.CONTENT + 'encoded'))
    with pytest.raises(ValueError, match=error):
        parser._ymca_feed(ElementTree.tostring(root, encoding='unicode'))


def test_ymca_entity_declaration_and_oversized_documents_are_rejected():
    with pytest.raises(ValueError, match='feed_document_invalid'):
        parser._ymca_feed('<!DOCTYPE rss [<!ENTITY test "boom">]>' + fixture('ymca_branch_feed.xml'))
    with pytest.raises(ValueError, match='document_invalid'):
        parser.parse_program_listing(' ' * (parser.MAX_DOCUMENT + 1))


def test_all_held_ymca_candidates_are_not_reported_as_healthy_empty():
    root = feed(True)
    body = root.find('./channel/item/' + parser.CONTENT + 'encoded')
    body.text = body.text.replace('10:00 AM – 12:00 PM', 'Time to be announced')
    with pytest.raises(ValueError, match='ymca_all_occurrences_held'):
        ymca_collect(ElementTree.tostring(root, encoding='unicode'))


@pytest.mark.parametrize('key', [parser.OLD_SANTEE, parser.ORANGEBURG_YMCA])
@pytest.mark.parametrize('field,value', [('feed_url', 'https://evil.example/feed'), ('kind', 'ical'),
                                        ('platform_adapter', 'generic'), ('timezone', 'UTC'),
                                        ('source_key', 'unknown')])
def test_source_tuple_is_validated_before_any_request(key, field, value):
    config, fetch, display = source(key), Mock(), Mock()
    config[field] = value
    with pytest.raises(ValueError, match='unregistered_holly_hill_institution_recovery'):
        parser.collect(config, fetch, fetch_programs=display)
    fetch.assert_not_called()
    display.assert_not_called()


def test_recdesk_never_substitutes_get_when_post_transport_is_missing():
    fetch = Mock()
    with pytest.raises(ValueError, match='display_transport_required'):
        parser.collect(source(parser.OLD_SANTEE), fetch)
    fetch.assert_not_called()


def test_deadline_is_checked_after_each_request(monkeypatch):
    tick = [1.0]
    monkeypatch.setattr(parser, 'monotonic', lambda: tick[0])
    def display():
        tick[0] = 10.0
        return fixture('recdesk_programs.html')
    fetch = Mock()
    with pytest.raises(TimeoutError, match='collection_deadline_exceeded'):
        parser.collect(source(parser.OLD_SANTEE), fetch, deadline_at=5, fetch_programs=display)
    fetch.assert_not_called()


@pytest.mark.parametrize('suffix', ['&delete=1', '#register', '&programId=101', '%26x=1'])
def test_recdesk_event_identity_rejects_extra_actions_or_encodings(suffix):
    assert parser.event_url(parser.OLD_SANTEE, listing()['url'] + suffix) is None


@pytest.mark.parametrize('url', [
    'https://columbiaymca.org:443/2026/11/03/create-with-us/',
    'https://user@columbiaymca.org/2026/11/03/create-with-us/',
    'https://columbiaymca.org/2026/02/30/create-with-us/',
    'https://columbiaymca.org/2026/11/03/create-with-us/?feed=1',
    'https://other.example/2026/11/03/create-with-us/',
])
def test_ymca_event_identity_is_exact(url):
    assert parser.event_url(parser.ORANGEBURG_YMCA, url) is None


@pytest.mark.parametrize('path', ['logo.png', 'event.svg', '../image.png', 'foo%2fbar.png', 'hero.png?x=1',
                                 'favicon-200x200.png', 'avatar.jpg'])
def test_ymca_artwork_policy_rejects_boilerplate_and_unsafe_paths(path):
    assert parser.image_url(parser.ORANGEBURG_YMCA,
                            'https://columbiaymca.org/wp-content/uploads/sites/22/2026/11/' + path) is None


def test_recdesk_has_no_unreviewed_image_allowlist():
    assert parser.image_url(parser.OLD_SANTEE, 'https://oldsanteecanal.recdesk.com/image.jpg') is None
