"""Feeds must not become HTML calendar evidence; known adapters keep ownership."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from roomquest import feed_registration as registration
from roomquest import registered_html_calendar as calendar
from roomquest import registration_formats as formats

pytestmark = pytest.mark.filterwarnings('error::bs4.XMLParsedAsHTMLWarning')
FIXTURES = Path(__file__).parent / 'fixtures'
URL = 'https://venue.example.org/events'
RSS = (FIXTURES / 'sustainable_ow/feed.xml').read_text()
PROVIDER_XML = (FIXTURES / 'batch2/clear-lake.xml').read_text()
ATOM = (FIXTURES / 'document_formats/atom.xml').read_text()
HTML = (FIXTURES / 'registered_html_calendar/lansdowne/lansdowne-full-calendar.html').read_text()
JSON = (FIXTURES / 'battersea_bloem/square-events.json').read_text()
XML_DECLARATION = '<?xml version="1.0" encoding="utf-8"?>'
LINKS = ('<h1>Upcoming Events</h1><a href="/events/one">One</a>'
         '<a href="/events/two">Two</a><a href="/calendar.ics">Subscribe</a>')


@pytest.mark.parametrize('body', [
    RSS, XML_DECLARATION + RSS, PROVIDER_XML, XML_DECLARATION + PROVIDER_XML,
    ATOM, ATOM.split('?>', 1)[1],
    '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">' + LINKS + '</rdf:RDF>',
    '<atom:feed xmlns:atom="http://www.w3.org/2005/Atom">' + LINKS + '</atom:feed>',
    '<calendar xmlns="urn:example:calendar">' + LINKS + '</calendar>',
    XML_DECLARATION + '<calendar>' + LINKS + '</calendar>',
    '<!DOCTYPE rss [<!ENTITY ignored "synthetic">]><rss>' + LINKS + '</rss>',
    '\ufeff \n<!-- a fake <html> root -->' + XML_DECLARATION + '<rss>' + LINKS + '</rss>',
    '<html xmlns="urn:example:not-xhtml">' + LINKS + '</html>',
    '<!DOCTYPE calendar><!DOCTYPE html><html>' + LINKS + '</html>',
])
def test_xml_envelopes_never_reach_html_parsers_or_calendar_navigation(body):
    assert formats.document_kind(body) == 'xml'
    with patch.object(registration, 'CalendarLinks', side_effect=AssertionError('HTML navigation')), \
            patch.object(formats, 'BeautifulSoup', side_effect=AssertionError('HTML evidence')), \
            patch.object(calendar, 'BeautifulSoup', side_effect=AssertionError('HTML calendar')):
        assert registration.classify(URL, body) == {
            'p_outcome': 'review', 'p_reason': 'xml_adapter_needed', 'p_type': None}
        assert formats.collection_evidence(URL, body) is None
        assert calendar.supports_listing(URL, body) is False
        assert calendar.calendar_destination('https://venue.example.org/', body) is None
        with pytest.raises(ValueError, match='^html_calendar_payload_invalid$'):
            calendar._html(body)


@pytest.mark.parametrize('body', [ATOM, RSS, XML_DECLARATION + '<calendar>' + LINKS + '</calendar>'])
def test_ordinary_registration_holds_unsupported_xml_with_one_fetch(body):
    with patch.object(registration, 'fetch_publisher', return_value=body) as fetch, \
            patch.object(registration, 'supabase_rpc', side_effect=[{
                'url': URL, 'registered_html_calendar_version': 1,
                'verified_venue_website': True}, True]) as rpc, \
            patch.object(registration, 'recover_html_feed', side_effect=AssertionError('HTML recovery')), \
            patch.object(registration, 'verify_html_calendar', side_effect=AssertionError('HTML verification')):
        assert registration.register('offline-ticket') == {'outcome': 'review'}
    assert fetch.call_count == 1
    assert rpc.call_count == 2
    assert rpc.call_args.args[1] == {
        'p_ticket': 'offline-ticket', 'p_outcome': 'review',
        'p_reason': 'xml_adapter_needed', 'p_type': None}


def test_direct_html_recovery_does_not_explore_a_feed():
    with patch('roomquest.venue_calendar_locator.find_calendar',
               side_effect=AssertionError('feed navigation')):
        assert registration.recover_html_feed(URL, ATOM, 10) is None


@pytest.mark.parametrize('prefix,root,close', [
    ('', '<html>', '</html>'),
    ('<!DOCTYPE html>', '<html>', '</html>'),
    (XML_DECLARATION, '<html xmlns="http://www.w3.org/1999/xhtml">', '</html>'),
    (XML_DECLARATION + '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" '
     '"https://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">',
     '<html xmlns="http://www.w3.org/1999/xhtml">', '</html>'),
    ('<!-- <rss> is only comment text -->', '<main>', '</main>'),
    ('', '<event-calendar>', '</event-calendar>'),
    ('', '<custom-wrapper xmlns="http://www.w3.org/1999/xhtml">', '</custom-wrapper>'),
    ('<!--' + 'x' * formats.MAX_DOCUMENT_PREFIX + '-->', '<event-calendar>', '</event-calendar>'),
])
def test_html_xhtml_fragments_and_custom_wrappers_keep_existing_calendar_evidence(prefix, root, close):
    body = prefix + root + LINKS + close
    assert formats.document_kind(body) == 'html'
    assert calendar.supports_listing(URL, body)
    assert registration.classify(URL, body) == {
        'p_outcome': 'discovered', 'p_endpoint': 'https://venue.example.org/calendar.ics', 'p_type': 'ical'}
    assert formats.collection_evidence(URL, body) == {
        'p_outcome': 'review', 'p_reason': 'html_adapter_needed', 'p_type': 'html'}
    assert len(calendar._html(body).select('a[href]')) == 3


def test_captured_html_and_xhtml_keep_the_same_links_and_collection_scope():
    original = calendar._html(HTML)
    xhtml = XML_DECLARATION + HTML.replace('<html>',
        '<html xmlns="http://www.w3.org/1999/xhtml">', 1)
    # The reduced capture's root is HTML; its links and structured evidence are
    # retained rather than parsed as XML or rewritten during detection.
    assert formats.document_kind(HTML) == formats.document_kind(xhtml) == 'html'
    parsed = calendar._html(xhtml)
    assert [a.get('href') for a in parsed.select('a[href]')] == [
        a.get('href') for a in original.select('a[href]')]


def test_custom_html_wrapper_jsonld_and_json_keep_normalized_registration_behavior():
    at = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    events = [{'@type': 'MusicEvent', 'url': URL + '/' + name,
               'name': 'Synthetic concert ' + name, 'startDate': at,
               'location': {'name': 'Community hall'}} for name in ('one', 'two')]
    payload = json.dumps(events)
    markup = '<event-calendar><script type="application/ld+json">' + payload + '</script></event-calendar>'
    expected = {'p_outcome': 'verified', 'p_type': 'jsonld', 'p_endpoint': URL}
    assert registration.classify(URL, markup) == expected
    with patch.object(formats, 'BeautifulSoup', side_effect=AssertionError('JSON sent to HTML')):
        assert registration.classify(URL, payload) == expected
    assert formats.document_kind(JSON) == 'json'


def test_document_detection_does_not_infer_format_from_url_suffix():
    assert registration.classify(URL + '.xml', '<html>' + LINKS + '</html>')['p_type'] == 'ical'
    assert registration.classify(URL + '.html', ATOM)['p_reason'] == 'xml_adapter_needed'


def test_root_detection_is_bounded_and_stops_before_the_document_body(monkeypatch):
    inputs = []
    actual_feed = formats._DocumentStart.feed

    def feed(reader, value):
        inputs.append(len(value))
        return actual_feed(reader, value)

    monkeypatch.setattr(formats._DocumentStart, 'feed', feed)
    body = '<rss>' + '<entry>synthetic</entry>' * formats.MAX_DOCUMENT_PREFIX + '</rss>'
    assert formats.document_kind(body) == 'xml'
    assert inputs == [formats.MAX_DOCUMENT_PREFIX]
    assert formats.document_kind('<html><script>"<?xml?><rss>"</script></html>') == 'html'


def test_direct_helper_keeps_ambiguous_text_prefix_and_long_whitespace_behavior():
    body = 'Publisher introduction <event-calendar>' + LINKS + '</event-calendar>'
    assert formats.collection_evidence(URL, body)['p_reason'] == 'html_adapter_needed'
    # classify already rejected non-markup prefixes before this change; the
    # direct evidence helper retains its distinct, existing fragment behavior.
    assert registration.classify(URL, body)['p_reason'] == 'no_reusable_calendar'
    spaced = ' ' * formats.MAX_DOCUMENT_PREFIX + '<event-calendar>' + LINKS + '</event-calendar>'
    assert calendar.supports_listing(URL, spaced)


def test_declared_xml_without_a_root_inside_prefix_limit_stays_on_review():
    body = XML_DECLARATION + '<!--' + 'x' * formats.MAX_DOCUMENT_PREFIX + '--><html>' + LINKS + '</html>'
    assert formats.document_kind(body) == 'xml'
    assert registration.classify(URL, body)['p_reason'] == 'xml_adapter_needed'


@pytest.mark.parametrize('body', [None, b'<rss/>', '', 'ordinary text'])
def test_nontext_and_nonmarkup_have_no_html_document_identity(body):
    assert formats.document_kind(body) is None


def test_existing_ical_and_json_error_paths_still_precede_markup_detection():
    ical = 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR'
    assert registration.classify(URL, ical)['p_type'] == 'ical'
    assert registration.classify(URL, '{invalid')['p_reason'] == 'invalid_json'
