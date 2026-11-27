import json
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from time import monotonic
import unittest
from unittest.mock import patch

from roomquest import boston_arts_additional as a
from roomquest.event_description import description
from icalendar import Calendar, Event

NOW = datetime(2026, 11, 15, 2, tzinfo=timezone.utc)


def source(key):
    return dict(source_key=key, feed_url=a.SOURCES[key][0], kind='html', platform_adapter='html', timezone=a.ZONE)


def hmsc_listing():
    return '<h1>Upcoming Programs</h1><main><a href="/calendar_event/fossil-day/">Fossil Day</a></main>'


def hmsc_detail(body='<p>Meet museum paleontologists and explore their complete research stories.</p>', location='Harvard Museum of Natural History,26 Oxford Street,Cambridge,MA02138'):
    return '<h1>Fossil Day</h1><a href="https://calendar.google.com/calendar/r/eventedit?dates=20261121T180000Z/20261121T210000Z">Google Calendar</a><article class="calendar_event"><div class="entry-content"><p>Location: ' + location + '</p>' + body + '</div></article>'


def mos_detail(line, body, title='Science of Wellness with Cody Rigsby'):
    return '<h1>' + title + '</h1><section class="event-show-header">Public Event<p class="date-time">' + line + '</p></section><section class="event-details"><div class="desktop-only">' + body + '</div><div class="mobile-only">' + body + '</div></section><div class="speaker-listing">Complete speaker biography.</div>'


def pem_detail(body, *, availability='https://schema.org/InStock', point_address='161 Essex Street, Salem, MA 01970'):
    url='https://www.pem.org/events/polar-origami'
    events=[dict({'@type':'Event'},name='Polar Origami',startDate='2026-12-04T15:00:00-05:00',endDate='2026-12-04T16:30:00-05:00',eventStatus='https://schema.org/EventScheduled',offers=dict(url=url,availability=availability),location=dict(address=dict(streetAddress=point_address)),description='Only an excerpt.')]
    return '<main><section class="introBlock">'+body+'</section><section class="keepExploring">Unrelated recommendations.</section><section class="newsletter">Subscribe.</section>'+''.join('<script type="application/ld+json">'+json.dumps(e)+'</script>' for e in events)+'</main>'


def eliot_card(url='/classes/bookbinding', title='Bookbinding', status='4 spots left', start='2026-11-22T13:00:00-05:00', end='2026-11-22T19:00:00-05:00'):
    return '<div class="calendar"><div class="contents"><a href="'+url+'">'+title+'</a><span class="date-display-start" content="'+start+'"></span><span class="date-display-end" content="'+end+'"></span>'+status+'</div></div>'


