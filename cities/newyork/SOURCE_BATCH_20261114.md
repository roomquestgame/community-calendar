# New York City source expansion — 14 November 2026

This batch contains 23 new official calendars and five existing sources with no active public events at preflight. All five boroughs are represented. Existing sources already working in production are excluded from registration and recollection.

## Source groups

| Group | New sources | Repairs |
| --- | --- | --- |
| Arts, culture, family, makers and markets | Staten Island Museum; Queens County Farm Museum; Museum of the Moving Image; Poster House; Materials for the Arts; Lewis Latimer House; Historic Richmond Town; POWERHOUSE bookstores; Grand Bazaar NYC | Children's Museum of Manhattan; Staten Island Children's Museum |
| Nightlife, social, food, drink and games | Chilo’s; Forever Brewing; Fifth Hammer Brewing; Wonderville; Starr Bar; Skinny Dennis; Kills Boro; Sake Studies Center at Brooklyn Kura; Twenty Sided Store | None |
| Outdoors, fitness, volunteering and community | Queens Botanical Garden; Van Cortlandt Park Alliance; Fort Tryon Park Conservancy; Dyckman Run Club; Astoria Park Alliance | Lower East Side Ecology Center; Riverside Park Conservancy; Randall’s Island Park Alliance |

## Collection and publication contracts

Existing Tribe Events, Squarespace HTML and shared event normalizers are reused. Thin source-specific adapters handle the public Shopify program variants, brewery calendars and bookstore listings. Full native descriptions are restored after legacy normalizers and are accepted only when nonblank and at most 12,000 characters. Larger descriptions are held; none are silently clipped to fit.

Twelve detail-heavy calendars use the existing lease-bound durable checkpoint worker. A partial manifest cannot be marked complete or sent for publication. Requests use ordinary publisher transport, its robots policy, crawl pacing, host restrictions and deadlines. Disallowed Squarespace exports and Google Calendar feeds are not alternate routes.

Every accepted record carries a street, city/borough, state and ZIP. Exact named park intersections/segments are retained instead of invented house numbers. A source/venue/address/coordinate allowlist admits those locations. Approximate meeting points are visibly labeled in venue names; venue-specific points never come from the city-wide source selection center. NYC Broadway and New York Turnpike addresses receive narrowly bounded street-normalization rules.

Source identity is bound to source key, URL, kind, adapter and America/New_York timezone. Registration guards refuse a duplicate source/host, a changed repair identity, an active collection lease or any candidate already publishing successfully. The old IDs for all five repairs remain intact. The existing ordinary geocoder resolves numbered addresses without supplied points.

Publisher descriptions are captured in full before category classification. No geographic category overlay or new taxonomy is introduced. The existing v2 staging path consumes direct `image_url` candidates for registered geocoder sources; this release does not require a new publisher-media capability.

## Evidence and release order

The three `docs/evidence/new-york-*-research-2026-11-14.json` reports contain official URLs, address evidence, completeness counts and held candidates. Matching capture files retain accepted event identities and complete description hashes. Parser tests cover real page structures and the critical failure boundaries. Worker tests cover source identity, long narratives, exact street points and complete-only checkpoints.

The backend migration is `20261114222346_new_york_source_expansion.sql` in RoomQuestGame. Deploy the collector commit first, wait for the production deployment to be READY, then merge and manually dispatch one guarded database deployment from current main. The migration enrolls all 28 sources and creates one ordinary HTML-category wake. No per-source PRs or Actions runs are required.

Use `RoomQuestGame/docs/evidence/new-york-production-verification.sql` after ingestion to compare published descriptions and postal addresses to staging. Local captured-page replay is parser evidence; production success requires the deployment receipt, completed source snapshots and live event readback.
