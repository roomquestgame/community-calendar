"""Two current publisher poster schedules, bound to exact reviewed image bytes.

The ordinary page must still advertise the reviewed poster. Complete event
text is a visually verified transcription of those exact bytes, never a
generated image caption or a placeholder. Changes require another review.
All requests use the worker's guarded callback, including image downloads.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
import re
from time import monotonic
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import record


ZONE = "America/New_York"
VAGABOND = "vagabond_eht_nj"
CHARITY = "charity_league_atlantic_county_nj"
SOURCES = {
    VAGABOND: ("https://www.vagabondkitchenandtap.com/home-eht", "html", "html"),
    CHARITY: ("https://charityleague-ac.com/", "html", "html"),
}
ALLOWED_HOSTS = {
    VAGABOND: ("www.vagabondkitchenandtap.com", "images.squarespace-cdn.com"),
    CHARITY: ("charityleague-ac.com", "img1.wsimg.com"),
}
VENUES = {
    VAGABOND: ("EHT Vagabond Kitchen & Taphouse", "3016 Ocean Heights Ave, Egg Harbor Township, NJ 08234", "Egg Harbor Township"),
    CHARITY: ("Linwood Country Club", "500 Shore Road, Linwood, NJ 08221", "Linwood"),
}
# NJ Office of GIS score-100 PointAddress results for each exact official
# venue street/city/ZIP. These are address destinations, not room or entrance
# precision. Independent literals prevent later venue edits rebinding a point.
REVIEWED_VENUE_POINTS = {
    (VAGABOND, "EHT Vagabond Kitchen & Taphouse", "3016 Ocean Heights Ave, Egg Harbor Township, NJ 08234"):
        (39.360186000003, -74.615697000001),
    (CHARITY, "Linwood Country Club", "500 Shore Road, Linwood, NJ 08221"):
        (39.352284000003, -74.561652000001),
}
MAX_DESCRIPTION = 12000
MAX_IMAGE = 3_000_000
MAX_RECORDS = 32
VAGABOND_SECTION = "68951f857e2b4c44d0243096"
VAGABOND_CDN = "https://images.squarespace-cdn.com/content/v1/5e1f48802f478d24fc7e1ae1/"
# Reviewed November 14, 2026. A static weekly flyer must not become an
# indefinite rolling calendar. The final authorized weekly date is Jan 12.
WEEKLY_REVIEWED_FROM = date(2026, 11, 14)
WEEKLY_REVIEWED_THROUGH = date(2027, 1, 12)
POSTERS = {
    "breakfast-with-santa-2026": {
        "source": VAGABOND, "title": "Breakfast with Santa",
        "block": "block-yui_3_17_2_1_1794525030824_1465",
        "url": VAGABOND_CDN + "fdce64d2-0e4e-4940-9775-07e804780b6f/santa+breakfast+2026.jpg",
        "sha256": "5edaf898a37553369378b0571bb75bdfeae1da0ec73588cbde8355f55d74e874",
        "date": date(2026, 12, 5), "start": "09:30", "end": "12:00",
        # The current filename explicitly says 2026 and Saturday Dec 5 agrees.
        # The printed 9:30-to-12 clock is attached to a breakfast buffet.
        "description": "Breakfast with Santa\nFace Painting\nEHT Vagabond Kitchen & Taphouse\nSaturday December 5th\n9:30 to 12\nBreakfast Buffet\n$25 adults $10 kids\nSpace is limited call or email to book today.\n$5 Bloody Marys $5 Mimosas",
    },
    "dj-trivia-wednesdays": {
        "source": VAGABOND, "title": "DJ Trivia",
        "block": "block-yui_3_17_2_1_1780698300548_1759",
        "url": VAGABOND_CDN + "6f874a31-4784-41be-8e9e-3b2d6d3d05bb/dj+trivia+wensdays+new.jpg",
        "sha256": "0d2b2359394337c8e9a40a12aed5fcf429c118dc0f1cebbf2d9ca59fe0a05d6f",
        "weekday": 2, "start": "19:00", "end": None,
        "description": "DJ Trivia\nWednesdays @ 7PM\nEHT Vagabond Kitchen & Taphouse",
    },
    "dj-bingo-tuesdays": {
        "source": VAGABOND, "title": "DJ Bingo — Music Bingo",
        "block": "block-yui_3_17_2_1_1778677012073_3604",
        "url": VAGABOND_CDN + "2358eea4-3e9a-4b15-9183-904e87f267a2/DJ+Bingo.jpg",
        "sha256": "c27fb9f114232d50a74b40487a93ac7f8e2b0ee442b11554022775d86738b51d",
        "weekday": 1, "start": "18:00", "end": None,
        "description": "Music Bingo\nDJ Bingo\nChance to win $300\nTuesdays @ 6pm\nEHT Vagabond Kitchen & Taphouse",
    },
    "christmas-mart-2026": {
        "source": CHARITY, "title": "79th Annual Christmas Mart",
        "url": "https://img1.wsimg.com/isteam/ip/49e5abf6-2631-4fb4-bb2f-8b2740c6c62a/Picture1.jpeg",
        "sha256": "f59019ca22f7bd67aa8ef79a3a1ad27636746bbf7ea1a47eb8e590d08e470c79",
        "date": date(2026, 11, 20), "start": "10:00", "end": "19:00",
        "description": "CHARITY LEAGUE OF ATLANTIC COUNTY\n79TH ANNUAL Christmas MART\nONE DAY ONLY\nFRIDAY NOVEMBER 20, 2026\n10 AM to 7 PM\nLinwood Country Club\n500 Shore Road, Linwood\nVisit Linwoodcountryclub.com for dining reservations\nSUPPORTING OUR COMMUNITY SINCE 1946",
    },
}
# These same-section images were inspected or identify ordinary food items;
# they do not authorize events. Any new/replacement image needs a review so a
# newly advertised program cannot silently disappear from a complete snapshot.
NON_PROGRAM_IMAGES = {
    VAGABOND_CDN + "eb1641db-d6fd-4919-871b-10d948336780/Flyers+Special.jpg",
    VAGABOND_CDN + "a8747bae-ce89-4ac3-ac8d-c63b57a6f3d3/sunday+funday.jpg",
    VAGABOND_CDN + "331aa7e0-722b-459e-91ef-e13e03a10bf0/Happy+Hour+every+day.jpg",
    VAGABOND_CDN + "0ca6c4f6-b6ea-4b52-b9f5-7a2c95de4b79/truffle+fries.jpg",
}
CHARITY_SITE = "fa9bc72d-4b07-402f-99de-a8fadd57ce62"
CHARITY_WIDGET = "3777fed1-e10b-4cf6-a58a-71c9c67d86f6"
CHARITY_TITLE = "2026 Christmas mart on november 20, 2026"


def event_url(key, value):
    return key in SOURCES and isinstance(value, str) and value == SOURCES[key][0]


def photo_url(key, value):
    return value if isinstance(value, str) and any(
        item["source"] == key and item["url"] == value for item in POSTERS.values()) else None


def reviewed_venue_location(key, venue, address):
    return REVIEWED_VENUE_POINTS.get((key, venue, address))


def _source(source):
    key = source.get("source_key") if isinstance(source, dict) else None
    if (key not in SOURCES or source.get("timezone") != ZONE
            or tuple(source.get(field) for field in ("feed_url", "kind", "platform_adapter")) != SOURCES.get(key)):
        raise ValueError("reviewed_poster_source_identity")
    return key


def _text(node):
    return " ".join(node.get_text(" ", strip=True).split()) if node is not None else ""


def _description(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("reviewed_poster_description_missing")
    if len(value) > MAX_DESCRIPTION:
        raise ValueError("reviewed_poster_description_limit")
    return value


def _fetch(fetch, url, accept, deadline_at):
    if deadline_at is not None and monotonic() + 2 >= deadline_at:
        raise ValueError("collection_deadline")
    return fetch(url, accept)


def _verify_image(item, fetch, deadline_at):
    payload = _fetch(fetch, item["url"], "image/jpeg", deadline_at)
    if (not isinstance(payload, bytes) or not 4 <= len(payload) <= MAX_IMAGE
            or not payload.startswith(b"\xff\xd8\xff")):
        raise ValueError("reviewed_poster_invalid_image")
    if sha256(payload).hexdigest() != item["sha256"]:
        raise ValueError("reviewed_poster_edition_changed")
    _description(item["description"])


def _page(payload, key):
    if not isinstance(payload, str):
        raise ValueError("reviewed_poster_page_changed")
    soup = BeautifulSoup(payload, "html.parser")
    canonical = [node.get("href") for node in soup.select('link[rel="canonical"]')]
    if canonical != [SOURCES[key][0]]:
        raise ValueError("reviewed_poster_page_identity")
    return soup


def _vagabond(payload, fetch, deadline_at, now):
    if now.astimezone(ZoneInfo(ZONE)).date() > WEEKLY_REVIEWED_THROUGH:
        raise ValueError("reviewed_poster_freshness_expired")
    soup = _page(payload, VAGABOND)
    sections = soup.select(f'section[data-section-id="{VAGABOND_SECTION}"]')
    if len(sections) != 1:
        raise ValueError("reviewed_poster_manifest_changed")
    footer = [h.find_parent(class_="sqs-html-content") for h in soup.find_all("h3")
              if _text(h) == "EHT VAGABOND"]
    if (len(footer) != 1 or "3016 Ocean Heights Ave" not in _text(footer[0])
            or "Egg Harbor Township, NJ 08234" not in _text(footer[0])):
        raise ValueError("reviewed_poster_venue_changed")
    expected = {name: item for name, item in POSTERS.items() if item["source"] == VAGABOND}
    known = {item["url"] for item in expected.values()} | NON_PROGRAM_IMAGES
    observed = {urljoin(SOURCES[VAGABOND][0], image.get("data-src") or image.get("src") or "")
                for image in sections[0].find_all("img")}
    if not observed or not observed.issubset(known):
        raise ValueError("reviewed_poster_manifest_changed")
    for item in expected.values():
        blocks = sections[0].select('[id="' + item["block"] + '"]')
        if len(blocks) != 1:
            raise ValueError("reviewed_poster_manifest_changed")
        urls = {urljoin(SOURCES[VAGABOND][0], image.get("data-src") or image.get("src") or "")
                for image in blocks[0].find_all("img")}
        if urls != {item["url"]}:
            raise ValueError("reviewed_poster_edition_changed")
        _verify_image(item, fetch, deadline_at)
    return expected


def _script_url(value):
    try:
        p = urlsplit(value)
        return (p.scheme == "https" and p.netloc == "img1.wsimg.com" and not p.query and not p.fragment
                and re.fullmatch(r"/blobby/go/" + CHARITY_SITE + r"/gpub/[a-f0-9]{16}/script\.js", p.path) is not None)
    except (ValueError, TypeError):
        return False


def _literal_objects(payload):
    # Same data-only JSON.parse-literal strategy as the GoDaddy calendar
    # adapter. Never execute publisher JavaScript.
    if not isinstance(payload, str):
        raise ValueError("reviewed_poster_script_changed")
    decoder = json.JSONDecoder()
    for match in re.finditer(r"JSON\.parse\(", payload):
        try:
            literal, _ = decoder.raw_decode(payload[match.end():])
            obj = json.loads(literal) if isinstance(literal, str) else None
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict):
            yield obj


def _charity(payload, fetch, deadline_at):
    soup = _page(payload, CHARITY)
    headings = [heading for heading in soup.select('[data-aid="GALLERY_SECTION_TITLE_RENDERED"]')
                if _text(heading) == CHARITY_TITLE]
    widget = headings[0].find_parent(attrs={"data-ux": "Widget"}) if len(headings) == 1 else None
    if widget is None or widget.get("id") != CHARITY_WIDGET:
        raise ValueError("reviewed_poster_manifest_changed")
    scripts = sorted({urljoin(SOURCES[CHARITY][0], node["src"]) for node in soup.select("script[src]")
                      if _script_url(urljoin(SOURCES[CHARITY][0], node["src"]))})
    if not 1 <= len(scripts) <= 4:
        raise ValueError("reviewed_poster_manifest_changed")
    galleries = []
    for url in scripts:
        for obj in _literal_objects(_fetch(fetch, url, "application/javascript", deadline_at)):
            # GoDaddy also emits a small bootstrap object with widgetId but
            # no gallery data; it is not a second program manifest.
            if (obj.get("id") == CHARITY_WIDGET or
                    obj.get("widgetId") == CHARITY_WIDGET and "galleryImages" in obj):
                galleries.append(obj)
    if len(galleries) != 1:
        raise ValueError("reviewed_poster_gallery_incomplete")
    gallery = galleries[0]
    if (gallery.get("id") != CHARITY_WIDGET or gallery.get("widgetId") != CHARITY_WIDGET
            or str(gallery.get("title", "")).strip() != CHARITY_TITLE
            or gallery.get("env") != "production" or gallery.get("renderMode") != "PUBLISH"):
        raise ValueError("reviewed_poster_gallery_changed")
    native = gallery.get("galleryImages")
    rendered = gallery.get("images")
    if not isinstance(native, list) or len(native) != 1 or not isinstance(rendered, list) or len(rendered) != 1:
        raise ValueError("reviewed_poster_gallery_changed")
    try:
        urls = {urljoin(SOURCES[CHARITY][0], native[0]["image"]["image"]),
                urljoin(SOURCES[CHARITY][0], rendered[0]["imageData"]["src"])}
    except (KeyError, TypeError, ValueError):
        raise ValueError("reviewed_poster_gallery_changed") from None
    item = POSTERS["christmas-mart-2026"]
    if urls != {item["url"]}:
        raise ValueError("reviewed_poster_edition_changed")
    _verify_image(item, fetch, deadline_at)
    return {"christmas-mart-2026": item}


def _occurrences(item, now):
    zone = ZoneInfo(ZONE)
    if "date" in item:
        days = [item["date"]]
    else:
        first = max(WEEKLY_REVIEWED_FROM, now.astimezone(zone).date())
        last = min(WEEKLY_REVIEWED_THROUGH, (now + timedelta(days=60)).astimezone(zone).date())
        days = [first + timedelta(days=i) for i in range(max(0, (last - first).days + 1))]
        days = [day for day in days if day.weekday() == item["weekday"]]
    for day in days:
        start = datetime.combine(day, time.fromisoformat(item["start"]), zone)
        end = datetime.combine(day, time.fromisoformat(item["end"]), zone) if item["end"] else None
        if start >= now + timedelta(days=60) or (end <= now if end else start <= now):
            continue
        yield day, start, end


def collect(source, fetch, *, deadline_at=None, now=None):
    key = _source(source)
    current = now or datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise ValueError("reviewed_poster_timezone_required")
    page = _fetch(fetch, SOURCES[key][0], "text/html", deadline_at)
    items = (_vagabond(page, fetch, deadline_at, current) if key == VAGABOND
             else _charity(page, fetch, deadline_at))
    rows = []
    venue, address, city = VENUES[key]
    point = reviewed_venue_location(key, venue, address)
    lat, lng = point or (None, None)
    for name, item in items.items():
        for day, start, end in _occurrences(item, current):
            row = record(item["title"], start.isoformat(), end.isoformat() if end else None,
                         venue, address, city, SOURCES[key][0], key + ":" + name + ":" + day.isoformat(),
                         "", lat=lat, lng=lng, tz=ZONE, retain_until_end=True)
            if row is not None:
                row.update(description=_description(item["description"]), timezone=ZONE,
                           attendance_mode="in_person", image_url=item["url"],
                           location_provenance=("reviewed_nj_ogis_point_address" if point
                                                else "reviewed_publisher_street_address_pending_geocode"))
                rows.append(row)
    if len(rows) > MAX_RECORDS:
        raise ValueError("reviewed_poster_record_limit")
    if len({(row["id"], row["starts_at"]) for row in rows}) != len(rows):
        raise ValueError("reviewed_poster_duplicate_identity")
    return sorted(rows, key=lambda row: (row["starts_at"], row["title"]))
