"""Guarded GrowthZone auto-discovery from normal publisher event listings."""
from unittest.mock import patch

from roomquest.feed_registration import growthzone_calendar_candidate, register
from roomquest.preview_worker import PreviewError

PAGE = "https://chamber.example.org/events"
NATIVE = "https://chamber.example.org/api/events"
LISTING = (
    "<h2>Events Calendar</h2><p>Results Found: 2</p>"
    '<a href="/events/details/community-gala-100">Gala</a>'
    '<a href="/events/details/author-talk-101">Author talk</a>'
)
XML = (
    "<ArrayOfEventDisplay><EventDisplay><Name>Gala</Name>"
    "<EventID>100</EventID><VisibilityFlags>Public</VisibilityFlags>"
    "</EventDisplay></ArrayOfEventDisplay>"
)


def test_candidate_requires_same_host_multiple_details_and_unfiltered_listing():
    assert growthzone_calendar_candidate(PAGE, LISTING) == NATIVE
    assert growthzone_calendar_candidate(PAGE + "?venue=East", LISTING) is None
    assert growthzone_calendar_candidate("https://chamber.example.org/venues/east", LISTING) is None
    assert growthzone_calendar_candidate(PAGE, '<h2>Events Calendar</h2>'
                                         '<a href="/events/details/community-gala-100">Gala</a>') is None
    foreign = LISTING.replace('/events/details/author-talk-101',
                              'https://other.example.org/events/details/author-talk-101')
    assert growthzone_calendar_candidate(PAGE, foreign) is None
    assert growthzone_calendar_candidate(PAGE, LISTING.replace("Events Calendar", "Homepage")) is None


def _run(profile=True, deny=False):
    receipts = []
    urls = []

    def rpc(method, args, **kwargs):
        if method == "community_collector_claim_registration":
            return {"url": PAGE}
        if method == "community_collector_feed_profile":
            assert (args["p_url"], args["p_adapter"]) == (NATIVE, "growthzone")
            return {"timezone": "America/New_York"} if profile else {}
        if method == "community_collector_finish_registration":
            receipts.append(args)
            return True
        raise AssertionError(method)

    def fetch(url, accept, **kwargs):
        assert kwargs["respect_robots"] is True
        urls.append(url)
        if url == PAGE:
            return LISTING
        if url == NATIVE:
            if deny:
                raise PreviewError("robots_denied")
            return XML
        raise AssertionError("Unexpected publisher URL: " + url)

    def collect_native(url, adapter, fetcher, *, deadline, profile=None, body=None):
        if not profile or not profile.get("timezone"):
            raise ValueError("source_timezone_required")
        return [{"event_url": PAGE + "/details/community-gala-100"}]

    with patch("roomquest.feed_registration.supabase_rpc", side_effect=rpc), \
         patch("roomquest.feed_registration.fetch_publisher", side_effect=fetch), \
         patch("roomquest.feed_registration.provider_registration.collect",
               side_effect=collect_native) as native:
        status = register("fixture-ticket")
    return status, receipts, urls, native.call_count


def test_native_xml_is_verified_before_discovery_and_reuses_provider():
    status, receipts, urls, calls = _run(profile=True)
    assert status == {"outcome": "discovered"}
    assert urls == [PAGE, NATIVE]
    assert calls == 1
    assert (receipts[0]["p_outcome"], receipts[0]["p_type"], receipts[0]["p_endpoint"]) == (
        "discovered", "growthzone", NATIVE
    )


def test_missing_timezone_retains_review_instead_of_fabricating_source_zone():
    status, receipts, urls, calls = _run(profile=False)
    assert status == {"outcome": "review"}
    assert urls[:2] == [PAGE, NATIVE]
    assert calls == 1
    assert receipts[0]["p_outcome"] == "review"
    assert receipts[0].get("p_endpoint") != NATIVE


def test_discovered_endpoint_denial_never_disables_accessible_original():
    status, receipts, urls, calls = _run(profile=True, deny=True)
    assert status == {"outcome": "review"}
    assert urls[:2] == [PAGE, NATIVE]
    assert calls == 0
    assert receipts[0]["p_outcome"] == "review"
