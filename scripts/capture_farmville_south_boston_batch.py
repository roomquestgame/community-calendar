"""Read-only preflight for the Farmville and South Boston source batch."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import json
from pathlib import Path
import re
import sys
from time import monotonic
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from roomquest import preview_worker, virginia_wix_events, visit_farmville


SOURCES = (
    ('farmville_parks_rec_va', 'ical', preview_worker.VIRGINIA_CIVIC_ICS['farmville_parks_rec_va']),
    (visit_farmville.SOURCE_KEY, 'html_parser', visit_farmville.SOURCE_URL),
    ('farmville_chamber_va', 'html_probe', 'https://www.farmvilleareachamber.org/upcoming-events'),
    ('longwood_campus_va', 'json_probe', 'https://calendar.longwood.edu/live/json/events/max/10'),
    ('longwood_visual_arts_va', 'json_probe', 'https://lcva.longwood.edu/wp-json/tribe/events/v1/events?per_page=10'),
    ('hampden_sydney_college_va', 'rss_index', 'https://ems.hsc.edu/mastercalendar/RSSFeeds.aspx'),
    ('longwood_basketball_va', 'html_probe', 'https://longwoodlancers.com/sports/mens-basketball/schedule'),
    ('north_street_press_club_va', 'html_parser', virginia_wix_events.SOURCES['north_street_press_club_va'][0]),
    ('discover_halifax_va', 'html_probe', 'https://gohalifaxva.com/events/'),
    ('halifax_county_chamber_va', 'html_probe', 'https://www.halifaxchamber.net/events/catgid/19'),
    ('prizery_va', 'html_parser', 'https://prizery.org/events/'),
    ('south_boston_speedway_va', 'html_probe', 'https://www.southbostonspeedway.com/schedule'),
    ('sova_innovation_hub_va', 'xml_probe', 'https://coworking.sovainnovationhub.com/events/rss'),
    ('berry_hill_resort_va', 'html_parser', virginia_wix_events.SOURCES['berry_hill_resort_va'][0]),
    ('halifax_county_main_va', 'ical', preview_worker.VIRGINIA_CIVIC_ICS['halifax_county_main_va']),
    ('waterworks_players_va', 'html_probe', 'https://waterworksplayers.ludus.com/'),
    ('red_door_104_va', 'html_parser', 'https://www.reddoor104.com/workshops-special-events'),
)


def probe(spec):
    key, route, url = spec
    deadline = monotonic() + 45
    result = {'source_key': key, 'route': route}
    allowed_host = urlsplit(url).hostname

    def fetch(target, accept):
        return preview_worker.fetch_publisher(target, accept, respect_robots=True,
                                              allowed_hosts=(allowed_host,), deadline_at=deadline)

    try:
        if route in ('html_parser', 'ical'):
            kind = 'html' if route == 'html_parser' else 'ical'
            output = preview_worker.preview_source(
                {'source_key': key, 'feed_url': url, 'timezone': 'America/New_York',
                 'kind': kind, 'platform_adapter': kind}, deadline_at=deadline)
            rows = output['p_events']
        elif route == 'json_probe':
            data = json.loads(fetch(url, 'application/json'))
            items = data if isinstance(data, list) else data.get('events') if isinstance(data, dict) else None
            if not isinstance(items, list):
                raise ValueError('calendar_payload_shape_unverified')
            return {**result, 'status': 'payload_only', 'raw_count': len(items)}
        elif route in ('rss_index', 'xml_probe'):
            target = url
            if route == 'rss_index':
                soup = BeautifulSoup(fetch(url, 'text/html'), 'html.parser')
                target = next((urljoin(url, a['href']) for a in soup.select('a[href]')
                               if re.fullmatch(r'https://ems\.hsc\.edu/MasterCalendar/RSSFeeds\.aspx\?data=[A-Za-z0-9%+]+',
                                               a['href'], flags=re.I)), None)
                if not target:
                    raise ValueError('public_rss_link_missing')
            tree = ElementTree.fromstring(fetch(target, 'application/rss+xml, application/atom+xml, application/xml'))
            if tree.tag not in ('rss', '{http://www.w3.org/2005/Atom}feed'):
                raise ValueError('calendar_payload_shape_unverified')
            items = tree.findall('./channel/item') if tree.tag == 'rss' else tree.findall('./{http://www.w3.org/2005/Atom}entry')
            return {**result, 'status': 'payload_only', 'raw_count': len(items)}
        else:
            payload = fetch(url, 'text/html')
            if not BeautifulSoup(payload, 'html.parser').title:
                raise ValueError('calendar_page_shape_unverified')
            return {**result, 'status': 'payload_only'}
        return {**result, 'status': 'parsed', 'candidate_count': len(rows),
                'image_candidate_count': sum(bool(row.get('image_url')) for row in rows)}
    except (ValueError, TypeError, KeyError, OSError, ElementTree.ParseError) as exc:
        reason = str(exc)
        if not re.fullmatch(r'[a-z0-9_]{3,120}', reason):
            reason = 'source_probe_failed'
        return {**result, 'status': 'held', 'reason': reason}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(probe, SOURCES))
    args.output.write_text(json.dumps({'read_only': True, 'sources': results}, indent=2) + '\n')
    for result in results:
        print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