class Contracts(unittest.TestCase):
    def test_exact_source_and_event_url_bindings(self):
        for key in a.SOURCES:
            self.assertEqual(a._source(source(key)),key)
            bad=source(key);bad['timezone']='UTC'
            with self.assertRaisesRegex(ValueError,'source_unregistered'):a._source(bad)
        url='https://www.pem.org/events/polar-origami'
        self.assertTrue(a.event_url(a.PEM,url))
        for bad in [url+'?next=https://evil.example',url+'#fragment',url.replace('www.pem.org','www.pem.org.evil.example'),url.replace('/events/','/events/../')]:
            self.assertFalse(a.event_url(a.PEM,bad))

    def test_checkpoint_complete_only_preserves_entire_body(self):
        narrative='<p>'+('The full native narrative contains essential detail. '*100)+'</p><p>Final paragraph must survive.</p>'
        payload=hmsc_detail(narrative)
        fetch=lambda url,accept: hmsc_listing() if url==a.SOURCES[a.HMSC][0] else payload
        first=a.collect_chunk(source(a.HMSC),fetch,now=NOW)
        self.assertFalse(first['complete']);self.assertEqual(first['events'],[])
        second=a.collect_chunk(source(a.HMSC),fetch,checkpoint=first['checkpoint'],now=NOW)
        self.assertTrue(second['complete']);self.assertEqual(len(second['events']),1)
        row=second['events'][0]
        self.assertGreater(len(row['description']),2000)
        self.assertIn('Final paragraph must survive.',row['description'])
        self.assertEqual(row['description'],description('<p>Location: Harvard Museum of Natural History,26 Oxford Street,Cambridge,MA02138</p>'+narrative,limit=12001))
        self.assertEqual(second['checkpoint']['started_at'],first['checkpoint']['started_at'])
        a._checkpoint(second['checkpoint'],a.HMSC,NOW)

    def test_original_facts_ignore_source_label_and_change_with_event_details(self):
        def run(src, body):
            detail = hmsc_detail(body).replace('20261121T180000Z/20261121T210000Z',
                                                '20261221T180000Z/20261221T210000Z')
            fetch = lambda url, accept: hmsc_listing() if url == a.SOURCES[a.HMSC][0] else detail
            now = datetime(2026, 11, 27, 2, tzinfo=timezone.utc)
            listed = a.collect_chunk(src, fetch, now=now)
            return a.collect_chunk(src, fetch, checkpoint=listed['checkpoint'], now=now)
        first = run(source(a.HMSC), '<p>The publisher owns these event details.</p>')
        renamed = run({**source(a.HMSC), 'publisher_name': 'Changed provider label'},
                      '<p>The publisher owns these event details.</p>')
        changed = run(source(a.HMSC), '<p>The publisher changed the event details.</p>')
        envelope = first['events'][0]['collector_event_content_v1']
        self.assertEqual(renamed['events'][0]['collector_event_content_v1'], envelope)
        self.assertNotEqual(changed['events'][0]['collector_event_content_v1'], envelope)
        self.assertIn('Harvard Museum of Natural History',
                      envelope['facts']['native_options']['location_text'])
        bad=deepcopy(first['checkpoint'])
        bad['events'][0]['collector_event_content_v1']['facts']['description']='Tampered facts.'
        bad['outcomes'][0]=a._outcome(bad['queue'][0],bad['events'],None)
        bad['outcome_hash']=a._hash(bad['outcomes'])
        with self.assertRaisesRegex(ValueError,'checkpoint_invalid'):
            a._checkpoint(bad,a.HMSC,datetime(2026,11,27,2,tzinfo=timezone.utc))

    def test_checkpoint_rejects_foreign_manifest_point_address_and_clock(self):
        fetch=lambda url,accept:hmsc_listing() if url==a.SOURCES[a.HMSC][0] else hmsc_detail()
        one=a.collect_chunk(source(a.HMSC),fetch,now=NOW)
        done=a.collect_chunk(source(a.HMSC),fetch,checkpoint=one['checkpoint'],now=NOW)
        for field,value in [('event_url','https://hmsc.harvard.edu/calendar_event/foreign/'),('venue_address','27 Oxford Street,Cambridge,MA02138'),('lat',42.3),('location_provenance','inferred'),('starts_at','2028-01-01T00:00:00+00:00'),('starts_at','2026-11-21T19:00:00+00:00'),('id','foreign'),('description','Changed native narrative.'),('title','Wrong title')]:
            bad=deepcopy(done['checkpoint']);bad['events'][0][field]=value
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'checkpoint_invalid'):a._checkpoint(bad,a.HMSC,NOW)
            with self.subTest(field=field,phase='completed_resume'),self.assertRaisesRegex(ValueError,'checkpoint_invalid'):
                a.collect_chunk(source(a.HMSC),lambda *_:self.fail('invalid completed checkpoint must not fetch'),checkpoint=bad,now=NOW)
        bad=deepcopy(one['checkpoint']);bad['queue'][0]['title']='Changed'
        with self.assertRaisesRegex(ValueError,'checkpoint_invalid'):a._checkpoint(bad,a.HMSC,NOW)
    def test_checkpoint_keeps_one_protocol_and_does_not_invent_legacy_facts(self):
        listing = ('<h1>Upcoming Programs</h1><main>'
                   '<a href="/calendar_event/fossil-day/">Fossil Day</a>'
                   '<a href="/calendar_event/rock-day/">Rock Day</a></main>')
        details = {
            'https://hmsc.harvard.edu/calendar_event/fossil-day/':
                hmsc_detail().replace('20261121T180000Z/20261121T210000Z','20261221T180000Z/20261221T210000Z'),
            'https://hmsc.harvard.edu/calendar_event/rock-day/':
                hmsc_detail().replace('Fossil Day','Rock Day').replace(
                    '20261121T180000Z/20261121T210000Z','20261221T180000Z/20261221T210000Z'),
        }
        fetch=lambda url,accept: listing if url==a.SOURCES[a.HMSC][0] else details[url]
        now=datetime(2026,11,27,2,tzinfo=timezone.utc)
        listed=a.collect_chunk(source(a.HMSC),fetch,now=now)
        partial=a.collect_chunk(source(a.HMSC),fetch,checkpoint=listed['checkpoint'],now=now,max_details=1)
        self.assertIn('collector_event_content_v1',partial['checkpoint']['events'][0])
        legacy=deepcopy(partial['checkpoint'])
        legacy['events'][0].pop('collector_event_content_v1')
        legacy['outcomes'][0]=a._outcome(legacy['queue'][0],legacy['events'],None)
        legacy['outcome_hash']=a._hash(legacy['outcomes'])
        full=a.collect_chunk(source(a.HMSC),fetch,checkpoint=legacy,now=now,max_details=1)
        self.assertTrue(full['complete'])
        self.assertTrue(all('collector_event_content_v1' not in row for row in full['events']))

    def test_checkpoint_expiry_and_deadline_reserve(self):
        fetch=lambda url,accept:hmsc_listing()
        one=a.collect_chunk(source(a.HMSC),fetch,now=NOW)
        self.assertIsNone(a._checkpoint(one['checkpoint'],a.HMSC,NOW+timedelta(hours=4,seconds=1)))
        with patch.object(a,'monotonic',return_value=100):
            with self.assertRaisesRegex(ValueError,'collection_deadline'):
                a.collect_chunk(source(a.HMSC),lambda *_:self.fail('fetch must not start inside reserve'),now=NOW,deadline_at=111)

    def test_only_unprocessed_legacy_checkpoint_upgrades_without_restarting(self):
        fetch=lambda url,accept:hmsc_listing() if url==a.SOURCES[a.HMSC][0] else hmsc_detail()
        one=a.collect_chunk(source(a.HMSC),fetch,now=NOW)
        legacy=deepcopy(one['checkpoint']);legacy.pop('outcomes');legacy.pop('outcome_hash')
        restored=a._checkpoint(legacy,a.HMSC,NOW)
        self.assertEqual(restored['started_at'],legacy['started_at'])
        self.assertEqual(restored['queue'],legacy['queue'])
        self.assertEqual(restored['listed_pages'],legacy['listed_pages'])
        self.assertEqual(restored['outcomes'],[])
        done=a.collect_chunk(source(a.HMSC),fetch,checkpoint=restored,now=NOW)
        processed_legacy=deepcopy(done['checkpoint']);processed_legacy.pop('outcomes');processed_legacy.pop('outcome_hash')
        with self.assertRaisesRegex(ValueError,'checkpoint_invalid'):
            a.collect_chunk(source(a.HMSC),lambda *_:self.fail('processed legacy rows cannot be re-attested'),checkpoint=processed_legacy,now=NOW)

    def test_missing_and_oversize_description_are_explicit_holds(self):
        for body,reason in [('', 'description_missing'),('<p>'+'x'*12001+'</p>','description_limit')]:
            item=a._item(a.PEM,'https://www.pem.org/events/polar-origami','Polar Origami')
            with self.subTest(reason=reason),self.assertRaisesRegex(ValueError,reason):a._pem_detail(item,pem_detail(body),NOW)


