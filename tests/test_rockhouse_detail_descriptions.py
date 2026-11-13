"""Exact event-page prose is retained without navigating beyond the event link."""
from datetime import datetime, timezone
from html import escape
from unittest.mock import Mock

import pytest

from roomquest import preview_worker, rockhouse


NOW = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
URL = "https://reverblounge.com/event/a-show/reverb-lounge/"
ROW = {"id": URL, "event_url": URL, "title": "A Show", "starts_at": "2026-11-21T02:00:00+00:00"}
NARRATIVE = "The band brings its new songs to Omaha, with an opening set from a local quartet."


def detail(*, url=URL, title="A Show", day="Friday, November 20", time="Show: 8 pm", body=NARRATIVE):
    narrative = "" if body is None else f'<div class="singleEventDescription">{body}</div>'
    return f"""<html><head><link rel="canonical" href="{escape(url)}">
      <meta name="description" content="Buy tickets and subscribe to our venue newsletter."></head>
      <body><nav>Site navigation</nav><main id="RhpEventsSingle">
      <div class="singleEventDetails"><h1>{escape(title)}</h1>
      <span class="eventStDate">{escape(day)}</span>
      <div class="eventDoorStartDate">Doors: 7 pm // {escape(time)}</div>
      {narrative}<a href="https://tickets.example/checkout">Buy Tickets</a></div></main>
      <footer>Newsletter and unrelated venue footer</footer></body></html>"""


def test_exact_page_keeps_scoped_narrative_and_removes_markup():
    page = detail(body=f"<p>{NARRATIVE}</p><style>.promo {{ color: red; }}</style>"
                       "<script>do_not_collect()</script><nav>Unrelated navigation</nav>")
    assert rockhouse.description_from_detail(page, ROW) == NARRATIVE


@pytest.mark.parametrize("change", [
    {"url": "https://reverblounge.com/event/another-show/reverb-lounge/"},
    {"url": "https://tickets.example/event/a-show"},
    {"title": "Another show"},
    {"day": "Saturday, November 21"},
    {"time": "Show: 9 pm"},
    {"time": "Doors: 8 pm"},
])
def test_unmatched_event_page_cannot_erase_or_replace_description(change):
    with pytest.raises(ValueError, match="rockhouse_detail_identity_mismatch"):
        rockhouse.description_from_detail(detail(**change), ROW)


@pytest.mark.parametrize("body", [None, "", "  A Show  "])
def test_matched_page_without_useful_body_is_explicitly_empty(body):
    assert rockhouse.description_from_detail(detail(body=body), ROW) == ""


def test_meaningful_short_publisher_copy_is_kept():
    assert rockhouse.description_from_detail(detail(body="No cover."), ROW) == "No cover."


@pytest.mark.parametrize("page", [
    detail().replace('rel="canonical"', 'rel="alternate"'),
    detail().replace('<link rel="canonical"', f'<link rel="canonical" href="{URL}"><link rel="canonical"'),
])
def test_missing_or_ambiguous_canonical_is_not_an_empty_description(page):
    with pytest.raises(ValueError, match="rockhouse_detail_identity_mismatch"):
        rockhouse.description_from_detail(page, ROW)


def test_unrecognized_or_ambiguous_event_body_requires_review():
    for page in [detail().replace('class="singleEventDetails"', 'class="unrelated"'),
                 detail(body=NARRATIVE + '<div class="singleEventDescription">Unrelated</div>')]:
        with pytest.raises(ValueError, match="rockhouse_detail_structure_missing"):
            rockhouse.description_from_detail(page, ROW)


@pytest.mark.parametrize("key", ["omaha_reverb_lounge_events", "omaha_sydney_rockhouse_ne"])
def test_explicit_detail_collection_uses_only_event_link_and_keeps_listing_identity(monkeypatch, key):
    monkeypatch.setattr(preview_worker, "_future_datetime", lambda value: value.astimezone(timezone.utc))
    listing, suffix, _, _ = rockhouse.SOURCES[key]
    origin = listing.removesuffix("events/")
    url = f"{origin}event/a-show/{suffix}"
    source = {"source_key": key, "feed_url": listing, "timezone": rockhouse.ZONE,
              "kind": "html", "platform_adapter": "html"}
    calendar = f"""<body><h1>Upcoming Events</h1><div class="generalView">
      <div class="rhp-events-list-separator-month">November 2026</div>
      <div class="rhpSingleEvent"><span class="singleEventDate">Fri, Nov 20</span>
      <a id="eventTitle" href="{url}"><h2>A Show</h2></a>
      <span class="rhp-event__time-text--list">Doors: 7 pm // Show: 8 pm</span>
      </div></div></body>"""
    pages = {listing: calendar, url: detail(url=url)}
    fetch = Mock(side_effect=lambda requested, accept: pages[requested])
    original = rockhouse.collect(source, fetch, now=NOW)
    fetch.assert_called_once_with(listing, "text/html")
    fetch.reset_mock()
    enriched = rockhouse.collect(source, fetch, now=NOW, enrich_details=True)
    assert fetch.call_args_list == [((listing, "text/html"),), ((url, "text/html"),)]
    assert len(enriched) == len(original) == 1
    assert enriched[0]["description"] == NARRATIVE
    assert {k: v for k, v in enriched[0].items() if k != "description"} == original[0]
