from datetime import datetime, timezone
from hashlib import sha256
from html import escape
from io import BytesIO
from time import monotonic
import unittest
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from roomquest import atlantic_city_local_recreation as local
from roomquest import preview_worker as worker


NOW = datetime(2026, 11, 14, 23, tzinfo=timezone.utc)
POLICY = (
    'Based on your feedback, we are excited to continue to offer the ability '
    'to drop into a class for the fall session! '
    'Programs marked with an * will allow drop-ins based on instructor maximum or equipment available. '
    'Fitness class drop-in fees are: $5/class for non-seniors and $2/class for seniors (age 60+). '
    'The fee must be paid at the CER front desk before attending. '
    'Late drop-ins will not be permitted. Limited drop-in spots are available. '
    'Once filled, no more drop-ins will be allowed for that class that day.'
)


def pdf_bytes(title='YOGA FUSION*', prose='Bring your own mat. Complete final program condition.',
              metadata='Instructor: Person Begins 10/5/26 Sr. $32.00\n'
                       '16 Sessions (8 Weeks) Monday & Wednesday 1:00pm - 2:00pm Non-Sr. $80.00',
              policy=POLICY):
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({
        NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/Helvetica'), NameObject('/Encoding'): NameObject('/WinAnsiEncoding')}))
    texts = {
        1: 'FALL PROGRAMS 2026\n'
           'All courses will be held at the Brigantine Community Center at 265 42nd St.\n'
           'CLOSURES THIS SESSION: 10/12, 11/3, 11/11, 11/26 & 11/27',
        2: policy + '\nFALL DROP-INS',
        4: title + '\n' + prose + '\n' + metadata,
    }
    for number in range(1, 22):
        page = writer.add_blank_page(width=612, height=792)
        if number not in texts:
            continue
        page[NameObject('/Resources')] = DictionaryObject({
            NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        lines = []
        for line in texts[number].splitlines():
            value = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            lines.append(f'({value}) Tj T*')
        stream = DecodedStreamObject()
        stream.set_data(('BT /F1 9 Tf 12 TL 36 750 Td\n' + '\n'.join(lines) + '\nET').encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def run_html(extra='', weekly='11/15/26', weekday='Sunday', save='Saturday, December 12th'):
    values = [
        f"This Week's Group Run Meetup ({weekly}):",
        f'1. {weekday} {weekly}, 8:00AM, Linwood Bike Path, meet at hockey rink parking '
        'near Mainland High School on Wabash Ave at the end of W Essex Ave, POC- Harry B.',
        'The Linwood Bike Path is a paved, traffic free path. ' + extra,
        'Directions to The Linwood Bike Path: park on Wabash Ave at the end of W Essex Ave.',
        'NOTE- All Are Welcome! Run as many miles as you like with us!',
        'Race meetups:', 'None this week.',
        f'Save The Date: Our 4th annual Ocean City Christmas Tree Run will be on {save}, '
        'at 8am, starting from the OC Music Pier. More info to come!',
    ]
    return ('<h1>NJShoreRun Weekly Group Runs and Local Race Meetup</h1><div>'
            + ''.join('<p>' + escape(value) + '</p>' for value in values) + '</div>')


class LocalRecreationTests(unittest.TestCase):
    def setUp(self):
        active = patch.object(worker, '_future_datetime', lambda value: value.astimezone(timezone.utc))
        active.start()
        self.addCleanup(active.stop)

    def brigantine(self, payload, title='YOGA FUSION*', now=NOW):
        with patch.object(local, 'BRIGANTINE_SHA256', sha256(payload).hexdigest()), \
             patch.object(local, 'BRIGANTINE_PROGRAMS', ((4, title),)):
            return local.parse_brigantine(payload, now=now)

    def test_full_pdf_narrative_policy_and_numeric_street_coordinates_survive(self):
        prose = 'Literal <class exercise> is preserved. ' + 'Complete participation detail. ' * 100 + 'Final condition.'
        rows = self.brigantine(pdf_bytes(prose=prose))
        self.assertEqual(len(rows), 4)
        for row in rows:
            self.assertTrue(row['description'].startswith(prose))
            self.assertTrue(row['description'].endswith(POLICY))
            self.assertGreater(len(row['description']), 3000)
            self.assertEqual(row['venue_address'], '265 42nd Street, Brigantine, NJ 08203')
            self.assertEqual((row['lat'], row['lng']), local.LOCATIONS['brigantine'][3:5])
            self.assertIn('approximate map location', row['venue_name'])
        self.assertEqual(rows[0]['starts_at'], '2026-11-16T18:00:00+00:00')
        self.assertEqual(rows[0]['ends_at'], '2026-11-16T19:00:00+00:00')

    def test_weekly_term_removes_closures_without_inventing_makeups(self):
        metadata = ('Instructor: Person Begins 10/6/26 Sr. $32.00\n'
                    '16 Sessions (8 Weeks) Tuesday & Thursday 9:00am - 10:00am Non-Sr. $80.00')
        rows = self.brigantine(pdf_bytes(metadata=metadata))
        self.assertEqual([r['starts_at'][:10] for r in rows],
                         ['2026-11-17', '2026-11-19', '2026-11-24'])
        self.assertFalse(any(r['starts_at'][:10] in ('2026-11-26', '2026-12-01') for r in rows))

    def test_explicit_art_dates_do_not_generate_missing_weekly_sessions(self):
        title = 'MIXED MEDIA*'
        metadata = ('Instructor: Person Tuesday 2:15pm - 4:15pm Sr. $96.00\n'
                    'Class Dates: Oct 13, 20, 27; Nov 10, 17; Dec 1, 8 and 15 Non-Sr. $144.00')
        rows = self.brigantine(pdf_bytes(title, metadata=metadata), title)
        self.assertEqual([r['starts_at'][:10] for r in rows],
                         ['2026-11-17', '2026-12-01', '2026-12-08', '2026-12-15'])
        self.assertEqual(rows[0]['ends_at'], '2026-11-17T21:15:00+00:00')
        self.assertTrue(all(r['category'] == 'Arts & Culture' for r in rows))

    def test_known_conflicting_classes_are_explicit_holds(self):
        for title in local.BRIGANTINE_HELD:
            with self.subTest(title=title):
                self.assertEqual(self.brigantine(pdf_bytes(title), title), [])

    def test_new_clock_conflicts_fail_instead_of_adjusting_days(self):
        metadata = ('Instructor: Person Begins 10/6/26 Sr. $32.00\n'
                    '16 Sessions (8 Weeks) Monday & Wednesday 1:00pm - 2:00pm Non-Sr. $80.00')
        with self.assertRaisesRegex(ValueError, 'clock_conflict'):
            self.brigantine(pdf_bytes(metadata=metadata))

    def test_changed_document_current_link_or_drop_in_eligibility_fail(self):
        with self.assertRaisesRegex(ValueError, 'edition_unreviewed'):
            local.parse_brigantine(pdf_bytes(), now=NOW)
        listing = '<a href="' + local.BRIGANTINE_DOCUMENT + '">Fall Brochure</a>'
        self.assertEqual(local.discover_brigantine(listing), local.BRIGANTINE_DOCUMENT)
        for changed in (listing.replace('2026', '2027'),
                        listing.replace('brigantinebeach.org', 'unreviewed.example'),
                        listing + '<a href="/winter.pdf">Winter Brochure</a>'):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, 'edition_unreviewed'):
                local.discover_brigantine(changed)
        with self.assertRaisesRegex(ValueError, 'drop_in_policy_changed'):
            self.brigantine(pdf_bytes(policy=POLICY.replace('will allow drop-ins', 'will not allow drop-ins')))
        with self.assertRaisesRegex(ValueError, 'drop_in_manifest_changed'):
            self.brigantine(pdf_bytes(title='YOGA FUSION'))

    def test_pdf_narrative_missing_or_oversized_is_rejected_not_clipped(self):
        with self.assertRaisesRegex(ValueError, 'description_limit'):
            self.brigantine(pdf_bytes(prose='x' * 12001))
        with self.assertRaisesRegex(ValueError, 'description_missing'):
            self.brigantine(pdf_bytes(prose=''))
        with self.assertRaisesRegex(ValueError, 'invalid_brigantine_pdf'):
            local.parse_brigantine(b'%PDF-' + b'x' * local.MAX_PDF, now=NOW)

    def test_run_paragraphs_stay_complete_and_unknown_ends_stay_unknown(self):
        prose = 'Literal <pace group> and ' + 'full route detail. ' * 150 + 'Last route condition.'
        rows = local.parse_njshorerun(run_html(extra=prose), now=NOW)
        self.assertEqual(len(rows), 2)
        self.assertIn(prose, rows[0]['description'])
        self.assertTrue(rows[0]['description'].endswith('Run as many miles as you like with us!'))
        self.assertTrue(rows[1]['description'].endswith('More info to come!'))
        self.assertEqual([r['starts_at'] for r in rows],
                         ['2026-11-15T13:00:00+00:00', '2026-12-12T13:00:00+00:00'])
        self.assertTrue(all(row['ends_at'] is None for row in rows))
        self.assertIn('address estimated; approximate map location', rows[0]['venue_name'])
        self.assertEqual(rows[0]['venue_address'], '1210 Wabash Avenue, Linwood, NJ 08221')
        self.assertEqual((rows[0]['lat'], rows[0]['lng']), local.LOCATIONS['linwood'][3:5])
        self.assertEqual(rows[1]['venue_address'], '825 Boardwalk, Ocean City, NJ 08226')
        self.assertEqual((rows[1]['lat'], rows[1]['lng']), local.LOCATIONS['music_pier'][3:5])

    def test_unavailable_run_is_not_published(self):
        rows = local.parse_njshorerun(run_html(extra='This run is cancelled.'), now=NOW)
        self.assertEqual(len(rows), 1)
        self.assertIn('Christmas Tree Run', rows[0]['title'])
        sold_out = run_html().replace('More info to come!', 'Sold out.')
        rows = local.parse_njshorerun(sold_out, now=NOW)
        self.assertEqual(len(rows), 1)
        self.assertIn('Linwood', rows[0]['title'])

    def test_run_clock_year_location_and_manifest_conflicts_fail_closed(self):
        changed = (
            run_html(weekday='Saturday'),
            run_html(save='Friday, December 12th'),
            run_html().replace('W Essex Ave', 'a different town'),
            run_html().replace('None this week.', 'Another race at noon.'),
            run_html().replace('<p>Race meetups:</p>', '<p>2. Another dated run.</p><p>Race meetups:</p>'),
        )
        for payload in changed:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                local.parse_njshorerun(payload, now=NOW)

    def test_full_run_description_has_no_slice_and_limit_is_an_error(self):
        with self.assertRaisesRegex(ValueError, 'description_limit'):
            local.parse_njshorerun(run_html(extra='x' * 12001), now=NOW)
        with self.assertRaisesRegex(ValueError, 'description_or_date_changed'):
            local.parse_njshorerun(run_html().replace('All Are Welcome!', ''), now=NOW)

    def test_expired_rows_become_valid_empty_without_annual_projection(self):
        after = datetime(2026, 12, 16, 23, tzinfo=timezone.utc)
        self.assertEqual(local.parse_njshorerun(run_html(), now=after), [])
        self.assertEqual(self.brigantine(pdf_bytes(), now=after), [])

    def test_source_identity_deadline_and_record_cap_prevent_partial_snapshot(self):
        source = dict(source_key=local.RUN, feed_url=local.SOURCES[local.RUN][0],
                      kind='html', platform_adapter='html', timezone=local.ZONE)
        calls = []
        rows = local.collect(source, lambda url, accept: calls.append((url, accept)) or run_html(), now=NOW)
        self.assertEqual(len(rows), 2)
        self.assertEqual(calls, [(local.SOURCES[local.RUN][0], 'text/html')])
        for field, value in (('timezone', 'UTC'), ('feed_url', 'https://unreviewed.example/'),
                             ('platform_adapter', 'jsonld')):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'unregistered'):
                local.collect(dict(source, **{field: value}), lambda *_: self.fail('unexpected fetch'))
        with self.assertRaisesRegex(ValueError, 'collection_deadline'):
            local.collect(source, lambda *_: self.fail('unexpected fetch'), deadline_at=monotonic() - 1)
        with patch.object(local, 'MAX_RECORDS', 1), self.assertRaisesRegex(ValueError, 'record_limit'):
            local.parse_njshorerun(run_html(), now=NOW)

    def test_brigantine_current_listing_and_exact_binary_use_two_requests(self):
        source = dict(source_key=local.BRIGANTINE, feed_url=local.SOURCES[local.BRIGANTINE][0],
                      kind='html', platform_adapter='html', timezone=local.ZONE)
        payload = pdf_bytes()
        calls = []
        def fetch(url, accept):
            calls.append((url, accept))
            if accept == 'text/html':
                return '<a href="' + local.BRIGANTINE_DOCUMENT + '">Fall Brochure</a>'
            return payload
        with patch.object(local, 'BRIGANTINE_SHA256', sha256(payload).hexdigest()), \
             patch.object(local, 'BRIGANTINE_PROGRAMS', ((4, 'YOGA FUSION*'),)):
            rows = local.collect(source, fetch, now=NOW)
        self.assertEqual(len(rows), 4)
        self.assertEqual(calls, [(source['feed_url'], 'text/html'), (local.BRIGANTINE_DOCUMENT, 'application/pdf')])
        self.assertEqual(local.CHECKPOINT_KEYS, set())
        self.assertTrue(local.event_url(local.RUN, local.SOURCES[local.RUN][0]))
        self.assertFalse(local.event_url(local.RUN, local.SOURCES[local.RUN][0] + '?unreviewed=1'))


if __name__ == '__main__':
    unittest.main()
