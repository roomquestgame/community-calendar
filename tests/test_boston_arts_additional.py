from copy import deepcopy
from datetime import datetime, timezone
from html import escape
import base64
import json
import unittest
from unittest.mock import Mock, patch

from roomquest import boston_arts_additional as b
from tests.test_new_york_arts import fake_record

NOW = datetime(2026, 11, 15, 1, tzinfo=timezone.utc)


def source(key):
    return dict(source_key=key, feed_url=b.SOURCES[key][0], kind='html', platform_adapter='html', timezone=b.ZONE)


def coolidge_detail(ticket='evtinfo=123~token', path='ticketsearchcriteria.aspx', body='Full cinema discussion.', extra=''):
    return ('<h1>Film and discussion</h1><div class="field--name-body"><div class="field__label">Body</div>'
            '<div class="field__item">' + escape(body) + '</div></div>'
            '<div class="film-showtime-list"><span class="datepicker__day">Tue</span><span class="datepicker__date">11/17</span>'
            '<div class="sales-state--DuringSales"><a class="showtime-ticket__button" href="https://store.coolidge.org/websales/pages/'
            + path + '?' + ticket + '"><span class="showtime-ticket__time">10:00am</span><span class="showtime-ticket__venue">ECEC</span></a></div>'
            + extra + '</div>')


def museum_detail(body='Full public program narrative.', dates='Sunday, November 22, 2026 | 12:00 pm', title='Science conversation'):
    return ('<h1>' + escape(title) + '</h1><div class="event-show-header"><span class="date-time">' + escape(dates)
            + '</span></div><div class="event-details"><div class="desktop-only">' + escape(body)
            + '</div><div class="mobile-only">Duplicate mobile text.</div></div><div class="speaker-listing">Complete speaker biography.</div>')


def pem_event(start='2027-01-08T15:00:00-05:00', end='2027-01-08T16:30:00-05:00'):
    return {'@type': 'Event', 'name': 'Winter art', 'startDate': start, 'endDate': end,
            'eventStatus': 'https://schema.org/EventScheduled', 'location': {'address': {'streetAddress': '161 Essex Street, Salem, MA 01970'}},
            'offers': {'url': 'https://www.pem.org/events/winter-art', 'availability': 'https://schema.org/InStock'}}


def pem_detail(events, body='Complete museum instructions.'):
    return '<main><section class="introBlock">' + escape(body) + '</section><section class="keepExploring">Unrelated event excerpt.</section></main>' + ''.join('<script type="application/ld+json">' + json.dumps(e) + '</script>' for e in events)


def pem_listing(events):
    return '<script type="application/ld+json">' + json.dumps({'@type': 'CollectionPage', 'mainEntity': {'itemListElement': [dict(position=i+1, item=dict(e, url=e['offers']['url'])) for i,e in enumerate(events)]}}) + '</script>'


