from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys

import pytest

MODULE = Path(__file__).resolve().parents[1] / 'roomquest/raleigh_next_community.py'
spec = importlib.util.spec_from_file_location('roomquest.raleigh_next_community', MODULE)
dose = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = dose
spec.loader.exec_module(dose)
NOW = datetime.fromisoformat('2026-11-15T13:45:00+00:00')
SOURCE = {'source_key':dose.SOURCE,'feed_url':dose.CALENDAR,'kind':'html',
    'platform_adapter':'html','timezone':dose.ZONE}
IMAGE = 'https://cdn.prod.website-files.com/6a6cc6aad2c72a2f2cf13480/6ada00a1e1a209182bed7662_event.png'
CARDS = [
    ('walk-raleigh','Dose Walk Club | Raleigh','Every Thursday Morning',''),
    ('book-raleigh','Dose Book Club | Raleigh','Thursday, November 19, 2026','6pm'),
    ('kirtan-north-hills','Community Kirtan — North Hills','Wednesday, December 9, 2026','7:30pm'),
    ('walk-durham','Dose Walk Club | Durham','Every Thursday Morning',''),
    ('book-durham','Dose Book Club | Durham','Monday, November 16, 2026','6:30pm'),
    ('kirtan-durham','Community Kirtan — Durham','Thursday, December 10, 2026','7:30m'),
    ('member-love','Member Love 2026','Friday, November 6 – Saturday, November 14, 2026',''),
]


@pytest.fixture(autouse=True)
def fixed_preview_clock(monkeypatch):
    import roomquest.preview_worker as worker
    monkeypatch.setattr(worker,'_future_datetime',lambda value:value.astimezone(timezone.utc))


def calendar(cards=CARDS):
    return '<h1 class="class-visual-name">Events</h1><div class="w-dyn-items">'+''.join(
        f'<div class="w-dyn-item"><a href="/events/{slug}"><h3 class="journal-card-title">{title}</h3>'
        f'<div class="journal-meta-row"><div class="journal-meta-item">{label}</div>'
        f'<div class="journal-meta-item">•</div><div class="journal-meta-item">{clock}</div></div></a></div>'
        for slug,title,label,clock in cards)+'</div>'


def detail(card,place,start,body,*,status='EventScheduled',geo=None,end=None):
    slug,title,label,clock=card
    event={'@context':'https://schema.org','@type':'Event','name':title,'url':'/events/'+slug,
        'description':'','startDate':start,'image':IMAGE,'eventStatus':'https://schema.org/'+status,
        'eventAttendanceMode':'https://schema.org/OfflineEventAttendanceMode',
        'location':{'@type':'Place','name':place}}
    if geo is not None:event['location']['geo']=geo
    if end is not None:event['endDate']=end
    return (f'<h1 class="class-visual-name">{title}</h1><div class="event-content-col"><div class="class-content-top">'
        f'<div class="journal-meta-row"><div class="journal-meta-item">{label}</div><div class="journal-meta-item">•</div>'
        f'<div class="journal-meta-item">{clock}</div><div class="journal-meta-item">•</div><p class="journal-meta-item">{place}</p></div>'
        '<div class="class-description w-richtext">'+body+'</div></div>'
        '<div class="class-content-bottom"><a href="https://unrelated.example/">RSVP</a></div></div>'
        '<script type="application/ld+json">'+json.dumps(event)+'</script>')


def payloads():
    data={dose.CALENDAR:calendar()}
    for url,(title,address) in dose.VENUE_PAGES.items():
        data[url]=f'<div class="class-visual-bottom"><h1 class="class-visual-name">{title}</h1><p class="class-visual-tagline">{address}</p></div>'
    data[dose.ORIGIN+'/events/walk-raleigh']=detail(CARDS[0],'Dose Downtown Raleigh','',
        '<p>Our public neighborhood walk welcomes everyone to move and meet neighbors.</p>'
        '<p>Start at 7:00am for a stretch, then depart at 7:15am. Join the café hang until 8:30am.</p>')
    data[dose.ORIGIN+'/events/book-raleigh']=detail(CARDS[1],'Sixty Vines, North Hills','2026-11-19T23:00:00Z',
        '<p>This monthly book gathering welcomes new readers. The one announced date is November 19.</p>')
    data[dose.ORIGIN+'/events/kirtan-north-hills']=detail(CARDS[2],'Dose North Hills Raleigh, 540 St. Albans','2026-12-10T00:30:00Z',
        '<p>Join our welcoming musical gathering for shared singing, listening and community.</p><p>Tickets support the musicians.</p>')
    return data


