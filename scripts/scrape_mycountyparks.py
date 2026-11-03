#!/usr/bin/env python3
"""Read-only MyCountyParks scrape using the production parser and HTTP guards.

Example:
    python scripts/scrape_mycountyparks.py --county iowa --output iowa-events.json

This command has no database credentials and never stages or publishes events.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from roomquest.mycountyparks import COUNTIES, TZ, collect, source_for_county
from roomquest.preview_worker import PreviewError, fetch_publisher


def scrape_county(county, timeout, *, deadline_at=None):
    started = monotonic()
    deadline = min(started + timeout, deadline_at if deadline_at is not None else float("inf"))
    source = source_for_county(county)
    rows = collect(source, lambda url, accept: fetch_publisher(
        url, accept, respect_robots=True, deadline_at=deadline,
        allowed_hosts=("www.mycountyparks.com",),
    ), deadline_at=deadline)
    if monotonic() >= deadline:
        raise ValueError("collection_deadline")
    return {
        "source_key": source["source_key"],
        "source_url": source["feed_url"],
        "timezone": TZ.key,
        "event_count": len(rows),
        "events": rows,
    }


def scrape_all_counties(timeout, overall_timeout):
    """Explicit read-only audit; reuse robots rules and host pacing throughout."""
    started = monotonic()
    deadline = started + overall_timeout
    results = []
    for county in sorted(COUNTIES):
        source = source_for_county(county)
        identity = {"source_key": source["source_key"], "source_url": source["feed_url"]}
        if monotonic() >= deadline:
            results.append({**identity, "status": "not_attempted", "error": "audit_deadline"})
            continue
        try:
            result = scrape_county(county, timeout, deadline_at=deadline)
        except (PreviewError, ValueError) as exc:
            results.append({**identity, "status": "failed", "error": str(exc)})
            print(f"mycountyparks_audit_failed {county} {exc}", file=sys.stderr)
        else:
            results.append({**result, "status": "complete"})
    successful = sum(result["status"] == "complete" for result in results)
    failed = sum(result["status"] == "failed" for result in results)
    return {
        "scope": "all_counties",
        "timezone": TZ.key,
        "source_count": len(results),
        "complete": successful == len(results),
        "event_count": sum(result["event_count"] for result in results if result["status"] == "complete"),
        "successful_count": successful,
        "failed_count": failed,
        "not_attempted_count": len(results) - successful - failed,
        "per_source_timeout_seconds": timeout,
        "overall_timeout_seconds": overall_timeout,
        "elapsed_seconds": round(monotonic() - started, 3),
        "sources": results,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--county", choices=tuple(sorted(COUNTIES)))
    selection.add_argument("--all-counties", action="store_true",
                           help="Explicitly audit every catalog county; no database writes.")
    selection.add_argument("--list-counties", action="store_true",
                           help="Print known county source identities without network access.")
    parser.add_argument("--output", type=Path, help="Write JSON here; default is standard output.")
    parser.add_argument("--timeout", type=int,
                        help="Per-county budget, 10–300 seconds; default 120 for one county, 30 for all.")
    parser.add_argument("--overall-timeout", type=int, default=900,
                        help="All-county audit budget, 10–3600 seconds (default: 900).")
    args = parser.parse_args(argv)
    timeout = args.timeout if args.timeout is not None else (30 if args.all_counties else 120)
    if not 10 <= timeout <= 300:
        parser.error("--timeout must be between 10 and 300 seconds")
    if not 10 <= args.overall_timeout <= 3600:
        parser.error("--overall-timeout must be between 10 and 3600 seconds")

    started = monotonic()
    exit_code = 0
    if args.list_counties:
        output = {"source_count": len(COUNTIES),
                  "sources": [source_for_county(county) for county in sorted(COUNTIES)]}
        summary = f"{len(COUNTIES)} county definitions"
    elif args.all_counties:
        output = scrape_all_counties(timeout, args.overall_timeout)
        exit_code = 0 if output["complete"] else 1
        summary = (f"{output['event_count']} events across {output['successful_count']} complete county scrapes, "
                   f"{output['failed_count']} failed, {output['not_attempted_count']} not attempted")
    else:
        try:
            output = scrape_county(args.county, timeout)
        except (PreviewError, ValueError) as exc:
            print(f"Scrape failed: {exc}", file=sys.stderr)
            return 1
        summary = f"{output['event_count']} events"

    payload = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
        print(f"Wrote {summary} to {args.output} ({monotonic() - started:.1f}s).")
    else:
        print(payload, end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
