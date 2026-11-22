# Forestry England calendar fixtures

Captured on 22 November 2026 from exact public URLs. The corpus covers all 66
calendar scopes discovered in the official 3,455-URL sitemap plus the explicit
Dodd Wood calendar link in its Event location. It contains 70 calendar pages
(including all four Westonbirt pages and both Bedgebury pages) and 123 event
details. The manifest records original byte counts and SHA-256 hashes.

The reduced files retain canonical URLs, Drupal venue/event body types, event
headings, complete calendar cards and pagination, visible schedule fields,
and each native Event's identity, dated envelope, venue address, coordinates
and image facts. Production never loads this fixture inventory or uses it to
register sources. New forests using the same published layout are supported
without a URL table.

All original narrative prose has been replaced by explicitly synthetic text.
The complete-body fixture extends the structured summary to test that native
full descriptions survive extraction. Synthetic schedule notes preserve the
restriction keywords actually present in the original bodies (term time,
holidays, selected dates, and similar qualifiers). Original-source replay is
reported separately from these reduced fixtures.

Raw captures used the honest `EventQuest-research/1.0` user agent and no sign-in,
challenge bypass or inferred endpoint. A later production-transport probe
stopped before contacting the publisher with `dns_unavailable` in the local
container; no DNS guard was patched or bypassed. Registration in the deployed
environment remains the acceptance check.

Forestry England permits reuse of website information under the Open Government
Licence with attribution, excluding logos, images and identified third-party
material: <https://www.forestryengland.uk/article/crown-copyright>.
The fixture image fields exist to prove that the collector **does not stage
them**. No image bytes were downloaded or added.
