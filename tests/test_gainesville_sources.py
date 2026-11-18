"""Contract tests for the bounded Gainesville source batch; no live fetches."""
from datetime import datetime, timedelta, timezone
import json
import unittest
from zoneinfo import ZoneInfo

from roomquest import gainesville_sources as g


def wordpress_event(*, desc='<p>Long <strong>real</strong> description</p>', address='514 Green Street NE', event_id=701):
    local = (datetime.now(timezone.utc) + timedelta(days=2)).astimezone(ZoneInfo(g.ZONE))
    utc = local.astimezone(timezone.utc)
    return {
        'id': event_id, 'status': 'publish', 'title': 'Watercolor Workshop',
        'start_date': local.strftime('%Y-%m-%d %H:%M:%S'),
        'end_date': (local+timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S'),
        'utc_start_date': utc.strftime('%Y-%m-%d %H:%M:%S'),
        'utc_end_date': (utc+timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S'),
        'timezone': g.ZONE, 'description': desc,
        'url': 'https://www.exploregainesville.org/event/watercolor-workshop/',
        'categories': [{'name': 'Classes and Workshops'}],
        'venue': {'venue':'Quinlan Visual Arts Center','address':address,
                  'city':'Gainesville','state':'GA','zip':'30501',
                  'geo_lat':34.295,'geo_lng':-83.825},
        'image': {'url':'https://www.exploregainesville.org/wp-content/uploads/2026/11/event-art.jpg','width':1200},
    }


def square_event(*, title='B-Movie Bingo', address='852 Main Street Southwest', excerpt='<p>Doors at 6pm; bingo cards $5. Movie at 7pm.</p>'):
    start = datetime.now(timezone.utc)+timedelta(days=2)
    return {'id':'6ac6d5972c49dc42fd0f5a4b','workflowState':1,'title':title,
            'fullUrl':'/events/b-movie-bingo','startDate':int(start.timestamp()*1000),
            'endDate':int((start+timedelta(hours=2)).timestamp()*1000),
            'body':'<div class="empty"></div>','excerpt':excerpt,
            'location': {'addressTitle':'Blackstrap Rock Hall','addressLine1':address,
                         'addressLine2':'Gainesville, GA, 30501','markerLat':34.2902575,'markerLng':-83.8211527},
            'categories':['Live Music'],
            'assetUrl':'https://images.squarespace-cdn.com/content/v1/123/456/event-photo.jpg'}


class GainesvilleTests(unittest.TestCase):
    def test_exact_profiles_and_reject_substitution(self):
        for key, profile in g.SOURCES.items():
            invalid={'source_key':key,'feed_url':profile[0].replace('https://','http://',1),
                     'kind':profile[1],'platform_adapter':profile[2],'timezone':g.ZONE}
            with self.assertRaisesRegex(ValueError,'unregistered_gainesville_source'):
                g.collect(invalid, lambda *_:None)

    def test_wordpress_complete_description_decodes_entities(self):
        item=wordpress_event(desc='<p>'+('Description with <b>bold</b> &amp; details. '*110)+'</p>')
        self.assertGreater(len(g._wordpress(item)['description']),2000)
        row=g._wordpress(item)
        self.assertNotIn('<b>',row['description'])
        self.assertIn('& details.',row['description'])
        self.assertEqual(row['venue_address'],'514 Green Street NE, Gainesville, GA 30501')
        self.assertIsNotNone(row['image_url'])
        self.assertNotEqual(row['category'].lower(),'other')

    def test_no_guessed_street_or_fake_pin(self):
        self.assertIsNone(g._wordpress(wordpress_event(address='Downtown Gainesville')))
        self.assertIsNone(g._wordpress(wordpress_event(address='')))
        self.assertIsNone(g._squarespace(g.BLACKSTRAP,square_event(address='Main Street'),datetime.now(timezone.utc)))

    def test_square_excerpt_full_narrative_and_precise_venue(self):
        row=g._squarespace(g.BLACKSTRAP,square_event(),datetime.now(timezone.utc))
        self.assertIsNotNone(row)
        self.assertIn('Movie at 7pm',row['description'])
        self.assertEqual(row['venue_address'],'852 Main Street Southwest, Gainesville, GA 30501')
        self.assertAlmostEqual(row['lat'],34.2902575)
        self.assertEqual(row['timezone'],g.ZONE)

    def test_missing_description_is_optional_not_fabricated(self):
        wp = g._wordpress(wordpress_event(desc=''))
        square = g._squarespace(g.BLACKSTRAP,square_event(excerpt=''),datetime.now(timezone.utc))
        self.assertEqual(wp['description'], '')
        self.assertEqual(square['description'], '')
        self.assertTrue(wp['venue_address'])
        self.assertTrue(square['venue_address'])

    def test_offered_oversize_description_is_not_truncated(self):
        with self.assertRaisesRegex(ValueError, 'publisher_description_limit'):
            g._wordpress(wordpress_event(desc='<p>' + ('x' * 12010) + '</p>'))

    def test_low_res_and_untrusted_images(self):
        self.assertIsNone(g.photo_url(g.EXPLORE,'https://www.exploregainesville.org/wp-content/uploads/2026/11/painting-150x150.jpg'))
        self.assertIsNone(g.photo_url(g.BLACKSTRAP,'https://images.squarespace-cdn.com/content/v1/123/logo.png'))
        self.assertIsNone(g.photo_url(g.EXPLORE,'https://untrusted.test/event.jpg'))

    def test_api_pagination_and_multiple_occurrences(self):
        item=wordpress_event(event_id=701)
        later=wordpress_event(event_id=702)
        pages=[]
        def fetch(url,content_type):
            self.assertEqual(content_type,'application/json')
            pages.append(url)
            return json.dumps({'events':[item] if 'page=1' in url else [later],'total_pages':2})
        source={'source_key':g.EXPLORE,'feed_url':g.SOURCES[g.EXPLORE][0],
                'kind':'json','platform_adapter':'wordpress','timezone':g.ZONE}
        rows=g.collect(source,fetch)
        self.assertEqual(len(rows),2)
        self.assertEqual(len(pages),2)
        self.assertNotEqual(rows[0]['id'],rows[1]['id'])


if __name__ == '__main__':
    unittest.main()
