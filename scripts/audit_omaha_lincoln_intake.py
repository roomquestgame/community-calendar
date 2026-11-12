#!/usr/bin/env python3
"""Read-only validation of the Omaha and Lincoln rollout using collector transport."""

import argparse
import json
from pathlib import Path
import re
import sys
from time import monotonic
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roomquest import community_formats, ics_adapter, mapsee_adapter, omaha_lincoln, preview_worker


BATCH_TWO_PROBES = {
    "Omaha Public Library": ("library_rss", "https://omaha.bibliocommons.com/events/rss/all"),
    "Sarpy Chamber": ("chambermaster_xml", "https://www.sarpychamber.org/api/events"),
    "University of Nebraska Omaha": ("localist", "https://events.unomaha.edu"),
    "University of Nebraska–Lincoln": ("ical", "https://events.unl.edu/upcoming/?format=ics&limit=-1"),
}


def candidate_counts(records):
    return {"candidates": len(records),
            "with_street_address": sum(
                bool(re.match(r"^\d+\s", (record.get("venue_address") or "").strip()))
                for record in records),
            "with_coordinates": sum(
                record.get("lat") is not None and record.get("lng") is not None
                for record in records)}


def probe_batch_two(format_name, url):
    """Test a proposed public feed without registering or publishing it."""
    source = {"feed_url": url, "url": url, "timezone": "America/Chicago"}
    host = urlsplit(url).hostname
    deadline = monotonic() + 35

    def fetch(candidate, accept):
        return preview_worker.fetch_publisher(candidate, accept, respect_robots=True,
                                              deadline_at=deadline, allowed_hosts=(host,))

    if format_name == "localist":
        return mapsee_adapter.collect(source, {"type": "localist"}, fetch)
    if format_name == "library_rss":
        return community_formats.parse_rss(fetch(url, "application/rss+xml,application/xml"),
                                           {**source, "platform_adapter": "library"}, source["timezone"])
    if format_name == "chambermaster_xml":
        return preview_worker.parse_growthzone_preview(fetch(url, "application/xml"), source)
    return ics_adapter.parse(fetch(url, "text/calendar"), source)


def check(row):
    result = {"publisher": row["publisher"], "batch": row["batch"],
              "disposition": row["disposition"]}
    probe = BATCH_TWO_PROBES.get(row["publisher"]) if row["batch"] == 2 else None
    if probe:
        format_name, url = probe
        try:
            records = probe_batch_two(format_name, url)
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            code = str(error)
            reason = code if re.fullmatch(r"[a-z0-9_]{3,100}", code) else "preview_failed"
            return {**result, "outcome": "review", "format": format_name, "reason": reason}
        return {**result, "outcome": "read_only_preview", "format": format_name,
                **candidate_counts(records)}
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
    return {**result, "outcome": "complete", **candidate_counts(preview["p_events"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=int, choices=(1, 2), required=True)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    rows = [row for row in omaha_lincoln.intake_rows() if row["batch"] == args.batch]
    if not 0 <= args.offset < len(rows):
        parser.error("--offset must point to an entry in the selected batch")
    if not 1 <= args.limit <= (12 if args.batch == 1 else len(rows)):
        parser.error("--limit is outside the selected batch bounds")
    failed = False
    for row in rows[args.offset:args.offset + args.limit]:
        result = check(row)
        failed |= result["outcome"] == "failed"
        print(json.dumps(result), flush=True)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
