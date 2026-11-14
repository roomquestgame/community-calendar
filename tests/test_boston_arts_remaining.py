from copy import deepcopy
from datetime import datetime, timezone
from html import escape
import json
import unittest
from unittest.mock import Mock, patch

from roomquest import boston_arts_remaining as b
from tests.test_new_york_arts import fake_record

NOW = datetime(2026, 11, 14, 22, tzinfo=timezone.utc)


def source(key):
    return dict(source_key=key, feed_url=b.SOURCES[key][0], kind='html', platform_adapter='html', timezone=b.ZONE)


def library_ics(location='Hunneman Hall - Brookline Village, Brookline Village', title='Family workshop', body='A complete family workshop description.', url=None):
    return ('BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:LibCal-20102-42\n'
            'DTSTART:20261118T190000Z\nDTEND:20261118T200000Z\nSUMMARY:' + title + '\n'
            'URL:' + (url or 'https://brooklinelibrary.libcal.com/event/42') + '\n'
            'LOCATION:' + location.replace(',', '\\,') + '\nDESCRIPTION:' + body + '\nEND:VEVENT\nEND:VCALENDAR')


def mfa_listing(index=1, next_page=None):
    return ('<main><h1>Program Calendar</h1><div class="well"><h2><a href="/event/workshop?event=' + str(index) + '">Workshop</a></h2>'
            '<span class="date-display-range">Wednesday, November 18, 2026<br>10:00 am–11:00 am</span></div>'
            + (f'<nav aria-label="Pagination"><a rel="next" href="?page={next_page}">Next</a></nav>' if next_page is not None else '') + '</main>')


def mfa_detail(index=1, body='Complete publisher description.', extra='This session uses clay.'):
    return (f'<main><h1>Workshop</h1><div class="node--type-performance" data-history-node-id="{index}">'
            '<add-to-calendar-button name="Workshop" timezone="America/New_York" startdate="2026-11-18" enddate="2026-11-18" '
            'starttime="10:00" endtime="11:00" location="Museum of Fine Arts, Boston, 465 Huntington Ave, Boston, MA 02115, USA"></add-to-calendar-button>'
            f'<div class="field--name-body">{escape(extra)}</div></div><div class="field--name-body">{escape(body)}</div>'
            '<div class="views-field-body">Another upcoming session summary.</div></main>')


def ica_detail(body='Full museum narrative.', days=2, canonical=True):
    url='https://www.icaboston.org/events/family-day/'
    event=dict(**{'@type':'Event'},name='Family day',eventAttendanceMode='https://schema.org/OfflineEventAttendanceMode',
               eventStatus='https://schema.org/EventScheduled',description='Truncated...',
               location={'name':'ICA Boston','address':'25 Harbor Shore Drive. Boston MA 02210'},
               startDate='2026-11-18T13:00:00-05:00',endDate='2026-11-18T14:00:00-05:00')
    head=f'<link rel="canonical" href="{url}">' if canonical else '<script type="application/ld+json">'+json.dumps({'@graph':[{'@type':'WebPage','url':url}]})+'</script>'
    return (head+'<h1 class="page-title">Family day</h1><script type="application/ld+json">'+json.dumps(event)+'</script>'
            f'<div class="field-name-body">{escape(body)}</div><div class="field-name-event-date">'
            + ''.join('<div class="event-date-display">Native date</div>' for _ in range(days))+'</div>'
            f'<a href="{url.rstrip("/")}/addtocal/ics">iCalendar</a>'
            '<aside><div class="field-name-event-date"><div class="event-date-display">Unrelated recommended event.</div></div></aside>')


def ica_ics(days=2, index_start=0):
    events=[]
    for n in range(days):
        events.append(f'BEGIN:VEVENT\nUID:event-100-{n+index_start}@www.icaboston.org\nSUMMARY:Family day\nDTSTART:202611{18+n:02}T180000Z\nDTEND:202611{18+n:02}T190000Z\nEND:VEVENT')
    return 'BEGIN:VCALENDAR\nVERSION:2.0\n'+'\n'.join(events)+'\nEND:VCALENDAR'


