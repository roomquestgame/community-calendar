"""Bound publisher narrative without copying site navigation or inventing prose."""
import re
from html import unescape
from bs4 import BeautifulSoup


_URL_ONLY = re.compile(r'https?://[^\s<>]+(?:\s+https?://[^\s<>]+)*', re.I)
# Some WordPress event exports contain Visual Composer layout instead of its
# rendered HTML. Remove only known controls, retaining the enclosed narrative.
_VISUAL_COMPOSER_SHORTCODE = re.compile(
    r'\[/?(?:vc_section|vc_row|vc_row_inner|vc_column|vc_column_inner|'
    r'vc_column_text|vc_custom_heading|vc_empty_space|vc_separator|'
    r'vc_single_image|vc_button|vc_btn|vc_icon)(?=[\s/\]])[^\[\]]*\]',
    re.I,
)
# Divi controls observed in Hurrdat's event narrative, not arbitrary et_pb tags.
_DIVI_SHORTCODE = re.compile(
    r'\[/?(?:et_pb_section|et_pb_row|et_pb_column|et_pb_text|et_pb_code)'
    r'(?=[\s/\]])[^\[\]]*\]',
    re.I,
)


MAX_EVENT_DESCRIPTION_CHARACTERS = 12000


def description(value, *, limit=MAX_EVENT_DESCRIPTION_CHARACTERS):
    if value is None:
        return ''
    if not isinstance(value, str):
        raise ValueError('invalid_event_description')
    if _URL_ONLY.fullmatch(value.strip()):
        return ''
    # TEC JSON-LD encodes the HTML narrative as entities. Decode before parsing,
    # otherwise BeautifulSoup turns &lt;p&gt; into literal tags in its text output
    # and the native-content validator correctly rejects the entire collection.
    # Bound repeated publisher escaping; never execute the decoded markup.
    for _ in range(3):
        decoded = unescape(value)
        if decoded == value:
            break
        value = decoded
    value = _VISUAL_COMPOSER_SHORTCODE.sub('\n', value)
    value = _DIVI_SHORTCODE.sub('\n', value)
    soup = BeautifulSoup(value, 'html.parser')
    for node in soup.select('script, style, template, noscript, nav, .post-navigation, .navigation, .sharedaddy'):
        node.decompose()
    text = '\n'.join(re.sub(r'[\t\r\f\v ]+', ' ', line).strip()
                     for line in soup.get_text('\n').splitlines() if line.strip())
    if _URL_ONLY.fullmatch(text):
        return ''
    return text[:limit]

def calendar_description(item, title=""):
    """Read the occurrence's own plain/HTML alternative; never fetch or guess."""
    primary = description(str(item.get("DESCRIPTION", "")))
    normalized_title = " ".join(str(title).split()).casefold()
    primary_key = " ".join(primary.split()).casefold()
    alternatives = item.get("X-ALT-DESC", [])
    alternatives = alternatives if isinstance(alternatives, list) else [alternatives]
    for value in alternatives:
        if str(getattr(value, "params", {}).get("FMTTYPE", "")).lower() != "text/html":
            continue
        candidate = description(str(value))
        candidate_key = " ".join(candidate.split()).casefold()
        if not candidate_key or candidate_key == normalized_title:
            continue
        if not primary_key or primary_key == normalized_title:
            return candidate
        if len(candidate_key) > len(primary_key) and primary_key in candidate_key:
            return candidate
    return primary
