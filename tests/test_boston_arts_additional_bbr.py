"""Exact meeting-site correction for Eliot's one observed BBR address hold."""
from copy import deepcopy
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from roomquest import boston_arts_additional as a
from roomquest.event_description import description

NOW = datetime(2026, 11, 15, 2, tzinfo=timezone.utc)
TITLE = 'Introduction to Sharpening 2F26'
URL = 'https://eliotschool.org/classes/introduction-sharpening-2f26'
START = '2026-12-05T11:00:00-05:00'
END = '2026-12-05T14:00:00-05:00'
ADDRESS = '100 Terrace Street, Boston, MA 02120'
NARRATIVE = ('Complete native sharpening course detail, including practice and safety. ' * 55)
COURSE = '<div class="view-classes-courses-tabs-view view-display-id-block_1"><p>' + NARRATIVE + '</p></div>'
INSTRUCTOR = '<div class="view-instructors view-display-id-class_quicktab"><p>Complete instructor biography and teaching experience.</p></div>'
MATERIALS = '<div class="view-classes-courses-tabs-view view-display-id-block_3"><p>Bring every listed tool. Final materials paragraph must survive.</p></div>'


def detail(location='Boston Building Resources, 100 Terrace St, Boston, MA 02120'):
    return ('<h1>' + TITLE + '</h1><div class="field-name-field-location">'
            '<div class="field-item">' + location + '</div></div>' + COURSE + INSTRUCTOR + MATERIALS)


def item():
    return a._item(a.ELIOT, URL, TITLE, sessions=[dict(start=START, end=END)])


def source():
    return dict(source_key=a.ELIOT, feed_url=a.SOURCES[a.ELIOT][0], kind='html',
                platform_adapter='html', timezone=a.ZONE)


class EliotBuildingResourcesPoint(unittest.TestCase):
    def test_native_detail_keeps_full_body_identity_and_exact_meeting_point(self):
        rows = a._eliot_detail(item(), detail(), NOW)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['description'], description(COURSE + '\n' + INSTRUCTOR + '\n' + MATERIALS, limit=12001))
        self.assertGreater(len(row['description']), 2000)
        self.assertTrue(row['description'].endswith('Final materials paragraph must survive.'))
        self.assertEqual(row['id'], a.ELIOT + ':classes:introduction-sharpening-2f26:' + START)
        self.assertEqual((row['starts_at'], row['ends_at']),
                         ('2026-12-05T16:00:00+00:00', '2026-12-05T19:00:00+00:00'))
        self.assertEqual((row['title'], row['event_url']), (TITLE, URL))
        self.assertEqual((row['venue_name'], row['venue_address']), ('Boston Building Resources', ADDRESS))
        self.assertEqual((row['lat'], row['lng']), (42.328649, -71.097821))
        self.assertEqual(row['location_provenance'], 'reviewed_municipal_exact_address_point')
        self.assertEqual(row['location_evidence_url'], a.ELIOT_BBR_EVIDENCE)

    def test_other_eliot_venues_keep_normal_geocoding(self):
        for location, venue, street in [
            ('24 Eliot St, Jamaica Plain, MA 02130', 'Eliot Schoolhouse', '24 Eliot Street, Jamaica Plain, MA 02130'),
            ('253 Amory St, Jamaica Plain, MA 02130', 'Eliot School Annex', '253 Amory Street, Jamaica Plain, MA 02130'),
        ]:
            with self.subTest(venue=venue):
                row = a._eliot_detail(item(), detail(location), NOW)[0]
                self.assertEqual((row['venue_name'], row['venue_address']), (venue, street))
                self.assertEqual((row['lat'], row['lng']), (None, None))
                self.assertNotIn('location_evidence_url', row)
                self.assertEqual(row['location_provenance'], 'publisher_class_street_neighborhood_zip_resolution')

    def test_neighboring_native_streets_are_held(self):
        for location in [
            'Boston Building Resources, 101 Terrace St, Boston, MA 02120',
            'Boston Building Resources, 100 Terrace St, Boston, MA 02121',
            'Boston Building Resources Annex, 100 Terrace St, Boston, MA 02120',
        ]:
            with self.subTest(location=location), self.assertRaisesRegex(ValueError, 'street_unresolved'):
                a._eliot_detail(item(), detail(location), NOW)

    def test_point_cannot_leak_to_another_source_venue_or_street(self):
        for key, venue, address in [
            (a.HMSC, 'Boston Building Resources', ADDRESS),
            (a.ELIOT, 'Boston Building Resources Annex', ADDRESS),
            (a.ELIOT, 'Boston Building Resources', '101 Terrace Street, Boston, MA 02120'),
        ]:
            url = URL if key == a.ELIOT else 'https://hmsc.harvard.edu/calendar_event/sharpening/'
            native = a._item(key, url, TITLE)
            with self.subTest(source=key, venue=venue, address=address), patch.dict(a.VENUES, {key: [(venue, address, 'Boston', None)]}):
                row = a._row(key, native, NARRATIVE, a.timestamp(START), a.timestamp(END))
                self.assertEqual((row['lat'], row['lng']), (None, None))
                self.assertNotEqual(row['location_provenance'], 'reviewed_municipal_exact_address_point')
                self.assertNotIn('location_evidence_url', row)

    def test_checkpoint_binds_point_and_primary_evidence_even_with_rehashed_outcome(self):
        listing = ('<div class="calendar-calendar"><div class="calendar"><div class="contents">'
                   '<a href="/classes/introduction-sharpening-2f26">' + TITLE + '</a>'
                   '<span class="date-display-start" content="' + START + '"></span>'
                   '<span class="date-display-end" content="' + END + '"></span>4 spots left</div></div></div>')
        fetch = lambda url, accept: listing if url == a.SOURCES[a.ELIOT][0] else detail()
        first = a.collect_chunk(source(), fetch, now=NOW)
        self.assertFalse(first['complete'])
        self.assertEqual(first['events'], [])
        done = a.collect_chunk(source(), fetch, checkpoint=first['checkpoint'], now=NOW)
        self.assertTrue(done['complete'])
        self.assertEqual(len(done['events']), 1)
        a._checkpoint(done['checkpoint'], a.ELIOT, NOW)
        for field, value in [
            ('lat', None), ('lat', 42.310855), ('lng', -71.117182),
            ('venue_name', 'Eliot Schoolhouse'),
            ('venue_address', '101 Terrace Street, Boston, MA 02120'),
            ('location_provenance', 'publisher_venue_coordinates'),
            ('location_evidence_url', 'https://example.org/unrelated'),
        ]:
            bad = deepcopy(done['checkpoint'])
            bad['events'][0][field] = value
            bad['outcomes'][0] = a._outcome(bad['queue'][0], bad['events'], None)
            bad['outcome_hash'] = a._hash(bad['outcomes'])
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'checkpoint_invalid'):
                a._checkpoint(bad, a.ELIOT, NOW)


if __name__ == '__main__':
    unittest.main()
