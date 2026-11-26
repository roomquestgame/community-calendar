# EVE-174 — publisher main-site event links

After the location correction, original receipts1514 Z-arts and1540 Plano moved to spektrix_event_link_unverified. Robots checks on both publisher ticketing hosts returned404 (no advertised restriction). Exact publisher APIs returned200: Z-arts webUrl points to www.z-arts.org; Plano webUrl points to planosymphony.org. Both are the same organizations as their approved tickets subdomains.

Ordinary inferred profiles now admit only the exact parent organization domain and its www alias for event links when the canonical API uses the existing tickets/ticketing/boxoffice/booking/book prefix. Stored reviewed profiles remain authoritative. No new API fetch hosts, central Spektrix access, unrelated siblings or cross-publisher links are admitted. Existing HTTPS, credential and fragment checks remain unchanged.

Validation:92 focused tests plus4 subtests pass, including both live publisher link shapes, co.uk handling, invalid/cross-publisher links, central API exclusion and existing working/venue cases. Deploy through existing protected PR/production Vercel route, then recheck original1514/1540 in Admin; no duplicate registration.
