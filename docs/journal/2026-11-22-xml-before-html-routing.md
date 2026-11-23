# XML/feed routing before generic HTML discovery — November 22, 2026 (EST)

## Source finding and change

Generic registration treated every non-JSON markup response as HTML evidence,
and the registered HTML calendar helper admitted any string beginning with `<`.
RSS/XML responses could consequently reach BeautifulSoup's HTML parser, produce
`XMLParsedAsHTMLWarning`, or expose embedded HTML subscription/event links to
generic calendar discovery. Dedicated feed adapters already existed and must
retain their separate source identity, extraction and completion rules.

`registration_formats.document_kind` now performs a **bounded lexical
`HTMLParser` pass** over at most 65,536 characters and stops at the first root
tag. It reads document identity only: no full DOM, XML tree, DTD loading, external
entity resolution, or additional publisher request. This is not a claim of zero
HTMLParser usage. Positive XML evidence prevents the subsequent BeautifulSoup
HTML parse and generic HTML calendar navigation.

The shared guard is used in `feed_registration.classify`,
`registration_formats.collection_evidence`, and
`registered_html_calendar._html`. HTML feed recovery is also guarded so direct
calls cannot explore a positively identified feed as an HTML listing.

| Input evidence | Generic handling |
| --- | --- |
| XML declaration with a non-HTML root | Review as `xml_adapter_needed`. |
| RSS, Atom, RDF, sitemap, or existing GrowthZone XML root | Review as `xml_adapter_needed`. |
| Namespace-prefixed root, non-HTML default namespace, or non-HTML DOCTYPE | Review as `xml_adapter_needed`. |
| Unprefixed `html` root with an XML declaration and the XHTML namespace | Retain existing HTML parsing and native evidence. |
| Ordinary HTML, fragments, or ambiguous undeclared custom-element wrappers | Retain the existing HTML path and all existing collection checks. |
| JSON and iCalendar | Retain their existing earlier classifier/normalizer branches. |

The URL suffix is not format evidence. An HTML response at a `.xml` URL retains
HTML behavior, while an Atom response at a `.html` URL remains a feed. XML
markers inside comments or inside an already identified HTML document do not
change its document identity. HTML embedded inside an RSS/Atom envelope does not
authorize generic calendar discovery.

## Bounded detection and compatibility

The prefix limit is **characters, not bytes**. If no positive XML signal is
established within that prefix, ambiguous markup retains the previous HTML
fallback, including custom components and long initial comments. Direct
`collection_evidence` calls also retain their existing behavior for ambiguous
text-prefixed HTML fragments; its two production callers are the JSON branch
with a parsed object and the markup branch after the existing `<` guard.

If an XML declaration is established but the root cannot be identified within
the bounded prefix, the document remains on review: the HTML/XHTML exception
cannot be established within the detection budget. Normal and captured XHTML
roots inside that prefix remain supported without stripping declarations,
rewriting the payload, switching tree builders, or suppressing warnings.

This lexical check is not a general XML validator or a new feed adapter. Bare
custom markup without declarations or namespace evidence is intrinsically
ambiguous and retains the old path. Malformed or unsupported collections still
face the existing source scope, canonical URL, event identity, pagination,
completeness, deadline and native-content validation requirements.

## Preserved dedicated adapter precedence

Registration still selects known Wildlife/OpenActive and provider endpoints
before generic classification. Both regional Wildlife calendar URLs and their
RSS aliases retain their original identity and the `registered_html_jsonld_v1`
registration receipt. Sustainable Oakington/Westwick remains eligible for its
existing exact-URL registered-listings adapter after the generic review result.
Its RSS envelope is parsed by that dedicated adapter, not promoted to a generic
HTML source. Existing GrowthZone/ChamberMaster XML, Fáilte CSV, Forestry HTML,
and JSON provider paths remain in place.

No registry or source allowlist is expanded. No source is activated, paused,
registered, fetched live, or rewritten by preparing this patch. Existing
transport permissions, publisher pacing, robots rules, demand gates, tickets,
leases, staging, publication and receipt contracts are unchanged.

The live finish-registration definitions were checked read-only:
`public.community_collector_finish_registration` delegates through
`rq_curator_gateway.finish_feed_registration` to the private implementation.
For a `review` result the reason must be nonnull and match
`^[a-z0-9_]{1,100}$`; the source-type restriction applies to `verified` results.
Thus `review` with `p_type = NULL` and `xml_adapter_needed` fits the existing
argument contract. Ticket/lease validation still applies. No live finish call
was invoked to test this behavior.

## Local validation and handoff

Prepared against collector main
`d8bb1e256b54603562c84c1f2f1eba00f1db94da`, including concurrent #447 Fáilte
changes and #446 geocode admission. All 1,951 baseline file blobs were verified
against that exact Git tree. The current `AGENTS.md` owner policy keeps routine
GitHub Actions disabled; verification is local and uses mocked transport/RPCs.

```sh
python -m pytest tests/test_document_formats.py tests/test_feed_registration.py tests/test_registered_html_calendar.py tests/test_registered_html_pipeline.py tests/test_sustainable_ow.py tests/test_national_feeds.py tests/test_provider_registration.py tests/test_forestry_england.py tests/test_failte_ireland.py -q -W error::bs4.XMLParsedAsHTMLWarning
```

The format regressions reuse captured RSS, provider XML, publisher HTML, and
JSON fixtures, with an explicitly synthetic Atom envelope and XHTML/custom
wrapper variants. XML tests assert that BeautifulSoup and `CalendarLinks` are
not called; ordinary registration makes one initial fetch and finishes on review
without HTML recovery or detail fetches. Complete registration tests prove
HTML/XHTML/custom-wrapper success through the existing linked-detail parser.
Dedicated Wildlife alias/native-receipt, Sustainable Oakington, provider XML,
Forestry and Fáilte tests verify their original contracts separately.

Local result: **427 tests passed**, with `XMLParsedAsHTMLWarning` treated as an
error. Against the unchanged pinned baseline, the captured RSS plus a standard
XML declaration reproduced one warning in registration classification and one
in the HTML calendar helper. The synthetic Atom fixture also demonstrated the
behavioral issue: generic classification discovered the embedded XHTML
subscription URL. The candidate keeps that envelope on review without an HTML
parse or follow-up discovery.

This is a local review candidate. Record review, merge, deployment and ordinary
production observations separately. The patch removes known unnecessary
parsing/discovery paths and warning causes; it does not establish a measured
production CPU reduction or certify previously unsupported XML feeds.
