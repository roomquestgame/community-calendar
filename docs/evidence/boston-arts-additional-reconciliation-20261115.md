# Boston additional arts: concurrent deployment reconciliation

**The reconciled collector preserves all 285 captured occurrences exactly as the deployed parser produces them. The remaining changes strengthen checkpoint integrity and apply only targeted in-flight compatibility handling. Existing source registrations and completed public records are preserved.**

## Comparison and retained behavior

The exact comparison baseline is collector main `7798bd5886a7de4ac0635ab8c3bca79d4b3f9105`, after concurrent PR229 and NYC PR230. All eight source tuples already exist in production. Brookline Arts Center’s nine workshops and the Aquarium’s zero-eligible snapshot retain their output and identities.

The reconciled module retains the deployed native pagination guards; PEM series-envelope and Markdown handling; Eliot availability and offsite-address variants; MOS explicit year fallback; Aquarium hidden/virtual/cancelled exclusions; and strict Coolidge ticket endpoint validation. No current occurrence’s full body, title, clock, URL, venue, street, point or identity differs from the deployed parser on the same captures.

| Source | Captured occurrences |
|---|---:|
| Museum of Science, Boston | 5 |
| Coolidge Corner Theatre | 179 |
| Brookline Arts Center | 9 |
| Eliot School of Fine & Applied Arts | 24 |
| Harvard Museums of Science & Culture | 5 |
| Peabody Essex Museum | 56 |
| deCordova Sculpture Park and Museum | 7 |
| New England Aquarium | 0 |

PEM’s deployed manifest has 19 programs because it excludes two fully expired programs before hydration. The earlier research manifest retained those two only as expired diagnostics. Both parsers produce the same 56 occurrence IDs. One historical research body included the UI heading “Know before you go”; reconciliation preserves the deployed normalization without that heading and retains all program prose. Its corrected expected body hash is recorded in the JSON.

## In-flight checkpoint handling

The reviewed production snapshot was taken at 2026-11-15T01:24:44.177656+00:00.

| Source | Source ID | Saved cursor | Handling |
|---|---:|---:|---|
| Coolidge Corner Theatre | 5640 | 20/74 | Conditionally reset only if this incompatible legacy checkpoint still exists. |
| Peabody Essex Museum | 5651 | 12/19 | Conditionally reset only if this incompatible legacy checkpoint still exists. |
| Eliot School of Fine & Applied Arts | 5642 | 0/1 | Resume listing progress with empty proofs; original start/manifest/pages retained. |

Only a legacy checkpoint with both proof fields absent, an integer zero cursor, no saved events and no diagnostics is upgraded automatically. The collector adds empty outcome fields to a copy and then performs every normal manifest, page, identity, size, TTL and source validation. Processed legacy rows are never silently re-attested.

At deployment, recheck the current checkpoint state: an old worker may have advanced Eliot beyond zero, and another source may have completed. Reset and queue only an actual incompatible processed legacy checkpoint. Skip absent/completed generations and snapshots already carrying outcome proofs. Museum of Science, HMSC, deCordova, Brookline Arts Center and the Aquarium were already complete in the reviewed snapshot and require no forced refresh.

## Verification

- All 285 reconciled captured rows match the deployed parser on full descriptions and factual fields.
- All 80 saved event rows in the actual Coolidge/PEM legacy checkpoints match captured native data.
- Twenty-six focused tests pass, including processed legacy rejection, safe empty-result compatibility, exact ticket paths and retained availability filters.
- Fresh actual integrated worker replay passes all eight profiles with 285 identical staged rows, 169 publisher requests, 28 checkpoint writes and zero incomplete staging.
- Actual Eliot revision 2 resumes from its four already-read listing pages, preserves `2026-11-15T01:21:45.206540+00:00`, and completes with the same 24 rows in 33 requests/nine checkpoint writes, honoring its ten-second crawl delay.
- Independent review found no blocker in the legacy compatibility path. No GitHub or production mutation was performed by this agent.

## Deliverables

- [boston-arts-additional-reconciliation-20261115.json](boston-arts-additional-reconciliation-20261115.json) contains exact baseline/source identities, compatibility decisions, body hashes and worker receipts.
- Updated accepted rows: `/workspace/scratch/3aa56d09ac0a/boston-additional/arts/concurrent-reconciliation/accepted-rows-reconciled.json`.
- Earlier capture evidence remains historical; use the reconciled accepted-row file for the final expected-data readback.
- The one BAC weekday/date conflict remains held: the native registration link exposes only an ACTIVE JavaScript/cookie interstitial, without corroborating date/time.
