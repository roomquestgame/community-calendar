# EVE-145 Batch002 collector handoff — verified 2026-11-19 14:28 ET

Batch002 is complete. No collector extraction or Vercel deployment was needed: the existing NPS adapter already stored the descriptions. The app-side rights projection is deployed through [PR #1353](https://github.com/roomquestgame/RoomQuestGame/pull/1353), merge `d1e48873f2e194450fe315c09d4c69e3510befb8`, protected [Database deploy #465](https://github.com/roomquestgame/RoomQuestGame/actions/runs/44597723104) SUCCESS, migration `20261130010000_eve145_nps_public_excerpts`.

Current bounded production readback: 6,081 linked eligible NPS occurrences, 6,081 nonempty stored descriptions, 6,080 meaningful by the >=40/not-title proxy, and 6,081 actual public excerpts. Every excerpt retains National Park Service attribution, an NPS source URL and the required government-work notice; lengths are 51–600 characters. The registry remains paused/deactivated, no duplicate provider or municipal collector was enabled, and `facts_only*` remains suppressed. The migration rewrites no event rows.

Exact sample OpenSEO before `fbbb765d-a604-4bda-8b36-386f1d74bc8f` versus after `56e7c225-87f1-4d26-8a04-561417013fdb`: 131→227 words, HTTP 200/indexable, thin warning cleared. Rendered About, attribution and source link were verified.

Next collector cursor is permission-limited, not an extraction patch: Riley has 110 staged / 97 meaningful and 27 stored / 0 descriptions but terms prohibit scrape/crawl and provide no commercial narrative grant; Apex has 20/20 staged and 18/0 stored with no affirmative reuse grant; Howard has 6/6 staged and 6/0 stored under noncommercial/personal terms forbidding reposting. Keep all three facts-only/restricted absent new affirmative evidence. Virginia Commonwealth Calendar remains facts/links-only.

---

# EVE-145 Batch002 collector handoff — 2026-11-19 10:45 ET

No collector extraction change was required or deployed in this batch. The existing NPS adapter already stores nonempty descriptions for all 6,154 linked upcoming occurrences measured (6,153 substantial by the >=40/not-title proxy). Batch002 is a narrowly reviewed public-projection change in app [PR #1324](https://github.com/roomquestgame/RoomQuestGame/pull/1324), not a new collector, source duplication or crawl.

Official NPS API/disclaimer evidence supports NPS-authored event-description reuse in external apps/websites with existing NPS attribution, original event URL and an explicit U.S.-Government-work notice; third-party material, images and marks remain excluded. The app migration leaves the municipal rights row paused/deactivated and preserves facts-only suppression. Production remains unchanged because the exact database replay [run #1713](https://github.com/roomquestgame/RoomQuestGame/actions/runs/44556719681) was blocked before a runner started by GitHub billing/spend-limit status. Do not merge/deploy until the exact current app head passes protected validation.

Current rights queue: Riley Street Art Supply has 110 upcoming staged / 97 meaningful but publisher terms prohibit spider/crawl/scrape and do not grant commercial narrative republication; Apex PRD has 20/20 but no affirmative reuse grant; Howard County Arts has 6/6 and its permission is noncommercial/personal with network reposting forbidden. These remain facts-only/restricted. No collector adapter changes, feed enrollment, provider duplication, forced crawl, event rewrite, Vercel collector deployment or mobile release occurred.

OpenSEO before: audit `fbbb765d-a604-4bda-8b36-386f1d74bc8f`, exact NPS sample HTTP 200/indexable, 131 words, thin warning present. After audit remains pending a verified protected deployment.

---

# Verified result — 2026-11-19 09:55 ET

Batch001 complete: same Think Iowa City event93158 stores2512characters (+512), matching upstream sanitized hash. Other12 existing descriptions and all13 IDs/titles/dates/timezones unchanged. Preview complete14:54:20UTC/errorNULL, publication queue drained. Public excerptNULL; final OpenSEO124→124words/thin warning unchanged. No public SEO gain.

CollectorPR318 deployed f38f8545bceed05af53ba14f1c07fe344cfa5c07, Vercel dpl_Ed2S4gkSPbfSWtj26dKk1APY8nN8 READY. AppPR1310 introduced a staging SQL alias-scope regression found in live validation; forward correctionPR1315/migration20261124193000/run44547972921 fixed it with procedural assertions, then normal queue retry succeeded. No applied migration edits. AppPR1314 provided bounded validation; PR1316 stores final13-ID measurements and complete receipts.

Authoritative current record: https://github.com/roomquestgame/RoomQuestGame/blob/main/docs/eve-145-description-audit.md and EVE-145. Hourly continuation uses shared atomic coordination ref automation/eve-145-execution-lock in app repo; do not rerun batch001. Next rights-review queue:NPS, then unreviewed Riley/Apex/Howard gaps. Earlier pending notes below are historical.

---

# EVE-145 — Think Iowa City batch 001

2026-11-19. Companion backend/audit PR: https://github.com/roomquestgame/RoomQuestGame/pull/1310

Deploy only after protected database workflow applies 20261124180000. Existing approved Think source #5106 supports bounded source narrative extraction. Event 93158 / external f9519f58-0d4c-4701-8369-c662f478dcba has 2,512 readable upstream characters, truncated to2,000 by generic TEC. This patch reparses only this exact enrolled source with the shared sanitizer at12,000. Generic TEC remains2,000. IDs, venue, dates, zone, attribution and URL unchanged; no extra fetches, crawl scope or queue expansion.

No rights/publication-mode or public600-character changes. Public excerpt is NULL before; expected NULL after. This is internal completeness, not a public SEO gain. Same-ID sanitized SHA256: f90cc41e86b18afcd3d5e7d85b97fbf6aee2e3473c934f9ade62aee2daf20f76. Production gain pending refresh/readback; do not claim512 restored until measured.

Validation:23 Iowa tests pass. Broader selected suite108 pass,10 subtests pass,1 pre-existing Madison Nov17 expired-fixture failure reproduced on unchanged baseline ffb9c4c86fde61e09ded83f32373ad261b226955. No routine GitHub CI dispatched.

Nationwide baseline and full source tables live in the private app repo docs/eve-145-description-audit.md and docs/audits/eve-145-*.csv. EVE-145 is central. Hourly continuation checks current branch/claim and active expansion jobs before mutations; resume this exact release, no duplicate batches. Next: same-ID stored/public readback, targeted OpenSEO, then ranked rights-review queue (NPS and three unreviewed staging/publication gaps). Empty Bellevue/ Triangle publisher descriptions and useful short Council Bluffs descriptions are not parser failures.
