# Boston Public Library pagination repair

The first production run completed with **298 parsed and staged events**, while the captured source contained **306 eligible events**. Eight exact event IDs were absent from staging at every start time. This was separate from the publication address issue: the preview count itself was 298, so these eight were missing before database staging. The production readback is recorded in the batch owner's `boston-first-capture-readback-20261114.json` receipt.

## Publisher-supported correction

The public calendar's own [BiblioCommons JavaScript client](https://cdn-nerf.bibliocommons.com/app.main_fa15a6122f23d68a2374.js), linked by the [BPL event calendar](https://bpl.bibliocommons.com/v2/events), calls its event collection with `sort: "definition.start asc"`. The collector now requests that exact supported sort. It keeps the same reviewed source identity, hosts, full-description mapping, native branch coordinates and seven-day scope.

Previously the collection request had no explicit sort. Focused rereads of two pages showed radically different ordering despite the same total and page count. The exact production response pages were not retained, so the server-side overlap is an inference. The completed sorted capture verifies that the eight events remain current, and that the entire native ID set matches the original capture; this is not a date-window or cancelled-event difference.

Each checkpoint now retains the native total and all raw event IDs, including events outside the seven-day publication window. Repeated IDs, changed totals/page counts, or a final unique-ID shortfall fail before staging. Resumed checkpoints must use the exact sorted URLs and contain unique native IDs. The ordinary publisher transport, deadline, pacing and database checkpoint limits are unchanged.

## Verification

| Check | Result |
|---|---:|
| Native pages traversed | 33 |
| Native total / distinct IDs | 3,259 / 3,259 |
| Eligible physical events | 306 |
| Previously missing IDs recovered | 8 of 8 |
| Changed descriptions or street addresses | 0 |
| Complete checkpoint, UTF-8 JSON | 538,850 bytes |
| Complete checkpoint, ASCII-escaped JSON | 540,540 bytes |
| Database limit | 900,000 bytes |
| Actual integrated worker checkpoint writes | 17 |
| Actual integrated worker staged events | 306 |
| Events staged before complete native coverage | 0 |

Ten arts tests pass, including the new duplicate-ID and missing-ID cases. The tests also reject a resumed checkpoint using the former unsorted URL, reject a duplicated native-ID list, and preserve full descriptions beyond 2,000 characters.

The eight recovered records are four November 19 homework-help sessions, the November 20 ESOL conversation group, the November 20 youth poetry workshop, the November 21 Davey the Clown show, and the November 21 consumer-label workshop. Their exact IDs, descriptions' SHA-256 hashes, event URLs and streets appear in the adjacent JSON.

Raw sorted pages, rows, checkpoint, publisher-client proof and integrated worker replay are retained under `/workspace/scratch/3aa56d09ac0a/research/bpl-diagnosis/`. This agent issued no production refresh. The batch owner will conditionally queue the existing BPL source after the repaired collector is deployed and verify the resulting production rows.
