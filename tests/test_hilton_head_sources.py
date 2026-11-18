"""Source-bound HHI direct-calendar intake regression tests."""
import json
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
from roomquest import hilton_head_sources as h


def source(key):
    return dict(source_key=key,feed_url=h.SOURCES[key][0],
                kind=h.SOURCES[key][1],platform_adapter=h.SOURCES[key][2],
                timezone=h.ZONE)


def event(title='Live Music Night', *, street='138 Island Drive',
          city='Hilton Head Island, SC 29926', marker=(32.2,-80.7),
          body='<p>Live &amp; acoustic concert <b>tonight</b>.</p>',
          identity='6a701234aa'):
    start=int((datetime.now(timezone.utc)+timedelta(days=2)).timestamp()*1000)
    return dict(id=identity, title=title, startDate=start,
                endDate=start+7200000,workflowState=1,
                fullUrl='/events/live-music-night',
                body=body,assetUrl='https://images.squarespace-cdn.com/content/v1/555a388ae4b05d23afa13ecc/example/2026-event.jpg',
                location=dict(addressTitle='Lincoln & South Brewing',
                              addressLine1=street,addressLine2=city,
                              markerLat=marker[0],markerLng=marker[1]))


def data(rows):
    return json.dumps(dict(website=dict(timeZone=h.ZONE),upcoming=rows,pagination={}))


class DirectHiltonHeadTests(unittest.TestCase):
    def test_five_exact_first_party_sources(self):
        self.assertEqual(set(h.SOURCES),{h.HHSO,h.CULTURE,h.ISLAND,h.SHELTER,h.LINCOLN})
        for key in h.SOURCES:
            self.assertTrue(h.source_valid(source(key)))
            self.assertFalse(h.source_valid({**source(key),'feed_url':'https://evil.test/events'}))
            self.assertFalse(h.source_valid({**source(key),'timezone':'UTC'}))
            with self.assertRaisesRegex(ValueError,'unregistered_hilton_head_source'):
                h.collect({**source(key),'feed_url':'https://evil.test/events'},lambda *_:'[]')

    def test_squarespace_full_sanitized_html_and_canonical_street(self):
        row=h.collect(source(h.LINCOLN),lambda *_:data([event(body='<p>'+'Long &amp; detailed text. '*120+'</p><script>BAD</script>')]))[0]
        self.assertGreater(len(row['description']),2500)
        self.assertIn('Long & detailed',row['description'])
        self.assertNotIn('<p>',row['description'])
        self.assertNotIn('BAD',row['description'])
        self.assertEqual(row['venue_address'],'138 Island Drive, Hilton Head Island, SC')
        self.assertEqual(row['timezone'],h.ZONE)
        self.assertTrue(row['image_url'])
        self.assertTrue(row['image_provenance'])

    def test_missing_street_and_nyc_default_coordinate_held(self):
        self.assertEqual(h.collect(source(h.LINCOLN),
             lambda *_:data([event(street='')])) ,[])
        x=event(marker=(40.7207559,-74.0007613))
        r=h.collect(source(h.LINCOLN),lambda *_:data([x]))[0]
        self.assertIsNone(r['lat'])
        self.assertIsNone(r['lng'])

    def test_missing_and_overlong_description_held(self):
        self.assertEqual(h.collect(source(h.LINCOLN),
            lambda *_:data([event(body='')])) ,[])
        self.assertEqual(h.collect(source(h.LINCOLN),
            lambda *_:data([event(body='ABC'*5000)])) ,[])

    def test_wrong_detail_url_and_publisher_timezone_held(self):
        self.assertEqual(h.collect(source(h.LINCOLN),
            lambda *_:data([{**event(), 'fullUrl':'https://evil.example/a'}])) ,[])
        malformed=json.loads(data([event()]))
        malformed['website']['timeZone']='America/Los_Angeles'
        with self.assertRaisesRegex(ValueError,'publisher_timezone_changed'):
            h.collect(source(h.LINCOLN),lambda *_:json.dumps(malformed))

    def test_same_source_separate_occurrences_preserved(self):
        rows=[event(identity='shared'),event(identity='shared')]
        rows[1]['startDate']+=604800000
        rows[1]['endDate']+=604800000
        out=h.collect(source(h.LINCOLN),lambda *_:data(rows))
        self.assertEqual(len(out),2)
        self.assertNotEqual(out[0]['id'],out[1]['id'])

    def test_ics_event_venue_only_corrects_reviewed_first_presbyterian(self):
        p=h._complete_ics_location(
            'First Presbyterian Church, 540 William Parkway, Hilton Head Island, SC, 29928')
        self.assertEqual(p[1],'540 William Hilton Pkwy, Hilton Head Island, SC')
        self.assertIsNone(h._complete_ics_location('The Cultural Arts Center, Hilton Head Island'))
        self.assertIsNone(h._complete_ics_location('Other Church, 540 William Parkway, Fake City, SC'))

    def test_ics_records_preserve_description_and_image_candidate(self):
        fake={'id':'123@hhso.org','title':'Holiday &amp; Pops',
              'description':'Celebrate with &amp; family music.',
              'venue_name':'First Presbyterian Church, 540 William Parkway, Hilton Head Island, SC, 29928',
              'venue_address':'First Presbyterian Church, 540 William Parkway, Hilton Head Island, SC, 29928',
              'event_url':'https://hhso.org/events/holiday-pops-hilton-head-concert-3/',
              'starts_at':(datetime.now(timezone.utc)+timedelta(days=2)).isoformat(),
              'lat':None,'lng':None}
        with patch('roomquest.ics_adapter.parse',return_value=[fake]),patch.object(h,'_ics_images',return_value={
             '123@hhso.org':'https://hhso.org/wp-content/uploads/2026/09/holiday-photo.jpg'}):
            rows=h._ics(h.HHSO,'BEGIN:VCALENDAR\nEND:VCALENDAR')
        self.assertEqual(len(rows),1)
        self.assertIn('music.',rows[0]['description'])
        self.assertEqual(rows[0]['title'],'Holiday & Pops')
        self.assertEqual(rows[0]['venue_address'],'540 William Hilton Pkwy, Hilton Head Island, SC')
        self.assertTrue(rows[0].get('image_url'))

    def test_photo_restrictions(self):
        self.assertIsNone(h.photo_url(h.LINCOLN,'https://example.com/malware.jpg'))
        self.assertIsNone(h.photo_url(h.LINCOLN,'https://images.squarespace-cdn.com/content/v1/a/logo.jpg'))
        self.assertIsNone(h.photo_url(h.HHSO,'https://hhso.org/wp-content/uploads/2026/11/poster-100x100.jpg'))
        self.assertIsNone(h.photo_url(h.HHSO,'https://attacker.tld/wp-content/uploads/2026/11/poster.jpg'))
        self.assertTrue(h.photo_url(h.HHSO,'https://hhso.org/wp-content/uploads/2026/11/poster.jpg'))

    def test_provenance_identity_family(self):
        from roomquest.publisher_evidence import family
        self.assertEqual(family(h.LINCOLN,'https://www.lincolnandsouth.com/events/rock-night'),
                         'hilton_head:'+h.LINCOLN)
        self.assertIsNone(family(h.LINCOLN,'https://other.example/events/rock-night'))


if __name__=='__main__':
    unittest.main()
