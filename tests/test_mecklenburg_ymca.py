"""Public YMCA session dates, eligibility, branch evidence and finite discovery."""
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from bs4 import BeautifulSoup
import pytest

from roomquest import mecklenburg_ymca as parser
from roomquest import preview_worker

FIXTURES = Path(__file__).with_name('fixtures') / 'mecklenburg_batch2'
NOW = datetime(2026, 11, 6, 13, tzinfo=timezone.utc)
SOURCE = {'source_key': parser.SOURCE_KEY, 'feed_url': parser.CALENDAR,
          'kind': 'html', 'platform_adapter': 'html', 'timezone': parser.TIMEZONE}
DANCE_SPECIFIC = (
    'Designed for ages 3–5, this playful, story-based 6-week dance class invites tiny dancers '
    'to use their imaginations as they explore movement, discover what their bodies can do, '
    'and learn to move through space in different ways. Through music, storytelling, and '
    'creative play, children build coordination, confidence, and a love of movement in a '
    'fun, welcoming environment where every child belongs.\n'
    'Sessions will be held on Wednesdays from 4:45-5:30PM at the Clarksville Branch.'
)
DANCE_CONTEXT = ('Registered session dates: 2026-11-11–2026-12-16. '
                 'This class is part of that full session.')
DANCE_PROGRAM = (
    'YMCA dance programs provide a welcoming, inclusive space where every child can explore '
    'movement, express their creativity, and grow in confidence. Through dance, children '
    'develop coordination and new skills while building connections, celebrating individuality, '
    'and experiencing the joy of being part of a community where everyone belongs.\n'
    'Classes will be held at the Clarksville Branch.'
)


class ClockMeta(type):
    def __instancecheck__(cls, value):
        return isinstance(value, datetime)


class FrozenDatetime(datetime, metaclass=ClockMeta):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def fixed_normalizer_clock(monkeypatch):
    monkeypatch.setattr(preview_worker, 'datetime', FrozenDatetime)


def fixture(name):
    return (FIXTURES / name).read_text()


def cards():
    return parser.discover(fixture('ymca_catalog.html'))


def card(number):
    return next(c for c in cards() if '/programs/' + str(number) + '/' in c['url'])


def locations():
    return parser.parse_locations(fixture('ymca_locations.html'))


def program(number):
    return BeautifulSoup(fixture('ymca_program_' + str(number) + '.html'), 'html.parser')


def parse(number=33, body=None, diagnostic=None, venue_map=None, now=NOW, program_card=None):
    return parser.parse_program(str(body) if body is not None else fixture('ymca_program_' + str(number) + '.html'),
                                program_card or card(number), locations() if venue_map is None else venue_map,
                                now=now, diagnostics=diagnostic)


def pages():
    result = {parser.CALENDAR: fixture('ymca_catalog.html'), parser.LOCATIONS: fixture('ymca_locations.html')}
    for item in cards():
        number = item['url'].split('/programs/')[1].split('/')[0]
        result[item['url']] = fixture('ymca_program_' + number + '.html')
    return result


def test_real_catalog_fetches_all_visible_programs_without_claiming_category_counter_completeness(capsys):
    captured = pages()
    fetch = Mock(side_effect=lambda url, accept: captured[url])
    rows = parser.collect(SOURCE, fetch, now=NOW)
    assert len(cards()) == 10 and len(rows) == 7
    assert len(fetch.call_args_list) == 12
    assert {call.args[0] for call in fetch.call_args_list} == set(captured)
    assert all(call.args[1] == 'text/html' for call in fetch.call_args_list)
    assert not any('/core/' in c.args[0] or '/register/' in c.args[0] or '/placeholder/' in c.args[0]
                   for c in fetch.call_args_list)
    assert 'visible_program_catalog_only' in capsys.readouterr().err


