"""Bound publisher narrative without copying site navigation or inventing prose."""
import re
from bs4 import BeautifulSoup


_URL_ONLY = re.compile(r'https?://[^\s<>]+(?:\s+https?://[^\s<>]+)*', re.I)
# Some WordPress ICS exports contain Visual Composer layout instead of its
# rendered HTML. Remove only known controls, retaining the enclosed narrative.
_VISUAL_COMPOSER_SHORTCODE = re.compile(
    r'\[/?(?:vc_section|vc_row|vc_row_inner|vc_column|vc_column_inner|'
    r'vc_column_text|vc_custom_heading|vc_empty_space|vc_separator|'
    r'vc_single_image|vc_button|vc_btn|vc_icon)(?=[\s/\]])[^\[\]]*\]',
    re.I,
)


def description(value, *, limit=2000):
    if value is None:
        return ''
    if not isinstance(value, str):
        raise ValueError('invalid_event_description')
    if _URL_ONLY.fullmatch(value.strip()):
        return ''
    value = _VISUAL_COMPOSER_SHORTCODE.sub('\n', value)
    soup = BeautifulSoup(value, 'html.parser')
    for node in soup.select('script, style, template, noscript, nav, .post-navigation, .navigation, .sharedaddy'):
        node.decompose()
    text = '\n'.join(re.sub(r'[\t\r\f\v ]+', ' ', line).strip()
                     for line in soup.get_text('\n').splitlines() if line.strip())
    if _URL_ONLY.fullmatch(text):
        return ''
    return text[:limit]
