"""Tannery Arts Center: exactly one original dated market and original 1050–1060 range."""
from datetime import datetime,timezone
import pytest
from roomquest import santa_cruz_local_venues as s
from roomquest import preview_worker

NOW=datetime(2026,11,19,16,0,tzinfo=timezone.utc)
SOURCE={'source_key':s.TANNERY,'feed_url':s.SOURCES[s.TANNERY][0],
        'kind':'html','platform_adapter':'html','timezone':s.ZONE}
PAGE="""<html><main><h1>WINTER ART MARKET 2026</h1>
<h2>Saturday, Dec. 12, 2026</h2>
<p>When: Saturday, December 12, 2026 | 10am–5pm</p>
<p>Where: Tannery Arts Center, 1050–1060 River Street, Santa Cruz</p>
<p>Admission: Free and open to the public</p>
<a href="/directions">Directions</a></main></html>"""

def test_exact_one_official_market_full_clock_and_street_range():
    rows=s.collect(SOURCE,lambda u,a:PAGE,now=NOW)
    assert len(rows)==1
    event=rows[0]
    assert event['id']=='tannery-2026-12-12-winter-art-market'
    assert event['venue_address']=='1050-1060 River Street, Santa Cruz, CA 95060'
    assert event['starts_at'].startswith('2026-12-12T18:00:00')
    assert event['ends_at'].startswith('2026-12-13T01:00:00')
    assert len(event['description'])>=190
    assert 'Free and open to the public' in event['description']
    assert event['lat'] is None and event['lng'] is None
    assert event.get('image_url') is None
    assert event['event_url']==s.SOURCES[s.TANNERY][0]

@pytest.mark.parametrize('bad',[
    PAGE.replace('2026 | 10am–5pm','2026 | 10am–6pm'),
    PAGE.replace('1050–1060','1070'),
    PAGE.replace('2026</h1>','2025</h1>'),
    PAGE.replace('Saturday, Dec. 12','Sunday, Dec. 12'),
    PAGE.replace('Free and open to the public',''),
])
def test_changed_or_missing_original_evidence_fails_closed(bad):
    with pytest.raises(ValueError,match='tannery_'):
        s.collect(SOURCE,lambda u,a:bad,now=NOW)

def test_source_contract_and_url_are_exact():
    assert s.event_url(s.TANNERY,SOURCE['feed_url'])
    assert not s.event_url(s.TANNERY,'https://evil.example.com/winter-art-market')
    assert not s.event_url(s.TANNERY,'https://www.tanneryartscenter.org/different-event')
    with pytest.raises(ValueError,match='unregistered_santa_cruz_local_source'):
        s.collect({**SOURCE,'timezone':'America/New_York'},lambda u,a:PAGE,now=NOW)

def test_preview_dispatch_respects_robots_and_preserves_full_original(monkeypatch):
    def fake(u,accept,**kw):
        assert kw['respect_robots'] is True
        assert kw['allowed_hosts']==('www.tanneryartscenter.org',)
        return PAGE
    monkeypatch.setattr(preview_worker,'fetch_publisher',fake)
    r=preview_worker.preview_source(SOURCE)
    assert r['p_error'] is None and r['p_future_count']==1
    assert len(r['p_events'][0]['description'])>=190