def replay(data=None,now=NOW,max_fetches=3):
    data=data or payloads();calls=[];state=None;chunks=[]
    def fetch(url,accept):
        assert accept=='text/html'
        calls.append(url)
        return data[url]
    for _ in range(10):
        result=dose.collect_chunk(SOURCE,fetch,checkpoint=state,now=now,max_fetches=max_fetches)
        chunks.append(result);state=result['checkpoint']
        if result['complete']:break
    assert result['complete']
    return result,calls,chunks


def test_complete_raleigh_calendar_is_two_bounded_chunks_and_ten_occurrences():
    result,calls,chunks=replay()
    assert len(calls)==6 and len(chunks)==2 and len(set(calls))==6
    assert chunks[0]['events']==[] and not chunks[0]['complete']
    cp=result['checkpoint']
    assert cp['listing_total']==7 and cp['outside_scope_count']==3 and cp['outside_window_count']==1
    assert cp['manifest_count']==cp['cursor']==3 and len(result['events'])==10
    assert dose.checkpoint_complete(cp)
    assert all(e['lat'] is None and e['lng'] is None for e in result['events'])
    assert all(e['image_url']==IMAGE for e in result['events'])
    assert sum(e['ends_at'] is None for e in result['events'])==2


def test_three_real_venues_keep_offsite_book_club_and_two_suites():
    rows=replay()[0]['events']
    book=next(e for e in rows if 'Book Club' in e['title'])
    kirtan=next(e for e in rows if 'Kirtan' in e['title'])
    assert book['venue_name']=='Sixty Vines, North Hills'
    assert book['venue_address']=='4000 Center at North Hills Street Suite 110, Raleigh, NC 27609'
    assert kirtan['venue_address']=='540 St. Albans Drive Suite 100, Raleigh, NC 27609'
    assert book['location_evidence_url']=='https://www.sixtyvines.com/locations/raleigh-nc'
    assert kirtan['location_evidence_url']=='https://www.visitnorthhills.com/directory/dose-yoga'


def test_weekday_recurrence_uses_explicit_clock_and_rolling_local_window():
    rows=replay()[0]['events'];walks=[e for e in rows if 'Walk Club' in e['title']]
    assert [e['starts_at'][:10] for e in walks]==['2026-11-19','2026-11-26','2026-12-03','2026-12-10','2026-12-17','2026-12-24','2026-12-31','2027-01-07']
    assert all(e['starts_at'].endswith('12:00:00+00:00') and e['ends_at'].endswith('13:30:00+00:00') for e in walks)
    late=replay(now=datetime.fromisoformat('2026-12-28T13:45:00+00:00'))[0]['events']
    assert late and all(e['starts_at'][:10]>='2026-12-28' for e in late)
    assert len({e['id'] for e in rows})==10


def test_weekly_times_follow_eastern_dst_without_changing_wall_clock():
    data=payloads();data[dose.CALENDAR]=calendar(CARDS[:6])
    rows=replay(data,now=datetime.fromisoformat('2026-10-20T13:45:00+00:00'))[0]['events']
    walks=[e for e in rows if 'Walk Club' in e['title']]
    assert walks[0]['starts_at']=='2026-10-22T11:00:00+00:00'
    assert next(e for e in walks if e['starts_at'].startswith('2026-11-05'))['starts_at']=='2026-11-05T12:00:00+00:00'


