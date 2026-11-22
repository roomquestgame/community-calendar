# Reviewed publisher calendar navigation

Morgan State registration #446 submits https://www.morgan.edu/. Its published
Events anchor points to https://events.morgan.edu/. The old same-host calendar
locator could not follow this first-party subdomain and left the receipt in
`html_adapter_needed` despite the existing Localist collector.

The registration parser now has a reviewed source-to-calendar map. It follows
only an exact anchor actually present in the exact submitted page. It does not
infer ownership from a domain suffix, crawl arbitrary external links, broaden
filtered URLs, or act in endpoint-only mode. Existing explicit subscriptions
retain precedence. The mapped calendar uses the existing robots-aware fetch,
same destination host redirect restriction and original 35-second budget.
Localist's published script fingerprint discovers its canonical collection API;
the existing child endpoint workflow independently verifies and normalizes it
before source creation. No approval, status, schedule or database behavior changes.

Publisher evidence captured November 21, 2026 (Eastern): homepage Events link;
calendar robots HTTP200, one-second crawl delay, root and collection API allowed;
calendar HTTP200 with existing Localist fingerprint; API HTTP200, one page,
40 publisher records. Replaying that response through the existing bounded
collector yields 29 normalized event occurrences, with actual venue addresses
and publisher coordinates where supplied. These are extraction results, not
registration, publication or Events/Map acceptance claims.

Focused verification: 54 tests pass across publisher navigation, registration,
Localist, LibCal and provider registration. Tests cover exact source/link proof,
near-miss domains, filtered/department/single-event URLs, endpoint-only checks,
missing destination evidence, robots/403/rate-limit handling, request budget
and the unchanged discovered-endpoint handoff. No routine CI or schedule added.

Deployment and original receipt Admin recheck remain to be verified after merge.
