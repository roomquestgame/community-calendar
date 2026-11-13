"""Bound publisher narrative without copying site navigation or inventing prose."""
import re
from bs4 import BeautifulSoup


_URL_ONLY = re.compile(r'https?://[^\s<>]+(?:\s+https?://[^\s<>]+)*', re.I)


def description(value, *, limit=2000):
    if value is None:
        return ''
    if not isinstance(value, str):
        raise ValueError('invalid_event_description')
    if _URL_ONLY.fullmatch(value.strip()):
        return ''
    soup = BeautifulSoup(value, 'html.parser')
    for node in soup.select('script, style, template, noscript, nav, .post-navigation, .navigation, .sharedaddy'):
        node.decompose()
    text = '\n'.join(re.sub(r'[\t\r\f\v ]+', ' ', line).strip()
                     for line in soup.get_text('\n').splitlines() if line.strip())
    if _URL_ONLY.fullmatch(text):
        return ''
    return text[:limit]
