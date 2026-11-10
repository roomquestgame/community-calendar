"""Expand a verified public service rule into a rolling eight-week calendar.

This module never infers a weekday or alternate-week phase from a place name.
Holiday changes must arrive as explicit, sourced exceptions. IDs retain the
original scheduled date when an occurrence moves, so the revised date updates
the same notice instead of creating a second pickup.
"""
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import re
from time import monotonic
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.civic_notices import date_notice, date_value, instant, public_url

WINDOW_DAYS = 56
MAX_EXCEPTIONS = 100
MAX_OCCURRENCES = 100
PUBLIC_WORKS_KEY = 'south_hill_public_works_va'
PUBLIC_WORKS_URL = 'https://www.southhillva.gov/municipal_services/index.php'
LOOKUP_URL = ('https://www.meridianwaste.com/guidelines/'
              'meridian-waste-lunenburg-hauling/town-of-south-hill/')
ZONE = 'America/New_York'


@dataclass(frozen=True)
class ScheduleRule:
    schedule_id: str
    title: str
    source_url: str
    jurisdiction_id: str
    jurisdiction_name: str
    weekday: int  # Monday=0, matching datetime.date.weekday().
    frequency: str = 'weekly'
    interval: int = 1
    anchor: date | None = None
    nth: int | None = None
    effective_from: date | None = None
    effective_until: date | None = None  # Exclusive, when the publisher supplies it.
    description: str = ''
    timezone: str = ZONE
    applicability: str = 'service_area'
    service_area_id: str | None = None
    service_area_name: str | None = None
    lookup_url: str | None = None

    def validate(self):
        if (not isinstance(self.schedule_id, str)
                or not re.fullmatch(r'[a-z0-9][a-z0-9_.:-]{0,159}', self.schedule_id)):
            raise ValueError('invalid_civic_schedule_id')
        public_url(self.source_url)
        if type(self.weekday) is not int or not 0 <= self.weekday <= 6:
            raise ValueError('civic_schedule_weekday_missing')
        if type(self.interval) is not int or self.frequency not in {'weekly', 'monthly'}:
            raise ValueError('unsupported_civic_schedule')
        if self.frequency == 'weekly':
            if self.interval not in (1, 2) or self.nth is not None:
                raise ValueError('unsupported_civic_schedule')
            if self.interval == 2 and self.anchor is None:
                raise ValueError('civic_schedule_anchor_missing')
        elif self.interval != 1 or type(self.nth) is not int or self.nth not in (-1, 1, 2, 3, 4, 5):
            raise ValueError('unsupported_civic_schedule')
        for value in (self.anchor, self.effective_from, self.effective_until):
            if value is not None:
                date_value(value)
        if self.anchor is not None and self.anchor.weekday() != self.weekday:
            raise ValueError('civic_schedule_anchor_conflict')
        if (self.effective_from is not None and self.effective_until is not None
                and self.effective_until <= self.effective_from):
            raise ValueError('invalid_civic_schedule_range')
        ZoneInfo(self.timezone)
        return self

    def matches(self, day):
        if ((self.effective_from and day < self.effective_from)
                or (self.effective_until and day >= self.effective_until)
                or day.weekday() != self.weekday):
            return False
        if self.frequency == 'weekly':
            return (self.interval == 1 or
                    (day >= self.anchor and (day - self.anchor).days % 14 == 0))
        if self.nth == -1:
            return day.day + 7 > monthrange(day.year, day.month)[1]
        return (day.day - 1) // 7 + 1 == self.nth

    @property
    def label(self):
        weekday = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')[self.weekday]
        if self.frequency == 'weekly':
            return ('Every ' if self.interval == 1 else 'Every other ') + weekday
        nth = {-1: 'Last', 1: 'First', 2: 'Second', 3: 'Third', 4: 'Fourth', 5: 'Fifth'}[self.nth]
        return nth + ' ' + weekday + ' of each month'


@dataclass(frozen=True)
class ScheduleException:
    original_date: date
    source_url: str
    verified_at: datetime
    replacement_date: date | None = None  # None means explicitly cancelled.
    description: str = ''


