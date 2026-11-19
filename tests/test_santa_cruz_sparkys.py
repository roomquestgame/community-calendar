"""First-party publisher calendar isolation, recurrence and evidence gates."""
from datetime import datetime, timezone
import pytest
from roomquest import santa_cruz_sparkys as s

NOW = datetime(2026,11,18,23,tzinfo=timezone.utc)
SOURCE = {'source_key':s.KEY,'feed_url':s.URL,'kind':'html',
          'platform_adapter':'html','timezone':s.ZONE}
VENUE = 'Located at the Santa Cruz County Fairgrounds: 2601 E Lake Ave, Watsonville, CA 95076'
PDF = '<a href="/s/Community-Display-Spaces-2026-PS.pdf">Community Display Spaces 2026</a>'
DRIVE_PROSE = ('Experience the magic of the season from the comfort of your car at Sparky’s Holiday Lights drive-thru! '
               'Cruise a mile through the Santa Cruz County Fairgrounds, surrounded by stunning light displays. '
               'Keep warm and cozy, enjoy holiday tunes, and make memories your whole family will cherish.')
WALK_PROSE = ('Wander through a dazzling winter wonderland at the Santa Cruz County Fairgrounds, illuminated by hundreds '
              'of thousands of twinkling lights and festive displays. Perfect for families, date nights, and '
              'friend outings—grab a warm cup of cocoa, savor your favorite festive treats, and shop the Holiday Faire.')
GROUPS = [('November 27, 28, & 29','Drive-Thru 5:30pm-9pm'),
          ('December 3rd','Walk-Thru Krampus 5pm-9:30pm'),
          ('December 4th & 5th','Walk-Thru/Heritage Holiday Fair 5pm -9pm'),
          ('December 6th','Drive-Thru 5:30pm-9pm'),
          ('December 11, 12, & 13','Drive-Thru 5:30pm-9pm'),
          ('December 18th thru 24th','Drive-Thru 5:30pm-9pm')]

def page(groups=GROUPS,venue=VENUE,pdf=PDF):
    parts=[f'<main>Sparky’s Holiday Lights {venue} Upcoming Events {pdf}']
    for d,t in groups:
        parts.append('<div class="sqs-html-content"><p class="sqsrte-large"><strong>'+d+
                     '</strong></p><p><a href="https://www.tickettailor.com/events/santacruzcountyfairgroundsfoundation/2435704">'+t+
                     '</a></p></div>')
    parts.append('<div class="sqs-html-content">'+DRIVE_PROSE+'</div>')
    parts.append('<div class="sqs-html-content">'+WALK_PROSE+'</div></main>')
    return ''.join(parts)

def run(html=None):
    return s.collect(SOURCE,lambda url,accept:html if html is not None else page(),now=NOW)

def test_sixteen_explicit_dates_correct_pacific_clocks_and_complete_publisher_prose():
    rows=run()
    assert len(rows)==16
    assert rows[0]['venue_address']==s.ADDRESS
    assert rows[0]['lat'] is None and rows[0]['lng'] is None
    assert rows[0]['starts_at'].startswith('2026-11-28T01:30')
    assert rows[0]['ends_at'].startswith('2026-11-28T05:00')
    assert rows[-1]['starts_at'].startswith('2026-12-25T01:30')
    assert all(row['description'] and len(row['description'])>=100 for row in rows)
    assert all(row['event_url']==s.URL for row in rows)
    assert len({row['id'] for row in rows})==16

def test_krampus_hold_and_walk_thru_end_time():
    rows=run()
    assert len([x for x in rows if 'Walk-Through' in x['title']])==2
    assert not any('Krampus' in x['title'] for x in rows)
    walks=[x for x in rows if 'Walk-Through' in x['title']]
    assert walks[0]['starts_at'].startswith('2026-12-05T01:00')
    assert walks[0]['ends_at'].startswith('2026-12-05T05:00')

def test_source_and_publisher_binding_reject_forged_urls():
    from roomquest.publisher_evidence import family
    assert family(s.KEY,s.URL)=='santa_cruz_sparkys'
    assert family(s.KEY,'https://other-site.invalid/') is None
    with pytest.raises(ValueError,match='unregistered_sparkys_source'):
        s.collect(SOURCE|{'source_key':'unregistered'},lambda u,a:page(),now=NOW)

def test_missing_official_street_or_unproven_year_rejects():
    with pytest.raises(ValueError,match='sparkys_venue_or_schedule_changed'):
        run(page(venue='Located somewhere in California'))
    with pytest.raises(ValueError,match='sparkys_season_year_missing_or_ambiguous'):
        run(page(pdf='<a href="/s/Community-Display-Spaces-2025.pdf">Old year</a>'))

def test_bad_day_range_or_missing_group_rejects():
    invalid=list(GROUPS)
    invalid[-1]=('December 18th thru 42nd','Drive-Thru 5:30pm-9pm')
    with pytest.raises(ValueError,match='sparkys_invalid_date_range'):
        run(page(groups=invalid))
    with pytest.raises(ValueError,match='sparkys_schedule_incomplete_or_overlimit'):
        run(page(groups=GROUPS[:3]))

def test_drifted_clock_not_silently_inferred():
    invalid=list(GROUPS)
    invalid[0]=('November 27, 28, & 29','Drive-Thru every evening')
    with pytest.raises(ValueError,match='sparkys_schedule_incomplete_or_overlimit'):
        run(page(groups=invalid))
