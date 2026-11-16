import unittest
from roomquest.things_to_do_content import extract_retained

URL = 'https://example.gov/Facilities/Facility/Details/Arlington-Park-23'
BODY = '''#### Arlington Park Playground

2700 Courthouse Road
Hopewell, VA 23860

## Arlington Park Playground

The park features a playground, basketball courts and a paved walking path. There is no off-street parking.

### Contact Us
300 N Main Street
Hopewell, VA 23860
Business hours: 8:30AM-4:30PM
'''

class RetainedContentTests(unittest.TestCase):
    def extract(self, raw=BODY, **extra):
        return extract_retained(dict(raw_content=raw, **extra), URL, 'web:test')

    def test_actual_address_and_footer_isolation(self):
        record, = self.extract()
        self.assertEqual(record['title'], 'Arlington Park Playground')
        self.assertEqual(record['location_text'], '2700 Courthouse Road, Hopewell, VA 23860')
        self.assertIn('no off-street parking', record['description'])
        self.assertNotIn('availability_text', record)

    def test_no_snippet_substitution(self):
        self.assertEqual(self.extract('', content=BODY), [])

    def test_directory_and_ambiguous_address(self):
        self.assertEqual(self.extract(BODY.replace('### Contact Us', '## Another Park')), [])
        self.assertEqual(self.extract(BODY.replace('### Contact Us', '## Second Location')), [])

    def test_no_footer_only_location(self):
        self.assertEqual(self.extract(BODY.replace('2700 Courthouse Road\nHopewell, VA 23860', '')), [])

    def test_truncation_does_not_invent_optional_fields(self):
        record, = self.extract(raw_content_truncated=True)
        self.assertTrue(record['content_evidence']['truncated'])
        self.assertNotIn('price_text', record)

    def test_stable_identity(self):
        self.assertEqual(self.extract()[0]['external_id'], self.extract(BODY + '\n')[0]['external_id'])

class RetainedWorkerTests(unittest.TestCase):
    def test_saved_content_finishes_without_network(self):
        from unittest.mock import patch
        from roomquest.things_to_do_worker import run_batch
        key = 'web:' + 'a' * 64
        claim = dict(status='claimed', job_id='11111111-1111-1111-1111-111111111111',
                     lease_token='22222222-2222-2222-2222-222222222222',source_key=key,
                     page_url=URL, park_context={}, policy_version='evergreen-v1',
                     scope=dict(parser='general',source_key=key,city='Arlington',state='VA',url_prefixes=[URL]))
        payloads = []
        def database(action, payload):
            if action == 'claim':
                return claim
            payloads.append(payload)
            return dict(status='finished',outcome=payload['status'],inserted=1)
        with patch('roomquest.things_to_do_worker.fetch_publisher',side_effect=AssertionError('network call')):
            result = run_batch(database=database, request_database=lambda *args: dict(status='ready',metadata=dict(raw_content=BODY)))
        self.assertEqual(result['inserted'],1)
        self.assertEqual(payloads[0]['activities'][0]['location_text'],'2700 Courthouse Road, Hopewell, VA 23860')
        self.assertEqual(payloads[0]['discovered_urls'],[])
