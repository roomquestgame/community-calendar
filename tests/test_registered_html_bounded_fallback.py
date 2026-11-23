"""Bounded numbered pagination and structured HTML microdata fallback.

No loose text/date inference. Every successful record needs a publisher Event
scope, offset-aware time, publisher Place/PostalAddress, and canonical page.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
import pytest

from roomquest import registered_html_calendar as calendar
from roomquest import registered_native_content as native
from roomquest.registration_formats import source_key

BASE = "https://publisher.example.org"
INDEX = BASE + "/events"
ONE = BASE + "/event/class-one"
TWO = BASE + "/event/class-two"


def source():
    return {"feed_url": INDEX, "source_key": source_key(INDEX),
            "kind": "html", "platform_adapter": "html",
            calendar.CAPABILITY: 1, native.CAPABILITY: 1}


def index(urls, extra=""):
    return ('<html><main><h1>Upcoming Events</h1>' +
            "".join('<a href="' + url + '">Event details</a>' for url in urls) +
            extra + '</main></html>')


def detail(url, *, extra_event=False, naive=False, incomplete=False):
    at = (datetime.now(timezone.utc) + timedelta(days=4)).replace(microsecond=0)
    start = at.isoformat()
    if naive:
        start = at.replace(tzinfo=None).isoformat()
    address = '' if incomplete else (
        '<span itemprop="streetAddress">12 Main St</span>'
        '<span itemprop="addressLocality">Richmond</span>'
        '<span itemprop="addressRegion">VA</span>'
        '<span itemprop="postalCode">23220</span>')
    item = ('<article itemscope itemtype="https://schema.org/MusicEvent">'
            '<h1 itemprop="name">Community concert</h1>'
            '<time itemprop="startDate" datetime="' + start + '">Starts</time>'
            '<div itemprop="location" itemscope itemtype="https://schema.org/Place">'
            '<span itemprop="name">Publisher Hall</span>'
            '<div itemprop="address" itemscope itemtype="https://schema.org/PostalAddress">' +
            address + '</div></div>'
            '<p itemprop="description">A local concert.</p></article>')
    return ('<html><head><link rel="canonical" href="' + url + '"></head>'
            '<main>' + item + (item if extra_event else '') + '</main></html>')


def fetcher(pages):
    return Mock(side_effect=lambda url, _accept: pages[url])


def test_event_microdata_with_explicit_offset_and_complete_venue_is_accepted():
    fetch = fetcher({ONE: detail(ONE)})
    [row] = calendar.collect(source(), fetch, listing=index([ONE]))
    assert row["event_url"] == ONE
    assert row["venue_name"] == "Publisher Hall"
    assert row["venue_address"] == "12 Main St, Richmond, VA 23220"
    assert row["description"] == "A local concert."
    native.validate_record(row, source())
    assert fetch.call_count == 1


@pytest.mark.parametrize("kwargs", [
    {"naive": True}, {"incomplete": True}, {"extra_event": True},
])
def test_microdata_must_be_uniquely_scoped_offset_aware_and_located(kwargs):
    fetch = fetcher({ONE: detail(ONE, **kwargs)})
    with pytest.raises(ValueError, match="html_calendar_event_"):
        calendar.collect(source(), fetch, listing=index([ONE]))


def test_conflicting_jsonld_identity_cannot_be_overridden_by_microdata():
    import json
    foreign = {
        "@context": "https://schema.org", "@type": "Event",
        "@id": "https://publisher.example.org/event/other", "url": "https://publisher.example.org/event/other",
        "name": "Conflicting record", "startDate": "2027-01-20T12:00:00+00:00",
        "location": {"@type": "Place", "name": "Other"}
    }
    payload = detail(ONE).replace(
        "</head>", '<script type="application/ld+json">' +
        json.dumps(foreign) + '</script></head>')
    with pytest.raises(ValueError, match="html_calendar_detail_identity_conflict"):
        calendar.collect(source(), fetcher({ONE: payload}), listing=index([ONE]))


def test_unstructured_prose_does_not_create_an_event():
    prose = ('<html><main><h1>Concert on December 5</h1>'
             '<p>12 Main St. Come see us at 7 pm.</p></main></html>')
    with pytest.raises(ValueError, match="html_calendar_event_jsonld_missing"):
        calendar.collect(source(), fetcher({ONE: prose}), listing=index([ONE]))


def test_numbered_pager_fetches_next_page_before_details():
    page2 = INDEX + "?page=2"
    first = index([ONE], '<nav class="pagination"><span aria-current="page">1</span>'
                  '<a href="?page=2">2</a></nav>')
    second = index([TWO])
    fetch = fetcher({page2: second, ONE: detail(ONE), TWO: detail(TWO)})
    rows = calendar.collect(source(), fetch, listing=first)
    assert len(rows) == 2
    assert [call.args[0] for call in fetch.call_args_list] == [page2, ONE, TWO]


def test_bare_numbered_link_without_active_page_stays_held():
    fetch = Mock()
    with pytest.raises(ValueError, match="html_calendar_pagination_needed"):
        calendar.collect(source(), fetch, listing=index([ONE],
            '<nav class="pagination"><a href="?page=2">2</a></nav>'))
    fetch.assert_not_called()


def test_numbered_pager_does_not_erase_calendar_filters():
    url = INDEX + "?venue=one"
    invalid = INDEX + "?venue=two&page=2"
    fetch = Mock()
    listing = index([ONE], '<nav class="pagination">'
                    '<span aria-current="page">1</span>'
                    '<a href="' + invalid + '">2</a></nav>')
    with pytest.raises(ValueError, match="html_calendar_pagination_scope_conflict"):
        calendar.collect({**source(), "feed_url": url,
                          "source_key": source_key(url)}, fetch, listing=listing)
    fetch.assert_not_called()
