from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import unittest
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from roomquest import atlantic_city_pdf_programs as programs
from roomquest import preview_worker as worker


NOW = datetime(2026, 11, 14, 20, tzinfo=timezone.utc)


def pdf_bytes(*texts):
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({
        NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/Helvetica'), NameObject('/Encoding'): NameObject('/WinAnsiEncoding')}))
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject('/Resources')] = DictionaryObject({
            NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        lines = []
        for line in text.splitlines():
            value = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            lines.append(f'({value}) Tj T*')
        stream = DecodedStreamObject()
        stream.set_data(('BT /F1 9 Tf 12 TL 36 750 Td\n' + '\n'.join(lines) + '\nET').encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class AtlanticPdfTests(unittest.TestCase):
    def setUp(self):
        active = patch.object(worker, '_future_datetime', lambda value: value.astimezone(timezone.utc))
        active.start()
        self.addCleanup(active.stop)

    def lighthouse(self, prose='Full Moon Climb, Caroling, DJ tunes, complete final admission condition.'):
        return pdf_bytes('2026 Calendar of Events PROCEEDS BENEFIT ABSECON LIGHTHOUSE\n'
                         'Friday, December 4 Luminary Light Festival, 5pm to 7pm\n' + prose)

    def test_native_lighthouse_pdf_keeps_entire_body_and_exact_time_address(self):
        prose = 'Full Moon Climb, ' + 'Complete publisher participation details. ' * 100 + 'Final condition.'
        row, = programs.parse_lighthouse(self.lighthouse(prose), now=NOW)
        self.assertEqual(row['description'], prose)
        self.assertGreater(len(row['description']), 3500)
        self.assertEqual(row['starts_at'], '2026-12-04T22:00:00+00:00')
        self.assertEqual(row['ends_at'], '2026-12-05T00:00:00+00:00')
        self.assertEqual(row['venue_address'], '31 South Rhode Island Avenue, Atlantic City, NJ 08401')
        self.assertEqual((row['lat'], row['lng']), programs.LIGHTHOUSE_POINT)

    def test_oversized_description_and_wrong_edition_fail_instead_of_clip(self):
        with self.assertRaisesRegex(ValueError, 'description_limit'):
            programs.parse_lighthouse(self.lighthouse('Full Moon Climb, ' + 'x' * 12001), now=NOW)
        changed = pdf_bytes('2027 Calendar of Events PROCEEDS BENEFIT ABSECON LIGHTHOUSE\n'
                            'Friday, December 4 Luminary Light Festival, 5pm to 7pm Full Moon Climb.')
        with self.assertRaisesRegex(ValueError, 'edition_unreviewed'):
            programs.parse_lighthouse(changed, now=NOW)
        self.assertEqual(programs.parse_lighthouse(self.lighthouse(), now=datetime(2026,12,5,1,tzinfo=timezone.utc)), [])

    def test_reviewed_grid_uses_fetched_complete_native_narratives(self):
        fragments = [first + ' middle text with full participation rules ' + last
                     for *_, first, last in programs.OCEANSIDE_PROGRAMS]
        body = ('201 Melrose Ave - Unit 3\n' + '\n'.join(fragments)
                + '\n*Registration & Confirmation is Required for ALL Giveaways & Workshops!!*')
        payload = pdf_bytes('November 2026 calendar grid', body)
        with patch.object(programs, 'OCEANSIDE_SHA256', sha256(payload).hexdigest()):
            rows = programs.parse_oceanside(payload, now=NOW)
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(row['description'].startswith(prose) for row, prose in zip(rows, fragments)))
        self.assertTrue(all(row['description'].endswith('Workshops!!*') for row in rows))
        self.assertTrue(all(row['venue_address'] == programs.OCEANSIDE_VENUE[1] for row in rows
                            if 'thanksgiving-dinner' not in row['id']))
        estimated = next(row for row in rows if 'thanksgiving-dinner' in row['id'])
        self.assertIn('(address estimated)', estimated['venue_name'])
        self.assertEqual(estimated['venue_address'], '1535 Bacharach Boulevard, Atlantic City, NJ 08401-4485')
        self.assertIsNone(estimated['lat'])
        self.assertIsNone(estimated['lng'])
        self.assertEqual(rows[0]['starts_at'], '2026-11-16T16:30:00+00:00')
        self.assertEqual(rows[-1]['starts_at'], '2026-11-23T18:00:00+00:00')

    def test_monthly_hash_and_live_document_link_prevent_stale_grid_reuse(self):
        with self.assertRaisesRegex(ValueError, 'edition_unreviewed'):
            programs.parse_oceanside(pdf_bytes('Changed program dates'), now=NOW)
        current = ('<h2>November Calendar 2026</h2><a href="' + programs.OCEANSIDE_DOCUMENT + '">Download</a>')
        self.assertEqual(programs.discover_oceanside(current), programs.OCEANSIDE_DOCUMENT)
        for changed in (current.replace('November', 'December'),
                        current.replace('1794503710309', '1794503710310'),
                        current.replace('img1.wsimg.com', 'evil.example')):
            with self.assertRaisesRegex(ValueError, 'edition_unreviewed'):
                programs.discover_oceanside(changed)

    def test_second_center_selects_english_and_keeps_both_parent_meetings(self):
        paragraphs = list(dict.fromkeys(first + ' complete native details ' + last
                        for *_, first, last in programs.OCEANSIDE_TWO_PROGRAMS))
        body = ('3201 Atlantic Avenue, Atlantic City, NJ 08401\n' + '\n'.join(paragraphs)
                + '\n***Registration is Required for PC appointments, Giveaways & Workshops!!***')
        payload = pdf_bytes('November calendar grid', body)
        with patch.object(programs, 'OCEANSIDE_TWO_SHA256', sha256(payload).hexdigest()):
            rows = programs.parse_oceanside(payload, source_key=programs.OCEANSIDE_TWO, now=NOW)
        self.assertEqual(len(rows), 5)
        self.assertEqual(sum(row['title'] == 'Teen Speak' for row in rows), 2)
        food = next(row for row in rows if row['title'] == 'Food Distribution with JFS')
        self.assertEqual((food['starts_at'], food['ends_at']), ('2026-11-18T17:00:00+00:00', '2026-11-18T18:00:00+00:00'))
        self.assertIn('** PLEASE BRING YOUR OWN BAG **', food['description'])
        html = ('<div>Oceanside II FSC - Nov 2026 Calendar (E)<a href="'
                + programs.OCEANSIDE_TWO_DOCUMENT + '">Download</a></div>'
                '<div>Oceanside II FSC - Nov 2026 Calendar (S)<a href="https://evil.example/spanish.pdf">Download</a></div>')
        self.assertEqual(programs.discover_oceanside(html, source_key=programs.OCEANSIDE_TWO), programs.OCEANSIDE_TWO_DOCUMENT)

    def test_large_pdf_allowance_is_exact_object_and_transport_scope_only(self):
        hosts = programs.ALLOWED_HOSTS[programs.OCEANSIDE]
        self.assertEqual(worker._publisher_body_limit(programs.OCEANSIDE_DOCUMENT, 'application/pdf', hosts, True), 16000000)
        for url, accept, allowed, robots in (
            (programs.OCEANSIDE_DOCUMENT.replace('(1)', '(2)'), 'application/pdf', hosts, True),
            (programs.OCEANSIDE_DOCUMENT.replace('?ver=', '%3Fver='), 'application/pdf', hosts, True),
            (programs.OCEANSIDE_DOCUMENT.replace('/downloads/', '%2Fdownloads%2F'), 'application/pdf', hosts, True),
            (programs.OCEANSIDE_DOCUMENT, 'text/html', hosts, True),
            (programs.OCEANSIDE_DOCUMENT, 'application/pdf', ('img1.wsimg.com',), True),
            (programs.OCEANSIDE_DOCUMENT, 'application/pdf', hosts, False),
            (programs.LIGHTHOUSE_DOCUMENT, 'application/pdf', programs.ALLOWED_HOSTS[programs.LIGHTHOUSE], True),
        ):
            self.assertEqual(worker._publisher_body_limit(url, accept, allowed, robots), worker.MAX_BODY)

    def test_source_identity_and_binary_size_are_bounded(self):
        with self.assertRaisesRegex(ValueError, 'unregistered'):
            programs.collect(dict(source_key=programs.OCEANSIDE, feed_url='https://evil.example',
                                  kind='html', platform_adapter='html', timezone=programs.ZONE), lambda *_: None)
        with self.assertRaisesRegex(ValueError, 'invalid_atlantic_pdf_document'):
            programs.parse_lighthouse(b'%PDF-' + b'x' * 1000000, now=NOW)


if __name__ == '__main__':
    unittest.main()
