"""Reviewed primary-event boundaries and exact Lincoln reserve Place shape."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from roomquest import preview_worker as worker, wildlife_trusts as wildlife
from roomquest.registration_formats import source_key

FIXTURES = Path(__file__).parent / 'fixtures' / 'national_feeds'
BODIES = {
    'crochet': (FIXTURES / 'wildlife-linc-related-cards.html').read_text(),
    'reserve': (FIXTURES / 'wildlife-linc-reserve-place.html').read_text(),
}
FEED = 'https://www.lincstrust.org.uk/events'
SOURCE = {'feed_url': FEED, 'source_key': source_key(FEED), 'kind': 'html',
          'platform_adapter': 'html', 'registered_native_content_version': 1}
NOW = datetime(2026, 11, 22, 9, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fixed_window(monkeypatch):
    monkeypatch.setattr(worker, '_future_datetime', lambda value: value.astimezone(timezone.utc)
                        if NOW <= value <= NOW + timedelta(days=60) else None)


def parse(kind='crochet', body=None):
    body = BODIES[kind] if body is None else body
    soup = BeautifulSoup(BODIES[kind], 'html.parser')
    url = soup.select_one('link[rel="canonical"]')['href']
    day = '2026-11-28' if kind == 'crochet' else '2026-12-02'
    return wildlife.parse_detail(body, {'url': url, 'title': 'Fixture control',
                                 'start': day, 'end': day}, source=SOURCE)


def mutate(kind, callback):
    soup = BeautifulSoup(BODIES[kind], 'html.parser')
    callback(soup)
    return str(soup)


def fragment(markup):
    return BeautifulSoup(markup, 'html.parser').contents[0]


def test_observed_related_cards_do_not_become_main_event_dates_or_clocks():
    [row], reason = parse()
    assert reason == 'included'
    assert row['starts_at'] == '2026-11-28T13:00:00+00:00'
    assert row['ends_at'] == '2026-11-28T15:30:00+00:00'
    assert row['venue_name'] == 'Far Ings Visitor Centre'
    assert row['venue_address'] == 'Far Ings Rd, Barton-upon-Humber, DN18 5RG'
    assert (row['lat'], row['lng']) == (53.696783, -0.459924)
    assert 'This synthetic main description must remain complete' in row['description']
    assert 'A second main paragraph' in row['description']
    assert 'Related event control' not in row['description']
    assert 'image_url' not in row
    wildlife.validate_native(row, SOURCE)


def test_observed_reserve_place_keeps_exact_native_name_address_and_point():
    [row], reason = parse('reserve')
    assert reason == 'included'
    assert row['starts_at'] == '2026-12-02T13:30:00+00:00'
    assert row['ends_at'] == '2026-12-02T14:30:00+00:00'
    assert row['venue_name'] == 'Gibraltar Point National Nature Reserve'
    assert row['venue_address'] == 'Gibraltar Road, Skegness, PE24 4SU'
    assert row['venue_city'] == 'Skegness'
    assert (row['lat'], row['lng']) == (53.09639490518, 0.32177925109863)
    assert row['timezone'] == 'Europe/London'
    assert 'This synthetic main description must remain complete' in row['description']
    wildlife.validate_native(row, SOURCE)


def test_true_main_duplicate_dates_still_hold_after_removing_related_cards():
    def duplicate(soup):
        main = soup.select_one('.group--templated-fields .field--name-field-event-date')
        main.append(fragment('<time itemprop="startDate" datetime="2026-11-28"></time>'))
    assert parse(body=mutate('crochet', duplicate)) == ([], 'wildlife_event_dates_unresolved')


def test_true_main_conflicting_clocks_still_hold():
    def duplicate(soup):
        main = soup.select_one('.group--templated-fields > .field-group-wrapper')
        main.append(fragment('<div class="field--name-field-event-time-value">2pm to 3.30pm</div>'))
    assert parse(body=mutate('crochet', duplicate)) == ([], 'wildlife_event_clock_unresolved')


@pytest.mark.parametrize('old,new', [
    ('field--name-field-further-content', 'unreviewed-related-content'),
    ('paragraph--type--event-feed', 'paragraph--type--unknown'),
    ('node--view-mode-event-card card', 'node--view-mode-unreviewed card'),
])
def test_unreviewed_card_boundaries_are_not_silently_ignored(old, new):
    assert parse(body=BODIES['crochet'].replace(old, new)) == (
        [], 'wildlife_event_dates_unresolved')


def test_an_additional_event_root_still_requires_review():
    def add_schema(soup):
        card = soup.select_one('.node__related__wrapper > article')
        card['itemtype'] = 'http://schema.org/Event'
        card['itemscope'] = ''
    assert parse(body=mutate('crochet', add_schema)) == (
        [], 'wildlife_detail_template_unreviewed')


def test_related_status_description_location_and_photo_cannot_supply_main_fields():
    def add_foreign_fields(soup):
        card = soup.select_one('.node__related__wrapper > article')
        card.append(fragment('<meta itemprop="eventStatus" content="http://schema.org/EventCancelled">'))
        card.append(fragment('<div class="field--name-field-event-summary">Related prose must not publish.</div>'))
        card.append(fragment('<div class="field--name-field-event-about">Another event description.</div>'))
        card.append(fragment('<div class="field--name-field-event-photos"><article itemprop="image"><img src="https://www.lincstrust.org.uk/related.jpg" width="1200" height="800"></article></div>'))
        place = soup.select_one('.node__header .field--name-field-event-location')
        card.append(fragment(str(place)))
    body = mutate('crochet', add_foreign_fields)
    [row], reason = parse(body=body)
    assert reason == 'included'
    assert 'Related prose' not in row['description'] and 'image_url' not in row
    assert row['venue_name'] == 'Far Ings Visitor Centre'
    soup = BeautifulSoup(body, 'html.parser')
    soup.select_one('.node__header .field--name-field-event-location').decompose()
    assert parse(body=str(soup)) == ([], 'wildlife_event_location_unresolved')
    soup = BeautifulSoup(body, 'html.parser')
    for section in soup.select('.standfirst .field--name-field-event-summary, .node__content > .field--name-field-event-about'):
        section.decompose()
    assert parse(body=str(soup)) == ([], 'wildlife_event_description_missing')


@pytest.mark.parametrize('kind', ['crochet', 'reserve'])
def test_multiple_main_location_entities_remain_ambiguous(kind):
    def duplicate(soup):
        field = soup.select_one('.node__header .field--name-field-event-location, '
                                '.node__header .field--name-field-event-reserve')
        field.append(fragment(str(field.select_one('[itemprop="location"]'))))
    assert parse(kind, mutate(kind, duplicate)) == ([], 'wildlife_event_location_unresolved')


@pytest.mark.parametrize('kind', ['crochet', 'reserve'])
def test_conflicting_main_names_remain_ambiguous(kind):
    def duplicate(soup):
        place = soup.select_one('.node__header [itemprop="location"]')
        selector = 'h3.node__title' if kind == 'reserve' else '.field--name-field-location-name'
        copy = fragment(str(place.select_one(selector)))
        copy.clear()
        copy.append('A different venue')
        place.append(copy)
    assert parse(kind, mutate(kind, duplicate)) == ([], 'wildlife_event_location_unresolved')


@pytest.mark.parametrize('old,new', [
    ('node--view-mode-address-string', 'node--view-mode-unreviewed'),
    ('node--type-reserve', 'node--type-unreviewed'),
    ('itemtype="http://schema.org/Place"', 'itemtype="http://schema.org/VirtualLocation"'),
    ('class="node__title"', 'class="unreviewed-title"'),
])
def test_only_the_observed_reserve_place_shape_is_supported(old, new):
    assert parse('reserve', BODIES['reserve'].replace(old, new)) == (
        [], 'wildlife_event_location_unresolved')


def test_reserve_address_and_name_must_belong_to_the_same_place():
    def move_address(soup):
        place = soup.select_one('.node__header [itemprop="location"]')
        address = place.select_one('[itemprop="address"]').extract()
        soup.select_one('.node__content').append(address)
    assert parse('reserve', mutate('reserve', move_address)) == (
        [], 'wildlife_event_location_unresolved')


def test_conflicting_reserve_address_fields_still_hold():
    def duplicate(soup):
        address = soup.select_one('.node__header [itemprop="address"]')
        address.append(fragment('<span class="field--name-field-reserve-postcode">DN18 5RG</span>'))
    assert parse('reserve', mutate('reserve', duplicate)) == (
        [], 'wildlife_event_location_unresolved')


@pytest.mark.parametrize('bad_point', ['91', 'NaN', 'unknown', ''])
def test_reserve_gps_must_remain_valid_native_evidence(bad_point):
    assert parse('reserve', BODIES['reserve'].replace('content="53.09639490518"',
        f'content="{bad_point}"')) == ([], 'wildlife_event_location_unresolved')


def test_reserve_point_cannot_be_missing_or_ambiguous():
    def remove(soup):
        soup.select_one('[itemprop="latitude"]').decompose()
    assert parse('reserve', mutate('reserve', remove)) == (
        [], 'wildlife_event_location_unresolved')
    def duplicate(soup):
        soup.select_one('[itemprop="geo"]').append(
            fragment('<meta itemprop="latitude" content="52.0">'))
    assert parse('reserve', mutate('reserve', duplicate)) == (
        [], 'wildlife_event_location_unresolved')


@pytest.mark.parametrize('selector', [
    '[itemprop="longitude"]', '[itemprop="geo"]',
    'h3.node__title', '[itemprop="address"]',
])
def test_required_reserve_identity_and_native_point_cannot_be_absent(selector):
    def remove(soup):
        soup.select_one('.node__header ' + selector).decompose()
    assert parse('reserve', mutate('reserve', remove)) == (
        [], 'wildlife_event_location_unresolved')


@pytest.mark.parametrize('kind', ['crochet', 'reserve'])
def test_places_in_both_native_wrappers_remain_ambiguous(kind):
    def add_other(soup):
        other_kind = 'reserve' if kind == 'crochet' else 'crochet'
        other = BeautifulSoup(BODIES[other_kind], 'html.parser')
        field = other.select_one('.node__header .field--name-field-event-location, '
                                 '.node__header .field--name-field-event-reserve')
        soup.select_one('.node__header .node__event-location').append(fragment(str(field)))
    assert parse(kind, mutate(kind, add_other)) == ([], 'wildlife_event_location_unresolved')


def test_related_reserve_wrapper_cannot_supply_or_override_the_primary_venue():
    def add_related_reserve(soup):
        other = BeautifulSoup(BODIES['reserve'], 'html.parser')
        field = other.select_one('.field--name-field-event-reserve')
        soup.select_one('.node__related__wrapper > article').append(fragment(str(field)))
    body = mutate('crochet', add_related_reserve)
    [row], reason = parse(body=body)
    assert reason == 'included' and row['venue_name'] == 'Far Ings Visitor Centre'
    soup = BeautifulSoup(body, 'html.parser')
    soup.select_one('.node__header .field--name-field-event-location').decompose()
    assert parse(body=str(soup)) == ([], 'wildlife_event_location_unresolved')


def test_reserve_alias_does_not_accept_an_unreviewed_generic_place():
    body = BODIES['crochet'].replace('field--name-field-event-location',
                                   'field--name-field-event-reserve', 1)
    assert parse(body=body) == ([], 'wildlife_event_location_unresolved')


def test_unknown_outer_place_fields_remain_unreviewed():
    body = BODIES['reserve'].replace('field--name-field-event-reserve',
                                   'field--name-field-unreviewed-reserve')
    assert parse('reserve', body) == ([], 'wildlife_event_location_unresolved')