def test_craft_retains_actual_branch_time_image_public_price_and_session_deadline():
    diagnostic = {}
    rows = parse(diagnostic=diagnostic)
    assert len(rows) == 1
    row = rows[0]
    assert row['id'] == 'mecklenburg_ymca:session:877:2026-11-17'
    assert row['title'] == 'Decoupage Ornament'
    assert row['starts_at'] == '2026-11-17T20:00:00+00:00'
    assert row['ends_at'] == '2026-11-17T22:00:00+00:00'
    assert row['venue_address'] == '316 N. Main Street, Chase City, VA 23924'
    assert row['venue_city'] == 'Chase City'
    assert row['lat'] is None and row['lng'] is None
    assert row['event_url'] == row['details_evidence_url'] == row['image_evidence_url'] == card(33)['url']
    assert row['publisher_categories'] == ['Craft Classes']
    assert row['image_url'].endswith('/2026/10/09072400/Decoupage-Ornament-300x265.png')
    assert row['image_provenance'] == 'publisher_event_candidates_v1' and 'image_verified_at' not in row
    assert row['publisher_details']['cost'] == 'Member $10.00; Non-Member $15.00.'
    assert '11/13/2026' in row['publisher_details']['registration']
    assert 'general pricing table lists 11/16/2026' in row['publisher_details']['registration']
    assert row['description'].startswith('Let’s create together!\nDecoupage ornament as a keepsake')
    assert row['description'].index('Chase City: 11/17, 3-5pm') < row['description'].index('Join us for beginner-friendly')
    assert 'Registered session dates:' not in row['description']
    assert 'Clarksville: 11/19' not in row['description']
    assert any(x['id'].endswith('878:2026-11-19') and x['reason'] == 'session_full' for x in diagnostic['excluded'])
    assert {x['id'] for x in diagnostic['held']} == {
        'mecklenburg_ymca:session:879:2026-11-19', 'mecklenburg_ymca:session:880:2026-11-20'}
    assert all(x['reason'] == 'publisher_time_conflict' for x in diagnostic['held'])


def test_weekly_course_has_exact_six_occurrences_full_session_fee_and_no_invented_photo():
    rows = parse(37)
    dates = ['2026-11-11', '2026-11-18', '2026-11-25', '2026-12-02', '2026-12-09', '2026-12-16']
    assert [r['id'] for r in rows] == ['mecklenburg_ymca:session:888:' + day for day in dates]
    for row, day in zip(rows, dates):
        assert row['starts_at'] == day + 'T21:45:00+00:00'
        assert row['ends_at'] == day + 'T22:30:00+00:00'
        assert row['venue_address'] == '1567 Noblin Farm Road, Clarksville, VA 23927'
        assert row['publisher_details']['cost'] == 'Full session 2026-11-11–2026-12-16: Member $60.00; Non-Member $75.00.'
        assert '11/09/2026' in row['publisher_details']['registration']
        assert row['publisher_details']['audience'] == 'Ages 3-5'
        assert row['description'] == '\n\n'.join((DANCE_SPECIFIC, DANCE_CONTEXT, DANCE_PROGRAM))
        assert '7 / 10' not in row['description'] and 'Available' not in row['publisher_details']['registration']
        assert 'image_url' not in row


@pytest.mark.parametrize('long_part', ['specific', 'program'])
def test_description_cap_keeps_class_facts_first_and_the_full_session_note(long_part):
    baseline = parse(37)
    soup = program(37)
    selector = '.division .desc' if long_part == 'specific' else '#single_program .content'
    soup.select_one(selector).append(' Publisher background.' * 150)
    rows = parse(37, soup)
    assert len(rows) == len(baseline) == 6
    for row, original in zip(rows, baseline):
        description = row['description']
        assert len(description) <= 2000
        assert description.startswith(DANCE_SPECIFIC)
        assert description.count(DANCE_CONTEXT) == 1
        assert description.index('4:45-5:30PM at the Clarksville Branch.') < description.index(DANCE_CONTEXT)
        if long_part == 'specific':
            assert description.endswith(DANCE_CONTEXT)
            assert DANCE_PROGRAM not in description
        else:
            assert len(description) == 2000
            assert description.startswith('\n\n'.join((DANCE_SPECIFIC, DANCE_CONTEXT, DANCE_PROGRAM)))
        # Narrative truncation cannot change the six public identities, times,
        # venue, full-session prices or explicit audience evidence.
        assert {key: value for key, value in row.items() if key != 'description'} == {
            key: value for key, value in original.items() if key != 'description'}


