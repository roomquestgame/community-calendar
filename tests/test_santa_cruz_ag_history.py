"""Agricultural History Project direct 2026 schedule; publisher evidence is mandatory."""
from datetime import datetime, timezone
import pytest
from roomquest import santa_cruz_local_venues as mod
from roomquest import preview_worker

NOW=datetime(2026,11,19,15,tzinfo=timezone.utc)

def source():
 url,kind,platform=mod.SOURCES[mod.AG_HISTORY]
 return dict(source_key=mod.AG_HISTORY,feed_url=url,kind=kind,
             platform_adapter=platform,timezone=mod.ZONE)

def fixtures():
 page="""<h2>2nd Saturday of each month</h2>
 <p>Every month we produce a 2nd Saturday on the Farm, a family event that focuses on a particular area of agriculture. Visitors can participate in the regular activities of the Ag History Project plus others related to the day's special focus.</p>
 <p>We have created some unique interactive educational activities to help you have fun learning about past agricultural practices. What we like to call our usual activities include the wooden cow milking, tractor simulator, puppet theater and wagon rides.</p>
 <h1>Upcoming Events:</h1><h2>2026 2nd Saturdays, 11:00am – 2:00pm</h2>
 <h4>November 14th – Harvest on the Farm</h4>
 <h4>December 12th – Holidays on the Farm</h4>
 <footer>Agricultural History Project Center & Museum 2601 East Lake Avenue Watsonville California 95076. Open 11 a.m.–3 p.m.</footer>"""
 hours="<p>Agricultural History Project Center & Museum at entrance to Fairgrounds, 2601 East Lake Avenue, Watsonville, CA 95076</p>"
 return page,hours

def fake_fetch(page,hours):
 def fetch(url,accept):
  assert accept=='text/html'
  if url==mod.SOURCES[mod.AG_HISTORY][0]:return page
  assert url=='https://aghistoryproject.org/hours-admission/'
  return hours
 return fetch

def test_exact_live_publisher_clock_street_full_prose_and_null_point():
 page,hours=fixtures()
 rows=mod.collect(source(),fake_fetch(page,hours),now=NOW)
 assert len(rows)==1
 row=rows[0]
 assert row['title']=='Holidays on the Farm'
 assert row['starts_at']=='2026-12-12T19:00:00+00:00'
 assert row['ends_at']=='2026-12-12T22:00:00+00:00'
 assert row['venue_address']=='2601 East Lake Avenue, Watsonville, CA 95076'
 assert row.get('lat') is None and row.get('lng') is None
 assert 'wooden cow milking' in row['description']
 assert len(row['description'])>350
 assert row['event_url']==mod.SOURCES[mod.AG_HISTORY][0]
 assert row['id']=='aghistoryproject-2026-12-12-holidays'

@pytest.mark.parametrize('replace', [
 lambda s:s.replace('2026 2nd Saturdays, 11:00am – 2:00pm','2026 2nd Saturdays, 11:00am – 3:00pm'),
 lambda s:s.replace('December 12th – Holidays on the Farm','December 12th – To Be Announced'),
 lambda s:s.replace('2601 East Lake Avenue','UNKNOWN STREET'),
 lambda s:s.replace('Every month we produce',''),
])
def test_rejects_calendar_date_address_narrative_drift(replace):
 page,hours=fixtures()
 with pytest.raises(ValueError):
  mod.collect(source(),fake_fetch(replace(page),hours),now=NOW)

def test_official_venue_street_independently_required():
 page,hours=fixtures()
 with pytest.raises(ValueError,match='street_unverified'):
  mod.collect(source(),fake_fetch(page,hours.replace('2601 East Lake Avenue','No Street')),now=NOW)

def test_does_not_fabricate_dates_after_december():
 page,hours=fixtures()
 assert mod.collect(source(),fake_fetch(page,hours),now=datetime(2026,12,15,tzinfo=timezone.utc))==[]

def test_source_contract_exact_and_reject_other_host():
 page,hours=fixtures()
 with pytest.raises(ValueError,match='unregistered_santa_cruz_local_source'):
  mod.collect(dict(source(),feed_url='https://example.com/'),fake_fetch(page,hours),now=NOW)
 assert not mod.event_url(mod.AG_HISTORY,'https://aghistoryproject.org/other/')
 assert not mod.event_url(mod.AG_HISTORY,'http://aghistoryproject.org/2nd-saturday-on-the-farm/')

def test_actual_preview_dispatch_uses_publisher_guard(monkeypatch):
 page,hours=fixtures()
 monkeypatch.setattr(preview_worker,'fetch_publisher',
   lambda url,accept,**kw:fake_fetch(page,hours)(url,accept))
 result=preview_worker.preview_source(source())
 assert result['p_future_count']==1 and result['p_error'] is None
 assert result['p_events'][0]['venue_address'].startswith('2601 East Lake Avenue')