def test_explicit_program_start_prevents_occurrences_before_launch():
    data=payloads();data[dose.CALENDAR]=calendar(CARDS[:6]);url=dose.ORIGIN+'/events/walk-raleigh'
    data[url]=data[url].replace('Our public neighborhood walk','Starting November 5th. Our public neighborhood walk')
    walks=[e for e in replay(data,now=datetime.fromisoformat('2026-10-20T13:45:00+00:00'))[0]['events'] if 'Walk Club' in e['title']]
    assert walks[0]['starts_at']=='2026-11-05T12:00:00+00:00'
    january=[e for e in replay(data,now=datetime.fromisoformat('2027-01-01T13:45:00+00:00'))[0]['events'] if 'Walk Club' in e['title']]
    assert january[0]['starts_at']=='2027-01-07T12:00:00+00:00'


def test_explicit_closure_dates_are_removed_and_other_programs_remain():
    data=payloads();url=dose.ORIGIN+'/events/walk-raleigh'
    data[url]=data[url].replace('</p></div>','</p><p>No walk on November 26, 2026 and December 24, 2026.</p></div>')
    rows=replay(data)[0]['events'];walks=[e for e in rows if 'Walk Club' in e['title']]
    assert len(rows)==8 and len(walks)==6
    assert not any(e['starts_at'].startswith(('2026-11-26','2026-12-24')) for e in walks)


@pytest.mark.parametrize('note',['No walk on Thanksgiving.','No walk on November 26 through December 24, 2026.',
    'No walk on Friday, November 26, 2026.','If it rains, the walk will be cancelled.',
    'Except February 30, 2027.'])
def test_unresolved_or_contradictory_closures_hold_weekly_program(note):
    data=payloads();url=dose.ORIGIN+'/events/walk-raleigh'
    data[url]=data[url].replace('</p></div>',f'</p><p>{note}</p></div>')
    result=replay(data)[0]
    assert len(result['events'])==2
    assert result['checkpoint']['diagnostics'][0]['reason']=='raleigh_dose_schedule_unresolved'


def test_concrete_schema_and_visible_time_must_agree():
    data=payloads();url=dose.ORIGIN+'/events/book-raleigh'
    data[url]=data[url].replace('2026-11-19T23:00:00Z','2026-11-19T18:00:00Z')
    result=replay(data)[0]
    assert len(result['events'])==9 and result['checkpoint']['diagnostics'][0]['reason']=='raleigh_dose_schedule_unresolved'


def test_changed_native_identity_fails_the_calendar():
    data=payloads();url=dose.ORIGIN+'/events/book-raleigh'
    data[url]=data[url].replace('"url": "/events/book-raleigh"','"url": "https://unrelated.example/event"')
    with pytest.raises(ValueError,match='raleigh_dose_detail_identity'):replay(data)


def test_visible_studio_change_never_reuses_old_binding():
    data=payloads();data[dose.NORTH_HILLS]=data[dose.NORTH_HILLS].replace('Suite 100','Suite 999')
    with pytest.raises(ValueError,match='raleigh_dose_street_unresolved'):replay(data)


def test_moved_event_is_held_without_studio_fallback():
    data=payloads();url=dose.ORIGIN+'/events/book-raleigh'
    data[url]=data[url].replace('This monthly book gathering','This event has moved to a new location. This monthly book gathering')
    result=replay(data)[0]
    assert len(result['events'])==9 and result['checkpoint']['diagnostics'][0]['reason']=='raleigh_dose_street_unresolved'


def test_full_native_prose_retained_even_when_jsonld_summary_empty():
    data=payloads();url=dose.ORIGIN+'/events/book-raleigh'
    text='Opening paragraph. '+('Detailed publisher prose about this gathering. '*60)+'Final unique sentence.'
    data[url]=detail(CARDS[1],'Sixty Vines, North Hills','2026-11-19T23:00:00Z','<p>'+text+'</p>')
    book=next(e for e in replay(data)[0]['events'] if 'Book Club' in e['title'])
    assert book['description']==text and len(text)>2000


