"""Synthetic contract/regression fixtures; no copied publisher narratives."""
import json
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode
import unittest
from unittest.mock import patch

from roomquest import raleigh_direct_arts as a
from roomquest.event_description import description

NOW = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)


def source(key):
    return dict(source_key=key, feed_url=a.SOURCES[key][0], kind='html', platform_adapter='html', timezone=a.ZONE)


def natural(identity=1, body='<p>Complete science program description.</p>'):
    return dict(id=identity, url=f'https://www.naturalsciences.org/calendar/event/program-{identity}/',
        title=f'Program {identity}', description=body, status='publish', all_day=False, hide_from_listings=False,
        timezone=a.ZONE, start_date='2026-11-21 13:30:00', end_date='2026-11-21 14:30:00',
        utc_start_date='2026-11-21 18:30:00', utc_end_date='2026-11-21 19:30:00', image=False,
        venue=dict(venue='Nature Research Center', address='121 West Jones Street', city='Raleigh', state='NC',
                   zip='27601', geo_lat=35.7822405, geo_lng=-78.6409677))


def natural_packet(value):
    return a._natural_listing(json.dumps(dict(events=[value], total=1, total_pages=1)), NOW, 1)[0][0]


def cary_item(identity='w_test', start='2026-11-21T13:30:00', end='2026-11-21T14:30:00'):
    return dict(id=identity, title='Program', start=start, end=end, allDay=False,
                url='https://downtowncarypark.com/things-to-do/calendar/' + identity)


def cary_detail(*, venue='DCP Academy Pavilion', body='<p>Full program narrative.</p>', clock='1:30 pm - 2:30 pm', recreation=False, title='Program'):
    address=dict(streetAddress='327 S. Academy St.', addressLocality='Cary', addressRegion='NC', postalCode='27511')
    ld='<script type="application/ld+json">'+json.dumps({'@type': 'Organization', 'address': address})+'</script>'
    intro='<div class="masthead_intro">'+body+'</div>' if recreation else ''
    return ld+'<main><div class="gutenberg"><div class="nmc-block--masthead"><div class="masthead_content"><h1 class="masthead_title">'+title+'</h1>'+intro+'<div class="event-info"><div class="event-meta"><span class="dates">Nov 21, 2026</span></div><div class="event-meta"><span class="dates">'+clock+'</span></div><div class="event-meta location-meta"><span class="venue">'+venue+'</span></div><ul><li>Native registration instruction.</li></ul></div></div></div><div class="follow-meta">Social navigation</div>'+('' if recreation else body)+'</div></main>'


def rlt_item(first='2026-11-18', last='2026-12-04'):
    return dict(id='shows/test', url='https://raleighlittletheatre.org/shows/test/', title='Test', first=first, last=last)


def rlt_detail(schedule, *, dates='November 18 - December 4, 2026', extra='', body='<p>Full dramatic narrative.</p>'):
    return '<div class="show-header"><h2>Test</h2><p class="meta">'+dates+'</p><p class="meta">Gaddy-Goodwin Teaching Theatre (General Admission)</p></div><div class="show-content"><div class="seven column dynamic-content">'+body+'</div><div class="four column"><p>Runtime approximately 30 minutes.</p><p>Show Times:</p><ul>'+''.join('<li>'+v+'</li>' for v in schedule)+'</ul>'+extra+'</div></div><div class="grid wrapper pad-xl"><p>Full cast and accessibility details.</p></div><footer>301 Pogue Street, Raleigh NC 27607</footer>'


def art_card(identity='1', day='2026-12-04', end=None, clock='5:00 pm', title='Program', body='<p>Full art program description.</p>'):
    event={'@type':'Event','startDate':day,'endDate':end or day,'eventStatus':'https://schema.org/EventScheduled', 'description':body}
    return '<div><script type="application/ld+json">'+json.dumps(event)+'</script><article class="mec-event-article"><div data-event-id="'+identity+'"></div><h4 class="mec-event-title">'+title+'</h4><div class="mec-event-time">'+clock+'</div></article></div>'


