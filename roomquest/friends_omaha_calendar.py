"""Read Friends of Omaha Public Library board meetings from its MEC calendar."""
from datetime import datetime, timedelta
from hashlib import sha256
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from lxml import html

from roomquest.mapsee_adapter import plain, record

KEY = "friends_omaha_library_mec_ne"
HOST = "friendsomahalibrary.org"
URL = f"https://{HOST}/calendar/"
ZONE = "America/Chicago"
ADDRESS = "9101 W Dodge Rd, Omaha, NE 68114"
TIME = re.compile(r"(\d{1,2}:\d{2}\s+[ap]m)\s*[-–—]\s*(\d{1,2}:\d{2}\s+[ap]m)", re.I)


def collect(source, fetch, *, deadline_at=None, now=None):
    if tuple(source.get(key) for key in ("source_key", "feed_url", "timezone", "kind", "platform_adapter")) != (
        KEY, URL, ZONE, "html", "html",
    ):
        raise ValueError("unregistered_friends_calendar")
    today = (now or datetime.now(ZoneInfo(ZONE))).astimezone(ZoneInfo(ZONE)).date()
    document = html.fromstring(fetch(URL, "text/html"))
    days = document.xpath("//dt[@data-mec-cell]")
    if not days:
        raise ValueError("missing_friends_calendar")
    events = {}
    for cell in days:
        raw_day = cell.get("data-mec-cell")
        if not re.fullmatch(r"\d{8}", raw_day):
            continue
        day = datetime.strptime(raw_day, "%Y%m%d").date()
        if not today <= day <= today + timedelta(days=59):
            continue
        for anchor in cell.xpath(".//a[@data-tooltip-content and @href]"):
            title = plain(anchor.text_content())
            if not re.fullmatch(r"(?:[A-Za-z]+ )?FOPL Board Meeting", title, re.I):
                continue
            url = anchor.get("href")
            target = urlsplit(url)
            if (target.scheme, target.netloc) != ("https", HOST) or not re.fullmatch(r"/events/[^/]+/", target.path):
                raise ValueError("invalid_friends_event_link")
            tooltip = anchor.get("data-tooltip-content").removeprefix("#")
            fields = cell.xpath(".//*[@id=$id]//*[contains(concat(' ',normalize-space(@class),' '),' mec-tooltip-event-time ')]",
                                id=tooltip)
            times = TIME.fullmatch(plain(fields[0].text_content())) if fields else None
            if times is None:
                continue
            start, end = (datetime.combine(day, datetime.strptime(x.upper(), "%I:%M %p").time())
                          for x in times.groups())
            if start < end:
                events[url, start] = (title, end)
    if len({url for url, _ in events}) > 8:
        raise ValueError("friends_event_detail_limit")
    verified = {}
    result = []
    for (url, start), (title, end) in events.items():
        if url not in verified:
            detail = html.fromstring(fetch(url, "text/html"))
            visible = plain(detail.text_content())
            verified[url] = bool(re.search(r"9101\s+W\.?\s+Dodge\s+Rd\.?\s*,?\s*Omaha", visible, re.I))
        if not verified[url]:
            continue
        identity = sha256(f"{url}:{start.isoformat()}".encode()).hexdigest()
        row = record(title, start.isoformat(), end.isoformat(), "W. Clarke Swanson Branch", ADDRESS,
                     "Omaha", url, identity, lat=41.26292, lng=-96.0538, tz=ZONE)
        if row is not None:
            result.append(row)
    return sorted(result, key=lambda row: (row["starts_at"], row["id"]))
