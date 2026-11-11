#!/usr/bin/env python3
"""Read-only validation of the Omaha and Lincoln rollout using collector transport."""

import argparse
import json
from pathlib import Path
import re
import sys
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roomquest import omaha_lincoln, preview_worker


def check(row):
    result = {"publisher": row["publisher"], "batch": row["batch"],
              "disposition": row["disposition"]}
    if row["disposition"] in {"Already covered", "Check coverage", "Publisher access", "Watch"}:
        return {**result, "outcome": "review", "reason": row["review"]}
    if "kind" not in row:
        return {**result, "outcome": "adapter_review", "reason": row["review"]}
    source = {
        "source_key": row["source_key"], "feed_url": row.get("registered_url") or row["feed_url"],
        "kind": row["kind"], "platform_adapter": row["adapter"], "timezone": "America/Chicago",
    }
    try:
        preview = preview_worker.preview_source(source, deadline_at=monotonic() + 40)
    except preview_worker.PreviewError as error:
        code = str(error)
        reason = code if re.fullmatch(r"[a-z0-9_]{3,100}", code) else "preview_failed"
        return {**result, "outcome": "failed", "reason": reason}
    records = preview["p_events"]
    return {**result, "outcome": "complete", "candidates": len(records),
            "with_street_address": sum(
                bool(re.match(r"^\d+\s", (record.get("venue_address") or "").strip()))
                for record in records
            )}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=int, choices=(1, 2), required=True)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=10, choices=range(1, 13))
    args = parser.parse_args()
    rows = [row for row in omaha_lincoln.intake_rows() if row["batch"] == args.batch]
    if not 0 <= args.offset < len(rows):
        parser.error("--offset must point to an entry in the selected batch")
    failed = False
    for row in rows[args.offset:args.offset + args.limit]:
        result = check(row)
        failed |= result["outcome"] == "failed"
        print(json.dumps(result), flush=True)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
