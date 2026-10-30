# Provider collector deployment — October 30, 2026

Ben authorized deploying and testing Orangeburg ChamberMaster, Frazier History Museum and Mission Garden while keeping Udell publisher job 33 off. App database release 41045737873 installed their registrations with 155 aligned migrations; ChamberMaster and media remain disabled. No collection Cron is added.

The existing Vercel production deployment dpl_9mbFmm8h15545eyQYUHkhoj22ewr identifies e6ef67bdba3695a927ae4f437db1930180d4be1f, a branch diverged from collector main. Preserve its forward_geocoder.py exactly before deploying the provider additions on main. Its postal-locality tolerance is already deployed behavior; tests now distinguish that behavior from wrong street, number or state. Database validation and quota remain authoritative. No collector-side SQL migrations from that branch are applied.

Local targeted collector/provider/geocoder/venue/media/Mapsee tests, Python compilation and diff whitespace checks pass. Deployment and authenticated intake receipts follow separately. Operator secrets must remain in Vercel; listing key metadata does not authorize revealing them. The current connector can fetch protected deployment URLs but supplies no application Authorization header. No production credential was retrieved, source enabled, source claimed, private intake written or publisher job reactivated during preparation.

## Scoped manual endpoint

/api/provider-pilot accepts only an empty operator-authenticated POST. It has no Cron and accepts no source IDs or URLs. Its fixed three reviewed source objects reuse the existing transport and private staging RPC. It never calls generic claims, geocoding or publication. A privileged operator must explicitly mark exactly source IDs 4827, 4888 and 4897 running before the bounded test; normal staging/preview validation remains active. Pending Orangeburg stays pending and its global provider disabled. Three distinct publishers run concurrently within the existing bounded worker deadline. Authentication/body/source-isolation tests and the targeted suite pass: 110 tests plus 10 subtests. No source setting has changed yet.
