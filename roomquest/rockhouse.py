"""Read published performance dates and show times from Rockhouse venue pages."""
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import re
from time import monotonic
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from roomquest.mapsee_adapter import plain, record

ZONE = "America/Chicago"
SOURCES = {
    "omaha_sydney_rockhouse_ne": (
        "https://thesydneybenson.com/events/", "the-sydney-benson/", "The Sydney",
        "5918 Maple St, Omaha, NE 68104",
    ),
    "omaha_reverb_lounge_events": (
        "https://reverblounge.com/events/", "reverb-lounge/", "Reverb Lounge",
        "6121 Military Ave, Omaha, NE 68104",
    ),
    "omaha_admiral_events": (
        "https://admiralomaha.com/events/", "the-admiral/omaha-nebraska/", "The Admiral",
        "2234 S 13th St, Omaha, NE 68108",
    ),
}
MAX_DETAILS = 45
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
DAY = re.compile(
    r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+([0-9]{1,2})(?:,\s+(20[0-9]{2}))?\b", re.I,
)
SHOW = re.compile(r"\bShow\s*:\s*(\d{1,2})(?::([0-5]\d))?\s*([ap])\.?m\.?\b", re.I)
CANCELLED = re.compile(r"^(?:cancelled|canceled|postponed)(?:$|\s*[:–—-])", re.I)


class Document(HTMLParser):
    def __init__(self, payload):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.content = []
        self.heading = []
        self.in_heading = False
        self.in_body = False
        self.skip = False
        self.feed(payload)
        self.close()

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "template"}:
            self.skip = True
        if tag == "body":
            self.in_body = True
        if tag == "h1":
            self.in_heading = True
        if tag == "a" and not self.skip:
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag in {"script", "style", "template"}:
            self.skip = False
        if tag == "h1":
            self.in_heading = False
        if tag == "body":
            self.in_body = False

    def handle_data(self, value):
        if self.skip or not self.in_body or not value.strip():
            return
        value = plain(value)
        self.content.append(value)
        if self.in_heading:
            self.heading.append(value)


def detail_links(payload, listing, suffix):
    doc = Document(payload)
    if not re.search(r"\bUpcoming Events\b", " ".join(doc.content), re.I):
        raise ValueError("invalid_rockhouse_calendar")
    base = urlsplit(listing)
    out = set()
    for href in doc.links:
        link = urljoin(listing, href)
        parsed = urlsplit(link)
        if parsed.scheme != "https" or parsed.netloc != base.netloc or parsed.query or parsed.fragment:
            continue
        match = re.fullmatch(r"/event/([^/]+)/" + re.escape(suffix), parsed.path)
        if match and SLUG.fullmatch(match.group(1)):
            out.add(link)
    if not out:
        raise ValueError("rockhouse_calendar_links_missing")
    if len(out) > MAX_DETAILS:
        raise ValueError("rockhouse_calendar_detail_limit")
    return sorted(out)


def show_date(match, today, horizon):
    weekday, month, day, year = match.groups()
    candidates = [int(year)] if year else range(today.year, horizon.year + 1)
    for candidate in candidates:
        try:
            found = datetime.strptime(f"{month} {day} {candidate}", "%B %d %Y").date()
        except ValueError:
            continue
        if today <= found <= horizon and found.strftime("%A").casefold() == weekday.casefold():
            return found
    return None


def timed_record(title, day, show, url, venue, street):
    hour, minute, half = show.groups()
    hour = int(hour)
    if not 1 <= hour <= 12:
        raise ValueError("rockhouse_show_time_invalid")
    starts = datetime.combine(day, datetime.min.time()).replace(
        hour=hour % 12 + (12 if half.casefold() == "p" else 0), minute=int(minute or 0),
    )
    return record(title, starts.isoformat(), None, venue, street, "Omaha", url, url, tz=ZONE)


def event_record(payload, url, venue, street, today, horizon):
    doc = Document(payload)
    title = plain(" ".join(doc.heading))
    if not title:
        raise ValueError("rockhouse_event_title_missing")
    if CANCELLED.match(title) or any(CANCELLED.fullmatch(line) for line in doc.content):
        return None
    # Limit matching to the publisher's event block after its H1.
    body = " ".join(doc.content).partition(title)[2].split("View All Events", 1)[0]
    date_match = DAY.search(body)
    if not date_match:
        raise ValueError("rockhouse_event_date_missing")
    day = show_date(date_match, today, horizon)
    if day is None:
        return None
    show = SHOW.search(body[date_match.end():])
    if not show:
        return None
    return timed_record(title, day, show, url, venue, street)


def listing_records(payload, listing, links, venue, street, today, horizon):
    from lxml import html

    document = html.fromstring(payload)
    has_class = "contains(concat(' ', normalize-space(@class), ' '), $class_name)"
    allowed = set(links)
    observed = {}
    for view in document.xpath(f"//*[{has_class}]", class_name=" generalView "):
        month = None
        for item in view:
            classes = (item.get("class") or "").split()
            if "rhp-events-list-separator-month" in classes:
                month = datetime.strptime(plain(item.text_content()), "%B %Y")
                continue
            if "rhpSingleEvent" not in classes:
                continue
            headings = item.xpath(".//a[@id='eventTitle' and @href]")
            dates = item.xpath(f".//*[{has_class}]", class_name=" singleEventDate ")
            times = item.xpath(f".//*[{has_class}]", class_name=" rhp-event__time-text--list ")
            if not headings or not dates or month is None:
                continue
            url = urljoin(listing, headings[0].get("href"))
            title = plain(headings[0].text_content())
            if url not in allowed or not title:
                continue
            date_text = plain(dates[0].text_content())
            day = datetime.strptime(f"{date_text} {month.year}", "%a, %b %d %Y").date()
            if day.month != month.month or day.strftime("%a").casefold() != date_text.split(",")[0].casefold():
                raise ValueError("rockhouse_calendar_date_mismatch")
            show = SHOW.search(plain(times[0].text_content())) if times else None
            cancelled = CANCELLED.match(title) or any(CANCELLED.fullmatch(line.strip()) for line in item.itertext())
            row = None
            if not cancelled and today <= day <= horizon:
                if show is None:
                    continue
                row = timed_record(title, day, show, url, venue, street)
            if url in observed and observed[url] != row:
                raise ValueError("rockhouse_calendar_duplicate_conflict")
            observed[url] = row
    return observed


def collect(source, fetch, *, deadline_at=None, now=None):
    profile = SOURCES.get(source.get("source_key"))
    if profile is None or (source.get("feed_url"), source.get("timezone"),
                           source.get("kind"), source.get("platform_adapter")) != (
            profile[0], ZONE, "html", "html"):
        raise ValueError("unregistered_rockhouse_source")
    listing, suffix, venue, street = profile
    today = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(ZONE)).date()
    horizon = today + timedelta(days=60)
    payload = fetch(listing, "text/html")
    links = detail_links(payload, listing, suffix)
    observed = {}
    if source["source_key"] in {"omaha_reverb_lounge_events", "omaha_sydney_rockhouse_ne"}:
        observed = listing_records(payload, listing, links, venue, street, today, horizon)
    result = []
    for link in links:
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError("collection_deadline")
        row = observed[link] if link in observed else event_record(
            fetch(link, "text/html"), link, venue, street, today, horizon,
        )
        if row is not None:
            result.append(row)
    return sorted(result, key=lambda row: (row["starts_at"], row["id"]))
