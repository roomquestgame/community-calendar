# EVE-170 immutable publisher semantics

This release carries original ICS all-day/date-end semantics, original series UID and recurrence anchor, and original publisher coordinates through the existing leased incremental staging protocol. It computes no canonical digest: PostgreSQL `event_content_v1` remains the sole authority.

Enrolled standard ICS profiles use the reviewed `ical-publisher-facts-1` normalization release value. Unrelated Python changes cannot invalidate their parser context. Increment that value only for an actual normalization-contract change; semantic processor versions are separate from source-content equality. Non-enrolled adapters retain the existing conservative context.

The standalone expanded UID format is unchanged for compatibility. Original recurrence evidence survives its transformation; cross-date moves still take ordinary backend identity/withdrawal reconciliation. Existing unsupported all-day publication remains unchanged. Operator-facing preview samples and legacy staging do not receive the new protocol-only metadata.

Release after protected backend migration `20261207062000`, which attaches immutable canonical inputs and distinguishes successful publication receipts from diagnostic `processed` markers. Backend activation is limited to the existing eligible +25 canary. This collector release does not enroll sources, queue collections or authorize +100/+500 expansion.

Focused result: 162 selected tests passed, with two pre-existing failures reproduced on unchanged main (old parser fixture parent-directory creation and stale 2k description cap). Five new tests cover moved recurrence anchors, nonmutating serialization, all-day exclusive dates/unknown end, immutable publisher coordinates and code-independent enrolled parser context. Actual authenticated canary baseline/repeat remains a separate production acceptance step.
