"""Isolated acceptance cases for direct Gainesville TEC, LibCal and Tockify feeds."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import json
import unittest

from roomquest import gainesville_direct_feeds as g


def source(key):
    url, kind, adapter = g.SOURCES[key]
    return dict(source_key=key, feed_url=url, kind=kind,
                platform_adapter=adapter, timezone=g.ZONE)


def wp_event(*, desc='<p>Full &amp; accurate <b>workshop</b> details</p>',
             street='340 Green St.', status='publish'):
    start = datetime.now(timezone.utc) + timedelta(days=2)
    from zoneinfo import ZoneInfo
    local = start.astimezone(ZoneInfo(g.ZONE))
    return dict(id=123456, status=status, title='Community Connection Workshop',
                url='https://www.brenau.edu/event/community-connection-day-2/',
                start_date=local.strftime('%Y-%m-%d %H:%M:%S'),
                utc_start_date=start.strftime('%Y-%m-%d %H:%M:%S'),
                end_date=(local+timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S'),
                utc_end_date=(start+timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S'),
                timezone=g.ZONE, description=desc,
                categories=[{'name':'Classes & Workshops'}],
                venue={'venue':'John W Jacobs Building', 'address':street,
                       'city':'Gainesville','state':'GA','zip':'30501'},
                image={'url':'https://www.brenau.edu/wp-content/uploads/2026/11/workshop.jpg','width':1200})


def rss(rows):
    head='<?xml version="1.0" encoding="utf-8"?>'
    entries=''.join('<item>'+''.join(f'<{k}>{v}</{k}>' for k,v in row.items())+'</item>' for row in rows)
    return head+'<rss version="2.0"><channel>'+entries+'</channel></rss>'


def lib_event(*, eventid='17770740', desc='Details', start='10:15:00', end='11:00:00',
              campus=g.LIBRARY_VENUE):
    date=(datetime.now(timezone.utc)+timedelta(days=3)).date().isoformat()
    return {'title':'Toddler Storytime', 'eventid':eventid, 'date':date,
            'start':start, 'end':end, 'campus':campus,
            'location':'Gainesville Storytime Room',
            'description':desc, 'link':f'https://hallcountylibrary.libcal.com/event/{eventid}'}


def meeple_event(*, location='Meeple Madness, 7400 Spout Springs Rd Suite 205, Flowery Branch, GA 30542, USA'):
    start=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
    return dict(id='TKF/1234/99/0', title='Warhammer 40k Wednesdays', starts_at=start,
                ends_at=None, venue_name=location, venue_address=location,
                venue_city='', lat=None, lng=None, category='Gaming',
                event_url='https://events.meeplemadness.com/meeplemadness/detail/99/1795039200000',
                description='Join our tabletop miniature games workshop.',
                publisher_categories=['Games'])


class DirectGainesvilleTests(unittest.TestCase):
    def test_source_keys_are_direct_not_mapsee(self):
        self.assertEqual(set(g.SOURCES), {g.BRENAU, g.MEEPLE, *g.LIBRARY_PROFILES})
        self.assertTrue(all(not k.startswith('municipal_mapsee_') for k in g.SOURCES))
        for key, spec in g.SOURCES.items():
            changed={**source(key), 'feed_url':spec[0]+'-injected'}
            with self.assertRaisesRegex(ValueError,'unregistered_gainesville_direct_source'):
                g.collect(changed,lambda *_:None)

    def test_wordpress_full_description_entities_address_and_image(self):
        row=g._brenau(wp_event(desc='<p>'+('Careful class &amp; workshop details. '*90)+'</p>'))
        self.assertGreater(len(row['description']),2000)
        self.assertIn('class & workshop',row['description'])
        self.assertNotIn('<p>',row['description'])
        self.assertEqual(row['venue_address'],'340 Green St., Gainesville, GA 30501')
        self.assertTrue(row['image_url'])

    def test_wordpress_no_description_or_image_still_valid(self):
        event=wp_event(desc='')
        event['image']={}
        row=g._brenau(event)
        self.assertIsNotNone(row)
        self.assertEqual(row['description'],'')
        self.assertNotIn('image_url',row)

    def test_wordpress_missing_street_virtual_and_private_held(self):
        self.assertIsNone(g._brenau(wp_event(street='Downtown Gainesville')))
        self.assertIsNone(g._brenau(wp_event(status='private')))

    def test_brenau_pagination_is_bounded(self):
        event=wp_event()
        urls=[]
        def fetch(url,accept):
            urls.append(url)
            return json.dumps({'events':[event], 'total_pages':1})
        rows=g.collect(source(g.BRENAU),fetch)
        self.assertEqual(len(rows),1)
        self.assertEqual(len(urls),1)
        self.assertIn('per_page=100',urls[0])

    def test_library_without_description_still_published_and_street_verified(self):
        inputs=[lib_event(desc=''),lib_event(eventid='17770741',desc='Library book club')]
        rows=g.collect(source(g.LIBRARY),lambda *_: rss(inputs))
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['venue_address'],g.LIBRARY_STREET)
        self.assertIn('',[x['description'] for x in rows])
        self.assertIn('Library book club',[x['description'] for x in rows])

    def test_each_hall_library_branch_has_distinct_verified_publisher_feed(self):
        self.assertEqual(len(g.LIBRARY_PROFILES), 6)
        self.assertEqual(len({p[0] for p in g.LIBRARY_PROFILES.values()}), 6)
        self.assertEqual(len({p[2] for p in g.LIBRARY_PROFILES.values()}), 6)
        for key, (cid, campus, street, city) in g.LIBRARY_PROFILES.items():
            with self.subTest(key=key):
                self.assertEqual(g.SOURCES[key][0],
                    f'https://hallcountylibrary.libcal.com/rss.php?iid=6354&m=month&cid={cid}')
                item = lib_event(eventid=str(18000000+cid), campus=campus,
                                 desc='First-party adult and youth program details')
                rows = g.collect(source(key), lambda *_: rss([item]))
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['venue_address'], street)
                self.assertEqual(rows[0]['venue_city'], city)
                self.assertEqual(rows[0]['description'],
                                 'First-party adult and youth program details')
                self.assertTrue(rows[0]['venue_name'].startswith(campus))
                self.assertIsNone(rows[0].get('image_url'))
                invalid = lib_event(eventid=str(19000000+cid), campus='Incorrect Branch')
                self.assertEqual(g.collect(source(key), lambda *_:rss([invalid])), [])

    def test_library_fingerprint_uses_event_facts_across_all_branches(self):
        for key, (cid, campus, street, city) in g.LIBRARY_PROFILES.items():
            with self.subTest(key=key):
                one = lib_event(eventid='20000001', campus=campus, desc='')
                two = lib_event(eventid='20000002', campus=campus, desc='Other')
                def capture(items):
                    rows = g.collect(source(key), lambda *_: rss(items), retain_original=True)
                    return {r['id']: r['collector_event_content_v1']['facts'] for r in rows}
                initial = capture([one, two])
                with patch.dict(g.LIBRARY_PROFILES, {key: (cid, campus, 'Different street', city)}):
                    self.assertEqual(capture([two, one]), initial)
                self.assertIsNone(initial['20000001']['description'])
                self.assertEqual(initial['20000001']['venue_name'], campus)
                self.assertNotIn('venue_address', initial['20000001'])
                edited = capture([{**one, 'location': 'Room B'}, two])
                self.assertNotEqual(initial['20000001'], edited['20000001'])
                self.assertEqual(initial['20000002'], edited['20000002'])

    def test_new_branch_missing_description_is_allowed(self):
        key = 'hall_library_spout_springs_ga'
        rows = g.collect(source(key), lambda *_:rss([
            lib_event(eventid='18345001', campus=g.LIBRARY_PROFILES[key][1], desc='')]))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['description'], '')
        self.assertEqual(rows[0]['venue_city'], 'Flowery Branch')

    def test_library_all_day_and_wrong_campus_are_held(self):
        items=[lib_event(start='00:00:00',end='23:59:59'),
               lib_event(eventid='17770742',campus='Other Branch')]
        self.assertEqual(g.collect(source(g.LIBRARY),lambda *_:rss(items)),[])

    def test_library_rejects_unsafe_xml(self):
        with self.assertRaisesRegex(ValueError,'unsafe_xml_payload'):
            g.collect(source(g.LIBRARY),lambda *_:'<!DOCTYPE rss><rss/>')

    def test_meeple_ics_uses_shared_parser_and_preserves_full_narrative(self):
        row=meeple_event()
        row['description']='Large full event narrative. '*110
        with patch('roomquest.ics_adapter.parse',return_value=[row]) as parser:
            records=g.collect(source(g.MEEPLE),lambda *_:'BEGIN:VCALENDAR\nEND:VCALENDAR')
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['venue_address'],g.MEEPLE_STREET)
        self.assertGreater(len(records[0]['description']),2000)
        self.assertEqual(records[0]['category'],'Gaming')
        self.assertTrue(parser.called)
        self.assertTrue(parser.call_args.kwargs['include_description'])

    def test_meeple_never_assumes_different_venue_or_untrusted_link(self):
        wrong=meeple_event(location='Meeple Madness, 7401 Spout Springs Rd Suite 205, Flowery Branch, GA 30542')
        url=meeple_event()
        url['event_url']='https://other.example.test/meeplemadness/detail/99/1795039200000'
        with patch('roomquest.ics_adapter.parse',return_value=[wrong,url]):
            self.assertEqual(g.collect(source(g.MEEPLE),lambda *_:'any'),[])

    def test_image_identity_restrictions(self):
        self.assertTrue(g.photo_url(g.BRENAU,
            'https://www.brenau.edu/wp-content/uploads/2026/11/workshop.jpg'))
        self.assertIsNone(g.photo_url(g.BRENAU,
            'https://www.brenau.edu/wp-content/uploads/2026/11/workshop-150x150.jpg'))
        self.assertIsNone(g.photo_url(g.LIBRARY,
            'https://www.brenau.edu/wp-content/uploads/2026/11/workshop.jpg'))
        self.assertIsNone(g.photo_url(g.BRENAU,
            'https://bad.test/wp-content/uploads/2026/11/workshop.jpg'))


if __name__=='__main__':
    unittest.main()
