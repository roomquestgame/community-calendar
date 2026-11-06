"""Shared bounded ICS validation; existing recurrence/VEVENT normalizer retained.

Legacy output fields and media stay intact to preserve venue-cache identity.
Mapsee URL/address fallbacks stay restricted to its existing catalog records.
"""
from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import logging
import re
from urllib.parse import urlsplit, parse_qs
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

MECKLENBURG_LIBRARY_KEY = 'mecklenburg_va_libraries'
MECKLENBURG_LIBRARY_FEED = 'https://calendar.google.com/calendar/ical/mecklib.org%40gmail.com/public/basic.ics'
MECKLENBURG_LIBRARY_CALENDAR = 'https://www.youseemore.com/mecklib/calendar.asp'
MECKLENBURG_LIBRARY_DIRECTORY = 'https://www.youseemore.com/mecklib/directory.asp'
_MECKLENBURG_TIMEZONE = ZoneInfo('America/New_York')

# Reviewed 2026-11-06 against the official directory. These are per-event branch
# identities, never a publisher/headquarters default or a substitute map point.
_MECKLENBURG_BRANCHES = {
    'boydton': {
        'name': 'Boydton Public Library',
        'address': '1294 Jefferson Street, Boydton, VA 23917',
        'city': 'Boydton',
        'aliases': ('Boydton Public Library and Mecklenburg County Public Library Headquarters',),
    },
    'clarksville': {
        'name': 'Burnett Library & Learning Center',
        'address': '914 Virginia Avenue, Clarksville, VA 23927',
        'city': 'Clarksville',
        'aliases': ('Burnett Library & Learning Center, 914 Virginia Ave, Clarksville, VA 23927, USA',),
    },
    'south_hill': {
        'name': 'R. T. Arnold Public Library',
        'address': '110 East Danville Street, South Hill, VA 23970',
        'city': 'South Hill',
        'aliases': (),
    },
    'chase_city': {
        'name': 'Butler Memorial Library',
        'address': '515 Marshall Street, Chase City, VA 23924',
        'city': 'Chase City',
        'aliases': (),
    },
}
# An omitted LOCATION is resolved only for an observed series identity AND its
# unchanged title, supported by the official shared calendar plus directory.
# An occurrence override with a different title must supply its own location.
_MECKLENBURG_SERIES = {
    '2vuprkgguf4ea6u7mljhjcbgsv@google.com': ('Clarksville Book Club', 'clarksville'),
    '43j08mloeosfkc6fm3j3o1bq36@google.com': ('Clarksville Storytime', 'clarksville'),
    'dnqendor8l3s7i44vquu5mbqln@google.com': ('South Hill Story Time', 'south_hill'),
    '54gq15h3o25rhbnss876dj7s81_R20260716T143000@google.com': ('Boydton Storytime', 'boydton'),
}


def _mecklenburg_source(source):
    if source.get('source_key') != MECKLENBURG_LIBRARY_KEY:
        return False
    if source.get('url') != MECKLENBURG_LIBRARY_FEED:
        raise ValueError('unregistered_mecklenburg_library_source')
    return True


def _aware(value):
    return isinstance(value, datetime) and value.tzinfo is not None


def _prune_expired_until_groups(calendar, now):
    """Drop only provably ended, timed UID groups after raw ICS validation.

    Keep COUNT-only/all-day rules, RDATE/EXRULE, RANGE exceptions, ambiguous
    masters, unresolved times and any override moved into the future. The
    cutoff precedes the collection-day boundary in every IANA timezone.
    Including the final occurrence's duration preserves ongoing occurrences.
    This is used only for the explicitly enrolled Mecklenburg library feed.
    """
    groups = defaultdict(list)
    for event in calendar.walk('VEVENT'):
        groups[str(event.get('UID', ''))].append(event)
    cutoff = datetime.combine(now.date(), time(), timezone.utc) - timedelta(days=1)
    expired = set()
    for uid, group in groups.items():
        if not uid:
            continue
        masters = [event for event in group if not event.get('RECURRENCE-ID')]
        if len(masters) != 1 or not masters[0].get('RRULE'):
            continue
        if any(event.get('RDATE') or event.get('EXRULE') or
               (event.get('RECURRENCE-ID') and event['RECURRENCE-ID'].params.get('RANGE'))
               for event in group):
            continue
        master = masters[0]
        untils = master['RRULE'].get('UNTIL') or []
        if len(untils) != 1:
            continue
        until = untils[0]
        start, end = master.decoded('DTSTART', None), master.decoded('DTEND', None)
        if not all(_aware(value) for value in (until, start, end)) or end < start:
            continue
        if until >= cutoff or end >= cutoff or until + (end - start) >= cutoff:
            continue
        if any(not _aware(event.decoded('DTSTART', None)) or
               not _aware(event.decoded('DTEND', None)) or
               event.decoded('DTEND') < event.decoded('DTSTART') or
               max(event.decoded('DTSTART'), event.decoded('DTEND')) >= cutoff
               for event in group):
            continue
        expired.add(uid)
    if not expired:
        return calendar
    trimmed = deepcopy(calendar)
    trimmed.subcomponents = [component for component in trimmed.subcomponents
                             if component.name != 'VEVENT' or
                             str(component.get('UID', '')) not in expired]
    logger.info('ics_expired_series_pruned source=%s groups=%s', MECKLENBURG_LIBRARY_KEY, len(expired))
    return trimmed


