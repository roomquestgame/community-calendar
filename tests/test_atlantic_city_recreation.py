from contextlib import ExitStack
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
import unittest
from unittest.mock import Mock, patch

from roomquest import atlantic_city_recreation as ac


NOW = datetime(2026, 11, 14, 22, tzinfo=timezone.utc)
SCHEDULE = b'%PDF-synthetic-reviewed-grid'
CLOSURES = b'%PDF-synthetic-reviewed-closures'


def preview_record(title, start, end, venue, address, city, url, identity, category='', **kw):
    return dict(id=identity, title=title, starts_at=start, ends_at=end, venue_name=venue,
                venue_address=address, venue_city=city, event_url=url, category=category,
                lat=kw.get('lat'), lng=kw.get('lng'))


def source(key):
    profile = ac.SOURCES[key]
    return dict(source_key=key, feed_url=profile[0], kind=profile[1],
                platform_adapter=profile[2], timezone=ac.ZONE)


def eht_program(pid='30031', *, body=None, extra='', start='12:00 PM', end='02:00 PM',
                register='Registration Unavailable', title=None):
    title = title or ('Open Gym Basketball' if pid == '30031' else ac.EHT_PROGRAMS[pid])
    body = body if body is not None else '<p>Public drop-in sessions are available as space allows.</p>'
    notes = ('<div class="note-section"><h2>Open Gym Basketball</h2>'
             '<p>Play a complete community game. Bring your own equipment.</p></div>' if pid == '30031'
             else '<div class="note-section"><h2>Instructor</h2><p>Publisher Instructor</p></div>')
    aid, weekday = ('148217', 'M') if pid == '30031' else ('148255', 'Tu')
    if pid == '30076':
        start, end = '10:00 AM', '11:00 AM'
    return f'''<h1>{ac.EHT_PROGRAMS[pid]}</h1><span id="Content_lblDescription">{body}{extra}</span>
    {notes}<table><tr><td data-title="Register">{register}
    <a class="view_availability" href="view_availability.aspx?ActivityID={aid}">Eligibility</a></td>
    <td data-title="Activity">{title}</td><td data-title="Ages">18y and up</td>
    <td data-title="Days">{weekday}</td><td data-title="Date/Time">
    11/01/2026 - 12/31/2026 {start} - {end}</td></tr></table>'''


def eht_calendar(*, dates=('Monday November 16, 2026',), clock='12:00 PM - 02:00 PM',
                 duplicate=False, facility='14784,0', activity='Open Gym Basketball', pid='30031'):
    result = f'''<select id="Content_lstFacilityID"><option selected value="{facility}">
    EHT Community Center</option></select><input id="Content_txtStartDate" value="11/14/2026">
    <input id="Content_txtEndDate" value="12/14/2026">'''
    for day in dates:
        row = f'''<tr class="row"><td>{clock}</td><td><a href="/info/activities/program_details.aspx?ProgramID={pid}">
        {ac.EHT_PROGRAMS[pid]} - {activity}</a></td><td></td></tr>'''
        result += '<table class="styled"><tr class="trTitle"><td>' + day + '</td></tr>' + row
        if duplicate:
            result += row
        result += '</table>'
    return result


def eht_bodies(**kw):
    return {'30031': eht_program(**kw), '30076': eht_program('30076')}


def oc_index():
    return f'''<p>1735 Simpson Avenue Ocean City, NJ 08226</p>
    <a href="{ac.OC_DOCUMENT}">2026-27 Winter Group Exercise Schedule</a>
    <a href="{ac.OC_CLOSURES}">Holiday exceptions</a><p>
    Online reservations for exercise classes are open. Please reserve a time slot.
    To cancel, call 609-398-6900.</p>'''


def oc_programs():
    return f'''<a href="{ac.OC_DOCUMENT}">Winter classes</a><div id="faq26836entry">
    <p>WATER EXERCISE</p><p>The water exercise class is designed for movement in the pool.
    Non-swimmers welcome.</p><p>MON.- THURS 11:05 - 11:50AM 12:00 – 12:45PM</p>
    <p>FRI. SAT. &amp; SUN. 11:05 – 11:50AM</p></div>'''


