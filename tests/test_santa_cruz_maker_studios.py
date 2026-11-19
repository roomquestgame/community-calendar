"""Santa Cruz Maker Studios original 2026 holiday workshop calendar."""
from datetime import datetime, timezone
import pytest
from roomquest import preview_worker
from roomquest import santa_cruz_local_venues as mod

NOW=datetime(2026,11,19,16,tzinfo=timezone.utc)

def source():
 url,kind,adapter=mod.SOURCES[mod.MAKER]
 return dict(source_key=mod.MAKER,feed_url=url,kind=kind,
             platform_adapter=adapter,timezone=mod.ZONE)

def fixtures():
 page="""<html><h1>Fall Events 2026</h1><div>Fall 2026 Event Registration
 Join us for our seasonal Sunday workshops! Each event features a unique hands-on project designed to inspire creativity and celebrate the season.
 Planning to join us throughout the season? Our Maker Sundays Semester Pass includes all Sunday Maker classes and special events, offering the best value while reserving your spot for the entire semester.
 Please note: Registering through the Maker Sundays Registration Form or purchasing a Semester Pass includes these special event dates, so there is no need to register for them separately.
 Fall Wreath Making: Sunday, November 29
 Nov. 29 (Youth Ages 7 – 12) 10:00am-12:00pm – $45.00
 Nov. 29 (Advanced Ages 10 – 15) 12:30pm-2:30pm – $45.00
 Holiday Wreath Making: Sunday, December 6
 Dec. 6 (Youth Ages 7 – 12) 10:00am-12:00pm – $45.00
 Dec. 6 (Advanced Ages 10 – 15) 12:30pm-2:30pm – $45.00
 Holiday Gift Making: Sunday, December 13
 Dec. 13 (Youth Ages 7 – 12) 10:00am-12:00pm – $45.00
 Dec. 13 (Advanced Ages 10 – 15) 12:30pm-2:30pm – $45.00
 Holiday Gift Making: Sunday, December 20
 Dec. 20 (Youth Ages 7- 12) 10:00am-12:00pm – $45.00
 Dec. 20 (Advanced Ages 10 – 15) 12:30pm-2:30pm – $45.00
 Signing up a second family member?
 Dec. 20 (Youth Ages 7 – 12) 10:00am-12:00pm – $36.00
 </div></html>"""
 about="""<html><h1>About Santa Cruz Maker Studios</h1>
 <p>Visit us at 427 A. Swift Street, Santa Cruz, CA 95060</p></html>"""
 return page,about

def fake_fetch(page,about):
 def fetch(url,accept):
  assert accept=="text/html"
  if url==mod.SOURCES[mod.MAKER][0]:return page
  assert url=="https://scmakerstudios.com/about/"
  return about
 return fetch

def test_exact_eight_original_sessions_street_text_timezone_and_no_fake_points():
 p,a=fixtures()
 rows=mod.collect(source(),fake_fetch(p,a),now=NOW)
 assert len(rows)==8
 assert len({(r["id"],r["starts_at"]) for r in rows})==8
 assert all(r["venue_address"]=="427 A. Swift Street, Santa Cruz, CA 95060" for r in rows)
 assert all(r.get("lat") is None and r.get("lng") is None for r in rows)
 assert all(r["timezone"]==mod.ZONE and len(r["description"])>=300 for r in rows)
 assert all(r["event_url"]==mod.SOURCES[mod.MAKER][0] for r in rows)
 assert all("Registering through the Maker Sundays" in r["description"] for r in rows)
 times={(r["id"],r["starts_at"],r["ends_at"]) for r in rows}
 assert ("scmaker-2026-11-29-youth","2026-11-29T18:00:00+00:00","2026-11-29T20:00:00+00:00") in times
 assert ("scmaker-2026-12-20-advanced","2026-12-20T20:30:00+00:00","2026-12-20T22:30:00+00:00") in times

@pytest.mark.parametrize("bad",[
 lambda s:s.replace("Fall Events 2026","Fall Events 2025"),
 lambda s:s.replace("Holiday Wreath Making: Sunday, December 6","Holiday Wreath Making: Sunday, December 7"),
 lambda s:s.replace("Dec. 13 (Youth Ages 7 – 12) 10:00am-12:00pm","Dec. 13 (Youth Ages 7 – 12) 10:00am-11:00am"),
 lambda s:s.replace("Join us for our seasonal Sunday workshops!","Join us some other time!"),
 lambda s:s.replace("Fall Wreath Making: Sunday, November 29","Private Appointment"),
])
def test_calendar_drift_rejected(bad):
 p,a=fixtures()
 with pytest.raises(ValueError):
  mod.collect(source(),fake_fetch(bad(p),a),now=NOW)

def test_independent_official_address_required():
 p,a=fixtures()
 with pytest.raises(ValueError,match="street_unverified"):
  mod.collect(source(),fake_fetch(p,a.replace("427 A. Swift Street","No real street")),now=NOW)

def test_do_not_invent_future_session_dates():
 p,a=fixtures()
 assert mod.collect(source(),fake_fetch(p,a),now=datetime(2027,1,1,tzinfo=timezone.utc))==[]

def test_strict_source_contract_and_event_url():
 p,a=fixtures()
 with pytest.raises(ValueError,match="unregistered_santa_cruz_local_source"):
  mod.collect(dict(source(),feed_url="https://example.org/"),fake_fetch(p,a),now=NOW)
 assert not mod.event_url(mod.MAKER,"https://scmakerstudios.com/sunday-maker-registration/")
 assert mod.event_url(mod.MAKER,mod.SOURCES[mod.MAKER][0])

def test_preview_dispatch_publisher_guard(monkeypatch):
 p,a=fixtures()
 def guarded(url,accept,**kw):
  assert kw.get("respect_robots") is True
  assert kw.get("allowed_hosts")==("scmakerstudios.com",)
  return fake_fetch(p,a)(url,accept)
 monkeypatch.setattr(preview_worker,"fetch_publisher",guarded)
 r=preview_worker.preview_source(source())
 assert r["p_error"] is None and r["p_future_count"]==8
 assert len(r["p_events"])==8