class Museums(unittest.TestCase):
    def test_mos_native_pagination_requires_all_rows(self):
        card='<h3 class="listing-item__title"><a href="/events/program">Program</a></h3><div class="listing-item__date">Saturday, November 21, 2026 | 1:00pm</div>'
        url='https://www.mos.org/api/v1/event-listing/event_detail/96+101/all/all/all/all?items_per_page=18&sort_by=date_asc'
        data=dict(pager=dict(current_page=0,items_per_page=18,total_pages=2,total_results=20),results=[dict(event_listing=card.replace('/program','/program-'+str(i))) for i in range(18)])
        queue,next_pages=a._mos_listing(json.dumps(data),url,NOW)
        self.assertEqual(len(queue),18);self.assertEqual(next_pages,[url+'&page=1'])
        data['results'].pop()
        with self.assertRaisesRegex(ValueError,'pagination_changed'):a._mos_listing(json.dumps(data),url,NOW)

    def test_mos_rejects_cross_page_duplicate_or_changed_total_before_completion(self):
        url='https://www.mos.org/api/v1/event-listing/event_detail/96+101/all/all/all/all?items_per_page=18&sort_by=date_asc'
        card='<h3 class="listing-item__title"><a href="/events/program-{0}">Program {0}</a></h3><div class="listing-item__date">Saturday, November 21, 2026 | 1:00pm</div>'
        page=lambda number,ids,total=20:json.dumps(dict(pager=dict(current_page=number,items_per_page=18,total_pages=2,total_results=total),results=[dict(event_listing=card.format(i)) for i in ids]))
        for second in (page(1,[17,19]),page(1,[18],19)):
            def fetch(target,accept):
                if target==a.SOURCES[a.MOS][0]:return '<div id="event-listing" data-api-url="'+url+'"></div>'
                return second if target.endswith('&page=1') else page(0,range(18))
            with self.subTest(second=second),self.assertRaisesRegex(ValueError,'pagination_changed'):
                a.collect_chunk(source(a.MOS),fetch,now=NOW)

    def test_mos_raw_coverage_includes_filtered_past_native_ids(self):
        url='https://www.mos.org/api/v1/event-listing/event_detail/96+101/all/all/all/all?items_per_page=18&sort_by=date_asc'
        card='<h3 class="listing-item__title"><a href="/events/program-{0}">Program {0}</a></h3><div class="listing-item__date">{1} | 1:00pm</div>'
        data=json.dumps(dict(pager=dict(current_page=0,items_per_page=18,total_pages=1,total_results=2),results=[dict(event_listing=card.format(1,'Friday, November 13, 2026')),dict(event_listing=card.format(2,'Saturday, November 21, 2026'))]))
        fetch=lambda target,accept:'<div id="event-listing" data-api-url="'+url+'"></div>' if target==a.SOURCES[a.MOS][0] else data
        result=a.collect_chunk(source(a.MOS),fetch,now=NOW)
        self.assertEqual(result['checkpoint']['native_total'],2)
        self.assertEqual(len(result['checkpoint']['native_seen']),2)
        self.assertEqual(result['checkpoint']['manifest_count'],1)
        a._checkpoint(result['checkpoint'],a.MOS,NOW)

    def test_trustees_rejects_cross_page_duplicate_before_completion(self):
        def page(number,ids):
            data=dict(preload_data=dict(settings=dict(pager=dict(page=number,per_page=16,total_rows=18,total_pages=2))))
            cards=''.join('<div class="teaser-event"><a href="https://thetrustees.org/event/'+str(i)+'/"></a><h3 class="teaser-event__title">Program '+str(i)+'</h3><div class="teaser-event__location">deCordova Sculpture Park and Museum | Lincoln</div></div>' for i in ids)
            return '<script>window.FWP_JSON = '+json.dumps(data)+';</script><div class="facetwp-template"><div class="event-cards">'+cards+'</div></div>'
        fetch=lambda url,accept:page(2,[16,18]) if '_paged=2' in url else page(1,range(1,17))
        with self.assertRaisesRegex(ValueError,'pagination_changed'):
            a.collect_chunk(source(a.DECORDOVA),fetch,now=NOW)

    def test_mos_family_session_survives_sold_out_evening(self):
        url='https://www.mos.org/events/science-wellness-cody-rigsby'
        item=a._item(a.MOS,url,'Science of Wellness with Cody Rigsby')
        line='Sunday, November 22, 2026 | Family-friendly “Ask Cody” session – 12:00 pm; Science of Wellness fireside chat – 7:30 pm'
        body='<p>The Science of Wellness Fireside Chat is SOLD OUT!</p><p>Families can attend the noon session. Full program details retained.</p>'
        rows=a._mos_detail(item,mos_detail(line,body),NOW)
        self.assertEqual(len(rows),1)
        self.assertEqual(a.timestamp(rows[0]['starts_at']).hour,17)
        self.assertIn('Ask Cody',rows[0]['title'])
        self.assertIn('Full program details retained.',rows[0]['description'])
        self.assertEqual(rows[0]['description'].count('Families can attend'),1)

    def test_mos_date_range_expands_only_explicit_dates(self):
        rows=a._mos_schedule('February 25–26, 2027 | 8:00pm; February 27, 2027 | 2:00pm and 8:00pm')
        self.assertEqual([(v[0].day,v[0].hour) for v in rows],[(25,20),(26,20),(27,14),(27,20)])

    def test_hmsc_named_museum_and_online(self):
        item=a._item(a.HMSC,'https://hmsc.harvard.edu/calendar_event/fossil-day/','Fossil Day')
        rows=a._hmsc_detail(item,hmsc_detail(location='Harvard Museum of Natural History,ClassroomB,Cambridge,MA02138'),NOW)
        self.assertEqual(rows[0]['venue_address'],'26 Oxford Street, Cambridge, MA 02138')
        with self.assertRaisesRegex(ValueError,'not_public'):a._hmsc_detail(item,hmsc_detail('<p>Online Workshop</p>'),NOW)

    def test_pem_full_body_and_native_point(self):
        item=a._item(a.PEM,'https://www.pem.org/events/polar-origami','Polar Origami')
        full='<p>'+('Fold and discover the complete native program. '*70)+'</p><p>Final access details.</p>'
        rows=a._pem_detail(item,pem_detail(full),NOW)
        self.assertEqual(len(rows),1);row=rows[0]
        self.assertEqual(row['description'],description(full,limit=12001))
        self.assertEqual((row['lat'],row['lng']),(42.521442,-70.892372))
        self.assertNotIn('excerpt',row['description']);self.assertNotIn('recommendations',row['description'])
        self.assertEqual(a._pem_detail(item,pem_detail(full,availability='https://schema.org/SoldOut'),NOW),[])

    def test_pem_native_markdown_binds_ics_and_all_manifest_sessions(self):
        url='https://www.pem.org/events/foldable-scenes'
        sessions=[dict(start='2026-12-04T15:00:00-05:00',end='2026-12-04T16:30:00-05:00'),
                  dict(start='2026-12-11T15:00:00-05:00',end='2026-12-11T16:30:00-05:00')]
        item=a._item(a.PEM,url,'Foldable Scenes',sessions=sessions)
        cal=Calendar();ev=Event();ev.add('summary',item['title']);ev.add('location','161 Essex St, Salem, MA 01970')
        ev.add('dtstart',a.timestamp(sessions[0]['start']).astimezone(timezone.utc));ev.add('dtend',a.timestamp(sessions[0]['end']).astimezone(timezone.utc));cal.add_component(ev)
        payload='---\ntitle: "Foldable Scenes"\ncanonical_url: "'+url+'"\n---\n[Apple](data:text/calendar;charset=utf8;base64,'+base64.b64encode(cal.to_ical()).decode()+')\n## Know before you go\nCreate Space Studios\n\nComplete native program and final access details.\n\nStay up to date.\nNewsletter'
        rows=a._pem_detail(item,payload,NOW)
        self.assertEqual(len(rows),2);self.assertIn('final access details.',rows[0]['description']);self.assertNotIn('Newsletter',rows[0]['description'])
        with self.assertRaisesRegex(ValueError,'identity_changed'):
            a._pem_detail(item,payload.replace('canonical_url: "'+url,'canonical_url: "https://www.pem.org/events/other'),NOW)

    def test_pem_concurrent_native_envelope_handling_retains_individual_sessions(self):
        values=[dict(start='2027-01-02T11:00:00-05:00',end='2027-01-02T11:30:00-05:00'),
                dict(start='2027-01-02T11:30:00-05:00',end='2027-01-02T12:00:00-05:00'),
                dict(start='2027-01-02T11:00:00-05:00',end='2027-01-02T12:00:00-05:00')]
        occurrences=a._pem_occurrences(values)
        self.assertEqual(len(occurrences),2)
        self.assertTrue(all(end-start==timedelta(minutes=30)for start,end in occurrences))
        standalone=[dict(start='2026-12-04T09:00:00-05:00',end='2026-12-06T17:00:00-05:00')]
        self.assertEqual(len(a._pem_occurrences(standalone)),1)

    def test_trustees_native_total_and_separate_yoga_sessions(self):
        card='<div class="teaser-event"><a href="https://thetrustees.org/event/123/"></a><h3 class="teaser-event__title">Art of Presence: Yoga at deCordova</h3><div class="teaser-event__location">deCordova Sculpture Park and Museum | Lincoln</div></div>'
        data=dict(preload_data=dict(settings=dict(pager=dict(page=1,per_page=16,total_rows=1,total_pages=1))))
        listing='<script>window.FWP_JSON = '+json.dumps(data)+';</script><div class="facetwp-template"><div class="event-cards">'+card+'</div></div>'
        items,following=a._trust_listing(listing,a.SOURCES[a.DECORDOVA][0])
        self.assertEqual(len(items),1);self.assertEqual(following,[])
        with self.assertRaisesRegex(ValueError,'pagination_changed'):
            a._trust_listing(listing.replace(card,''),a.SOURCES[a.DECORDOVA][0])
        html='<link rel="canonical" href="https://thetrustees.org/event/123/"><meta property="og:title" content="Art of Presence: Yoga at deCordova"><div class="event-text__when"><p>Monday, November 23, 2026</p><p>10:30-11AM (Family Yoga) and 11:30AM-12:30PM (Adult Yoga)</p></div><div class="event-text__column-right wysiwyg"><p>Complete native program details.</p></div><div class="event-text__location">51 Sandy Pond Road Lincoln, MA 01773</div>'
        rows=a._trust_detail(items[0],html,NOW)
        self.assertEqual(len(rows),2);self.assertIn('Family Yoga',rows[0]['title']);self.assertIn('Adult Yoga',rows[1]['title'])
        self.assertNotEqual(rows[0]['id'],rows[1]['id'])