@pytest.mark.parametrize('program_copy', [DANCE_SPECIFIC, ' '.join(DANCE_SPECIFIC.split()), ''])
def test_repeated_or_missing_program_copy_does_not_duplicate_the_class_description(program_copy):
    soup = program(37)
    node = soup.select_one('#single_program .content')
    node.clear()
    node.append(program_copy)
    rows = parse(37, soup)
    assert len(rows) == 6
    assert all(row['description'] == DANCE_SPECIFIC + '\n\n' + DANCE_CONTEXT for row in rows)


def test_closed_full_members_only_and_undated_services_do_not_become_cancellations():
    diagnostic = {}
    for number in (1, 13, 14, 15, 16, 18, 26, 32):
        assert parse(number, diagnostic=diagnostic) == []
    reasons = {x['reason'] for key in ('held', 'excluded') for x in diagnostic[key]}
    assert {'registration_closed', 'nonpublic_or_members_only_session', 'publisher_time_unresolved'} <= reasons
    assert all('publisher_status' not in x for key in ('held', 'excluded') for x in diagnostic[key])


@pytest.mark.parametrize('status', ['Cancelled', 'Postponed'])
def test_explicit_dated_status_preserves_ids_when_venue_registration_and_prices_disappear(status):
    soup = program(37)
    heading = soup.select_one('.division .top h3')
    heading.string = status + ': ' + heading.get_text(' ', strip=True)
    for node in soup.select('.desc, .content, .class_register_container, .might-of > .table-responsive'):
        node.clear()
    rows = parse(37, soup, venue_map={})
    assert len(rows) == 6
    assert [r['id'] for r in rows] == [r['id'] for r in parse(37)]
    assert all(r['publisher_status'] == status.lower() and not r['venue_address'] for r in rows)
    assert all(r['details_evidence_url'] == card(37)['url'] for r in rows)


def test_weekly_exceptions_or_conflicting_publisher_times_hold_instead_of_inventing_classes():
    for text in ('No classes November 25.', 'Sessions will be held on Wednesdays from 5:45-6:30PM at the Clarksville Branch.'):
        soup = program(37)
        soup.select_one('.desc').append(text)
        diagnostic = {}
        assert parse(37, soup, diagnostic) == []
        assert diagnostic['held']


def test_actual_enumerated_pickleball_dates_cannot_expand_into_christmas_and_new_year():
    description = parser._text(program(14).select_one('.desc'))
    with pytest.raises(parser.SessionHold, match='series_explicit_dates_require_review'):
        parser._schedule(date(2026, 12, 4), date(2027, 1, 22),
                         'Session 1 - Fr - 4:30 pm - 6:30 pm', description)


@pytest.mark.parametrize('eligibility', ['Exclusively for members.', 'Coaches recommendation required for placement.'])
def test_explicit_membership_or_coach_selection_is_not_public_eligibility(eligibility):
    soup = program(37)
    soup.select_one('.desc').append(eligibility)
    diagnostic = {}
    assert parse(37, soup, diagnostic) == []
    assert diagnostic['excluded'][0]['reason'] == 'nonpublic_or_members_only_session'


def test_exact_post_start_cancellation_keeps_unknown_end_for_backend_existing_record_policy():
    soup = program(37)
    heading = soup.select_one('.division .top h3')
    heading.string = 'Cancelled: ' + heading.get_text(' ', strip=True)
    for node in soup.select('.desc, .content, .class_register_container, .might-of > .table-responsive'):
        node.clear()
    soup.select_one('tr[id] .ml-sm-3').string = 'Session 1 - We - 4:45 pm'
    rows = parse(37, soup, venue_map={}, now=datetime(2026, 11, 12, 22, 45, tzinfo=timezone.utc))
    assert len(rows) == 6
    first = rows[0]
    assert first['id'] == 'mecklenburg_ymca:session:888:2026-11-11'
    assert first['starts_at'] == '2026-11-11T21:45:00+00:00' and first['ends_at'] is None
    assert first['publisher_status'] == 'cancelled' and not first['venue_address']


