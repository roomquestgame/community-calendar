from datetime import datetime, timezone
from roomquest import santa_cruz_symphony as sym
from roomquest import preview_worker

SOURCE={'source_key':sym.KEY,'feed_url':sym.URL,'kind':'html','platform_adapter':'html','timezone':sym.ZONE}
NOW=datetime(2026,11,18,22,tzinfo=timezone.utc)
CAL="""<html><body><h1>2026-27 Concert Season Overview</h1>
<p>Our January concerts feature Rachmaninoff’s monumental 3rd Piano Concerto and the world premiere of Singularity Variations by local luminary Jaron Lanier, both works featuring piano soloist Serene.</p>
<h2>Classical Series Concert 3 RACHMANINOFF’S 3RD</h2>
<p>Jaron Lanier: Singularity Variations [World Premiere] —- featuring piano soloist Serene Sergei Rachmaninoff: Piano Concerto No. 3 —- featuring piano soloist Serene</p>
<h3>FEATURED SOLOIST</h3>
<p>OPEN REHEARSAL Friday, January 15, 7:30 PM – 10:00 PM (doors open at 7 PM)</p>
<h2>CONCERT DATES</h2>
<p>SATURDAY, January 16 at 7:30 PM, Civic Auditorium Doors open at 6:00 PM | Pre-concert talk at 6:30 PM Concert duration: 1 hour 45 minutes</p>
<p>SUNDAY, January 17 at 2:00 PM, Henry J. Mello Center Doors open at 12:45 PM | Pre-concert talk at 1:00 PM Concert duration: 1 hour 45 minutes</p>
<h2>Classical Series Concert 4</h2></body></html>"""
CIVIC='<html><body>307 Church St., Santa Cruz, CA 95060</body></html>'
MELLO='<html><body>250 E. Beach St. at Lincoln, Watsonville, CA 95076</body></html>'
PAGES={sym.URL:CAL,sym.HOST_URLS['Civic Auditorium'][0]:CIVIC,
       sym.HOST_URLS['Henry J. Mello Center'][0]:MELLO}

def collect(pages=None):
    return sym.collect(SOURCE,lambda url,accept:(pages or PAGES)[url],now=NOW)

def test_two_original_local_clock_concerts_and_official_streets():
    rows=collect()
    assert len(rows)==2
    assert rows[0]['venue_address'].startswith('307 Church')
    assert rows[1]['venue_address'].startswith('250 E. Beach')
    assert rows[0]['starts_at'].startswith('2027-01-17T03:30')
    assert rows[1]['starts_at'].startswith('2027-01-17T22:00')
    assert rows[0]['lat'] is None and rows[1]['lng'] is None
    assert all('Singularity Variations' in r['description'] for r in rows)
    assert all(r['event_url']==sym.URL for r in rows)

def test_drift_in_times_venue_or_ownership_fails_closed():
    import pytest
    with pytest.raises(ValueError,match='symphony_unregistered_source'):
        sym.collect(SOURCE|{'source_key':'somewhere_else'},lambda url,accept:PAGES[url],now=NOW)
    p=PAGES|{sym.HOST_URLS['Civic Auditorium'][0]:'<body>Santa Cruz</body>'}
    with pytest.raises(ValueError,match='symphony_official_venue_address_changed'): collect(p)
    p=PAGES|{sym.URL:CAL.replace('SATURDAY, January 16','SUNDAY, January 16')}
    with pytest.raises(ValueError,match='symphony_date_changed'): collect(p)

def test_expired_events_are_not_invented_future_recurrence():
    rows=sym.collect(SOURCE,lambda url,accept:PAGES[url],
                     now=datetime(2027,2,1,tzinfo=timezone.utc))
    assert rows==[]

def test_source_identity_is_exact_firstparty_calendar():
    assert sym.event_url(sym.URL)
    assert not sym.event_url('https://santacruzsymphony.org/2025-26-concert-season-overview')
