import json
import os
import struct
import unittest
from unittest.mock import MagicMock, patch

from roomquest import event_media as m
from roomquest.preview_worker import event_image, calendar_image

CLAIM = {'media_key': 'fixture', 'lease_id': 'fixture-lease', 'title': 'Community concert',
         'event_url': 'https://venue.example.org/event/concert', 'candidate_url': None}
PHOTO = 'https://cdn.example.org/concert-poster.jpg'


class PhotoTests(unittest.TestCase):
    def test_matching_event_jsonld_image_is_preferred(self):
        data = {'@type':'MusicEvent','name':CLAIM['title'],'image':{'@type':'ImageObject','url':PHOTO}}
        html = '<script type="application/ld+json">'+json.dumps(data)+'</script>'
        self.assertEqual(m.extract_photo(html, CLAIM['event_url'], CLAIM['title']), PHOTO)
        self.assertIsNone(m.extract_photo(html, CLAIM['event_url'], 'Unrelated show'))

    def test_open_graph_requires_this_event_title(self):
        html = '<h1>Community concert</h1><meta property="og:image" content="'+PHOTO+'">'
        self.assertEqual(m.extract_photo(html, CLAIM['event_url'], CLAIM['title']), PHOTO)
        self.assertIsNone(m.extract_photo(html.replace('Community concert','Venue home'), CLAIM['event_url'], CLAIM['title']))

    def test_generic_logo_and_tiny_tracking_image_are_not_posters(self):
        self.assertIsNone(event_image('https://cdn.example.org/logo.png'))
        html = '<h1>Community concert</h1><meta property="og:image" content="'+PHOTO+'"><meta property="og:image:width" content="1">'
        self.assertIsNone(m.extract_photo(html, CLAIM['event_url'], CLAIM['title']))
        tiny = b'\x89PNG\r\n\x1a\n'+b'\x00'*8+struct.pack('>II',1,1)
        self.assertFalse(m.image_signature(tiny,'image/png'))

    def test_image_bytes_and_mime_must_match(self):
        png = b'\x89PNG\r\n\x1a\n'+b'\x00'*8+struct.pack('>II',1200,630)
        self.assertTrue(m.image_signature(png,'image/png'))
        self.assertFalse(m.image_signature(b'<html>not an image</html>','image/jpeg'))
        self.assertFalse(m.image_signature(b'<svg></svg>','image/svg+xml'))
        self.assertTrue(m.image_signature(b'\xff\xd8\xff\xe0jpeg','image/jpeg'))

    def test_feed_candidate_reuses_direct_url_without_event_page_fetch(self):
        fetch=MagicMock();probe=MagicMock(return_value=(PHOTO,'image/jpeg'))
        result=m.resolve_photo({**CLAIM,'candidate_url':PHOTO},fetcher=fetch,probe=probe,clock=lambda:0,deadline=30)
        fetch.assert_not_called();probe.assert_called_once_with(PHOTO)
        self.assertEqual(result['evidence_url'],CLAIM['event_url'])

    def test_event_page_photo_is_probed_before_publication(self):
        html='<h1>Community concert</h1><meta property="og:image" content="'+PHOTO+'">'
        self.assertIsNone(m.resolve_photo(CLAIM,fetcher=lambda _:html,probe=lambda _:None,clock=lambda:0,deadline=30))

    def test_private_credentialed_nonhttps_urls_are_rejected(self):
        for value in ['http://example.org/a.jpg','https://127.0.0.1/a.jpg',
                      'https://u:p@example.org/a.jpg','data:image/png;base64,AA','https://example.org/a.svg']:
            self.assertIsNone(event_image(value))

    def test_relative_and_image_object_urls(self):
        self.assertEqual(event_image({'contentUrl':'/poster.jpg'},'https://venue.example.org/event/1'),
                         'https://venue.example.org/poster.jpg')

    def test_ics_image_attachment_ignores_nonimage_files(self):
        from icalendar import Event,vUri
        event=Event();event.add('url',CLAIM['event_url'])
        event.add('attach',vUri('https://cdn.example.org/brochure.pdf'),parameters={'FMTTYPE':'application/pdf'})
        event.add('attach',vUri(PHOTO),parameters={'FMTTYPE':'image/jpeg'})
        self.assertEqual(calendar_image(event),PHOTO)

    def test_disabled_worker_does_not_claim(self):
        db=MagicMock()
        with patch.dict(os.environ,{'VERCEL_ENV':'preview','FORWARD_GEOCODER_ENABLED':'true'}):
            self.assertEqual(m.run_batch(database=db)['claimed'],0)
        db.assert_not_called()

    def test_only_claimed_media_can_be_submitted_and_unavailable_is_recorded(self):
        calls=[]
        def db(action,payload):
            calls.append((action,payload));return [CLAIM] if action=='claim' else {'recorded':True}
        with patch.dict(os.environ,{'VERCEL_ENV':'production','FORWARD_GEOCODER_ENABLED':'true'}):
            result=m.run_batch(database=db,resolver=lambda *a,**kw:None)
        self.assertEqual(result['unavailable'],1)
        self.assertEqual([x[0] for x in calls],['claim','fail'])
        self.assertEqual(calls[-1][1]['lease_id'],CLAIM['lease_id'])

    def test_network_probe_bounds_content_and_validates_magic(self):
        response=MagicMock();response.status_code=200
        response.headers={'Content-Type':'image/jpeg','Content-Length':'200000'}
        response.iter_content.return_value=iter([b'\xff\xd8\xff\xe0jpeg'])
        response.__enter__.return_value=response
        session=MagicMock();session.get.return_value=response
        session.__enter__.return_value=session
        with patch.object(m.requests,'Session',return_value=session),patch.object(m,'validate_public_dns'):
            self.assertEqual(m.probe_image(PHOTO),(PHOTO,'image/jpeg'))
        self.assertTrue(session.get.call_args.kwargs['stream'])
        self.assertFalse(session.get.call_args.kwargs['allow_redirects'])
        self.assertEqual(session.get.call_args.kwargs['headers']['Range'],'bytes=0-4095')


if __name__=='__main__':unittest.main()
