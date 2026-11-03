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

from roomquest.mycountyparks import collect, source_for_county
from roomquest.preview_worker import PreviewError, fetch_publisher


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--county", required=True, choices=("iowa", "johnson", "linn", "story"))
    parser.add_argument("--output", type=Path, help="Write JSON here; default is standard output.")
    parser.add_argument("--timeout", type=int, default=120,
                        help="Overall read-only scrape budget in seconds (10–300; default: 120).")
    args = parser.parse_args(argv)
    if not 10 <= args.timeout <= 300:
        parser.error("--timeout must be between 10 and 300 seconds")

    started = monotonic()
    deadline = started + args.timeout
    source = source_for_county(args.county)
    try:
        rows = collect(source, lambda url, accept: fetch_publisher(
            url, accept, respect_robots=True, deadline_at=deadline,
            allowed_hosts=("www.mycountyparks.com",),
        ), deadline_at=deadline)
    except (PreviewError, ValueError) as exc:
        print(f"Scrape failed: {exc}", file=sys.stderr)
        return 1
    output = {
        "source_key": source["source_key"],
        "source_url": source["feed_url"],
        "timezone": "America/Chicago",
        "event_count": len(rows),
        "events": rows,
    }
    payload = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
        print(f"Wrote {len(rows)} events to {args.output} ({monotonic() - started:.1f}s).")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