def test_program_date_bounds_conflicting_with_session_dates_hold():
    soup = program(37)
    soup.select_one('.top .dates').string = 'Dates: 11/12/26 - 12/16/26'
    diagnostic = {}
    assert parse(37, soup, diagnostic) == []
    assert diagnostic['held'][0]['reason'] == 'publisher_schedule_conflict'


def test_branch_affiliation_is_not_an_offsite_address_or_gymnastics_default():
    soup = str(program(37)).replace('at the Clarksville Branch', 'at Bluestone High School Gym in Skipwith')
    diagnostic = {}
    assert parse(37, soup, diagnostic) == []
    assert diagnostic['held'][0]['reason'] == 'event_venue_unreviewed'
    soup = str(program(37)).replace('Clarksville', 'Gymnastics')
    rows = parse(37, soup)
    assert len(rows) == 6 and all(r['venue_address'] == '612 Virginia Ave, Clarksville, VA 23927' for r in rows)


def test_an_explicit_complete_offsite_address_is_preserved_without_a_branch_pin():
    soup = program(37)
    soup.select_one('.content').clear()
    soup.select_one('.desc').clear()
    soup.select_one('.desc').append('Location: Community Hall; 123 Example Street, Boydton, VA 23917')
    rows = parse(37, soup)
    assert len(rows) == 6
    assert all(r['venue_address'] == '123 Example Street, Boydton, VA 23917' for r in rows)
    assert all(r['location_provenance'] == 'publisher_event_address_pending_geocode' for r in rows)
    assert all(r['lat'] is None and r['lng'] is None for r in rows)


def test_future_new_session_is_discovered_without_a_hardcoded_event_id_or_date():
    soup = program(33)
    original = soup.select_one('#division_91')
    new = deepcopy(original)
    new['id'] = 'division_990'
    new.select_one('.top h3').string = 'Winter Paper Lantern'
    new.select_one('.top .dates').string = 'Dates: 12/01/26 - 12/01/26'
    new.select_one('.desc').clear()
    new.select_one('.desc').append('Chase City: 12/1, 3-5pm')
    for node in new.select('tbody tr[id]')[1:]:
        node.decompose()
    session = new.select_one('tr[id]')
    session['id'] = 'session_990'
    session.select_one('.d-inline-block').string = '12/01/26'
    for node in session.select('[data-session-id]'):
        node['data-session-id'] = '990'
    session.select_one('a.reg_single')['href'] = '/programs/register/s/990/'
    original.parent.append(new)
    rows = parse(body=soup)
    assert {r['id'] for r in rows} == {
        'mecklenburg_ymca:session:877:2026-11-17', 'mecklenburg_ymca:session:990:2026-12-01'}
    assert next(r for r in rows if ':990:' in r['id'])['title'] == 'Winter Paper Lantern'


def test_unknown_end_is_preserved_and_an_unsafe_image_is_a_valid_no_image_event():
    soup = program(33)
    node = soup.select_one('#division_91 .desc')
    node.clear()
    node.append('Chase City: 11/17, 3pm')
    image = soup.new_tag('img', src='https://s3.amazonaws.com/recliquecore-imagestack/generic.jpg')
    node.append(image)
    rows = parse(body=soup)
    assert len(rows) == 1 and rows[0]['ends_at'] is None
    assert 'image_url' not in rows[0]


def test_full_text_is_validated_before_the_2000_character_output_cap():
    soup = program(33)
    node = soup.select_one('#division_91 .desc')
    node.insert(0, 'Publisher background. ' * 150)
    rows = parse(body=soup)
    assert len(rows) == 1 and len(rows[0]['description']) == 2000
    node.append(' Private event.')
    assert parse(body=soup) == []
    node.append('x' * parser.MAX_FACT_TEXT)
    with pytest.raises(ValueError, match='fact_text_limit'):
        parse(body=soup)


def test_nonmember_cost_and_current_registration_are_required_without_implying_availability():
    soup = program(37)
    soup.select_one('.might-of > .table-responsive table tbody tr').find_all('td')[-1].string = 'Members only'
    diagnostic = {}
    assert parse(37, soup, diagnostic) == []
    assert diagnostic['held'][0]['reason'] == 'public_registration_cost_unresolved'
    soup = program(37)
    soup.select_one('.class_register_container').clear()
    soup.select_one('.class_register_container').append('Session is Full')
    diagnostic = {}
    assert parse(37, soup, diagnostic) == []
    assert diagnostic['excluded'][0]['reason'] == 'session_full'
    assert 'held' not in diagnostic