class BostonAdditionalArtsTests(unittest.TestCase):
    def setUp(self):
        stub = patch.object(b, 'record', side_effect=fake_record)
        stub.start(); self.addCleanup(stub.stop)

    def test_registration_is_exact_and_untrusted_urls_cannot_expand_scope(self):
        self.assertEqual(len(b.SOURCES), 8)
        for key in b.SOURCES:
            self.assertEqual(b._source(source(key)), key)
            wrong = source(key); wrong['feed_url'] += '?next=http://127.0.0.1'
            with self.assertRaisesRegex(ValueError, 'source_unregistered'): b._source(wrong)
        self.assertFalse(b.event_url(b.MOS, 'https://www.mos.org/events/%2e%2e/private'))
        self.assertFalse(b._listing_url(b.COOLIDGE, 'https://coolidge.org/films-events/welcome-coolidge-corner-theatre?view_args=202612&redirect=other'))

    def test_museum_complete_body_and_speaker_biography_survive(self):
        body = 'A native science narrative. ' * 100 + 'Final accessibility instructions.'
        item = b._item(b.MOS, 'https://www.mos.org/events/conversation', 'Science conversation')
        row = b._mos_detail(item, museum_detail(body), NOW)[0]
        self.assertIn(body, row['description'])
        self.assertIn('Complete speaker biography.', row['description'])
        self.assertNotIn('Duplicate mobile', row['description'])
        self.assertEqual(row['venue_address'], '1 Science Park, Boston, MA 02114')
        with self.assertRaisesRegex(ValueError, 'description_limit'):
            b._mos_detail(item, museum_detail('X' * 12001), NOW)

    def test_museum_multiple_native_dates_and_times_do_not_invent_end(self):
        slots = b._mos_schedule('February 25–26, 2027 | 8:00 pm; February 27, 2027 | 2:00 pm and 8:00 pm')
        self.assertEqual([s[0].isoformat() for s in slots], ['2027-02-25T20:00:00-05:00', '2027-02-26T20:00:00-05:00', '2027-02-27T14:00:00-05:00', '2027-02-27T20:00:00-05:00'])
        self.assertTrue(all(s[1] is None for s in slots))
        with self.assertRaisesRegex(ValueError, 'schedule_unresolved'):
            b._mos_schedule('Monday, November 22, 2026 | 12:00 pm')

    def test_museum_keeps_open_family_session_but_excludes_sold_out_evening(self):
        item = b._item(b.MOS, 'https://www.mos.org/events/science-wellness-cody-rigsby', 'Science of Wellness with Cody Rigsby')
        body = 'The Science of Wellness Fireside Chat is SOLD OUT! Family-friendly Ask Cody remains available. Complete program text.'
        slots = 'Sunday, November 22, 2026 | Family-friendly “Ask Cody” session – 12:00 pm; Science of Wellness fireside chat – 7:30 pm'
        rows = b._mos_detail(item, museum_detail(body, slots, item['title']), NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['starts_at'], '2026-11-22T12:00:00-05:00')
        self.assertIn('SOLD OUT', rows[0]['description'])
        self.assertIn('Family-friendly', rows[0]['title'])

    def test_cinema_bundle_guid_and_individual_tickets_preserve_native_sessions(self):
        item = b._item(b.COOLIDGE, 'https://coolidge.org/events/film-discussion', 'Film and discussion')
        row = b._coolidge_detail(item, coolidge_detail(body='A full cinema narrative. '*100 + 'Last instruction.'), NOW)[0]
        self.assertTrue(row['id'].endswith(':123'))
        self.assertIn('Last instruction.', row['description'])
        self.assertEqual(row['venue_address'], '290 Harvard Street, Brookline, MA 02446')
        guid = 'fe57c7b0-0962-42cd-9479-cbf03c4082cb'
        row = b._coolidge_detail(item, coolidge_detail('guid=' + guid, 'entrypoint.aspx'), NOW)[0]
        self.assertTrue(row['id'].endswith(guid + ':2026-11-17T10:00:00-05:00'))
        with self.assertRaisesRegex(ValueError, 'identity_changed'):
            b._coolidge_detail(item, coolidge_detail('guid=unvalidated', 'entrypoint.aspx'), NOW)

    def test_cinema_sold_out_ticket_does_not_block_other_native_times(self):
        item = b._item(b.COOLIDGE, 'https://coolidge.org/events/film-discussion', 'Film and discussion')
        extra = '<div class="sales-state--AfterSales"><a class="showtime-ticket__button" href="https://store.coolidge.org/websales/pages/ticketsearchcriteria.aspx?evtinfo=999"><span class="showtime-ticket__time">9:00am</span></a></div>'
        rows = b._coolidge_detail(item, coolidge_detail(extra=extra), NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['starts_at'], '2026-11-17T10:00:00-05:00')

    def test_eliot_preserves_exact_offsite_partner_location_and_full_materials(self):
        item = b._item(b.ELIOT, 'https://eliotschool.org/classes/sharpening', 'Sharpening',
                       sessions=[dict(start='2026-11-18T18:00:00-05:00',end='2026-11-18T20:00:00-05:00')])
        payload = ('<h1>Sharpening</h1><div class="field-name-field-location"><div class="field-item">'
                   'Boston Building Resources, 100 Terrace St, Boston, MA 02120</div></div>'
                   '<div class="view-classes-courses-tabs-view view-display-id-block_1">Full class instructions.</div>'
                   '<div class="view-classes-courses-tabs-view view-display-id-block_3">Final tools and materials.</div>')
        row = b._eliot_detail(item,payload,NOW)[0]
        self.assertEqual(row['venue_address'],'100 Terrace Street, Boston, MA 02120')
        self.assertEqual(row['venue_name'],'Boston Building Resources')
        self.assertIn('Final tools and materials.',row['description'])
        with self.assertRaisesRegex(ValueError,'street_unresolved'):
            b._eliot_detail(item,payload.replace('100 Terrace St','200 Terrace St'),NOW)

    def test_trustees_canonical_identity_and_separate_native_yoga_sessions(self):
        item = b._item(b.DECORDOVA, 'https://thetrustees.org/event/123/', 'Family and adult yoga')
        payload = ('<link rel="canonical" href="'+item['url']+'"><meta property="og:title" content="'+item['title']+'">'
                   '<div class="event-text__when">Wednesday, November 18, 2026<br>10:30-11AM (Family Yoga) and 11:30AM-12:30PM (Adult Yoga)</div>'
                   '<div class="event-text__column-right wysiwyg">Complete class instructions.</div>'
                   '<div class="event-text__location">51 Sandy Pond Road Lincoln, MA 01773</div>')
        rows = b._trust_detail(item,payload,NOW)
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['starts_at'],'2026-11-18T10:30:00-05:00')
        self.assertEqual(rows[1]['ends_at'],'2026-11-18T12:30:00-05:00')
        self.assertEqual(rows[1]['title'],'Family and adult yoga — Adult Yoga')
        item['title']='Family – adult yoga'
        changed=payload.replace('Family and adult yoga','Family - adult yoga')
        self.assertEqual(len(b._trust_detail(item,changed,NOW)),2)
        item['title']='Family and adult yoga'
        with self.assertRaisesRegex(ValueError,'identity_changed'):
            b._trust_detail(item,payload.replace(item['url'],item['url']+'other'),NOW)

    def test_aquarium_native_body_and_complete_rest_totals(self):
        body = 'Full Aquarium native event narrative. '*100+'Final visitor instruction.'
        event = dict(id=42,title='Public science talk',url='https://www.neaq.org/event/public-science-talk/',
                     description=body,categories=[],status='publish',all_day=False,
                     timezone=b.ZONE,start_date='2026-11-18 18:00:00',end_date='2026-11-18 19:00:00',
                     utc_start_date='2026-11-18 23:00:00',utc_end_date='2026-11-19 00:00:00',
                     venue=dict(address='1 Central Wharf',city='Boston',state='MA',zip='02110'))
        html='<h1>Events and Programs</h1><article class="tribe-events-pro-photo__event"><time datetime="2026-11-18"></time><h3 class="tribe-events-pro-photo__event-title">Public science talk</h3><a>Tickets</a></article>'
        data=dict(events=[event],total=1,total_pages=1)
        row=b.collect(source(b.AQUARIUM),Mock(side_effect=[html,json.dumps(data)]),now=NOW)[0]
        self.assertEqual(row['description'],body)
        self.assertEqual(row['venue_address'],'1 Central Wharf, Boston, MA 02110')
        data['total']=2
        with self.assertRaisesRegex(ValueError,'pagination_changed'):
            b.collect(source(b.AQUARIUM),Mock(side_effect=[html,json.dumps(data)]),now=NOW)
        data['total']=1
        for key,value in [('event_status','canceled'),('event_status','cancelled'),('event_status','postponed'),('hide_from_listings',True),('is_virtual',True),('virtual','1')]:
            event[key]=value
            self.assertEqual(b.collect(source(b.AQUARIUM),Mock(side_effect=[html,json.dumps(data)]),now=NOW),[])
            del event[key]
        event['start_date']='2026-12-18 18:00:00'
        with self.assertRaisesRegex(ValueError,'pagination_changed'):
            b.collect(source(b.AQUARIUM),Mock(side_effect=[html,json.dumps(data)]),now=NOW)
        event['start_date']='2026-11-18 18:00:00'
        self.assertEqual(b.collect(source(b.AQUARIUM),Mock(side_effect=[html.replace('Tickets','SOLD OUT'),json.dumps(data)]),now=NOW),[])
        event['categories']=[dict(name='Members')]
        self.assertEqual(b.collect(source(b.AQUARIUM),Mock(side_effect=[html,json.dumps(data)]),now=NOW),[])

    def test_pem_retains_ended_siblings_only_for_programs_with_current_occurrences(self):
        expired = pem_event('2026-11-14T10:30:00-05:00', '2026-11-14T12:00:00-05:00')
        current = pem_event()
        items, pages = b._pem_listing(pem_listing([expired, current]), NOW)
        self.assertEqual(len(items), 1); self.assertEqual(len(items[0]['sessions']), 2)
        self.assertEqual(b._pem_listing(pem_listing([expired]), NOW), ([], []))
        self.assertEqual(pages, [])

    def test_pem_narrow_native_sessions_replace_series_envelopes(self):
        a = pem_event(); broad = pem_event(end='2027-01-29T16:30:00-05:00')
        item = b._item(b.PEM, a['offers']['url'], a['name'], sessions=[dict(start=a['startDate'], end=a['endDate'])])
        rows = b._pem_detail(item, pem_detail([a,broad], 'Full art directions. '*100+'Final material list.'), NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['ends_at'], '2027-01-08T16:30:00-05:00')
        self.assertIn('Final material list.', rows[0]['description'])
        self.assertNotIn('Unrelated event', rows[0]['description'])
        self.assertEqual((rows[0]['lat'],rows[0]['lng']), (42.521442,-70.892372))
        a1 = dict(start='2027-01-02T11:00:00-05:00', end='2027-01-02T11:30:00-05:00')
        a2 = dict(start='2027-01-02T11:30:00-05:00', end='2027-01-02T12:00:00-05:00')
        envelope = dict(start=a1['start'], end='2027-01-02T15:00:00-05:00')
        self.assertEqual(len(b._pem_occurrences([a1,a2,envelope])),2)

    def test_pem_refresh_after_first_session_ends_cannot_publish_series_envelope(self):
        now=datetime(2027,1,10,15,tzinfo=timezone.utc)
        first=pem_event(); later=pem_event('2027-01-15T15:00:00-05:00','2027-01-15T16:30:00-05:00')
        envelope=pem_event(end='2027-01-29T16:30:00-05:00')
        item=b._pem_listing(pem_listing([first,later,envelope]),now)[0][0]
        self.assertEqual(len(item['sessions']),3)
        rows=b._pem_detail(item,pem_detail([first,later,envelope]),now)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['starts_at'],later['startDate'])
        future_only=b._pem_occurrences([dict(start=e['startDate'],end=e['endDate'])for e in [later,envelope]])
        self.assertEqual(future_only,[(b.timestamp(later['startDate']),b.timestamp(later['endDate']))])
        fetch=Mock(side_effect=[pem_listing([first,later,envelope]),pem_detail([first,later,envelope])])
        stage=b.collect_chunk(source(b.PEM),fetch,now=now)
        final=b.collect_chunk(source(b.PEM),fetch,checkpoint=stage['checkpoint'],now=now)
        self.assertTrue(final['complete']);self.assertEqual(len(final['events']),1)

    def test_pem_native_markdown_validates_canonical_ics_and_preserves_full_narrative(self):
        event = pem_event(); item = b._item(b.PEM,event['offers']['url'],event['name'],sessions=[dict(start=event['startDate'],end=event['endDate'])])
        ics='BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:test\nSUMMARY:Winter art\nDTSTART:20270108T200000Z\nDTEND:20270108T213000Z\nLOCATION:161 Essex St\\, Salem\\, MA 01970\nEND:VEVENT\nEND:VCALENDAR'
        body = 'Native art materials and instructions. '*100 + 'Last safety instruction.'
        payload = '---\ntitle: "Winter art"\ncanonical_url: "'+item['url']+'"\n---\n# Winter art\n[Apple](data:text/calendar;charset=utf8;base64,'+base64.b64encode(ics.encode()).decode()+')\n## Know before you go\nIncluded with admission\n'+body+'\nStay up to date.\nNewsletter'
        row = b._pem_detail(item,payload,NOW)[0]
        self.assertIn(body,row['description']);self.assertNotIn('Newsletter',row['description'])
        with self.assertRaisesRegex(ValueError,'identity_changed'):
            b._pem_detail(item,payload.replace(item['url'],item['url']+'-changed'),NOW)

    def test_durable_checkpoint_emits_only_complete_batch_and_rejects_address_tampering(self):
        event=pem_event(); listing=pem_listing([event]); details=pem_detail([event])
        fetch=Mock(side_effect=[listing,details])
        first=b.collect_chunk(source(b.PEM),fetch,now=NOW)
        self.assertFalse(first['complete']);self.assertEqual(first['events'],[])
        final=b.collect_chunk(source(b.PEM),fetch,checkpoint=first['checkpoint'],now=NOW)
        self.assertTrue(final['complete']);self.assertEqual(len(final['events']),1)
        b._checkpoint(final['checkpoint'],b.PEM,NOW)
        tampered=deepcopy(final['checkpoint']);tampered['events'][0]['venue_address']='1 Fake Street, Boston, MA 02110'
        with self.assertRaisesRegex(ValueError,'checkpoint_invalid'):b._checkpoint(tampered,b.PEM,NOW)
        tampered=deepcopy(first['checkpoint']);tampered['queue'][0]['url']='https://127.0.0.1/private';tampered['manifest_hash']=b._hash(tampered['queue'])
        with self.assertRaisesRegex(ValueError,'checkpoint_invalid'):b._checkpoint(tampered,b.PEM,NOW)
        fetch.reset_mock();b.collect_chunk(source(b.PEM),fetch,checkpoint=final['checkpoint'],now=NOW);fetch.assert_not_called()


    def test_mos_rejects_cross_page_duplicate_or_changed_total_before_completion(self):
        url='https://www.mos.org/api/v1/event-listing/event_detail/96+101/all/all/all/all?items_per_page=18&sort_by=date_asc'
        card='<h3 class="listing-item__title"><a href="/events/program-{0}">Program {0}</a></h3><div class="listing-item__date">Saturday, November 21, 2026 | 1:00pm</div>'
        page=lambda number,ids,total=20:json.dumps(dict(pager=dict(current_page=number,items_per_page=18,total_pages=2,total_results=total),results=[dict(event_listing=card.format(i)) for i in ids]))
        for second in (page(1,[17,19]),page(1,[18],19)):
            def fetch(target,accept):
                if target==b.SOURCES[b.MOS][0]:return '<div id="event-listing" data-api-url="'+url+'"></div>'
                return second if target.endswith('&page=1') else page(0,range(18))
            with self.subTest(second=second),self.assertRaisesRegex(ValueError,'pagination_changed'):
                b.collect_chunk(source(b.MOS),fetch,now=NOW)


    def test_mos_raw_coverage_includes_filtered_past_native_ids(self):
        url='https://www.mos.org/api/v1/event-listing/event_detail/96+101/all/all/all/all?items_per_page=18&sort_by=date_asc'
        card='<h3 class="listing-item__title"><a href="/events/program-{0}">Program {0}</a></h3><div class="listing-item__date">{1} | 1:00pm</div>'
        data=json.dumps(dict(pager=dict(current_page=0,items_per_page=18,total_pages=1,total_results=2),results=[dict(event_listing=card.format(1,'Friday, November 13, 2026')),dict(event_listing=card.format(2,'Saturday, November 21, 2026'))]))
        fetch=lambda target,accept:'<div id="event-listing" data-api-url="'+url+'"></div>' if target==b.SOURCES[b.MOS][0] else data
        result=b.collect_chunk(source(b.MOS),fetch,now=NOW)
        self.assertEqual(result['checkpoint']['native_total'],2)
        self.assertEqual(len(result['checkpoint']['native_seen']),2)
        self.assertEqual(result['checkpoint']['manifest_count'],1)
        b._checkpoint(result['checkpoint'],b.MOS,NOW)


    def test_trustees_rejects_cross_page_duplicate_before_completion(self):
        def page(number,ids):
            data=dict(preload_data=dict(settings=dict(pager=dict(page=number,per_page=16,total_rows=18,total_pages=2))))
            cards=''.join('<div class="teaser-event"><a href="https://thetrustees.org/event/'+str(i)+'/"></a><h3 class="teaser-event__title">Program '+str(i)+'</h3><div class="teaser-event__location">deCordova Sculpture Park and Museum | Lincoln</div></div>' for i in ids)
            return '<script>window.FWP_JSON = '+json.dumps(data)+';</script><div class="facetwp-template"><div class="event-cards">'+cards+'</div></div>'
        fetch=lambda url,accept:page(2,[16,18]) if '_paged=2' in url else page(1,range(1,17))
        with self.assertRaisesRegex(ValueError,'pagination_changed'):
            b.collect_chunk(source(b.DECORDOVA),fetch,now=NOW)



if __name__ == '__main__':
    unittest.main()
