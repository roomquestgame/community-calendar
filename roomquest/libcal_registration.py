"""Discover LibCal's declared subscription without executing publisher JavaScript."""
import json
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup


def subscription(url, body):
    page = urlsplit(url)
    # Query/hash filters may be populated by JavaScript rather than selected
    # options. Leave those to explicit export links instead of widening scope.
    if not (page.hostname or '').endswith('.libcal.com') or page.query or page.fragment:
        return None
    soup = BeautifulSoup(body, 'html.parser')
    scripts = '\n'.join(s.get_text() for s in soup.find_all('script', src=False))
    bases = re.findall(r"\biCalUrlBase\s*:\s*'([^'\n]+)'", scripts)
    ids = re.findall(r'\bbaseCalendarId\s*:\s*(\d+)\b', scripts)
    if len(bases) != 1 or len(ids) != 1:
        return None
    try:
        base = json.loads('"' + bases[0] + '"')
    except ValueError:
        return None
    target = urlsplit(base)
    if (target.scheme != 'https' or target.netloc != page.netloc
            or target.path != '/ical_subscribe.php' or target.query != 'src=p'
            or target.fragment or target.username):
        return None
    selectors = []
    for element_id, parameter in [('cal-dd', 'cid'), ('cat-dd', 'cat'),
                                  ('audience-dd', 'aud'), ('cam-dd', 'cam')]:
        elements = soup.find_all('select', id=element_id)
        if len(elements) > 1 or (element_id == 'cal-dd' and not elements):
            return None
        values = [o.get('value', '') for e in elements for o in e.find_all('option', selected=True)]
        if any(not re.fullmatch(r'[1-9]\d*', value) for value in values):
            return None
        if parameter == 'cid' and values != [ids[0]]:
            return None
        if values:
            selectors.append(parameter + '=' + ','.join(values))
    return base + '&' + '&'.join(selectors)