class SchoolsAndCinema(unittest.TestCase):
    def test_eliot_follows_native_overflow_and_month(self):
        html='<div class="calendar-calendar">'+eliot_card()+'<a href="/calendar/day/2026-11-22">See all7events</a><a href="/calendar/month/2026-12">December »</a></div>'
        rows,pages=a._eliot_listing(html,a.SOURCES[a.ELIOT][0],NOW)
        self.assertEqual(len(rows),1)
        self.assertEqual(a.timestamp(rows[0]['sessions'][0]['start']),a.timestamp('2026-11-22T18:00:00+00:00'))
        self.assertEqual(len(pages),2)
        both=a._merge(rows+rows)
        self.assertEqual(len(both[0]['sessions']),1)

    def test_eliot_excludes_closed_and_private_reservations(self):
        html='<div class="calendar-calendar">'+eliot_card(status='Closed')+eliot_card(title='Private Studio Sessions')+'</div>'
        rows,_=a._eliot_listing(html,a.SOURCES[a.ELIOT][0],NOW)
        self.assertEqual(rows,[])
        rows,_=a._eliot_listing('<div class="calendar-calendar">'+eliot_card(title='Full Color Painting')+'</div>',a.SOURCES[a.ELIOT][0],NOW)
        self.assertEqual(len(rows),1)

    def test_bac_conflicting_weekday_never_publishes(self):
        html='<footer>86 Monmouth Street,Brookline,MA02446</footer><figcaption class="caption"><span class="class-listing">Watercolor Ages:16+ Date:Tue, Dec 10, 2026 Time:6:30–9:30pm Workshop Fee:$95 Full native workshop description. <a href="https://campscui.active.com/orgs/BrooklineArtsCenter?session=123">Register</a></span></figcaption>'
        # Native footer is formatted with spaces; the contradiction is the weekday.
        html=html.replace('86 Monmouth Street,Brookline,MA02446','86 Monmouth Street, Brookline, MA 02446')
        self.assertEqual(a._bac(html,NOW),[])

    def test_coolidge_each_native_showtime_is_an_occurrence(self):
        item=a._item(a.COOLIDGE,'https://coolidge.org/films/example','Example')
        html='<h1>Example</h1><div class="field--name-body"><div class="field__label">Body</div><div class="field__item"><p>Full native film narrative.</p></div></div>'
        html+='<div class="film-showtime-list"><span class="datepicker__day">Sun</span><span class="datepicker__date">11/22</span>'
        for i,t in [('100','10:30am'),('101','1:00pm')]:
            html+='<div class="availability--individual sales-state--DuringSales"><a class="showtime-ticket__button" href="https://store.coolidge.org/websales/pages/ticketsearchcriteria.aspx?evtinfo='+i+'~native"><span class="showtime-ticket__time">'+t+'</span><span class="showtime-ticket__venue">MH2</span></a></div>'
        html+='</div>'
        rows=a._coolidge_detail(item,html,NOW)
        self.assertEqual(len(rows),2);self.assertNotEqual(rows[0]['id'],rows[1]['id'])
        self.assertEqual(rows[0]['description'],'Full native film narrative.')
        self.assertTrue(all(r['venue_address']=='290 Harvard Street, Brookline, MA 02446' for r in rows))
        with self.assertRaisesRegex(ValueError,'identity_changed'):
            a._coolidge_detail(item,html.replace('ticketsearchcriteria.aspx','unrelated.aspx'),NOW)

    def test_coolidge_native_group_sessions_are_distinct_and_closed_sales_excluded(self):
        item=a._item(a.COOLIDGE,'https://coolidge.org/events/class','Class')
        html='<h1>Class</h1><div class="field--name-body"><div class="field__label">Body</div><div class="field__item"><p>Complete native class description.</p></div></div>'
        for day,status in [('11/22','DuringSales'),('11/29','DuringSales'),('12/06','AfterEvent')]:
            html+='<div class="film-showtime-list"><span class="datepicker__day">Sun</span><span class="datepicker__date">'+day+'</span><div class="availability--all sales-state--'+status+'"><a class="showtime-ticket__button" href="https://store.coolidge.org/websales/pages/entrypoint.aspx?guid=fe57c7b0-0962-42cd-9479-cbf03c4082cb"><span class="showtime-ticket__time">10:00am</span><span class="showtime-ticket__venue">ECEC</span></a></div></div>'
        rows=a._coolidge_detail(item,html,NOW)
        self.assertEqual(len(rows),2);self.assertNotEqual(rows[0]['id'],rows[1]['id'])
        self.assertEqual(rows[0]['description'],rows[1]['description'])

    def test_coolidge_pager_is_native_bounded_and_followed(self):
        html='<div class="film-card"><h3 class="film-card__title"><a href="/films/example">Example</a></h3></div><div class="pager__item--next"><a href="/films-events/welcome-coolidge-corner-theatre?view_args=202612">Next</a></div>'
        items,pages=a._coolidge_listing(html,a.SOURCES[a.COOLIDGE][0],NOW)
        self.assertEqual(len(items),1);self.assertEqual(len(pages),2)
        with self.assertRaisesRegex(ValueError,'pagination_changed'):
            a._coolidge_listing(html.replace('/films-events/welcome','https://foreign.example/films-events/welcome'),a.SOURCES[a.COOLIDGE][0],NOW)

    def test_eliot_native_offsite_street_is_not_assigned_to_schoolhouse(self):
        item=a._item(a.ELIOT,'https://eliotschool.org/classes/sharpening','Sharpening',sessions=[dict(start='2026-11-22T13:00:00-05:00',end='2026-11-22T16:00:00-05:00')])
        html='<h1>Sharpening</h1><div class="view-classes-courses-tabs-view view-display-id-block_1"><p>Complete native sharpening description.</p></div><div class="field-name-field-location"><div class="field-item">Boston Building Resources, 100 Terrace St, Boston, MA 02120</div></div>'
        rows=a._eliot_detail(item,html,NOW)
        self.assertEqual(rows[0]['venue_address'],'100 Terrace Street, Boston, MA 02120')
        with self.assertRaisesRegex(ValueError,'street_unresolved'):
            a._eliot_detail(item,html.replace('100 Terrace St','101 Terrace St'),NOW)


