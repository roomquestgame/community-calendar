"""Reviewed Inland PDF dates, entire native descriptions, and exact venue evidence."""
from datetime import datetime, timezone
from hashlib import sha256
import unittest
from unittest.mock import patch

from roomquest import atlantic_city_remaining_inland as inland
from roomquest import preview_worker as worker

NOW = datetime(2026, 11, 15, tzinfo=timezone.utc)
BLOB = b'%PDF-reviewed-test-edition'
REGISTRATION = inland.REGISTRATION_PREFIX + ' Register for events by visiting Eventbrite or calling 609.569.0376.'


def source():
    url, kind, adapter = inland.SOURCES[inland.KEY]
    return dict(source_key=inland.KEY, feed_url=url, kind=kind, platform_adapter=adapter, timezone=inland.ZONE)


def listing():
    return ('<h1>Welcome to the Inland Family Success Center Neighborhood Gathering Place</h1>'
            '<p>All services and workshops are free.</p><p>' + REGISTRATION + '</p>'
            '<p>' + inland.OLD_RELOCATION_NOTICE + '</p>'
            '<p>Visit Inland Family Success Center<br>3050 Spruce Avenue<br>Egg Harbor Township, NJ 08234</p>'
            '<a href="' + inland.DOCUMENT + '">' + inland.DOCUMENT_LABEL + '</a>'
            '<a href="spanish.pdf">Noviembre 2026 Spanish Calendar</a>')


def pages(extra='Complete native details and participation instructions. '):
    paragraphs = [first + ' ' + extra + last for *_, first, last in inland.PROGRAMS]
    return [' '.join(row[5] for row in inland.PROGRAMS) + ' 26 *Center Closed* Happy Thanksgiving! 27 *Center Closed* Black Friday!',
            ' '.join(paragraphs)], paragraphs


class InlandTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(worker, '_future_datetime', lambda dt: dt.astimezone(timezone.utc))
        patcher.start(); self.addCleanup(patcher.stop)

    def parse(self, texts=None, *, now=NOW, registration=REGISTRATION):
        if texts is None:
            texts, _ = pages()
        with patch.object(inland, 'DOCUMENT_SHA256', sha256(BLOB).hexdigest()), patch.object(inland, '_pages', return_value=texts):
            return inland.parse_document(BLOB, registration_text=registration, now=now)

    def test_complete_native_bodies_and_registration_survive_without_reparse(self):
        texts, paragraphs = pages('Full publisher prose. ' * 120 + 'Literal <bring a mat> survives. Final native detail. ')
        rows = self.parse(texts)
        self.assertEqual(len(rows), 5)
        for row, paragraph in zip(rows, paragraphs):
            self.assertEqual(row['description'], paragraph + '\n\n' + inland.PUBLIC_POLICY + '\n' + REGISTRATION)
            self.assertGreater(len(row['description']), 2000)
            self.assertIn('<bring a mat>', row['description'])
            self.assertEqual(row['venue_address'], '3050 Spruce Avenue, Egg Harbor Township, NJ 08234')
            self.assertEqual((row['lat'], row['lng']), inland.POINT)

    def test_all_five_reviewed_date_cells_and_known_ends_are_exact(self):
        rows = self.parse()
        self.assertEqual([(r['starts_at'], r['ends_at']) for r in rows], [
            ('2026-11-16T22:00:00+00:00', '2026-11-17T00:00:00+00:00'),
            ('2026-11-21T16:00:00+00:00', '2026-11-21T17:00:00+00:00'),
            ('2026-11-23T22:00:00+00:00', '2026-11-24T00:00:00+00:00'),
            ('2026-11-24T21:00:00+00:00', '2026-11-24T22:00:00+00:00'),
            ('2026-11-30T21:30:00+00:00', '2026-11-30T23:00:00+00:00'),
        ])
        self.assertNotIn('2026-11-26', ' '.join(r['starts_at'] for r in rows))

    def test_changed_pdf_or_oversized_document_fails_before_parsing(self):
        for blob in (b'changed PDF', BLOB + b'x', b'x' * (inland.MAX_DOCUMENT_BYTES + 1)):
            with self.subTest(bytes=len(blob)), patch.object(inland, '_pages') as parse:
                with self.assertRaisesRegex(ValueError, 'edition_unreviewed'):
                    inland.parse_document(blob, registration_text=REGISTRATION, now=NOW)
                parse.assert_not_called()

    def test_new_month_missing_or_ambiguous_english_link_is_rejected(self):
        for html in (listing().replace('November 2026 English Calendar', 'December 2026 English Calendar'),
                     listing().replace(inland.DOCUMENT, 'https://other.example/calendar.pdf'),
                     listing() + '<a href="another.pdf">November 2026 English Calendar</a>'):
            with self.subTest(html=html[-150:]), self.assertRaisesRegex(ValueError, 'edition_unreviewed'):
                inland.discover_document(html)

    def test_current_english_link_ignores_spanish_and_preserves_registration(self):
        self.assertEqual(inland.discover_document(listing()), (inland.DOCUMENT, REGISTRATION))

    def test_changed_or_missing_participation_instructions_are_rejected(self):
        for html in (listing().replace(REGISTRATION, ''), listing().replace('609.569.0376', '609.000.0000'),
                     listing().replace('All services and workshops are free.', 'Members only.'),
                     listing() + '<p>' + REGISTRATION + '</p>'):
            with self.assertRaisesRegex(ValueError, 'registration_changed'):
                inland.discover_document(html)

    def test_a_new_relocation_notice_or_unreviewed_contact_address_is_rejected(self):
        for html in (listing().replace('beginning in June', 'beginning in November'),
                     listing().replace('<br>3050 Spruce Avenue', '<br>3073 English Creek Avenue')):
            with self.assertRaisesRegex(ValueError, 'venue_context_changed'):
                inland.discover_document(html)
        self.assertEqual(inland.discover_document(listing().replace('<p>' + inland.OLD_RELOCATION_NOTICE + '</p>', ''))[0], inland.DOCUMENT)

    def test_native_grid_change_cannot_keep_the_reviewed_date_mapping(self):
        texts, _ = pages(); texts[0] = texts[0].replace('5:00pm-7:00pm', '6:00pm-7:00pm', 1)
        with self.assertRaisesRegex(ValueError, 'program_manifest_changed'): self.parse(texts)

    def test_missing_or_duplicate_paragraph_never_returns_a_partial_snapshot(self):
        texts, paragraphs = pages()
        for text in (texts[1].replace(paragraphs[3], ''), texts[1] + ' ' + paragraphs[3]):
            with self.assertRaisesRegex(ValueError, 'program_description_changed'):
                self.parse([texts[0], text])

    def test_description_over_12000_is_rejected_not_clipped(self):
        texts, _ = pages('x' * 12001)
        with self.assertRaisesRegex(ValueError, 'description_limit'): self.parse(texts)

    def test_past_occurrences_are_removed_and_no_next_month_is_projected(self):
        self.assertEqual(len(self.parse(now=datetime(2026, 11, 16, 23, tzinfo=timezone.utc))), 5)
        self.assertEqual(len(self.parse(now=datetime(2026, 11, 17, tzinfo=timezone.utc))), 4)
        self.assertEqual(self.parse(now=datetime(2026, 12, 1, tzinfo=timezone.utc)), [])
        self.assertEqual(self.parse(now=datetime(2026, 9, 1, tzinfo=timezone.utc)), [])

    def test_source_identity_deadline_and_event_url_are_exact(self):
        for field, value in [('source_key', 'another_source'), ('feed_url', inland.SOURCES[inland.KEY][0] + '?x=1'),
                             ('kind', 'ical'), ('platform_adapter', 'wordpress'), ('timezone', 'UTC')]:
            bad = source(); bad[field] = value
            with self.assertRaisesRegex(ValueError, 'unregistered'): inland.collect(bad, None)
        with self.assertRaisesRegex(ValueError, 'collection_deadline'): inland.collect(source(), None, deadline_at=0)
        self.assertTrue(inland.event_url(inland.KEY, inland.SOURCES[inland.KEY][0]))
        self.assertFalse(inland.event_url(inland.KEY, inland.DOCUMENT))
        self.assertIsNone(inland.reviewed_venue_location(inland.KEY, inland.VENUE[0], '3073 English Creek Avenue'))

    def test_collector_uses_only_the_two_guarded_callback_requests(self):
        texts, _ = pages(); calls = []
        def fetch(url, accept):
            calls.append((url, accept))
            return listing() if accept == 'text/html' else BLOB
        with patch.object(inland, 'DOCUMENT_SHA256', sha256(BLOB).hexdigest()), patch.object(inland, '_pages', return_value=texts):
            self.assertEqual(len(inland.collect(source(), fetch, now=NOW)), 5)
        self.assertEqual(calls, [(inland.SOURCES[inland.KEY][0], 'text/html'), (inland.DOCUMENT, 'application/pdf')])


if __name__ == '__main__':
    unittest.main()