def bca_detail(body='Complete public program narrative.', schedule='11/18/2026<br>6pm-8pm'):
    return ('<link rel="canonical" href="https://bostonarts.org/event/program/"><main>'
            '<section class="section-hero"><h1>Public program</h1></section><section class="section-copy is-description">'
            f'<div class="wysiwyg sidebar"><p><strong>{schedule}</strong></p><h6 class="address-title">BCA Mills Gallery</h6>'
            '<p>551 Tremont St.<br>Boston, MA 02116</p></div>'
            f'<div class="wysiwyg">{escape(body)}</div></section>'
            '<section class="section-copy"><div class="wysiwyg">Complete speaker biography.</div></section>'
            '<section class="related-events">Other event summary.</section></main>')


def sowa_page():
    november='<br>'.join(b.SOWA_NOVEMBER_HOURS)
    december='<br>'.join(b.SOWA_DECEMBER_HOURS)
    def question(title, content):
        return f'<div class="elementor-toggle-item"><a class="elementor-toggle-title">{title}</a><div class="elementor-tab-content">{content}</div></div>'
    return ('<link rel="canonical" href="https://www.sowaboston.com/sowa-christmas-market/">'
            '<article id="post-23882"><h2>The 11th Annual SoWa Christmas Market</h2>'
            '<h4>November 20 through December 27, 2026</h4>'
            '<div class="elementor-widget-text-editor">Boston’s premier indoor holiday shopping experience. '+('Full original program detail. '*100)+'Final admission instruction.</div>'
            '<div class="elementor-widget-text-editor"><h3>Hours of Operation</h3>'
            f'<h5>November Hours</h5><p>{november}</p><h5>Starting December 1</h5><p>{december}</p></div>'
            + question('When is the Christmas Market open?',november+'<br>'+december)
            + question('Where is SoWa Christmas Market located?','SoWa Boston, 550 Harrison Ave., Boston, MA 02118')
            + question('What should visitors know?','The full visitor FAQ is preserved.')
            + '<aside>The old 8th annual winter festival.</aside></article>')