def _location_key(value):
    return re.sub(r'\s+', ' ', str(value or '').strip()).casefold()


def _mecklenburg_branch(location):
    key = _location_key(location)
    if not key:
        return None
    for branch, profile in _MECKLENBURG_BRANCHES.items():
        aliases = (profile['name'], profile['address'],
                   profile['name'] + ', ' + profile['address'],
                   profile['name'] + ', ' + profile['address'] + ', USA',
                   *profile['aliases'])
        if key in {_location_key(alias) for alias in aliases}:
            return branch
    return None


def _mecklenburg_closures(calendar, expanded):
    from icalendar import Calendar
    if expanded is None:
        components = calendar.walk('VEVENT')
    else:
        components = []
        for content in expanded:
            item = Calendar.from_ical('BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\n' +
                                      content + '\nEND:VEVENT\nEND:VCALENDAR')
            components.extend(item.walk('VEVENT'))
    result = []
    for event in components:
        if (str(event.get('SUMMARY', '')).strip().casefold() != 'closed' or
                str(event.get('STATUS', '')).upper() in {'CANCELLED', 'CANCELED'}):
            continue
        start, end = event.decoded('DTSTART'), event.decoded('DTEND', None)
        if isinstance(start, datetime):
            if not _aware(start) or not _aware(end):
                raise ValueError('library_closure_time_unresolved')
        else:
            # RFC DATE end is exclusive. A missing DATE end means one day;
            # these are closure intervals, never invented public event times.
            end = end or start + timedelta(days=1)
            if not isinstance(end, date) or isinstance(end, datetime):
                raise ValueError('library_closure_time_unresolved')
            start = datetime.combine(start, time(), _MECKLENBURG_TIMEZONE)
            end = datetime.combine(end, time(), _MECKLENBURG_TIMEZONE)
        if end <= start:
            raise ValueError('library_closure_time_unresolved')
        location = str(event.get('LOCATION', '')).strip()
        result.append((start.astimezone(timezone.utc), end.astimezone(timezone.utc),
                       location, _mecklenburg_branch(location)))
    return result


