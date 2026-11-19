"""The Hall: first-party, fail-closed Webflow calendar contracts."""
from datetime import datetime, timezone
from roomquest.hall_bourbon_ga import URL, KEY, ZONE, parse, collect, event_url, photo_url

NOW = datetime(2026, 11, 19, 16, tzinfo=timezone.utc)
EVENT = "https://tixr.com/e/201143"
IMG = "https://cdn.prod.website-files.com/68ffc927e723da37f0cde31f/art.webp"

def html(date="November 20, 2026", title="Nappy Roots", doors="6:00 pm",
         show="7:30 pm", url=EVENT, street="312 Jesse Jewell Pkwy, Gainesville, GA 30501"):
    return f"""
    <div class="cal-info w-dyn-item"><a class="cal-card-link" href="{url}">
    <p class="b-venue date">{date}</p><div class="b-show">{title}</div>
    <div class="times"><div class="home_events-preview_header-text space">Door Time:</div>
    <div class="home_events-preview_header-text">{doors}</div></div>
    <div class="times"><div class="home_events-preview_header-text space">Show Time:</div>
    <div class="home_events-preview_header-text">{show}</div></div>
    <div class="event-info_featuring-wrapper">Featuring: Nappy Roots</div>
    <div class="poster" style="background-image:url('{IMG}')"></div></a></div>
    <footer>{street}</footer>
    <section><h2>Rock night fever</h2>123 Sample St, Sydney</section>
    """

def test_publisher_clock_venue_image_and_demo_rejection():
    s = {"source_key": KEY, "feed_url": URL, "kind": "html", "platform_adapter": "html", "timezone": ZONE}
    items = collect(s, lambda url, accept: html(), now=NOW)
    assert len(items) == 1
    x = items[0]
    assert x["event_url"] == EVENT
    assert "2026-11-21T00:30:00+00:00" in x["starts_at"]
    assert x["venue_address"] == "312 Jesse Jewell Pkwy, Gainesville, GA 30501"
    assert x["image_url"] == IMG
    assert "Nappy Roots" in x["description"]
    assert x["publisher_details"]["door_time"] == "18:00:00"

def test_missing_dates_clocks_real_street_and_cancelled():
    for values in ({"date": "November 20"}, {"show": ""}, {"show": "TBD"},
                   {"doors": "7:45 pm"}, {"street": "Gainesville, GA"},
                   {"title": "CANCELLED Nappy Roots"},
                   {"date": "November 20, 2025"}):
        sample = html(**values)
        if values.get("street"):
            try:
                parse(sample, now=NOW)
                assert False, "missing venue must fail closed"
            except ValueError as exc:
                assert str(exc) == "publisher_venue_unverified"
        else:
            assert parse(sample, now=NOW) == []

def test_bad_tickets_and_asset_domains():
    for url in ("https://evil.example/e/201143", "https://tixr.com/e/201143?x=1",
                "https://tixr.com@evil.example/e/201143", "http://tixr.com/e/201143"):
        assert not event_url(url)
        assert not parse(html(url=url), now=NOW)
    assert photo_url(IMG) == IMG
    assert photo_url("https://cdn.prod.website-files.com/not-this-publisher/art.webp") is None

def test_requires_correct_source_registration():
    source = {"source_key": KEY, "feed_url": URL, "kind": "html", "platform_adapter": "html", "timezone": ZONE}
    for key, bad in (("feed_url", "https://evil.example/"), ("timezone", "UTC"),
                     ("source_key", "wrong")):
        clone = dict(source)
        clone[key] = bad
        try:
            collect(clone, lambda url, accept: html(), now=NOW)
            assert False, "wrong source must reject"
        except ValueError as exc:
            assert str(exc) == "unregistered_hall_bourbon_source"
