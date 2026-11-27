from copy import deepcopy
from datetime import datetime, timedelta, timezone
from time import monotonic
from unittest.mock import Mock

import pytest

from roomquest import new_york_family_final as family
from tests.test_new_york_arts import fake_record

NOW = datetime(2026, 11, 14, 23, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolate_fixture_clock(monkeypatch):
    # The shared normalizer uses the real clock; native capture separately
    # exercises it. Keep these explicit 2026 parser cases valid in later years.
    monkeypatch.setattr(family, "record", fake_record)


def source(key):
    url, kind, adapter = family.SOURCES[key]
    return dict(source_key=key, feed_url=url, kind=kind, platform_adapter=adapter, timezone=family.ZONE)


def fixture(key, *, extra=""):
    if key == family.AQUARIUM:
        page = ('<meta property="og:title" content="Holiday Tides - New York Aquarium">'
                '<main id="content"><h2>December 26–31, 2026 - 11am-3pm</h2>'
                '<p>Holiday activities are included with paid Aquarium admission.</p>'+extra+'</main>')
        return {family.SOURCES[key][0]:page,
                family.CONTACTS[key][0]:'<main id="content">'+family.CONTACTS[key][1]+'</main>'}
    dates = '2026: November 21–22 and 27–29. December 3–6, 10–13, 17–23, 26–31. 2027: January 2–3.'
    answers = [
        ('When is Holiday Lights?', dates),
        ('What are the Holiday Lights hours of operation?', 'Holiday Lights operates 1pm to 9pm. Lights go on at 4:30pm.'),
        ('Which gates/entrances are open for Holiday Lights?', 'Only Bronx River and Southern Boulevard Gates are open.'),
        ('Is there a night for guests with sensory sensitivities?', 'Sensory-Friendly Night on December 3, 2026.'),
    ]
    faq = '<p>PUBLIC EVENT DATES: '+dates+'</p>'+''.join(
        '<p class="bz-lights-faqs__question">'+q+'</p><div class="bz-lights-faqs__answer">'+a+'</div>' for q,a in answers)
    page = ('<meta property="og:title" content="Holiday Lights at the Bronx Zoo">'
            '<main id="content"><p>Holiday Lights complete public event description.</p>'
            '<p>Exclusive Member Previews November 19 and 20.</p>'+extra+'</main>')
    return {family.SOURCES[key][0]:page, family.FAQ_URL:faq,
            family.CONTACTS[key][0]:'<main id="content">'+family.CONTACTS[key][1]+'</main>'}


def collect(key, pages=None, **kwargs):
    pages = pages or fixture(key)
    return family.collect(source(key), lambda url, accept:pages[url], deadline_at=monotonic()+36, now=NOW, **kwargs)


def test_public_dates_preserve_gaps_year_rollover_and_exclude_member_previews():
    rows = collect(family.ZOO)
    assert len(rows) == 28
    dates = {r['starts_at'][:10] for r in rows}
    assert '2026-11-21' in dates and '2027-01-03' in dates
    assert not dates.intersection({'2026-11-19','2026-11-20','2026-11-23','2026-12-24','2026-12-25','2027-01-01'})
    first = datetime.fromisoformat(rows[0]['starts_at'])
    last = datetime.fromisoformat(rows[0]['ends_at'])
    assert first.astimezone(timezone.utc).hour == 18
    assert (last-first).total_seconds() == 8*3600
    assert sum('Sensory-Friendly Night' in r['title'] for r in rows) == 1
    assert next(r for r in rows if 'Sensory-Friendly Night' in r['title'])['starts_at'].startswith('2026-12-03')


def test_aquarium_has_six_explicit_days_and_its_own_location():
    rows = collect(family.AQUARIUM)
    assert len(rows) == 6
    assert {r['venue_address'] for r in rows} == {'602 Surf Avenue, Brooklyn, NY 11224'}
    assert {r['lat'] for r in rows} == {40.574008}
    assert {r['venue_city'] for r in rows} == {'Brooklyn'}
    assert all(datetime.fromisoformat(r['ends_at'])-datetime.fromisoformat(r['starts_at']) == timedelta(hours=4) for r in rows)


@pytest.mark.parametrize('key',[family.ZOO,family.AQUARIUM])
def test_original_facts_ignore_source_label_and_exclude_reviewed_point(key):
    row = collect(key)[0]
    envelope = deepcopy(row['collector_event_content_v1'])
    facts = envelope['facts']
    assert facts['venue_name'] == family.VENUES[key][0]
    assert facts['venue_address'] == family.VENUES[key][1]
    assert facts['venue_city'] == family.VENUES[key][2]
    assert 'source_latitude' not in facts and 'source_longitude' not in facts
    assert (row['lat'], row['lng']) == family.VENUES[key][3:]
    renamed = source(key)
    renamed['publisher_name'] = 'Renamed provider label'
    pages = fixture(key)
    again = family.collect(renamed, lambda url, accept:pages[url],
                           deadline_at=monotonic()+36, now=NOW)[0]
    assert again['collector_event_content_v1'] == envelope


def test_one_publisher_narrative_change_changes_each_affected_occurrence_only():
    first = collect(family.AQUARIUM)
    changed = collect(family.AQUARIUM, fixture(family.AQUARIUM, extra='<p>Bring binoculars.</p>'))
    assert [row['id'] for row in changed] == [row['id'] for row in first]
    assert all(new['collector_event_content_v1'] != old['collector_event_content_v1']
               for old, new in zip(first, changed))


@pytest.mark.parametrize('key',[family.ZOO,family.AQUARIUM])
def test_full_native_narrative_and_tail_survive_display_limit(key):
    text = '<p>'+('Full publisher paragraph with substantive program details. '*65)+'</p><p>Final participation caveat.</p>'
    rows = collect(key,fixture(key,extra=text))
    assert all(len(r['description'])>2000 and 'Final participation caveat.' in r['description'] for r in rows)


def test_shared_headquarters_footer_is_not_aquarium_address_evidence():
    pages = fixture(family.AQUARIUM)
    pages[family.CONTACTS[family.AQUARIUM][0]] = '<main id="content">New York Aquarium</main><footer>'+family.CONTACTS[family.ZOO][1]+'</footer>'
    with pytest.raises(ValueError,match='nyc_family_address_changed'):
        collect(family.AQUARIUM,pages)


def test_conflicting_two_official_public_date_lists_cannot_publish():
    pages = fixture(family.ZOO)
    pages[family.FAQ_URL] = pages[family.FAQ_URL].replace('PUBLIC EVENT DATES: 2026: November 21–22', 'PUBLIC EVENT DATES: 2026: November 21–23')
    with pytest.raises(ValueError,match='nyc_family_schedule_conflict'):
        collect(family.ZOO,pages)


@pytest.mark.parametrize('text',['November 21-22','2026: November 31','2026: November 21,21','2026: November 29-21','2026: November weekends'])
def test_ambiguous_invalid_or_duplicate_public_dates_are_held(text):
    with pytest.raises(ValueError,match='nyc_family_(calendar_changed|schedule_conflict)'):
        family.public_dates(text)


def test_oversized_narrative_is_held_without_clipping():
    with pytest.raises(ValueError,match='nyc_family_description_limit'):
        collect(family.AQUARIUM,fixture(family.AQUARIUM,extra='<p>'+'x'*12001+'</p>'))


def test_changed_profile_rejected_before_http():
    fetch=Mock();bad={**source(family.ZOO),'feed_url':'https://bronxzoo.com/other'}
    with pytest.raises(ValueError,match='unregistered_nyc_family_final'):
        family.collect(bad,fetch,deadline_at=monotonic()+36,now=NOW)
    fetch.assert_not_called()


def test_expired_season_returns_no_future_occurrences():
    pages=fixture(family.AQUARIUM)
    assert family.collect(source(family.AQUARIUM),lambda url,accept:pages[url],
                          deadline_at=monotonic()+36,now=datetime(2027,2,1,tzinfo=timezone.utc)) == []
