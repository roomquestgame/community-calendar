from datetime import datetime, timedelta, timezone

from icalendar import Calendar
import pytest

from roomquest.ics_adapter import apply_declared_calendar_timezone, parse
from roomquest.registration_formats import probe


def calendar(start='20270105T180000', end='20270105T190000', header='Europe/London', extra=''):
    return ('BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//EN\r\n' +
            (f'X-WR-TIMEZONE:{header}\r\n' if header else '') +
            'BEGIN:VEVENT\r\nUID:test\r\nSUMMARY:Community match\r\n' +
            f'DTSTART:{start}\r\nDTEND:{end}\r\n' + extra +
            'LOCATION:Long Road Sixth Form College, Long Road, Cambridge, CB2 8PX\r\n' +
            'URL:https://example.org/match/1\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n')


@pytest.mark.parametrize('month,hour', [('01',18), ('07',17)])
def test_publisher_default_respects_london_summer_time(month,hour):
    c=Calendar.from_ical(calendar(f'2027{month}05T180000',f'2027{month}05T190000'))
    assert apply_declared_calendar_timezone(c)
    e=c.walk('VEVENT')[0]
    assert e.decoded('DTSTART').astimezone(timezone.utc).hour==hour
    assert e['DTSTART'].params['TZID']=='Europe/London'
    assert not apply_declared_calendar_timezone(c)


@pytest.mark.parametrize('start,end,reason', [
    ('20270328T013000','20270328T023000','timezone_nonexistent'),
    ('20271031T013000','20271031T023000','timezone_ambiguous'),
])
def test_ambiguous_or_missing_wall_times_are_not_invented(start,end,reason):
    with pytest.raises(ValueError,match=reason):
        apply_declared_calendar_timezone(Calendar.from_ical(calendar(start,end)))


def test_explicit_utc_and_date_only_values_are_unchanged():
    for payload in [calendar('20270105T180000Z','20270105T190000Z'),
                    calendar().replace('DTSTART:20270105T180000','DTSTART;VALUE=DATE:20270105').replace('DTEND:20270105T190000','DTEND;VALUE=DATE:20270106'),
                    calendar().replace('DTSTART:', 'DTSTART;TZID=America/New_York:').replace('DTEND:', 'DTEND;TZID=America/New_York:')]:
        c=Calendar.from_ical(payload); before=c.to_ical()
        assert not apply_declared_calendar_timezone(c)
        assert c.to_ical()==before


@pytest.mark.parametrize('field', ['RRULE:FREQ=WEEKLY', 'RDATE:20270112T180000',
                                 'EXDATE:20270112T180000', 'RECURRENCE-ID:20270105T180000'])
def test_floating_recurrence_is_held(field):
    c=Calendar.from_ical(calendar(extra=field+'\r\n'));before=c.to_ical()
    assert not apply_declared_calendar_timezone(c)
    assert c.to_ical()==before


def test_absent_or_invalid_default_is_not_guessed():
    assert not apply_declared_calendar_timezone(Calendar.from_ical(calendar(header=None)))
    with pytest.raises(ValueError,match='calendar_timezone_unresolved'):
        apply_declared_calendar_timezone(Calendar.from_ical(calendar(header='Invalid/Zone')))
    with pytest.raises(ValueError,match='calendar_timezone_conflict'):
        apply_declared_calendar_timezone(Calendar.from_ical(calendar().replace('X-WR-TIMEZONE:Europe/London','X-WR-TIMEZONE:Europe/London\r\nX-WR-TIMEZONE:America/New_York')))


def test_registration_probe_and_recurring_collection_share_normalization():
    start=(datetime.now(timezone.utc)+timedelta(days=3)).replace(hour=18,minute=0,second=0,microsecond=0)
    payload=calendar(start.strftime('%Y%m%dT%H%M%S'),(start+timedelta(hours=1)).strftime('%Y%m%dT%H%M%S'))
    url='https://example.org/events.ics'
    assert probe(url,payload,'ical')
    rows=parse(payload,{'url':url,'source_key':'fixture'},legacy=True)
    assert len(rows)==1 and rows[0]['timezone']=='Europe/London'
    assert rows[0]['id']=='test' and rows[0]['venue_name'].endswith('CB2 8PX')


def test_reviewed_hockey_retains_actual_publisher_street_without_coordinates():
    from roomquest.reviewed_venue_addresses import complete_address
    from roomquest.registration_formats import source_key
    url='https://cambridgesouthhockeyclub.co.uk/matches/cshc_matches.ics'
    source={'url':url,'source_key':source_key(url)}
    row={'venue_name':'Long Road Sixth Form College, Long Road, Cambridge, CB2 8PX','venue_address':''}
    complete_address(row,source)
    assert row['venue_address']==row['venue_name']
    assert 'lat' not in row and 'lng' not in row
    for location in ['Venue TBC','Cambridge, CB2 8PX','Virtual meeting']:
        other={'venue_name':location,'venue_address':''};complete_address(other,source)
        assert other['venue_address']==''
    for other_source in [{'url':url,'source_key':'wrong'}, {'url':'https://other.example','source_key':source_key(url)}]:
        other={'venue_name':row['venue_name'],'venue_address':''};complete_address(other,other_source)
        assert other['venue_address']==''
    other={'venue_name':row['venue_name'],'venue_address':'Publisher supplied address'}
    complete_address(other,source);assert other['venue_address']=='Publisher supplied address'