def test_description_over_limit_fails_instead_of_truncating():
    data=payloads();url=dose.ORIGIN+'/events/book-raleigh'
    data[url]=detail(CARDS[1],'Sixty Vines, North Hills','2026-11-19T23:00:00Z','<p>'+('Long public prose. '*800)+'</p>')
    with pytest.raises(ValueError,match='raleigh_dose_description_limit'):replay(data)


def test_empty_body_is_held_without_using_short_schema_summary():
    data=payloads();url=dose.ORIGIN+'/events/book-raleigh'
    data[url]=detail(CARDS[1],'Sixty Vines, North Hills','2026-11-19T23:00:00Z','<p>RSVP</p>')
    result=replay(data)[0]
    assert len(result['events'])==9 and result['checkpoint']['diagnostics'][0]['reason']=='raleigh_dose_description_missing'


def test_complete_checkpoint_resumes_without_refetch_and_tampering_is_rejected():
    result=replay()[0]
    def forbidden(*args):raise AssertionError('completed checkpoint refetched')
    assert dose.collect_chunk(SOURCE,forbidden,checkpoint=result['checkpoint'],now=NOW)['events']==result['events']
    bad=deepcopy(result['checkpoint']);bad['events'][0]['description']='Changed body'
    with pytest.raises(ValueError,match='raleigh_dose_checkpoint_invalid'):
        dose.collect_chunk(SOURCE,forbidden,checkpoint=bad,now=NOW)


def test_partial_zero_cursor_is_not_complete_and_count_forgery_is_rejected():
    data=payloads();data[dose.CALENDAR]=calendar([CARDS[-1]])
    one=dose.collect_chunk(SOURCE,lambda url,accept:data[url],now=NOW,max_fetches=1)
    assert one['checkpoint']['cursor']==one['checkpoint']['manifest_count']==0
    assert not one['complete'] and not dose.checkpoint_complete(one['checkpoint'])
    complete=dose.collect_chunk(SOURCE,lambda url,accept:data[url],checkpoint=one['checkpoint'],now=NOW)
    assert complete['complete'] and complete['events']==[]
    partial=replay(max_fetches=1)[2][0]['checkpoint'];partial=deepcopy(partial)
    partial['cursor']=partial['manifest_count'];dose._seal(partial)
    with pytest.raises(ValueError,match='raleigh_dose_checkpoint_invalid'):
        dose.collect_chunk(SOURCE,lambda *args:None,checkpoint=partial,now=NOW)


def test_listing_pagination_fails_instead_of_silently_collecting_first_page():
    data=payloads();data[dose.CALENDAR]+='<a class="w-pagination-next" href="?page=2">Next</a>'
    with pytest.raises(ValueError,match='raleigh_dose_calendar_changed'):replay(data)


def test_native_points_only_and_no_coordinate_from_studio_footer():
    data=payloads();url=dose.ORIGIN+'/events/book-raleigh'
    data[url]=detail(CARDS[1],'Sixty Vines, North Hills','2026-11-19T23:00:00Z',
        '<p>The book club meets to discuss an excellent book together with new friends.</p>',geo={'latitude':35.8,'longitude':-78.64})
    book=next(e for e in replay(data)[0]['events'] if 'Book Club' in e['title'])
    assert (book['lat'],book['lng'])==(35.8,-78.64) and book['location_provenance']=='publisher_event_geo'
    bad=deepcopy(data);bad[url]=bad[url].replace('35.8','45.8')
    assert len(replay(bad)[0]['events'])==9


def test_exact_source_tuple_and_deadline_gate_precede_fetch():
    def forbidden(*args):raise AssertionError('unauthorized fetch')
    with pytest.raises(ValueError,match='raleigh_dose_source_unregistered'):
        dose.collect_chunk(dict(SOURCE,feed_url=dose.CALENDAR+'?other=1'),forbidden,now=NOW)
    with pytest.raises(ValueError,match='collection_deadline'):
        dose.collect_chunk(SOURCE,forbidden,now=NOW,deadline_at=0)