def _enrich_mecklenburg(records, calendar, expanded):
    declared_timezone = str(calendar.get('X-WR-TIMEZONE', '')).strip()
    if declared_timezone and declared_timezone != 'America/New_York':
        raise ValueError('publisher_timezone_conflict')
    closures = _mecklenburg_closures(calendar, expanded)
    result = []
    for record in records:
        if record['title'].strip().casefold() == 'closed':
            logger.warning('ics_record_withheld source=%s uid=%s reason=publisher_closure_record',
                           MECKLENBURG_LIBRARY_KEY, record['id'])
            continue
        supplied_location = str(record.get('venue_name') or '').strip()
        branch = _mecklenburg_branch(supplied_location)
        basis = 'event_location'
        if not supplied_location:
            profile = _MECKLENBURG_SERIES.get(record['id'].split('__', 1)[0])
            if profile and record['title'] == profile[0]:
                branch, basis = profile[1], 'exact_series_and_title'
        if branch:
            profile = _MECKLENBURG_BRANCHES[branch]
            record.update(venue_name=profile['name'], venue_address=profile['address'], venue_city=profile['city'])
            logger.info('ics_branch_evidence source=%s uid=%s branch=%s basis=%s directory=%s',
                        MECKLENBURG_LIBRARY_KEY, record['id'], branch, basis, MECKLENBURG_LIBRARY_DIRECTORY)
        elif not supplied_location:
            # Preserve the factual event unlocated for the existing review
            # and publication gates; do not silently drop a new unknown series.
            logger.warning('ics_location_unresolved source=%s uid=%s reason=publisher_branch_unresolved',
                           MECKLENBURG_LIBRARY_KEY, record['id'])
        # Explicit off-site locations and supplied coordinates remain intact.
        start = datetime.fromisoformat(record['starts_at'])
        end = datetime.fromisoformat(record['ends_at']) if record.get('ends_at') else None
        conflict = False
        for closed_start, closed_end, closed_location, closed_branch in closures:
            overlap = (start < closed_end and end > closed_start) if end else closed_start <= start < closed_end
            same_scope = (not closed_location or
                          (closed_branch is not None and closed_branch == branch) or
                          _location_key(closed_location) == _location_key(supplied_location))
            if overlap and same_scope:
                conflict = True
                break
        if conflict:
            # An unspecified/system closure conflicts with the occurrence.
            # Withhold for review; never infer cancellation or change an ID.
            logger.warning('ics_record_withheld source=%s uid=%s reason=publisher_closure_overlap',
                           MECKLENBURG_LIBRARY_KEY, record['id'])
            continue
        if record.get('event_url') in (None, '', MECKLENBURG_LIBRARY_FEED):
            record['event_url'] = MECKLENBURG_LIBRARY_CALENDAR
        if record.get('description') is not None:
            # This reviewed source uses the shared 2,000-character narrative
            # contract; the larger Independence/DCR allowance does not apply.
            record['description'] = record['description'][:2000]
        result.append(record)
    return result


def civicplus_detail_url(description, identity, source_url):
    """Use an explicit same-publisher EID link; never synthesize from the UID."""
    origin = urlsplit(source_url)
    matches = []
    for candidate in re.findall(r'https://[^\s<>"\']+', description):
        candidate = candidate.rstrip('.,;)')
        parsed = urlsplit(candidate)
        if (parsed.scheme == 'https' and parsed.netloc.lower() == origin.netloc.lower()
                and not parsed.username and not parsed.password
                and parsed.path.lower() == '/calendar.aspx'
                and parse_qs(parsed.query) == {'EID': [identity]}):
            matches.append(candidate)
    return matches[0] if len(set(matches)) == 1 else None

