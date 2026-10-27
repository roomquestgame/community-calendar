#!/usr/bin/env python3
"""Inventory Udell's existing eight city catalogs for RoomQuest candidate staging.

No network requests, approvals or writes by default. Human/source-rights review
is mandatory. Use --post only with a real RoomQuest admin JWT held in environment,
never with an anonymous/public token or a service-role secret.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
AREAS = {
    "raleighdurham": "raleigh-durham-nc",
    "asheville": "asheville-nc", "bloomington": "bloomington-in",
    "davis": "davis-ca", "lancaster": "lancaster-pa",
    "montclair": "montclair-nj", "santarosa": "santa-rosa-ca",
    "toronto": "toronto-on",
}
API = "https://drpqjuqghpjivtwznfdj.supabase.co"
NOTE = "Inherited from Jon Udell community-calendar; rights, future events and precise venues unverified."


def catalog(city: str):
    if city not in AREAS:
        raise ValueError("Unsupported upstream catalog area")
    lines = (ROOT / "cities" / city / "feeds.txt").read_text(encoding="utf-8").splitlines()
    title = ""
    pending_cmd = None
    rows, skipped = [], []
    section = "feeds"
    for line in lines:
        stripped = line.strip()
        if stripped == "# --- Scrapers ---":
            section = "scrapers"
            continue
        if stripped.startswith("# cmd:"):
            pending_cmd = stripped[6:].strip()
            continue
        if stripped.startswith("#"):
            name = stripped[1:].strip()
            if name and not name.startswith("---") and not name.startswith("Generated") and not name.startswith("To add"):
                title = name
            continue
        if section == "feeds" and stripped.startswith("https://"):
            rows.append({
                "area_slug": AREAS[city], "publisher": title or "Unnamed publisher",
                "feed_url": stripped, "adapter": "ical", "kind": "ical", "note": NOTE,
            })
        elif section == "scrapers" and stripped.startswith("cities/"):
            cmd = pending_cmd or ""
            args = shlex.split(cmd) if cmd else []
            candidate = ""
            for flag in ("--url", "--api-base"):
                if flag in args and args.index(flag) + 1 < len(args):
                    candidate = args[args.index(flag) + 1]
                    break
            # Local generated *.ics files are not publisher URLs. A scraper
            # without a verifiable original endpoint needs manual curation.
            if not candidate.startswith("https://"):
                skipped.append({"publisher": title, "script": cmd[:150], "reason": "publisher_url_required"})
            else:
                adapter = "wordpress" if "tribe_" in cmd else (
                    "growthzone" if "growthzone" in cmd else
                    "simpleview" if "simpleview" in cmd else
                    "squarespace" if "squarespace" in cmd else "jsonld"
                )
                rows.append({
                    "area_slug": AREAS[city], "publisher": title or "Unnamed publisher",
                    "feed_url": candidate, "adapter": adapter, "kind": "json",
                    "note": NOTE + " Confirm actual API path and format.",
                })
            pending_cmd = None
            title = ""
    return rows, skipped


def post_pending(rows):
    token = os.environ.get("ROOMQUEST_ADMIN_JWT", "")
    key = os.environ.get("ROOMQUEST_PUBLISHABLE_KEY", "")
    if not token or not key:
        raise RuntimeError("ROOMQUEST_ADMIN_JWT and ROOMQUEST_PUBLISHABLE_KEY required in environment")
    # Never save credentials in this repo; RLS/RPC independently verifies app_admins.
    successes = 0
    for item in rows:
        request = urllib.request.Request(API + "/rest/v1/rpc/community_source_stage",
            data=json.dumps({
                "p_area_id": item["area_id"], "p_publisher": item["publisher"],
                "p_feed_url": item["feed_url"], "p_adapter": item["adapter"],
                "p_kind": item["kind"], "p_note": item["note"],
            }).encode("utf-8"),
            headers={"apikey": key, "Authorization": "Bearer " + token,
                     "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=10):
            successes += 1
    return successes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", choices=sorted(AREAS), default="raleighdurham")
    parser.add_argument("--out", default="-", help="JSON report path or - for stdout")
    parser.add_argument("--post", action="store_true", help="Stage only with a verified admin JWT")
    parser.add_argument("--area-id", type=int, help="Required for --post, from Admin Areas")
    args = parser.parse_args()
    rows, skipped = catalog(args.city)
    # Stable first occurrence: one calendar may appear twice in a publisher catalog.
    seen = set()
    unique = []
    for row in rows:
        if row["feed_url"] in seen:
            continue
        seen.add(row["feed_url"])
        unique.append(row)
    report = {"area": args.city, "area_slug": AREAS[args.city],
              "candidate_count": len(unique), "needs_manual_url": len(skipped),
              "candidates": unique, "skipped_scrapers": skipped}
    if args.post:
        if not args.area_id or args.area_id < 1:
            parser.error("--post requires a valid --area-id")
        report["staged"] = post_pending([dict(row, area_id=args.area_id) for row in unique])
    output = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out == "-":
        print(output)
    else:
        Path(args.out).write_text(output + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
