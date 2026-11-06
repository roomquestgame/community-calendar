#!/usr/bin/env python3
"""Read-only verification of the three exact EVE-41 publisher sources.

Only preview_source is called: no database authentication, source claims,
staging, demand, publication, source registration or image probes. Publisher
facts and bounded diagnostic codes are the only artifact content.
"""
from datetime import datetime, timezone
from contextlib import contextmanager
import argparse
import json
from pathlib import Path
import re
import sys
from time import monotonic
from urllib.error import HTTPError

from bs4 import BeautifulSoup, Comment

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from roomquest import clarksville_tourism, coopers_landing, good_shepherd, preview_worker

SOURCES = (
    ('clarksville_tourism_va', clarksville_tourism.CALENDAR),
    ('coopers_landing_clarksville_va', coopers_landing.CALENDAR),
    ('good_shepherd_food_pantry_south_hill_va', good_shepherd.CALENDAR),
)
PER_SOURCE_SECONDS = 41
OVERALL_SECONDS = 135
MAX_RECORDS = 500
MAX_DIAGNOSTIC_INPUT = 2_000_000
MAX_DIAGNOSTIC_MARKUP = 160_000


def _http_error_status(error):
    """Observe only a bounded cause chain; never serialize exception contents."""
    seen = set()
    for _ in range(6):
        if error is None or id(error) in seen:
            break
        seen.add(id(error))
        if isinstance(error, HTTPError) and isinstance(error.code, int):
            return error.code if 100 <= error.code <= 599 else None
        error = error.__cause__
    return None


def _public_calendar_markup(calendar, placeholder_id, public_tokens=()):
    """Keep the rendered grid, with no active content, links or public tokens.

    This is diagnostic evidence, never parser input. The original response is
    returned unchanged to the collector. Unrelated parish event contents are
    removed while retaining their grid cells and event-count structure.
    """
    calendar_id = calendar.get('id', '')
    label = 'CALENDAR_PLACEHOLDER' if calendar_id == placeholder_id else 'CALENDAR_RENDERED'
    copy = BeautifulSoup(str(calendar), 'html.parser')
    for node in copy.select('script,style,template,noscript,form,input,textarea,button,iframe,object,embed,svg,img'):
        node.decompose()
    for node in copy.find_all(string=lambda value: isinstance(value, Comment)):
        node.extract()
    for event in copy.select('li.event'):
        title = event.select_one('.title')
        if title is None or 'food pantry' not in title.get_text(' ', strip=True).casefold():
            event.clear()
            event.string = '[outside pantry scope]'
    allowed_classes = {
        'ics-calendar', 'layout-month', 'combinemultiday', 'stickymonths',
        'ics-calendar-select', 'ics-calendar-label', 'ics-calendar-month-wrapper',
        'ics-calendar-month-grid', 'events', 'event', 'day', 'phone_only',
        'title', 'time', 'end_time', 'descloc', 'eventdesc', 'eventloc',
        'past', 'present', 'future', 'today', 'empty', 'all-day', 'multiday',
        'screen-reader-text', 'screen_reader_text', 'pagination',
    }
    for tag in copy.find_all(True):
        clean = {}
        for key, value in tag.attrs.items():
            if key == 'class':
                classes = [item for item in value if item in allowed_classes
                           or re.fullmatch(r'(?:d_\d{2}|dow_[0-6])', item)]
                if classes:
                    clean[key] = classes
            elif key in ('id', 'aria-labelledby', 'for'):
                if isinstance(value, str) and re.fullmatch(re.escape(calendar_id) + r'(?:-[a-z0-9-]{1,24})?', value):
                    clean[key] = label + value[len(calendar_id):]
                else:
                    clean[key] = 'UNREVIEWED_ID'
            elif key in ('data-this-month', 'data-year-month', 'value'):
                if isinstance(value, str) and re.fullmatch(r'20\d{2}(?:0[1-9]|1[0-2])', value):
                    clean[key] = value
            elif key in ('data-dow', 'data-events-count', 'data-feed-key', 'data-feed-keys'):
                if isinstance(value, str) and re.fullmatch(r'[0-9, ]{0,40}', value):
                    clean[key] = value
            elif key == 'rel' and 'next' in value:
                clean[key] = ['next']
            elif key == 'data-next-page':
                clean[key] = '[PRESENT]'
        tag.attrs = clean
    for node in copy.find_all(string=True):
        if not str(node).strip():
            node.extract()
    markup = str(copy)
    for token in public_tokens:
        if isinstance(token, str) and token:
            markup = markup.replace(token, '[REDACTED_PUBLIC_TOKEN]')
    return markup[:MAX_DIAGNOSTIC_MARKUP], len(markup) > MAX_DIAGNOSTIC_MARKUP