def parse(payload, source, *, legacy=False, include_description=False):
    from icalendar import Calendar
    from roomquest.preview_worker import parse_ics_preview
    mecklenburg = _mecklenburg_source(source)
    include_description = include_description or mecklenburg
    if not payload.lstrip("\ufeff \r\n").upper().startswith("BEGIN:VCALENDAR") or "END:VCALENDAR" not in payload.upper():
        raise ValueError("invalid_calendar_payload")
    cal=Calendar.from_ical(payload)
    events=cal.walk("VEVENT")
    original_event_count = len(events)
    if len(events)>5000:raise ValueError("source_record_limit")
    unsupported=[]
    for e in events:
        if str(e.get("STATUS","")).upper() in {"CANCELLED","CANCELED"}:continue
        if e.errors:
            if any(str(error[0]).upper() in {"RRULE","RDATE","EXDATE","RECURRENCE-ID"} for error in e.errors):
                raise ValueError("recurrence_invalid")
            raise ValueError("invalid_ical_component")
        start=e.decoded("DTSTART") if e.get("DTSTART") else None
        if start is None:raise ValueError("invalid_ical_missing_start")
        # Date-only events have no advertised time; the existing collector does
        # not invent one. Distinguish that unsupported shape from valid empty.
        if not isinstance(start,datetime):
            if mecklenburg and e.get('RRULE'):
                rule = e['RRULE']
                frequency = str((rule.get('FREQ') or [''])[0]).upper()
                density = 1
                for field in ('BYSECOND', 'BYMINUTE', 'BYHOUR', 'BYDAY'):
                    density *= max(1, len(rule.get(field) or []))
                if frequency not in {'DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY'} or density > 24:
                    raise ValueError('unsupported_dense_recurrence')
            end = e.decoded('DTEND') if e.get('DTEND') else start
            if max(start, end) >= datetime.now(timezone.utc).date():
                closure = mecklenburg and str(e.get('SUMMARY', '')).strip().casefold() == 'closed'
                if not closure:
                    unsupported.append("unsupported_all_day_time")
                logger.warning('ics_record_withheld source=%s uid=%s reason=%s',
                               source.get('source_key', ''), str(e.get('UID', ''))[:180],
                               'publisher_closure_record' if closure else 'unsupported_all_day_time')
            continue
        if start.tzinfo is None:
            if start.date()>=datetime.now(timezone.utc).date():unsupported.append("timezone_unresolved")
            continue
        if e.get("RRULE"):
            rule=e["RRULE"]
            frequency=str((rule.get("FREQ") or [""])[0]).upper()
            density=1
            for field in ("BYSECOND","BYMINUTE","BYHOUR","BYDAY"):
                density*=max(1,len(rule.get(field) or []))
            if frequency not in {"DAILY","WEEKLY","MONTHLY","YEARLY"} or density>24:
                raise ValueError("unsupported_dense_recurrence")
            try:
                from dateutil.rrule import rrulestr
                rrulestr(e["RRULE"].to_ical().decode(),dtstart=start)
            except (ValueError,TypeError,OverflowError) as exc:raise ValueError("recurrence_invalid") from exc
    if mecklenburg:
        # Do not let pruning evade the original raw-component ceiling. All
        # component/recurrence validation above still sees the full payload.
        if original_event_count > 1000:
            raise ValueError('source_record_limit')
        cal = _prune_expired_until_groups(cal, datetime.now(timezone.utc))
        events = cal.walk('VEVENT')
        payload = cal.to_ical().decode()
    # Udell's recurrence expander intentionally returns None on a malformed
    # recurrence. For new catalog sources that must be reported as a failure.
    if sum(bool(e.get("RRULE")) for e in events)>50:
        raise ValueError("recurrence_record_limit")
    expanded = None
    if any(e.get("RRULE") for e in events):
        from scripts.combine_ics import expand_rrules
        expanded = expand_rrules(payload,window_days=60)
        if expanded is None:
            raise ValueError("recurrence_expansion_failed")
        if mecklenburg and len(expanded) > 1000:
            # The unchanged normalizer reads at most 1000 components. Never
            # call a truncated Mecklenburg snapshot complete.
            raise ValueError('source_record_limit')
    # Feed histories can precede the future records. Keep the existing 1000-item
    # parser bound honest instead of silently calling a truncated feed empty.
    if original_event_count>1000:
        raise ValueError("source_record_limit")
    result=parse_ics_preview(payload,allow_ongoing=True,include_images=legacy, include_description=include_description)
    if not result and unsupported:raise ValueError(unsupported[0])
    # A feed URL is an actual publisher link when its VEVENT omits URL. Never
    # fabricate a detail URL, venue, publisher host, description or image.
    # Retain the actual publisher labels separately from the legacy single text
    # category. VEVENT CATEGORIES can be a multi-valued vCategory or repeated.
    # Bound the labels before they enter our JSON staging contract.
    categories = {}
    detail_urls = {}
    for event in events:
        labels = []
        raw = event.get("CATEGORIES")
        for value in (raw if isinstance(raw, list) else [raw]):
            if value is None:
                continue
            for label in getattr(value, "cats", []):
                cleaned = str(label).strip()
                if cleaned and cleaned not in labels:
                    labels.append(cleaned[:100])
                if len(labels) >= 20:
                    break
        categories[str(event.get("UID", ""))] = labels
        if include_description and source.get('source_key') == 'independence_ia_library_family':
            uid = str(event.get('UID', ''))
            detail_urls[uid] = civicplus_detail_url(str(event.get('DESCRIPTION', '')), uid, source['url'])

    for e in result:
        if include_description and source.get('source_key') == 'independence_ia_library_family':
            uid = e['id'].split('__', 1)[0]
            if not detail_urls.get(uid):
                raise ValueError('publisher_detail_link_missing')
            e['event_url'] = detail_urls[uid]
        if legacy and not include_description:
            continue
        if not mecklenburg:
            e.pop("image_url",None)
        e["publisher_categories"]=categories.get(e["id"].split("__",1)[0], [])
        e["category"]=", ".join(e["publisher_categories"])[:80]
        if not e.get("event_url"):e["event_url"]=source["url"]
        if not e.get("venue_address") and e.get("venue_name"):e["venue_address"]=e["venue_name"]
    if mecklenburg:
        if len({event['id'] for event in result}) != len(result):
            raise ValueError('recurrence_identity_conflict')
        result = _enrich_mecklenburg(result, cal, expanded)
    if len(result)>500:raise ValueError("source_record_limit")
    return result
