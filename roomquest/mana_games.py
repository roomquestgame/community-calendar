"""Read dated public Mana Games events from the café's linked TopDeck page."""
from datetime import datetime, timedelta
from hashlib import sha256
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from lxml import html

from roomquest.mapsee_adapter import plain, record

KEY = "mana_games_topdeck_ne"
HOST = "topdeck.gg"
URL = f"https://{HOST}/managames"
ZONE = "America/Chicago"
START = re.compile(r"^([A-Za-z]{3} \d{1,2}, \d{4} \d{1,2}:\d{2} [AP]M) C[SD]T\b")
ADDRESS = "1400 Pioneers Blvd, Lincoln, NE 68502"
LEAGUE_PATH = "/event/mana-games-commander-league-fall-bracket-2"


def collect(source, fetch, *, deadline_at=None, now=None):
    if tuple(source.get(k) for k in ("source_key", "feed_url", "timezone", "kind", "platform_adapter")) != (
        KEY, URL, ZONE, "html", "html",
    ):
        raise ValueError("unregistered_mana_games_calendar")
    zone = ZoneInfo(ZONE)
    today = (now or datetime.now(zone)).astimezone(zone).date()
    document = html.fromstring(fetch(URL, "text/html"))
    cards = document.xpath("//*[@data-placement='upcoming' and @data-event-id]")
    links = {}
    for card in cards:
        anchors = card.xpath(".//a[starts-with(@href,'/event/')]")
        titles = card.xpath(".//h5[contains(@class,'card-title')]")
        if not anchors or not titles:
            continue
        url = urljoin(URL, anchors[0].get("href"))
        target = urlsplit(url)
        title = plain(titles[0].text_content())
        if ((target.scheme, target.netloc) != ("https", HOST) or
                not re.fullmatch(r"/event/[^/]+", target.path) or not title):
            continue
        links[url] = title
    if not links:
        links[urljoin(URL, LEAGUE_PATH)] = "Mana Games Commander League Fall - Bracket 2"
    if len(links) > 12:
        raise ValueError("mana_games_event_detail_limit")
    results = []
    for url, title in links.items():
        detail = html.fromstring(fetch(url, "text/html"))
        if re.search(r"\b(canceled|cancelled|postponed)\b", title, re.I):
            continue
        if not re.search(r"Mana Games Café,\s*(?:P Street|[^,]*Pioneers[^,]*),\s*Lincoln",
                         plain(detail.text_content()), re.I):
            continue
        fields = detail.xpath("//*[@id='EDate']/text()")
        if not fields and urlsplit(url).path == LEAGUE_PATH:
            raise ValueError("missing_topdeck_event_time")
        match = START.match(plain(" ".join(fields)))
        if not match:
            continue
        start = datetime.strptime(match[1], "%b %d, %Y %I:%M %p")
        if not today <= start.date() <= today + timedelta(days=59):
            continue
        identity = sha256(f"{url}:{start.isoformat()}".encode()).hexdigest()
        row = record(title, start.isoformat(), None, "Mana Games Café", ADDRESS, "Lincoln",
                     url, identity, tz=ZONE)
        if row is not None:
            results.append(row)
    return sorted(results, key=lambda row: (row["starts_at"], row["id"]))