def oc_pages(*, strength=None):
    definitions = ' '.join(label + ': ' + (strength if label == 'Strength' and strength is not None else
                            'Complete published ' + label + ' class narrative.')
                            for label in ac.OC_DEFINITION_LABELS)
    return ['OCEAN CITY AQUATIC & FITNESS CENTER WINTER Nov 9 - March 7, 2027 MATS ARE NOT PROVIDED',
            'CLASS DESCRIPTIONS: ' + definitions + ' How to Register for Classes Instructions.']


class AtlanticCityRecreationTest(unittest.TestCase):
    def setUp(self):
        self.record_patch = patch.object(ac, 'record', side_effect=preview_record)
        self.record_patch.start()
        self.addCleanup(self.record_patch.stop)

    def oc(self, *, now=NOW, strength=None, index=None, schedule=SCHEDULE, closures=CLOSURES):
        def pages(payload, **kw):
            if payload == SCHEDULE:
                return oc_pages(strength=strength)
            return ['2026 Holidays and Early Closings Thanksgiving Day CLOSED Christmas Day CLOSED '
                    'Christmas Eve Open 5am – 1pm New Year’s Eve Open 5am – 1pm']
        with ExitStack() as stack:
            stack.enter_context(patch.object(ac, 'OC_DOCUMENT_SHA256', sha256(SCHEDULE).hexdigest()))
            stack.enter_context(patch.object(ac, 'OC_CLOSURES_SHA256', sha256(CLOSURES).hexdigest()))
            stack.enter_context(patch.object(ac, '_pdf_pages', side_effect=pages))
            return ac.parse_ocean_city(index or oc_index(), schedule, closures, oc_programs(), now=now)

    def test_eht_uses_individual_dates_and_deduplicates_reservations(self):
        rows = ac.parse_eht(eht_calendar(dates=('Monday November 16, 2026', 'Monday November 30, 2026'),
                                           duplicate=True), eht_bodies(), now=NOW)
        self.assertEqual(len(rows), 2)
        self.assertEqual([r['starts_at'][:10] for r in rows], ['2026-11-16', '2026-11-30'])
        self.assertEqual(rows[0]['starts_at'], '2026-11-16T12:00:00-05:00')
        self.assertEqual(rows[0]['ends_at'], '2026-11-16T14:00:00-05:00')
        self.assertNotIn('2026-11-23', str(rows))
        self.assertEqual(rows[0]['venue_address'], ac.VENUES[ac.EHT][1])
        self.assertEqual(rows[0]['location_provenance'], 'reviewed_nj_ogis_point_address')

    def test_eht_full_narrative_preserves_long_suffix_and_escaped_literal(self):
        body = 'Public drop-in sessions. ' + 'A complete exercise instruction. ' * 100
        ending = 'Final public condition with <literal text>.'
        raw = '<p>' + escape(body) + '</p><p>' + escape(ending) + '</p>'
        rows = ac.parse_eht(eht_calendar(), eht_bodies(body=raw), now=NOW)
        description = rows[0]['description']
        self.assertGreater(len(description), 2000)
        self.assertIn(body.rstrip(), description)
        self.assertIn(ending, description)
        self.assertIn('Bring your own equipment.', description)
        self.assertTrue(description.endswith('Ages: 18y and up'))

    def test_eht_closed_season_registration_keeps_explicit_public_drop_in(self):
        rows = ac.parse_eht(eht_calendar(), eht_bodies(), now=NOW)
        self.assertEqual(len(rows), 1)
        for body in ('<p>Seasonal registration only.</p>', '<p>A members-only drop-in session.</p>'):
            with self.subTest(body=body):
                self.assertEqual(ac.parse_eht(eht_calendar(), eht_bodies(body=body), now=NOW), [])
        self.assertEqual(ac.parse_eht(eht_calendar(), eht_bodies(register='Sold out'), now=NOW), [])

    def test_eht_yoga_keeps_program_body_and_instructor(self):
        calendar = eht_calendar(dates=('Tuesday November 17, 2026',), clock='10:00 AM - 11:00 AM',
                                activity=ac.EHT_PROGRAMS['30076'], pid='30076')
        rows = ac.parse_eht(calendar, eht_bodies(), now=NOW)
        self.assertEqual(len(rows), 1)
        self.assertIn('Publisher Instructor', rows[0]['description'])
        self.assertIn('#148255', rows[0]['event_url'])

    def test_eht_conflicting_dates_and_clocks_fail_instead_of_inventing(self):
        for kw, error in (({'clock': '12:00 PM - 03:00 PM'}, 'schedule_conflict'),
                          ({'clock': 'Time TBD'}, 'clock_missing'),
                          ({'dates': ('Tuesday November 17, 2026',)}, 'schedule_conflict'),
                          ({'dates': ('Monday November 17, 2026',)}, 'date_conflict')):
            with self.subTest(kw=kw), self.assertRaisesRegex(ValueError, error):
                ac.parse_eht(eht_calendar(**kw), eht_bodies(), now=NOW)

    def test_eht_wrong_facility_and_old_calendar_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'venue_changed'):
            ac.parse_eht(eht_calendar(facility='99999,0'), eht_bodies(), now=NOW)
        with self.assertRaisesRegex(ValueError, 'calendar_window_changed'):
            ac.parse_eht(eht_calendar(), eht_bodies(), now=datetime(2027, 1, 2, tzinfo=timezone.utc))

    def test_eht_missing_and_oversized_description_is_never_clipped(self):
        for body in ('<p> </p>', '<p>Public drop-in. ' + 'x' * 12000 + '</p>'):
            with self.subTest(size=len(body)), self.assertRaisesRegex(ValueError, 'description_'):
                ac.parse_eht(eht_calendar(), eht_bodies(body=body), now=NOW)

    def test_oc_applies_closures_early_hours_and_reviewed_year(self):
        rows = self.oc()
        self.assertGreater(len(rows), 250)
        self.assertLess(len(rows), 500)
        self.assertFalse(any(r['starts_at'][:10] in ('2026-11-26', '2026-12-25') for r in rows))
        self.assertFalse(any(r['starts_at'][:4] == '2027' for r in rows))
        for day in ('2026-12-24', '2026-12-31'):
            day_rows = [r for r in rows if r['starts_at'].startswith(day)]
            self.assertTrue(any(r['title'] == 'Yoga' for r in day_rows))
            self.assertTrue(all(datetime.fromisoformat(r['starts_at']).hour < 13 for r in day_rows))
            self.assertFalse(any(r['title'] == 'Wheels & Steel' for r in day_rows))
        with self.assertRaisesRegex(ValueError, 'holiday_scope_expired'):
            self.oc(now=datetime(2027, 1, 2, tzinfo=timezone.utc))

    def test_oc_unknown_ends_and_explicit_durations_remain_distinct(self):
        rows = [r for r in self.oc() if r['starts_at'].startswith('2026-11-17')]
        early = next(r for r in rows if r['title'] == 'TBW' and 'T05:15:' in r['starts_at'])
        self.assertIsNone(early['ends_at'])
        zumba = next(r for r in rows if r['title'] == 'Zumba')
        self.assertEqual(zumba['starts_at'], '2026-11-17T16:45:00-05:00')
        self.assertEqual(zumba['ends_at'], '2026-11-17T17:45:00-05:00')
        water = next(r for r in rows if r['title'] == 'Water Exercise' and 'T11:05:' in r['starts_at'])
        self.assertEqual(water['ends_at'], '2026-11-17T11:50:00-05:00')
        self.assertIn('Non-swimmers welcome.', water['description'])
        self.assertIn('approximate map location', water['venue_name'])
        self.assertEqual(water['location_provenance'], 'reviewed_nj_ogis_street_address')

    def test_oc_complete_native_definition_preserves_plain_literal_and_suffix(self):
        body = 'Complete body with <literal native text>. ' + 'Native class instruction. ' * 120 + 'Final condition.'
        rows = self.oc(strength=body)
        strength = next(r for r in rows if r['title'] == 'Strength')
        self.assertIn('Strength: ' + body, strength['description'])
        self.assertGreater(len(strength['description']), 2000)
        self.assertIn('reserve a time slot', strength['description'])
        with self.assertRaisesRegex(ValueError, 'description_limit'):
            self.oc(strength='x' * 12001)

    def test_oc_changed_document_or_current_link_cannot_reuse_captured_grid(self):
        for kw in ({'schedule': SCHEDULE + b'changed'}, {'closures': CLOSURES + b'changed'},
                   {'index': oc_index().replace(ac.OC_DOCUMENT, ac.OC_DOCUMENT.replace('2026-27', '2027-28'))}):
            with self.subTest(kw=kw), self.assertRaisesRegex(ValueError, 'edition_unreviewed'):
                self.oc(**kw)

    def test_oc_missing_definition_is_not_replaced_with_title(self):
        with self.assertRaisesRegex(ValueError, 'class_descriptions_changed'):
            ac._oc_definitions(oc_pages()[1].replace('Strength:', 'New label:'))
        with self.assertRaisesRegex(ValueError, 'description_missing'):
            ac._oc_definitions(oc_pages(strength='')[1])

    def test_both_snapshot_caps_fail_without_partial_return(self):
        with patch.object(ac, 'MAX_RECORDS', 1):
            with self.assertRaisesRegex(ValueError, 'source_record_limit'):
                ac.parse_eht(eht_calendar(dates=('Monday November 16, 2026', 'Monday November 30, 2026')),
                             eht_bodies(), now=NOW)
            with self.assertRaisesRegex(ValueError, 'source_record_limit'):
                self.oc()

    def test_source_identity_and_deadline_fail_before_network(self):
        fetch = Mock()
        for key in ac.SOURCES:
            for field, wrong in (('feed_url', ac.SOURCES[key][0] + '&extra=1'),
                                 ('kind', 'ics'), ('platform_adapter', 'jsonld'), ('timezone', 'UTC')):
                with self.subTest(key=key, field=field), self.assertRaisesRegex(ValueError, 'unregistered'):
                    ac.collect(dict(source(key), **{field: wrong}), fetch, now=NOW)
            with self.assertRaisesRegex(ValueError, 'collection_deadline'):
                ac.collect(source(key), fetch, deadline_at=0, now=NOW)
        fetch.assert_not_called()

    def test_changed_venue_street_cannot_reuse_reviewed_pin(self):
        changed = (ac.VENUES[ac.EHT][0], '5050 English Creek Avenue, Egg Harbor Township, NJ 08234', 'Egg Harbor Township')
        with patch.dict(ac.VENUES, {ac.EHT: changed}):
            row = ac.parse_eht(eht_calendar(), eht_bodies(), now=NOW)[0]
        self.assertIsNone(row['lat'])
        self.assertIsNone(row['lng'])
        self.assertEqual(row['location_provenance'], 'reviewed_venue_street_address_pending_geocode')

    def test_eht_collect_fetches_all_bodies_with_guarded_callback_contract(self):
        data = {ac.SOURCES[ac.EHT][0]: eht_calendar(),
                ac.EHT_PROGRAM_BASE + '30031': eht_program(),
                ac.EHT_PROGRAM_BASE + '30076': eht_program('30076')}
        calls = []
        def fetch(url, accept):
            calls.append((url, accept))
            return data[url]
        self.assertEqual(len(ac.collect(source(ac.EHT), fetch, now=NOW)), 1)
        self.assertEqual(len(calls), 3)
        self.assertEqual({accept for _, accept in calls}, {'text/html'})


if __name__ == '__main__':
    unittest.main()
