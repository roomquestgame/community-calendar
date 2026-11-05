# Iowa expansion — November 5, 2026

Independence Library uses its exact enrolled CivicPlus ICS feed and the existing
on-demand ICS lane. Full descriptions opt in only for this source. Each timed
occurrence requires an explicitly advertised same-host `/calendar.aspx?EID=UID`
link; the collector never invents it. At most 20 already eligible details are
fetched within the existing 20-second source deadline and publisher guards.
Detail title/start must match ICS. The actual PostalAddress and full narrative
are retained; no discovery coordinates become event pins.

The captured feed has two VEVENTs: Lego UID 5975, Nov 16 6–7 p.m. Central
(00:00–01:00 UTC Nov 17), and date-only UID 5956 (Oct 19–Nov 6 exclusive end).
The latter is logged as `unsupported_all_day_time` and withheld, including when
already ongoing. This is timed-event coverage, not full all-day support.

The event's detail photo is `/ImageRepository/Document?documentID=10215`.
This batch does not enroll ICS in the verified HTML image lane or enable the
disabled legacy media backlog. Photo publication remains an explicit gap.
Publisher categories remain empty when absent; full factual narrative reaches
shared classification through the companion backend migration.

## Read-only evidence

Fixtures are exact publisher responses fetched by curl on November 5. Python
requests may return misleading empty 404 responses in this environment; that is
not proof the publisher feed is unavailable. Production uses its established
transport without an alternate policy-bypassing fallback.

- `independence-library.ics` SHA-256 `e9f4fd037f7781bf11f551f45741d306053b0e4a693d8b87d3da2befdb5ff18c`
- `independence-lego.html` SHA-256 `702160c835b1b6c0cd3a2ac3000b613202e06cc937b28ac6ba049924fc57942c`