@contextmanager
def _observe_existing_transport(source_key, receipt):
    """Observe the exact existing calls, with no added requests or guard changes."""
    original_fetch = preview_worker.fetch_publisher
    original_render = preview_worker.render_good_shepherd_calendar
    observation = {}
    placeholder_id = None

    def observe_error(error):
        observation['transport_error_type'] = type(error).__name__
        status = _http_error_status(error)
        if status is not None:
            observation['caused_by_http_status'] = status

    def fetch(url, accept, **kwargs):
        nonlocal placeholder_id
        try:
            payload = original_fetch(url, accept, **kwargs)
        except Exception as error:
            observe_error(error)
            raise
        if source_key == good_shepherd.SOURCE_KEY and url == good_shepherd.CALENDAR:
            observation['calendar_get_calls'] = observation.get('calendar_get_calls', 0) + 1
            try:
                if not isinstance(payload, str) or len(payload) > MAX_DIAGNOSTIC_INPUT:
                    raise ValueError
                nodes = BeautifulSoup(payload, 'html.parser').select('main .r34ics-ajax-container')
                observation['placeholder_count'] = len(nodes)
                raw_id = nodes[0].get('id', '') if len(nodes) == 1 else ''
                valid = isinstance(raw_id, str) and bool(re.fullmatch(r'r[a-f0-9]{8,40}-ajax', raw_id))
                observation['placeholder_id_valid'] = valid
                placeholder_id = raw_id[:-5] if valid else None
            except Exception:
                observation['placeholder_observation_failed'] = True
        return payload

    def render(*, nonce, args, **kwargs):
        observation['render_calls'] = observation.get('render_calls', 0) + 1
        try:
            payload = original_render(nonce=nonce, args=args, **kwargs)
        except Exception as error:
            observe_error(error)
            raise
        if source_key == good_shepherd.SOURCE_KEY:
            try:
                if not isinstance(payload, str) or len(payload) > MAX_DIAGNOSTIC_INPUT:
                    raise ValueError
                nodes = BeautifulSoup(payload, 'html.parser').select('.ics-calendar')
                observation['rendered_calendar_count'] = len(nodes)
                if len(nodes) == 1:
                    calendar = nodes[0]
                    raw_id = calendar.get('id', '')
                    observation['rendered_id_valid'] = isinstance(raw_id, str) and bool(re.fullmatch(r'r[a-f0-9]{8,40}', raw_id))
                    observation['placeholder_render_id_equal'] = placeholder_id is not None and raw_id == placeholder_id
                    observation['pagination_selector_count'] = len(calendar.select('[rel~=next], .pagination, [data-next-page]'))
                    observation['month_selector_count'] = len(calendar.select('select.ics-calendar-select'))
                    observation['month_grid_count'] = len(calendar.select('table.ics-calendar-month-grid'))
                    markup, truncated = _public_calendar_markup(calendar, placeholder_id, (nonce, args))
                    receipt['calendar_diagnostic_html'] = markup
                    observation['calendar_diagnostic_truncated'] = truncated
                    observation['placeholder_label'] = 'CALENDAR_PLACEHOLDER'
                    observation['rendered_label'] = ('CALENDAR_PLACEHOLDER' if raw_id == placeholder_id else 'CALENDAR_RENDERED')
            except Exception:
                observation['render_observation_failed'] = True
        return payload

    preview_worker.fetch_publisher = fetch
    preview_worker.render_good_shepherd_calendar = render
    try:
        yield
    finally:
        preview_worker.fetch_publisher = original_fetch
        preview_worker.render_good_shepherd_calendar = original_render
        if observation:
            receipt['transport_observation'] = observation


def audit():
    overall = monotonic() + OVERALL_SECONDS
    result = {'checked_at': datetime.now(timezone.utc).isoformat(),
              'read_only': True, 'sources': []}
    for key, url in SOURCES:
        started = monotonic()
        deadline = min(overall, started + PER_SOURCE_SECONDS)
        receipt = {'source_key': key, 'kind': 'html', 'platform_adapter': 'html'}
        try:
            if started >= overall:
                raise preview_worker.PreviewError('collection_deadline')
            source = {'source_key': key, 'kind': 'html', 'platform_adapter': 'html',
                      'feed_url': url, 'timezone': 'America/New_York'}
            with _observe_existing_transport(key, receipt):
                output = preview_worker.preview_source(source, deadline_at=deadline)
            if monotonic() >= deadline:
                raise preview_worker.PreviewError('collection_deadline')
            if not isinstance(output, dict) or 'p_error' not in output:
                raise preview_worker.PreviewError('snapshot_shape_missing')
            if output['p_error'] is not None:
                raise preview_worker.PreviewError(output['p_error'])
            if output.get('p_parser_capability') != 'publisher_event_candidates_v1':
                raise preview_worker.PreviewError('snapshot_capability_missing')
            records = output.get('p_events')
            if (not isinstance(records, list) or len(records) > MAX_RECORDS
                    or any(not isinstance(event, dict) for event in records)):
                raise preview_worker.PreviewError('snapshot_records_invalid')
            receipt.update(outcome='complete', candidate_count=len(records),
                           candidate_image_count=sum(bool(event.get('image_url')) for event in records),
                           parser_capability=output['p_parser_capability'], events=records)
        except Exception as error:
            # Raw exception messages may contain transport URLs or headers.
            # Keep only the existing collector's bounded diagnostic-code form.
            value = error.args[0] if isinstance(error, preview_worker.PreviewError) and len(error.args) == 1 else ''
            code = value if isinstance(value, str) and re.fullmatch(r'[a-z_0-9]{3,100}', value) else 'source_audit_failed'
            receipt.update(outcome='failed', error=code)
        receipt['duration_seconds'] = round(monotonic() - started, 2)
        result['sources'].append(receipt)
        print(json.dumps({key: value for key, value in receipt.items()
                          if key not in ('events', 'calendar_diagnostic_html')}), flush=True)
    result['complete'] = all(row['outcome'] == 'complete' for row in result['sources'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    return 0 if result['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
