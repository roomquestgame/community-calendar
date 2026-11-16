import json
import unittest
from roomquest.things_to_do_extract import parse_page, discover_links

URL = 'https://parks.example.gov/parks/pine'
CONTEXT = {'source_key': 'pine', 'city': 'South Hill', 'state': 'VA',
           'url_prefixes': ['https://parks.example.gov/parks']}


def page(**changes):
    node = {'@type': 'Park', 'name': 'Pine Park', 'url': URL,
            'address': {'addressLocality': 'South Hill', 'addressRegion': 'VA'}}
    node.update(changes)
    return '<script type="application/ld+json">' + json.dumps(node) + '</script><main><h1>Pine Park</h1></main>'


class ExtractionTests(unittest.TestCase):
    def test_minimal_core_needs_no_optional_facts(self):
        row, = parse_page(page(), URL, CONTEXT)
        self.assertEqual(row['location_text'], 'South Hill, VA')
        self.assertNotIn('description', row)
        self.assertNotIn('is_free', row)
        self.assertNotIn('is_kid_friendly', row)

    def test_wrong_location_and_generic_organization_do_not_pass(self):
        self.assertEqual(parse_page(page(address={'addressLocality': 'South Hill', 'addressRegion': 'WA'}), URL, CONTEXT), [])
        self.assertEqual(parse_page(page(**{'@type': 'Organization'}), URL, CONTEXT), [])

    def test_dated_events_do_not_become_evergreen(self):
        self.assertEqual(parse_page(page(startDate='2026-11-20'), URL, CONTEXT), [])

    def test_bad_optional_fields_do_not_reject_core(self):
        self.assertEqual(len(parse_page(page(description={'bad': True}, openingHours=42), URL, CONTEXT)), 1)

    def test_identity_does_not_depend_on_title(self):
        a, = parse_page(page(), URL, CONTEXT)
        b, = parse_page(page(name='Renamed Pine Park'), URL, CONTEXT)
        self.assertEqual(a['external_id'], b['external_id'])

    def test_index_cannot_claim_another_pages_facts(self):
        self.assertEqual(parse_page(page(url=URL+'/other'), URL, CONTEXT), [])

    def test_unusable_200_is_not_successful_verification(self):
        with self.assertRaises(ValueError):
            parse_page('<main>Access denied</main>', URL, CONTEXT)

    def test_links_are_bounded_scoped_and_do_not_blacklist_known_domain(self):
        raw = '<main>' + ''.join(f'<a href="/parks/trail-{i}">Trail</a>' for i in range(100))
        raw += '<a href="https://other.test/parks/trail">Trail</a></main>'
        links = discover_links(raw, URL, CONTEXT)
        self.assertEqual(len(links), 40)
        self.assertTrue(all(x.startswith('https://parks.example.gov/parks/') for x in links))


if __name__ == '__main__':
    unittest.main()
