import unittest
import ast
import json
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit
import re
import sys
from types import SimpleNamespace
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

from roomquest.collection_window import (
    claimed_window, collection_scope, collection_window, explicit_window,
    localist_dates, recurrence_start,
)


def claim(start="2027-01-20T00:00:00+00:00"):
    end = datetime.fromisoformat(start) + timedelta(days=60)
    return {"collection_window": {"version": 1, "start": start, "end": end.isoformat()}}


class CollectionWindowTests(unittest.TestCase):
    def test_actual_wordpress_request_uses_selected_window(self):
        # Isolate unrelated source-specific adapters; execute the real request
        # builder and stop at the network boundary, before parsing any response.
        unrelated = SimpleNamespace(KEY="unrelated", URL="https://unrelated.example", ZONE="UTC", ROOT="https://unrelated.example")
        modules = {"roomquest.event_description": SimpleNamespace(MAX_EVENT_DESCRIPTION_CHARACTERS=10000),
                   "roomquest.registered_native_content": SimpleNamespace(enabled=lambda *args, **kwargs: False),
                   "roomquest.mapsee_adapter": SimpleNamespace(TRIBE_UTC_DEFAULT_ZONES={}, parse_tribe=lambda *args, **kwargs: [], profiles=lambda: {}),
                   **{"roomquest."+name: unrelated for name in
                      ("richmond_performances", "ncma_calendar", "hurrdat_calendar", "jpb_basketball")}}
        urls = []
        class RequestCaptured(Exception):
            pass
        def fetch(url, accept):
            urls.append(url)
            raise RequestCaptured()
        with patch.dict(sys.modules, modules):
            namespace = {"__name__": "wordpress_request_test"}
            exec(compile(Path("roomquest/wordpress_adapter.py").read_text(), "wordpress_adapter.py", "exec"), namespace)
            source = {"source_key": "request_test", "feed_url": "https://events.example.org/wp-json/tribe/events/v1/events"}
            with collection_scope(claim()), self.assertRaises(RequestCaptured):
                namespace["collect"](source, fetch)
        query = parse_qs(urlsplit(urls.pop()).query)
        self.assertEqual(query, {"start_date": ["2027-01-20"], "end_date": ["2027-03-21"],
                                 "per_page": ["100"], "page": ["1"]})

    def test_actual_localist_request_keeps_venue_and_adds_future_start(self):
        module = ast.parse(Path("roomquest/localist_registration.py").read_text())
        functions = [n for n in module.body if isinstance(n, ast.FunctionDef)]
        namespace = {"json": json, "re": re, "parse_qsl": parse_qsl, "urlencode": urlencode,
                     "urlsplit": urlsplit, "urlunsplit": urlunsplit, "MAX_PAGES": 5,
                     "MAX_RECORDS": 500, "localist_dates": localist_dates,
                     "parse_localist": lambda data, **kwargs: []}
        exec(compile(ast.Module(body=functions, type_ignores=[]), "localist_registration.py", "exec"), namespace)
        urls = []
        def fetch(url, accept):
            urls.append(url)
            return json.dumps({"page": {"current": 1, "total": 0, "total_items": 0}, "events": []})
        url = "https://calendar.example.org/api/2/events?venue_id=123"
        with collection_scope(claim()):
            self.assertEqual(namespace["collect"](url, fetch), [])
        query = parse_qs(urlsplit(urls.pop()).query)
        self.assertEqual(query, {"venue_id": ["123"], "start": ["2027-01-20"],
                                 "days": ["60"], "page": ["1"], "pp": ["50"]})
        namespace["collect"](url, fetch)
        self.assertNotIn("start", parse_qs(urlsplit(urls.pop()).query))

    def test_shared_event_filter_accepts_only_requested_window(self):
        # Execute the production function without importing unrelated collectors.
        module = ast.parse(Path("roomquest/preview_worker.py").read_text())
        function = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == "_future_datetime")
        namespace = {"datetime": datetime, "timezone": timezone, "collection_window": collection_window}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "preview_worker.py", "exec"), namespace)
        filter_date = namespace["_future_datetime"]
        with collection_scope(claim()):
            self.assertIsNone(filter_date(datetime(2027, 1, 19, tzinfo=timezone.utc)))
            self.assertEqual(filter_date(datetime(2027, 2, 11, tzinfo=timezone.utc)).month, 2)
            self.assertIsNotNone(filter_date(datetime(2027, 3, 20, 23, 59, tzinfo=timezone.utc)))
            self.assertIsNone(filter_date(datetime(2027, 3, 21, tzinfo=timezone.utc)))
            self.assertIsNone(filter_date(datetime(2027, 2, 11)))

    def test_recurring_feed_expands_future_occurrences(self):
        from scripts.combine_ics import expand_rrules
        from icalendar import Calendar
        payload = "\r\n".join([
            "BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT", "UID:weekly-poker",
            "DTSTART:20261125T230000Z", "DTEND:20261126T010000Z",
            "RRULE:FREQ=WEEKLY;BYDAY=WE", "SUMMARY:Weekly Poker Tournament",
            "END:VEVENT", "END:VCALENDAR", "",
        ])
        with collection_scope(claim()):
            rows = expand_rrules(payload, window_days=60, window_start=recurrence_start())
        self.assertIsNotNone(rows)
        dates = [Calendar.from_ical("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n" + row
                 + "\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n").walk("VEVENT")[0].decoded("DTSTART") for row in rows]
        self.assertEqual(len(dates), 9)
        self.assertEqual(min(dates).date().isoformat(), "2027-01-20")
        self.assertEqual(max(dates).date().isoformat(), "2027-03-17")
        self.assertEqual(len([d for d in dates if d < datetime(2027, 2, 12, tzinfo=timezone.utc)]), 4)

    def test_ordinary_window_uses_real_clock(self):
        now = datetime(2026, 11, 27, 15, 30, tzinfo=timezone.utc)
        self.assertEqual(collection_window(now).start, now)
        self.assertEqual(collection_window(now).end, now + timedelta(days=60))
        self.assertIsNone(recurrence_start())
        self.assertEqual(localist_dates(), {"days": 60})

    def test_owner_range_crossing_horizon_anchors_selected_start(self):
        now = datetime(2026, 11, 27, tzinfo=timezone.utc)
        with collection_scope(claim()):
            window = collection_window(now)
            self.assertEqual(window.start.isoformat(), "2027-01-20T00:00:00+00:00")
            self.assertEqual(window.end.isoformat(), "2027-03-21T00:00:00+00:00")
            self.assertEqual(recurrence_start(), window.start)
            self.assertEqual(localist_dates(), {"start": "2027-01-20", "days": 60})
        self.assertIsNone(explicit_window())

    def test_explicit_offset_is_normalized_without_changing_instant(self):
        with collection_scope(claim("2027-01-20T00:00:00-05:00")):
            self.assertEqual(collection_window().start.hour, 5)
            self.assertEqual(collection_window().end - collection_window().start, timedelta(days=60))

    def test_scope_resets_after_error(self):
        with self.assertRaises(RuntimeError):
            with collection_scope(claim()):
                raise RuntimeError("provider failed")
        self.assertIsNone(explicit_window())

    def test_nested_ordinary_claim_does_not_inherit_future_scope(self):
        with collection_scope(claim()):
            expected = explicit_window()
            with collection_scope({}):
                self.assertIsNone(explicit_window())
            self.assertEqual(explicit_window(), expected)

    def test_concurrent_workers_are_isolated(self):
        barrier = Barrier(2)
        def run(source):
            with collection_scope(source):
                barrier.wait(timeout=3)
                return recurrence_start()
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(run, claim()), pool.submit(run, {})
            self.assertEqual(a.result().year, 2027)
            self.assertIsNone(b.result())
        self.assertIsNone(explicit_window())

    def test_invalid_contracts_fail_closed(self):
        valid = claim()["collection_window"]
        for invalid in [True, {}, {**valid, "version": True}, {**valid, "version": 2},
                        {**valid, "start": "2027-01-20"},
                        {**valid, "start": "2027-02-30T00:00:00Z"},
                        {**valid, "end": "2028-03-21T00:00:00Z"},
                        {**valid, "end": valid["start"]},
                        {**valid, "extra": "unverified"}]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                claimed_window({"collection_window": invalid})


if __name__ == "__main__":
    unittest.main()