class ArtsContracts(unittest.TestCase):
    def setUp(self):
        self.patch = patch('roomquest.preview_worker._future_datetime', side_effect=lambda value, **kw: value.astimezone(timezone.utc) if value else None)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_exact_registered_tuple_and_safe_urls(self):
        for key in a.SOURCES:
            self.assertEqual(a._source(source(key)), key)
            bad=source(key); bad['timezone']='UTC'
            with self.assertRaisesRegex(ValueError, 'source_unregistered'): a._source(bad)
        url=rlt_item()['url']
        for bad in (url+'?next=evil',url+'#secret',url.replace('/shows/','/shows/../'),url.replace('.org/', '.org.evil/')):
            self.assertFalse(a.event_url(a.RLT,bad))
        self.assertTrue(a.event_url(a.NATURAL,'https://www.naturalsciences.org/calendar/event/program/2026-12-12/2/'))

    def test_artspace_form_is_exact_bounded_and_independently_validated(self):
        form=a.artspace_calendar_form(2027,1,deepcopy(a.ARTSPACE_ATTS),'2026-11-15')
        self.assertLess(len(urlencode(form).encode()),8192)
        self.assertTrue(a.valid_artspace_calendar_form(form,now=NOW))
        for key,value in [('action','delete_event'),('mec_month','4'),('atts[id]','999'),('atts[category]','private'),('url','https://evil.example')]:
            changed=dict(form);changed[key]=value
            self.assertFalse(a.valid_artspace_calendar_form(changed,now=NOW))
        for y,m in [(2026,10),(2027,2),(2028,1)]:
            with self.assertRaisesRegex(ValueError,'form_invalid'):a.artspace_calendar_form(y,m,a.ARTSPACE_ATTS,'2026-11-15')
        changed=deepcopy(a.ARTSPACE_ATTS);changed['atts[show_past_events]']='1'
        with self.assertRaisesRegex(ValueError,'form_invalid'):a.artspace_calendar_form(2026,12,changed,'2026-11-15')

    def test_month_window_uses_all_sixty_local_dates_and_year_boundary(self):
        self.assertEqual(a._window(NOW),(date(2026,11,15),date(2027,1,13)))
        self.assertEqual(a._months(NOW),[(2026,11),(2026,12),(2027,1)])
        january=a._cary_listing(json.dumps([cary_item(start='2027-01-14T00:30:00+0000',end='2027-01-14T01:30:00+0000')]),NOW)
        self.assertEqual(len(january),1)  # Jan13 in Raleigh.
        january=a._cary_listing(json.dumps([cary_item(start='2027-01-14T10:30:00+0000',end='2027-01-14T11:30:00+0000')]),NOW)
        self.assertEqual(january,[])

    def test_natural_complete_pagination_and_changed_total(self):
        first=json.dumps(dict(events=[natural(i) for i in range(1,51)],total=51,total_pages=2))
        second=json.dumps(dict(events=[natural(51)],total=51,total_pages=2))
        fetch=lambda url,accept:second if url.endswith('page=2') else first
        start=a.collect_chunk(source(a.NATURAL),fetch,now=NOW,max_fetches=1)
        self.assertFalse(start['complete']); self.assertEqual(start['events'],[])
        self.assertEqual(start['checkpoint']['cursor'],0)
        done=a.collect_chunk(source(a.NATURAL),fetch,now=NOW,checkpoint=json.loads(json.dumps(start['checkpoint'])),max_fetches=1)
        self.assertTrue(done['complete']);self.assertEqual(len(done['events']),51)
        restored=a.collect_chunk(source(a.NATURAL),lambda *_:self.fail('completed snapshot must not fetch'),now=NOW,checkpoint=done['checkpoint'])
        self.assertEqual(restored['events'],done['events'])
        changed=json.dumps(dict(events=[],total=50,total_pages=1))
        with self.assertRaisesRegex(ValueError,'pagination_changed'):
            a.collect_chunk(source(a.NATURAL),lambda *_:changed,now=NOW,checkpoint=start['checkpoint'])

    def test_full_descriptions_and_native_clock_and_street(self):
        body='<p>'+('Detailed material requirements and safety instructions. '*60)+'</p><p>Final native paragraph.</p>'
        value=natural(body=body); item=natural_packet(value)
        row=a._natural_detail(item,NOW)[0]
        self.assertEqual(row['description'],description(body,limit=12001))
        self.assertGreater(len(row['description']),2000)
        self.assertEqual(row['starts_at'],'2026-11-21T18:30:00+00:00')
        self.assertEqual(row['venue_address'],'121 West Jones Street, Raleigh, NC 27601')
        self.assertEqual(row['location_provenance'],a.NATIVE_PROVENANCE)
        for field,new in [('timezone','UTC'),('utc_start_date','2026-11-21 13:30:00'),('all_day',True)]:
            changed=deepcopy(item);changed['native'][field]=new
            with self.assertRaisesRegex(ValueError,'schedule_unresolved'):a._natural_detail(changed,NOW)
        missing=deepcopy(item);missing['native']['venue'].pop('address')
        with self.assertRaisesRegex(ValueError,'street_unresolved'):a._natural_detail(missing,NOW)
        far=deepcopy(item);far['native']['venue']['city']='Whiteville'
        with self.assertRaisesRegex(ValueError,'outside_area'):a._natural_detail(far,NOW)

    def test_description_limit_fails_instead_of_truncating(self):
        with self.assertRaisesRegex(ValueError,'description_limit'):a._body('<p>'+'x'*12001+'</p>')
        self.assertEqual(len(a._body('x'*12000)),12000)

    def test_cary_requires_both_native_feeds_and_every_detail_before_returning(self):
        feed0=json.dumps([cary_item('w_test')]);feed1=json.dumps([cary_item('r_test')])
        def fetch(url,accept):
            if url==a.SOURCES[a.CARY][0]:return ' '.join(a.CARY_APIS)
            if url.startswith(a.CARY_APIS[0]+'?'):return feed0
            if url.startswith(a.CARY_APIS[1]+'?'):return feed1
            return cary_detail()
        state=None
        for n in range(5):
            result=a.collect_chunk(source(a.CARY),fetch,now=NOW,checkpoint=state,max_fetches=1)
            state=json.loads(json.dumps(result['checkpoint']))
            if n<4:self.assertFalse(result['complete']);self.assertEqual(result['events'],[])
        self.assertTrue(result['complete']);self.assertEqual(len(result['events']),2)
        for field,value in [('description','Foreign prose'),('starts_at','2026-11-21T14:30:00+00:00'),('venue_address','Different Street'),('lat',35.8)]:
            bad=deepcopy(state);bad['events'][0][field]=value
            with self.assertRaisesRegex(ValueError,'checkpoint_invalid'):a._checkpoint(bad,a.CARY,NOW)
        self.assertIsNone(a._checkpoint(state,a.CARY,NOW+timedelta(hours=4,seconds=1)))

    def test_cary_keeps_both_native_narrative_layouts_and_holds_conflicting_clock(self):
        item=a._cary_listing(json.dumps([cary_item()]),NOW)[0]
        body='<p>All workshop details.</p><p>Final native paragraph.</p>'
        for recreation in (True,False):
            row=a._cary_detail(item,cary_detail(body=body,recreation=recreation),NOW)[0]
            self.assertIn('Final native paragraph.',row['description'])
            self.assertIn('Native registration instruction.',row['description'])
            self.assertNotIn('Social navigation',row['description'])
        for kwargs,reason in [({'clock':'2:30 pm - 3:30 pm'},'schedule_unresolved'),({'venue':'East Park Street'},'street_unresolved')]:
            with self.assertRaisesRegex(ValueError,reason):a._cary_detail(item,cary_detail(**kwargs),NOW)

    def test_rlt_expands_explicit_weekdays_with_holiday_and_exception(self):
        schedule=['Wednesdays, Thursdays, and Fridays at 10:00am, 11:15am, & 12:30pm',
                  'Saturdays and Sundays* at 10:00am, 11:15am & 12:30pm',
                  'No shows November 25 & 26 (Thanksgiving)']
        payload=rlt_detail(schedule,extra='<p>*except on Saturday, November 21 when shows are at 3pm and 4:15pm</p>')
        rows=a._rlt_detail(rlt_item(),payload,NOW)
        self.assertEqual(len(rows),32)
        local=[a.timestamp(v['starts_at']).astimezone(a.ZoneInfo(a.ZONE)) for v in rows]
        self.assertFalse(any(v.day in (25,26) and v.month==11 for v in local))
        self.assertEqual([(v.hour,v.minute) for v in local if v.date()==date(2026,11,21)],[(15,0),(16,15)])
        self.assertTrue(all(v.get('ends_at') is None for v in rows))
        self.assertIn('Full cast and accessibility details.',rows[0]['description'])

    def test_cary_market_organizer_address_requires_exact_current_street(self):
        native=cary_item('w_cary-farmers-market-123');native['title']='Cary Farmers Market'
        item=a._cary_listing(json.dumps([native]),NOW)[0]
        body='<p>Join the market along East Park St., next to Downtown Cary Park. Full vendor details.</p>'
        payload=cary_detail(venue='East Park Street',body=body,title=native['title'])
        row=a._cary_detail(item,payload,NOW)[0]
        self.assertEqual(row['venue_address'],a.CARY_MARKET_ADDRESS)
        self.assertEqual(row['location_provenance'],a.ORGANIZER_PROVENANCE)
        self.assertEqual(row['location_evidence_url'],a.CARY_MARKET_EVIDENCE)
        self.assertIsNone(row.get('lat'))
        for changed in [body+'<p>Moved to Town Hall this week.</p>', '<p>At Town Hall instead of East Park Street.</p>', body+'<p>Relocated offsite.</p>']:
            with self.assertRaisesRegex(ValueError,'street_unresolved'):
                a._cary_detail(item,cary_detail(venue='East Park Street',body=changed,title=native['title']),NOW)

    def test_rlt_explicit_dates_do_not_turn_range_into_daily_series(self):
        item=rlt_item('2026-12-12','2026-12-19')
        rows=a._rlt_detail(item,rlt_detail(['Saturday, December 12, 4:00 – 5:00 PM','Saturday, December 19, 4:00 – 5:00 PM'],dates='December 12 - 19, 2026'),NOW)
        self.assertEqual(len(rows),2)
        self.assertEqual([v['starts_at'] for v in rows],['2026-12-12T21:00:00+00:00','2026-12-19T21:00:00+00:00'])
        with self.assertRaisesRegex(ValueError,'schedule_unresolved'):
            a._rlt_detail(item,rlt_detail(['Friday, December 12, 4:00 – 5:00 PM'],dates='December 12 - 19, 2026'),NOW)

    def test_artspace_date_only_jsonld_requires_tile_clock_and_holds_multiday(self):
        cards=art_card()+art_card(identity='2',day='2026-12-05',end='2026-12-12')+art_card(identity='3',clock='All Day')
        items=a._art_month('<div class="mec-event-tile-view">'+cards+'</div>',NOW,2026,12)
        self.assertIsNone(items[0]['held'])
        self.assertEqual(items[1]['held'],'raleigh_arts_schedule_unresolved')
        self.assertEqual(items[2]['held'],'raleigh_arts_schedule_unresolved')
        native=dict(id=1,status='publish',link='https://artspacenc.org/events/program/',title=dict(rendered='Program'),content=dict(rendered='<p>Full art program description.</p>'))
        rows,url=a._art_detail(items[0],json.dumps(native),NOW)
        self.assertEqual(rows[0]['starts_at'],'2026-12-04T22:00:00+00:00')
        self.assertEqual(rows[0]['venue_address'],a.VENUES[a.ARTSPACE][1])
        native['content']['rendered']='<p>A changed shortened excerpt.</p>'
        with self.assertRaisesRegex(ValueError,'calendar_changed'):a._art_detail(items[0],json.dumps(native),NOW)

    def test_artspace_overflow_never_becomes_false_complete(self):
        payload='<div class="mec-event-tile-view">'+''.join(art_card(identity=str(i+1)) for i in range(80))+'</div>'
        with self.assertRaisesRegex(ValueError,'pagination_changed'):a._art_month(payload,NOW,2026,12)

    def test_native_image_entity_decoding_is_safe(self):
        native='https://i0.wp.com/artspacenc.org/wp-content/uploads/a.jpg?fit=20%2C20&#038;ssl=1'
        self.assertEqual(a.photo_url(a.ARTSPACE,native),'https://i0.wp.com/artspacenc.org/wp-content/uploads/a.jpg?fit=20%2C20&ssl=1')
        self.assertIsNone(a.photo_url(a.ARTSPACE,'https://i0.wp.com/other.example/a.jpg'))

    def test_deadline_blocks_new_request(self):
        with patch.object(a,'monotonic',return_value=100):
            with self.assertRaisesRegex(ValueError,'collection_deadline'):
                a.collect_chunk(source(a.CARY),lambda *_:self.fail('late fetch'),now=NOW,deadline_at=111)


if __name__ == '__main__':
    unittest.main()
