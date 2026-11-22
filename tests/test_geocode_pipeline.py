"""Request-budget admission must defer optional work before claiming it."""
from contextlib import ExitStack
import json
import os
import unittest
from unittest.mock import patch

from roomquest import event_media, forward_geocoder, venue_resolver


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class PipelineTests(unittest.TestCase):
    def run_phase(self, phase, *, geocode_seconds=0, capability_seconds=0,
                  dedicated=False, geocode_error=None, optional_error=None):
        clock, order = Clock(), []
        geocode_result = {'claimed': 2, 'resolved': 1, 'failed': 1}

        def geocode(**kwargs):
            order.append('geocoder')
            clock.advance(geocode_seconds)
            if geocode_error:
                raise geocode_error
            return geocode_result

        def capability():
            order.append('capability')
            clock.advance(capability_seconds)
            return dedicated

        def optional(name, completion_seconds):
            def work(*, deadline_seconds):
                order.append(name)
                # Exercise the entire allowance, including completion RPCs.
                clock.advance(deadline_seconds + completion_seconds)
                if optional_error:
                    raise optional_error
                return {'claimed': 1, 'resolved': 1}
            return work

        with ExitStack() as stack:
            date = stack.enter_context(patch('datetime.datetime'))
            date.now.return_value.timestamp.return_value = phase * 60
            stack.enter_context(patch.object(venue_resolver, 'monotonic', clock))
            geocode_call = stack.enter_context(patch.object(
                forward_geocoder, 'run_batch', side_effect=geocode))
            capability_call = stack.enter_context(patch.object(
                event_media, 'dedicated_media_ready', side_effect=capability))
            venues = stack.enter_context(patch.object(
                venue_resolver, 'run_batch', side_effect=optional('venues', 11)))
            photos = stack.enter_context(patch.object(
                event_media, 'run_batch', side_effect=optional('photos', 12)))
            result = venue_resolver.run_pipeline()
        return result, clock, order, geocode_call, capability_call, venues, photos

    def test_primary_only_phase_retains_geocoder_budget_and_result(self):
        result, clock, order, geocoder, capability, venues, photos = self.run_phase(
            0, geocode_seconds=45)
        geocoder.assert_called_once_with(deadline_seconds=45)
        self.assertEqual(result, {'phase': 'geocoder',
                                 'geocoder': {'claimed': 2, 'resolved': 1, 'failed': 1}})
        self.assertEqual(order, ['geocoder'])
        capability.assert_not_called()
        venues.assert_not_called()
        photos.assert_not_called()

    def test_address_evidence_runs_after_geocoding_with_its_existing_budget(self):
        result, clock, order, geocoder, capability, venues, photos = self.run_phase(
            1, geocode_seconds=10)
        geocoder.assert_called_once_with(deadline_seconds=45)
        venues.assert_called_once_with(deadline_seconds=15)
        self.assertEqual(order, ['geocoder', 'venues'])
        self.assertEqual(result['geocoder']['resolved'], 1)
        self.assertEqual(result['venues']['resolved'], 1)
        self.assertLessEqual(clock.now, 155)
        capability.assert_not_called()
        photos.assert_not_called()

    def test_address_evidence_requires_time_for_lookup_and_completion(self):
        for elapsed, admitted in ((29, True), (29.001, False), (45, False)):
            with self.subTest(elapsed=elapsed):
                result, clock, _, _, _, venues, _ = self.run_phase(
                    1, geocode_seconds=elapsed)
                if admitted:
                    venues.assert_called_once_with(deadline_seconds=15)
                    self.assertLessEqual(clock.now, 155)
                else:
                    venues.assert_not_called()
                    self.assertEqual(result['venues'], {'stop_reason': 'deadline'})

    def test_legacy_media_budget_leaves_time_for_every_completion_rpc(self):
        result, clock, order, _, capability, venues, photos = self.run_phase(
            2, geocode_seconds=3, capability_seconds=2)
        photos.assert_called_once_with(deadline_seconds=38)
        self.assertEqual(order, ['geocoder', 'capability', 'photos'])
        self.assertEqual(result['photos']['resolved'], 1)
        self.assertEqual(clock.now, 155)  # Includes all three receipt RPCs.
        capability.assert_called_once_with()
        venues.assert_not_called()

    def test_fast_legacy_media_retains_its_existing_maximum_budget(self):
        result, clock, _, _, _, _, photos = self.run_phase(
            2, geocode_seconds=1, capability_seconds=1)
        photos.assert_called_once_with(deadline_seconds=38)
        self.assertLessEqual(clock.now, 155)
        self.assertEqual(result['geocoder']['claimed'], 2)

    def test_photo_admission_preserves_existing_work_allowance(self):
        for elapsed, admitted in ((5, True), (5.001, False), (45, False)):
            with self.subTest(elapsed=elapsed):
                result, clock, _, _, _, _, photos = self.run_phase(
                    2, geocode_seconds=elapsed)
                if admitted:
                    photos.assert_called_once_with(deadline_seconds=38)
                    self.assertLessEqual(clock.now, 155)
                else:
                    photos.assert_not_called()
                    self.assertEqual(result['photos'], {'stop_reason': 'deadline'})

    def test_slow_capability_probe_can_exhaust_optional_admission_budget(self):
        result, _, order, _, capability, _, photos = self.run_phase(
            2, geocode_seconds=2, capability_seconds=4)
        self.assertEqual(order, ['geocoder', 'capability'])
        capability.assert_called_once_with()
        photos.assert_not_called()
        self.assertEqual(result['photos'], {'stop_reason': 'deadline'})

    def test_dedicated_media_skips_compatibility_work_even_after_busy_geocoding(self):
        result, _, order, _, capability, venues, photos = self.run_phase(
            2, geocode_seconds=45, dedicated=True)
        self.assertEqual(order, ['geocoder', 'capability'])
        capability.assert_called_once_with()
        venues.assert_not_called()
        photos.assert_not_called()
        self.assertEqual(result['photos'], {'stop_reason': 'dedicated_worker'})

    def test_no_capability_rpc_when_even_its_timeout_will_not_fit(self):
        for elapsed in (51.001, 55, 65):
            with self.subTest(elapsed=elapsed):
                result, _, order, _, capability, venues, photos = self.run_phase(
                    2, geocode_seconds=elapsed)
                self.assertEqual(order, ['geocoder'])
                capability.assert_not_called()
                venues.assert_not_called()
                photos.assert_not_called()
                self.assertEqual(result['photos'], {'stop_reason': 'deadline'})

    def test_geocoder_failure_does_not_reset_elapsed_time_or_block_eligible_work(self):
        for elapsed, admitted in ((1, True), (45, False)):
            with self.subTest(elapsed=elapsed), patch('builtins.print'):
                result, _, _, _, _, venues, _ = self.run_phase(
                    1, geocode_seconds=elapsed, geocode_error=RuntimeError('fixture'))
                self.assertEqual(result['geocoder'], {'stop_reason': 'stage_failed'})
                self.assertEqual(venues.call_count, int(admitted))
                if not admitted:
                    self.assertEqual(result['venues'], {'stop_reason': 'deadline'})

    def test_optional_failure_does_not_discard_successful_geocoding(self):
        for phase, key in ((1, 'venues'), (2, 'photos')):
            with self.subTest(phase=phase):
                result, _, _, _, _, _, _ = self.run_phase(
                    phase, optional_error=RuntimeError('fixture'))
                self.assertEqual(result['geocoder']['resolved'], 1)
                self.assertEqual(result[key], {'stop_reason': 'stage_failed'})

    def test_late_real_workers_do_not_claim_or_write_negative_results(self):
        for phase, key in ((1, 'venues'), (2, 'photos')):
            with self.subTest(phase=phase), ExitStack() as stack:
                clock = Clock()
                date = stack.enter_context(patch('datetime.datetime'))
                date.now.return_value.timestamp.return_value = phase * 60
                stack.enter_context(patch.dict(os.environ, {
                    'VERCEL_ENV': 'production', 'FORWARD_GEOCODER_ENABLED': 'true'}))
                stack.enter_context(patch.object(venue_resolver, 'monotonic', clock))
                stack.enter_context(patch.object(forward_geocoder, 'run_batch',
                    side_effect=lambda **_: clock.advance(45) or {'claimed': 1}))
                venue_rpc = stack.enter_context(patch.object(venue_resolver, 'rpc'))
                media_rpc = stack.enter_context(patch.object(event_media, 'rpc',
                                                             return_value={'dedicated_ready': False}))
                result = venue_resolver.run_pipeline()
                venue_rpc.assert_not_called()
                if phase == 2:
                    media_rpc.assert_called_once_with('capabilities')
                else:
                    media_rpc.assert_not_called()
                self.assertEqual(result[key], {'stop_reason': 'deadline'})

    def test_slow_photo_lookup_keeps_full_budget_or_remains_unclaimed(self):
        claim = {'media_key': 'fixture', 'lease_id': 'fixture-lease',
                 'title': 'Community concert',
                 'event_url': 'https://venue.example.org/event/concert'}
        photo = 'https://cdn.example.org/concert-poster.jpg'
        html = '<h1>Community concert</h1><meta property="og:image" content="' + photo + '">'
        actual_extract, actual_resolve = event_media.extract_photo, event_media.resolve_photo
        for elapsed, admitted in ((3, True), (17, False)):
            with self.subTest(elapsed=elapsed), ExitStack() as stack:
                clock, actions, probes = Clock(), [], []

                def database(action, payload=None):
                    actions.append(action)
                    if action == 'capabilities':
                        return {'dedicated_ready': False}
                    clock.advance(4)
                    return [claim] if action == 'claim' else {'recorded': True}

                def fetch(_):
                    clock.advance(13)  # Fetch deadline plus the final read tail.
                    return html

                def extract(*args):
                    result = actual_extract(*args)
                    clock.advance(1)  # Parsing/dispatch has no hard time bound.
                    return result

                def probe(url):
                    probes.append(url)
                    clock.advance(1)
                    return url, 'image/jpeg'

                def resolve(value, *, deadline):
                    return actual_resolve(value, fetcher=fetch, probe=probe,
                                          clock=clock, deadline=deadline)

                date = stack.enter_context(patch('datetime.datetime'))
                date.now.return_value.timestamp.return_value = 120
                stack.enter_context(patch.dict(os.environ, {
                    'VERCEL_ENV': 'production', 'FORWARD_GEOCODER_ENABLED': 'true'}))
                stack.enter_context(patch.object(venue_resolver, 'monotonic', clock))
                stack.enter_context(patch.object(event_media, 'monotonic', clock))
                stack.enter_context(patch.object(forward_geocoder, 'run_batch',
                    side_effect=lambda **_: clock.advance(elapsed) or {'claimed': 1}))
                stack.enter_context(patch.object(event_media, 'rpc', side_effect=database))
                stack.enter_context(patch.object(event_media, 'extract_photo', side_effect=extract))
                stack.enter_context(patch.object(event_media, 'resolve_photo', side_effect=resolve))
                result = venue_resolver.run_pipeline()
                if admitted:
                    self.assertEqual(result['photos']['ready'], 1)
                    self.assertEqual(actions, ['capabilities', 'claim', 'submit'])
                    self.assertEqual(probes, [photo])
                else:
                    # A shortened 26s allowance would reach the real resolver's
                    # no-image guard after 4s claim + 13s fetch + 1s parse.
                    self.assertEqual(result['photos'], {'stop_reason': 'deadline'})
                    self.assertEqual(actions, ['capabilities'])
                    self.assertEqual(probes, [])
                self.assertNotIn('fail', actions)

    def test_address_lookup_and_its_final_read_tail_fit_or_remain_unclaimed(self):
        claim = {'venue_key': 'fixture', 'lease_id': 'fixture-lease',
                 'venue_name': 'Community Gallery', 'event_title': 'Exhibition',
                 'event_url': 'https://venue.example.org/event/exhibit'}
        place = {'@type': 'Place', 'name': 'Community Gallery', 'address': {
            '@type': 'PostalAddress', 'streetAddress': '100 Main Street',
            'addressLocality': 'Raleigh', 'addressRegion': 'NC', 'addressCountry': 'US'}}
        actual_resolve = venue_resolver.resolve
        for elapsed, admitted in ((29, True), (34, False)):
            with self.subTest(elapsed=elapsed), ExitStack() as stack:
                clock, actions, fetched = Clock(), [], []

                def database(action, payload):
                    actions.append(action)
                    clock.advance(4)
                    return [claim] if action == 'claim' else {'recorded': True}

                def fetch(url):
                    fetched.append(url)
                    clock.advance(4.9 if len(fetched) == 1 else 13)
                    return ('<a href="/gallery">Community Gallery</a>' if len(fetched) == 1
                            else '<script type="application/ld+json">' + json.dumps(place) + '</script>')

                def resolve(value, *, deadline):
                    return actual_resolve(value, fetcher=fetch, clock=clock, deadline=deadline)

                date = stack.enter_context(patch('datetime.datetime'))
                date.now.return_value.timestamp.return_value = 60
                stack.enter_context(patch.dict(os.environ, {
                    'VERCEL_ENV': 'production', 'FORWARD_GEOCODER_ENABLED': 'true'}))
                stack.enter_context(patch.object(venue_resolver, 'monotonic', clock))
                stack.enter_context(patch.object(forward_geocoder, 'run_batch',
                    side_effect=lambda **_: clock.advance(elapsed) or {'claimed': 1}))
                stack.enter_context(patch.object(venue_resolver, 'rpc', side_effect=database))
                stack.enter_context(patch.object(venue_resolver, 'resolve', side_effect=resolve))
                result = venue_resolver.run_pipeline()
                if admitted:
                    self.assertEqual(result['venues']['resolved'], 1)
                    self.assertEqual(actions, ['claim', 'submit'])
                    self.assertEqual(len(fetched), 2)
                    self.assertAlmostEqual(clock.now, 154.9)
                else:
                    self.assertEqual(result['venues'], {'stop_reason': 'deadline'})
                    self.assertEqual(actions, [])
                    self.assertEqual(fetched, [])


if __name__ == '__main__':
    unittest.main()