@pytest.mark.parametrize('change', ['missing_year', 'conflicting_session_id', 'conflicting_title', 'missing_dates'])
def test_malformed_or_changed_session_evidence_never_returns_a_guessed_event(change):
    soup = program(37)
    if change == 'missing_year':
        soup.select_one('tr[id] .d-inline-block').string = '11/11 - 12/16'
        diagnostic = {}
        assert parse(37, soup, diagnostic) == []
        assert diagnostic['held'][0]['reason'] == 'publisher_date_unresolved'
        return
    if change == 'conflicting_session_id':
        soup.select_one('[data-session-id]')['data-session-id'] = '999'
    elif change == 'conflicting_title':
        soup.select_one('h1.entry-title').string = 'Different Program'
    else:
        soup.select_one('tr[id] .d-inline-block').decompose()
    with pytest.raises(ValueError, match='identity|structure'):
        parse(37, soup)


@pytest.mark.parametrize('url', [
    'https://other.example/programs/33/craft-classes/?locations=-1',
    'https://mecklenburg.recliquecore.com:443/programs/33/craft-classes/?locations=-1',
    'https://user@mecklenburg.recliquecore.com/programs/33/craft-classes/?locations=-1',
    '/core/programs/33', '/programs/33/craft-classes/?locations=13',
    '/programs/33/craft-classes/?locations=-1&locations=13',
    '/programs/33/craft-classes/?locations=-1#session-877',
    '/programs/../core/?locations=-1', '/programs/%33/craft-classes/?locations=-1',
])
def test_program_identity_rejects_unreviewed_urls(url):
    with pytest.raises(ValueError, match='url_unverified'):
        parser.program_url(url)


def test_unknown_pagination_caps_and_duplicate_cards_fail_the_snapshot():
    soup = BeautifulSoup(fixture('ymca_catalog.html'), 'html.parser')
    soup.select_one('#program_results').append(soup.new_tag('a', rel='next', href='?page_n=1'))
    with pytest.raises(ValueError, match='pagination'):
        parser.discover(str(soup))
    soup = BeautifulSoup(fixture('ymca_catalog.html'), 'html.parser')
    original = soup.select_one('.program')
    for _ in range(parser.MAX_PROGRAM_PAGES):
        original.parent.append(deepcopy(original))
    with pytest.raises(ValueError, match='page_limit'):
        parser.discover(str(soup))


@pytest.mark.parametrize('field,value', [
    ('source_key', 'unrelated'), ('feed_url', parser.CALENDAR + '?locations=13'),
    ('kind', 'json'), ('platform_adapter', 'jsonld'), ('timezone', 'UTC'),
])
def test_source_identity_fails_before_fetch(field, value):
    fetch = Mock()
    with pytest.raises(ValueError, match='unregistered'):
        parser.collect(dict(SOURCE, **{field: value}), fetch, now=NOW)
    fetch.assert_not_called()


def test_partial_fetch_and_expired_budget_never_return_the_successful_prefix():
    captured = pages()
    def fetch(url, accept):
        if url == card(37)['url']:
            raise OSError('unavailable')
        return captured[url]
    with pytest.raises(OSError):
        parser.collect(SOURCE, fetch, now=NOW)
    expired = Mock()
    with pytest.raises(ValueError, match='collection_deadline'):
        parser.collect(SOURCE, expired, deadline_at=0, now=NOW)
    expired.assert_not_called()


def test_deadline_expires_after_a_slow_fetch_without_continuing(monkeypatch):
    clock = [0]
    monkeypatch.setattr(parser, 'monotonic', lambda: clock[0])
    def fetch(url, accept):
        clock[0] = 31
        return fixture('ymca_catalog.html')
    call = Mock(side_effect=fetch)
    with pytest.raises(ValueError, match='collection_deadline'):
        parser.collect(SOURCE, call, now=NOW)
    assert call.call_count == 1