def occurrences(rule, *, now=None, exceptions=(), horizon_days=WINDOW_DAYS):
    rule.validate()
    current = instant(now or datetime.now(timezone.utc))
    if type(horizon_days) is not int or not 1 <= horizon_days <= WINDOW_DAYS:
        raise ValueError('civic_schedule_window_limit')
    today = current.astimezone(ZoneInfo(rule.timezone)).date()
    horizon = today + timedelta(days=horizon_days)
    if len(exceptions) > MAX_EXCEPTIONS:
        raise ValueError('civic_schedule_exception_limit')
    overrides = {}
    for change in exceptions:
        original = date_value(change.original_date)
        public_url(change.source_url)
        verified = instant(change.verified_at)
        if verified > current + timedelta(minutes=1):
            raise ValueError('civic_schedule_exception_unverified')
        if original in overrides or not rule.matches(original):
            raise ValueError('civic_schedule_exception_conflict')
        if change.replacement_date is not None:
            replacement = date_value(change.replacement_date)
            if replacement == original or abs((replacement - original).days) > 31:
                raise ValueError('invalid_civic_schedule_exception')
        overrides[original] = change
    scheduled = {today + timedelta(days=offset) for offset in range(horizon_days)
                 if rule.matches(today + timedelta(days=offset))}
    # A delayed occurrence may have its original date before today's window.
    scheduled.update(original for original, change in overrides.items()
                     if change.replacement_date is not None and today <= change.replacement_date < horizon)
    # A moved pickup can be cancelled after its original day has passed. Keep
    # that exact ID in the bounded revision set so the later replacement date
    # is retired; absence is never interpreted as a cancellation.
    scheduled.update(original for original, change in overrides.items()
                     if change.replacement_date is None
                     and today - timedelta(days=31) <= original < horizon)
    result = []
    for original in sorted(scheduled):
        change = overrides.get(original)
        actual = change.replacement_date if change and change.replacement_date is not None else original
        # Explicit revisions update a previously generated ID even when moved
        # outside the ordinary display window. In particular, an already-ended
        # replacement must expire the old future occurrence, not leave it behind
        # through omission. These extra rows are bounded by the 31-day move cap.
        if change is None and not today <= actual < horizon:
            continue
        status = 'cancelled' if change and change.replacement_date is None else None
        description = rule.description
        if change and change.description:
            description = description + '\n\n' + change.description
        row = date_notice(identity='civic-schedule:' + rule.schedule_id + '__' + original.strftime('%Y%m%d'),
                          title=rule.title, starts_on=actual, description=description,
                          now=current, topic='waste', jurisdiction_id=rule.jurisdiction_id,
                          jurisdiction_name=rule.jurisdiction_name, source_url=rule.source_url,
                          tz=rule.timezone, applicability=rule.applicability,
                          service_area_id=rule.service_area_id, service_area_name=rule.service_area_name,
                          lookup_url=rule.lookup_url, status=status,
                          horizon_days=horizon_days + 31 if change else horizon_days,
                          retain_revision=change is not None)
        row['civic'].update(schedule_id=rule.schedule_id, recurrence_label=rule.label,
                            original_date=original.isoformat())
        if change:
            row['civic'].update(schedule_exception='cancelled' if status else 'moved',
                                exception_source_url=change.source_url,
                                exception_verified_at=instant(change.verified_at).isoformat())
        result.append(row)
        if len(result) > MAX_OCCURRENCES:
            raise ValueError('source_record_limit')
    return sorted(result, key=lambda item: (item['starts_on'], item['id']))


def public_works_source():
    return {'source_key': PUBLIC_WORKS_KEY, 'feed_url': PUBLIC_WORKS_URL,
            'kind': 'html', 'platform_adapter': 'html', 'timezone': ZONE,
            'civic_contract_version': 1, 'civic_jurisdiction_id': 'us-va-south-hill',
            'civic_jurisdiction_name': 'Town of South Hill'}


def parse_public_works(payload, *, now=None):
    if not isinstance(payload, str) or len(payload) > 2_000_000:
        raise ValueError('unsupported_public_works_payload')
    soup = BeautifulSoup(payload, 'html.parser')
    for element in soup.select('script, style, template, noscript, nav, header, footer'):
        element.decompose()
    text = ' '.join(soup.get_text(' ', strip=True).split())
    # Require the reviewed publisher's specific, current rule and booking
    # condition together. Weekly/alternate-week text without route/anchor never
    # becomes a household schedule. A changed rule is held for a new review.
    if not re.search(r'\bTown of South Hill\b', text, re.I):
        raise ValueError('public_works_publisher_unresolved')
    matches = re.findall(r'Bulky items:\s*(.{0,500}?)\(call Town Hall at\s*\(434\)\s*447-3191\)', text, re.I)
    if (len(matches) != 1 or not re.search(r'collected by request;?\s*pickup on the third Wednesday of the month', matches[0], re.I)
            or re.search(r'\b(?:cancelled|canceled|suspended|discontinued|no longer|except|holiday|delay|reschedul)\w*\b', matches[0], re.I)):
        raise ValueError('public_works_schedule_requires_review')
    rule = ScheduleRule(
        schedule_id='south-hill-bulky-items', title='South Hill bulky item pickup (request required)',
        source_url=PUBLIC_WORKS_URL, jurisdiction_id='us-va-south-hill',
        jurisdiction_name='Town of South Hill', frequency='monthly', weekday=2, nth=3,
        applicability='address', lookup_url=LOOKUP_URL,
        description=('The Town of South Hill collects bulky items, such as furniture, by request '
                     'on the third Wednesday of each month. Call Town Hall at (434) 447-3191 '
                     'to arrange collection and confirm eligibility.'))
    return occurrences(rule, now=now)


def collect_public_works(source, fetch, *, deadline_at=None, now=None):
    expected = public_works_source()
    if (type(source.get('civic_contract_version')) is not int
            or any(source.get(key) != value for key, value in expected.items()
                   if key != 'civic_jurisdiction_name')):
        raise ValueError('unregistered_public_works_source')
    deadline = min(monotonic() + 25, deadline_at if deadline_at is not None else float('inf'))
    if monotonic() >= deadline:
        raise ValueError('collection_deadline')
    payload = fetch(PUBLIC_WORKS_URL, 'text/html')
    if monotonic() >= deadline:
        raise ValueError('collection_deadline')
    return parse_public_works(payload, now=now)