class BostonArtsRemainingTests(unittest.TestCase):
    def setUp(self):
        p=patch.object(b,'record',side_effect=fake_record);p.start();self.addCleanup(p.stop)

    def test_library_repairs_existing_key_with_full_native_body_and_exact_branches(self):
        body='Original library details. '*130+'Final entry instruction.'
        row=b.collect(source(b.BROOKLINE),Mock(return_value=library_ics(body=body)),now=NOW)[0]
        self.assertEqual(b.EXISTING_SOURCE_IDS[b.BROOKLINE],3718)
        self.assertEqual(row['description'],body)
        self.assertEqual(row['venue_address'],'361 Washington Street, Brookline, MA 02445')
        row=b._brookline(library_ics(location='Meeting Room - Putterham, Putterham'),NOW)[0]
        self.assertEqual(row['venue_address'],'959 West Roxbury Parkway, Chestnut Hill, MA 02467')

    def test_library_canonical_slugs_offsite_resolution_and_private_admin_exclusion(self):
        body='Meet OFF SITE at the United Parish Church at 210 Harvard Street. Entrance is on Marion Street.'
        row=b._brookline(library_ics(location='Off-site',body=body,url='https://brooklinelibrary.libcal.com/calendar/events/english-class'),NOW)[0]
        self.assertEqual(row['venue_address'],'210 Harvard Street, Brookline, MA 02446')
        self.assertEqual(b._brookline(library_ics(location='Off-site',body='Meet somewhere to be announced.'),NOW),[])
        for title in ('Staff Use','Room Unavailable','Virtual storytime','CANCELED: Workshop'):
            self.assertEqual(b._brookline(library_ics(title=title),NOW),[])
        self.assertEqual(b._brookline(library_ics(body=''),NOW),[])

    def test_mfa_preserves_generic_and_selected_occurrence_descriptions(self):
        item=b._mfa_listing(mfa_listing(),b.SOURCES[b.MFA][0],NOW)[0][0]
        body='Full published workshop instructions. '*100+'Final accessibility detail.'
        row=b._mfa_detail(item,mfa_detail(body=body),NOW)[0]
        self.assertIn('This session uses clay.',row['description'])
        self.assertIn(body,row['description'])
        self.assertNotIn('Another upcoming',row['description'])
        self.assertEqual(row['venue_address'],'465 Huntington Avenue, Boston, MA 02115')
        self.assertEqual((row['lat'],row['lng']),(42.339381,-71.094048))
        self.assertEqual(row['location_provenance'],'publisher_partner_museum_geo')
        self.assertEqual(row['starts_at'],'2026-11-18T10:00:00-05:00')

    def test_mfa_rejects_selected_id_and_timezone_conflicts(self):
        item=b._mfa_listing(mfa_listing(),b.SOURCES[b.MFA][0],NOW)[0][0]
        for payload in (mfa_detail(index=2),mfa_detail().replace('America/New_York','UTC'),
                        mfa_detail().replace('465 Huntington Ave','230 The Fenway')):
            with self.assertRaises(ValueError):b._mfa_detail(item,payload,NOW)

    def test_mfa_all_listing_pages_finish_before_any_rows_are_exposed(self):
        fetch=Mock(side_effect=[mfa_listing(1,1),mfa_listing(2),mfa_detail(1),mfa_detail(2)])
        first=b.collect_chunk(source(b.MFA),fetch,now=NOW)
        self.assertFalse(first['checkpoint']['listing_complete'])
        second=b.collect_chunk(source(b.MFA),fetch,checkpoint=first['checkpoint'],now=NOW)
        self.assertFalse(second['complete']);self.assertEqual(second['events'],[])
        third=b.collect_chunk(source(b.MFA),fetch,checkpoint=second['checkpoint'],now=NOW,max_details=1)
        self.assertFalse(third['complete']);self.assertEqual(third['events'],[])
        final=b.collect_chunk(source(b.MFA),fetch,checkpoint=third['checkpoint'],now=NOW)
        self.assertTrue(final['complete']);self.assertEqual(len(final['events']),2)
        b._checkpoint(final['checkpoint'],b.MFA,NOW)
        changed=deepcopy(final['checkpoint']);changed['events'][0]['lat']=42.36
        with self.assertRaisesRegex(ValueError,'checkpoint_invalid'):b._checkpoint(changed,b.MFA,NOW)
        fetch.reset_mock();b.collect_chunk(source(b.MFA),fetch,checkpoint=final['checkpoint'],now=NOW);fetch.assert_not_called()

    def test_ica_full_html_hydrates_all_native_ics_occurrences_and_stable_identity(self):
        item=dict(url='https://www.icaboston.org/events/family-day/',title='Family day',labels=['ICA Kids'])
        body='An original family activity. '*120+'Full final directions.'
        rows=b._ica_detail(item,ica_detail(body=body,canonical=False),Mock(return_value=ica_ics()),NOW)
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['description'],body)
        self.assertEqual(rows[0]['venue_address'],'25 Harbor Shore Drive, Boston, MA 02210')
        moved=b._ica_detail(item,ica_detail(body=body),Mock(return_value=ica_ics(index_start=4)),NOW)
        self.assertEqual([r['id']for r in rows],[r['id']for r in moved])

    def test_larger_mfa_chunk_remains_bounded_and_stops_before_deadline_reserve(self):
        listing=''.join(mfa_listing(n) for n in range(1,13)).replace('</main><main>','')
        state=b.collect_chunk(source(b.MFA),Mock(return_value=listing),now=NOW)['checkpoint']
        def detail(url, accept):
            return mfa_detail(int(url.rsplit('=',1)[1]))
        fetch=Mock(side_effect=detail)
        chunk=b.collect_chunk(source(b.MFA),fetch,checkpoint=state,now=NOW)
        self.assertEqual(chunk['checkpoint']['cursor'],10)
        self.assertEqual(fetch.call_count,10)
        self.assertFalse(chunk['complete']);self.assertEqual(chunk['events'],[])
        fetch.reset_mock()
        with patch.object(b,'monotonic',side_effect=[0,24]):
            chunk=b.collect_chunk(source(b.MFA),fetch,checkpoint=state,now=NOW,deadline_at=35)
        self.assertEqual(chunk['checkpoint']['cursor'],1)
        self.assertEqual(fetch.call_count,1)
        self.assertFalse(chunk['complete']);self.assertEqual(chunk['events'],[])

    def test_ica_native_schedule_mismatch_or_missing_full_body_is_held(self):
        item=dict(url='https://www.icaboston.org/events/family-day/',title='Family day')
        for payload,ics in ((ica_detail(),ica_ics(days=1)),(ica_detail(),ica_ics().replace('20261118T180000Z','20261118T190000Z')),(ica_detail(body=''),ica_ics())):
            with self.assertRaises(ValueError):b._ica_detail(item,payload,Mock(return_value=ics),NOW)

    def test_bca_preserves_full_biography_and_actual_clock_and_street(self):
        item=dict(url='https://bostonarts.org/event/program/',title='Public program')
        body='Complete artist program description. '*100
        row=b._bca_detail(item,bca_detail(body),NOW)[0]
        self.assertIn(body.strip(),row['description']);self.assertIn('Complete speaker biography.',row['description'])
        self.assertNotIn('Other event',row['description'])
        self.assertEqual(row['venue_address'],'551 Tremont St., Boston, MA 02116')
        self.assertEqual(row['ends_at'],'2026-11-18T20:00:00-05:00')
        row=b._bca_detail(item,bca_detail(schedule='11/18/2026<br>6pm'),NOW)[0]
        self.assertIsNone(row['ends_at'])

    def test_bca_date_ranges_require_an_explicit_native_occurrence(self):
        item=dict(url='https://bostonarts.org/event/program/',title='Public program')
        with self.assertRaisesRegex(ValueError,'schedule_unresolved'):
            b._bca_detail(item,bca_detail(schedule='11/18/2026 - 11/20/2026'),NOW)
        row=b._bca_detail(item,bca_detail(body='Tuesday November 17 | 6pm. Join our community conversation.',schedule='09/17/2026 - 11/17/2026<br>6pm'),NOW)[0]
        self.assertEqual(row['starts_at'],'2026-11-17T18:00:00-05:00')

    def test_sowa_uses_only_explicit_2026_hours_and_holiday_exceptions(self):
        rows=b.collect(source(b.SOWA),Mock(return_value=sowa_page()),now=NOW)
        self.assertEqual(len(rows),31)
        byday={r['starts_at'][:10]:r for r in rows}
        self.assertNotIn('2026-11-23',byday)
        self.assertNotIn('2026-11-26',byday)
        self.assertNotIn('2026-12-25',byday)
        self.assertEqual(byday['2026-11-27']['starts_at'],'2026-11-27T10:00:00-05:00')
        self.assertEqual(byday['2026-11-27']['ends_at'],'2026-11-27T19:00:00-05:00')
        self.assertEqual(byday['2026-12-24']['ends_at'],'2026-12-24T16:00:00-05:00')
        self.assertEqual(byday['2026-12-04']['ends_at'],'2026-12-04T22:00:00-05:00')
        self.assertGreater(len(rows[0]['description']),2000)
        self.assertIn('Final admission instruction.',rows[0]['description'])
        self.assertIn('The full visitor FAQ is preserved.',rows[0]['description'])
        self.assertNotIn('8th annual',rows[0]['description'])
        self.assertEqual(rows[0]['venue_address'],'550 Harrison Avenue, Boston, MA 02118')
        self.assertEqual(b._sowa_season(sowa_page(),datetime(2027,11,14,tzinfo=timezone.utc)),[])
        for changed in (sowa_page().replace('December 27, 2026','December 27, 2027'),sowa_page().replace('Christmas Eve (Dec 24): 10 AM – 4 PM','Christmas Eve (Dec 24): 10 AM – 6 PM')):
            with self.assertRaisesRegex(ValueError,'season_changed'):b._sowa_season(changed,NOW)

    def test_checkpoint_url_tampering_cannot_gain_extra_fetch_scope(self):
        state=b.collect_chunk(source(b.MFA),Mock(return_value=mfa_listing()),now=NOW)['checkpoint']
        state=deepcopy(state);state['queue'][0]['url']='https://attacker.example/event/private?event=1';state['manifest_hash']=b._hash(state['queue'])
        with self.assertRaisesRegex(ValueError,'checkpoint_invalid'):
            b.collect_chunk(source(b.MFA),Mock(),checkpoint=state,now=NOW)
        self.assertFalse(b.event_url(b.MFA,'https://www.mfa.org/event/workshop?event=1&url=http://127.0.0.1'))


if __name__=='__main__':unittest.main()