class Aquarium(unittest.TestCase):
    def test_future_eligible_feed_preserves_full_description(self):
        native=dict(id=12,title='Ocean Science Night',status='publish',all_day=False,url='https://www.neaq.org/event/ocean-science-night/',timezone=a.ZONE,start_date='2026-11-20 18:00:00',end_date='2026-11-20 21:00:00',utc_start_date='2026-11-20 23:00:00',utc_end_date='2026-11-21 02:00:00',description='<p>'+('Complete native marine-science program. '*75)+'</p><p>Final details.</p>',venue=dict(address='1 Central Wharf',city='Boston',state='MA',zip='02110'),categories=[])
        data=dict(events=[native],total_pages=1,total=1)
        html='<h1>Events and Programs</h1><article class="tribe-events-pro-photo__event"><time datetime="2026-11-20"></time><h3 class="tribe-events-pro-photo__event-title">Ocean Science Night</h3><a>Tickets</a></article>'
        fetch=lambda url,accept:html if '/wp-json/' not in url else json.dumps(data)
        rows=a.collect(source(a.AQUARIUM),fetch,now=NOW)
        self.assertEqual(len(rows),1);self.assertIn('Final details.',rows[0]['description']);self.assertGreater(len(rows[0]['description']),2000)
        native['categories']=[dict(name='Members')]
        self.assertEqual(a.collect(source(a.AQUARIUM),fetch,now=NOW),[])
        native['categories']=[]
        for field in ['is_virtual','hide_from_listings']:
            native[field]=True
            self.assertEqual(a.collect(source(a.AQUARIUM),fetch,now=NOW),[])
            native.pop(field)

    def test_sold_out_calendar_excludes_native_feed_record(self):
        native=dict(id=12,title='Aquarium After Dark',status='publish',all_day=False,categories=[],start_date='2026-11-20 18:00:00')
        data=dict(events=[native],total_pages=1,total=1)
        html='<h1>Events and Programs</h1><article class="tribe-events-pro-photo__event"><time datetime="2026-11-20"></time><h3 class="tribe-events-pro-photo__event-title">Aquarium After Dark</h3><a>SOLD OUT</a></article>'
        fetch=lambda url,accept:html if '/wp-json/' not in url else json.dumps(data)
        self.assertEqual(a.collect(source(a.AQUARIUM),fetch,now=NOW),[])
        native['start_date']='2026-12-20 18:00:00'
        with self.assertRaisesRegex(ValueError,'pagination_changed'):
            a.collect(source(a.AQUARIUM),fetch,now=NOW)


if __name__=='__main__':unittest.main()
