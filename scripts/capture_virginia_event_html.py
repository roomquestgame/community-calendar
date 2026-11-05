#!/usr/bin/env python3
"""Read-only capture of reviewed public DCR pages using production guards.

The default remains two fixed photo examples. A reviewed manifest can capture
at most 350 known official event URLs for a fingerprinted details repair. There
is no listing crawl, database access, image request, credential, or fallback.
The saved responses are publisher HTML, not synthetic test fixtures.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
from time import monotonic
from urllib.parse import parse_qs, urlparse
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bs4 import BeautifulSoup, Tag
from roomquest.collector_errors import safe_error_code
from roomquest.preview_worker import MAX_BODY, PreviewError, fetch_publisher
from roomquest.virginia_state_parks import (DETAILS_EXTRACTOR_VERSION, EVENT_ID,
    IMAGE_EXTRACTOR_VERSION, ROOT, catalog, event_photo_candidate, parse_event)

PAGES = (
    ("archery-club", "https://www.dcr.virginia.gov/state-parks/event?id=2026-10-25-09-24-08-914874-7iv"),
    ("widewater-volunteers", "https://www.dcr.virginia.gov/state-parks/event?id=2026-09-08-13-24-45-158426-gse"),
)
MANIFEST_VERSION = "virginia_event_details_capture_v1"
MAX_MANIFEST_EVENTS = 350
MAX_MANIFEST_BYTES = 1_000_000
MAX_CAPTURE_BYTES = 60_000_000
MAX_CAPTURE_SECONDS = 1200


def tag_identity(tag):
    return {"tag": tag.name, "id": str(tag.get("id", ""))[:200],
            "classes": list(tag.get("class", []))[:15], "role": str(tag.get("role", ""))[:100]}


def image_summary(html, url):
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one("main") or soup.select_one("article") or soup.body
    images = soup.find_all("img")
    summaries = []
    for index, image in enumerate(images[:200]):
        summaries.append({"index": index,
            "attributes": {key: str(image.get(key, ""))[:2000]
                           for key in ("src", "alt", "title", "width", "height", "loading",
                                       "data-src", "data-lazy-src", "srcset", "itemprop")},
            "tag_html": str(image)[:4000],
            "ancestors": [tag_identity(tag) for tag in list(image.parents)[:12] if isinstance(tag, Tag)],
            "preceding_headings": [{"tag": tag.name, "text": tag.get_text(" ", strip=True)[:300]}
                                   for tag in image.find_all_previous(re.compile(r"^h[1-6]$"), limit=6)],
        })
    candidate = None
    title = ""
    if main is not None:
        section = BeautifulSoup(str(main), "html.parser")
        for tag in section.select("script,style,nav,footer,noscript"):
            tag.decompose()
        heading = section.find("h1")
        title = heading.get_text(" ", strip=True) if heading else ""
        candidate = event_photo_candidate(soup, section, url, title)
    return {"title": title, "main": tag_identity(main) if main else None,
            "parser_version": IMAGE_EXTRACTOR_VERSION, "selected_candidate": candidate,
            "image_count": len(images), "images": summaries,
            "headings": [{"tag": tag.name, "text": tag.get_text(" ", strip=True)[:300]}
                         for tag in soup.find_all(re.compile(r"^h[1-6]$"))[:100]]}


def capture(output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    deadline = monotonic() + 45
    results = []
    stopped = False
    for name, url in PAGES:
        result = {"name": name, "source_url": url,
                  "observed_at": datetime.now(timezone.utc).isoformat()}
        if stopped or monotonic() >= deadline:
            results.append({**result, "status": "not_attempted", "error": "publisher_audit_stopped"})
            continue
        try:
            html = fetch_publisher(url, "text/html", respect_robots=True,
                                   deadline_at=deadline, allowed_hosts=("www.dcr.virginia.gov",))
            raw = html.encode("utf-8")
            if len(raw) > MAX_BODY:
                raise ValueError("audit_html_oversized")
            (output_dir / (name + ".html")).write_bytes(raw)
            result.update(status="complete", bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                          html_file=name + ".html", **image_summary(html, url))
        except (PreviewError, ValueError, OSError) as exc:
            result.update(status="failed", error=safe_error_code(exc))
            # A denied/unavailable publisher is not retried through another
            # page, client, user agent, transport, or proxy.
            stopped = True
        results.append(result)
    report = {"scope": "two_fixed_dcr_event_pages", "read_only": True, "pages": results}
    (output_dir / "audit.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def _utc(value):
    if not isinstance(value, str) or len(value) > 50:
        raise ValueError("audit_timestamp_invalid")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("audit_timestamp_invalid") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("audit_timestamp_invalid")
    return result.astimezone(timezone.utc)


def load_manifest(path):
    """Validate the complete reviewed scope before making any publisher call."""
    raw = path.read_bytes()
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("audit_manifest_oversized")
    try:
        manifest = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("audit_manifest_invalid") from exc
    if (not isinstance(manifest, dict) or set(manifest) != {"version", "observed_at", "events"}
            or manifest["version"] != MANIFEST_VERSION or not isinstance(manifest["events"], list)
            or not 1 <= len(manifest["events"]) <= MAX_MANIFEST_EVENTS):
        raise ValueError("audit_manifest_invalid")
    _utc(manifest["observed_at"])
    parks = catalog()
    ids, urls = set(), set()
    required = {"event_id", "source_key", "event_url", "title", "starts_at", "ends_at"}
    for event in manifest["events"]:
        if (not isinstance(event, dict) or not required <= set(event)
                or set(event) - required - {"baseline_fingerprint"}):
            raise ValueError("audit_event_invalid")
        event_id, key, url = event["event_id"], event["source_key"], event["event_url"]
        try:
            if not isinstance(event_id, str) or str(UUID(event_id)) != event_id:
                raise ValueError("audit_event_identity_invalid")
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("audit_event_identity_invalid") from exc
        if not isinstance(key, str) or key not in {"virginia_state_parks_" + code for code in parks}:
            raise ValueError("audit_source_invalid")
        if not isinstance(url, str) or len(url) > 250:
            raise ValueError("audit_url_invalid")
        try:
            parsed = urlparse(url)
            page_ids = parse_qs(parsed.query).get("id", [])
            if (len(page_ids) != 1 or not EVENT_ID.fullmatch(page_ids[0])
                    or url != ROOT + "/state-parks/event?id=" + page_ids[0]):
                raise ValueError("audit_url_invalid")
        except (ValueError, TypeError) as exc:
            raise ValueError("audit_url_invalid") from exc
        if event_id in ids or url in urls:
            raise ValueError("audit_duplicate_event")
        ids.add(event_id)
        urls.add(url)
        if not isinstance(event["title"], str) or not 1 <= len(event["title"].strip()) <= 180:
            raise ValueError("audit_title_invalid")
        start = _utc(event["starts_at"])
        if event["ends_at"] is not None and _utc(event["ends_at"]) < start:
            raise ValueError("audit_end_invalid")
        fingerprint = event.get("baseline_fingerprint")
        if fingerprint is not None and (not isinstance(fingerprint, str)
                or not re.fullmatch(r"(?:[0-9a-f]{32}|[0-9a-f]{64})", fingerprint)):
            raise ValueError("audit_fingerprint_invalid")
    return manifest, hashlib.sha256(raw).hexdigest()


def _write_report(output_dir, report):
    # Preserve bounded progress even if an external job timeout interrupts the
    # remaining pages. This is an artifact checkpoint, never a database write.
    pending = output_dir / "audit.json.tmp"
    pending.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    pending.replace(output_dir / "audit.json")


def capture_manifest(output_dir, manifest_path, *, overall_timeout=MAX_CAPTURE_SECONDS):
    if not isinstance(overall_timeout, (int, float)) or not 30 <= overall_timeout <= MAX_CAPTURE_SECONDS:
        raise ValueError("audit_timeout_invalid")
    manifest, manifest_sha = load_manifest(manifest_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(exist_ok=True)
    deadline = monotonic() + overall_timeout
    total_bytes, stopped = 0, False
    parks = catalog()
    report = {"scope": "reviewed_virginia_event_details", "read_only": True,
              "manifest_version": MANIFEST_VERSION, "manifest_sha256": manifest_sha,
              "baseline_observed_at": manifest["observed_at"], "requested_events": len(manifest["events"]),
              "started_at": datetime.now(timezone.utc).isoformat(),
              "details_parser_version": DETAILS_EXTRACTOR_VERSION,
              "photo_parser_version": IMAGE_EXTRACTOR_VERSION,
              "limits": {"events": MAX_MANIFEST_EVENTS, "body_bytes": MAX_BODY,
                         "total_response_bytes": MAX_CAPTURE_BYTES, "overall_seconds": overall_timeout},
              "pages": []}
    _write_report(output_dir, report)
    for expected in manifest["events"]:
        url, event_id = expected["event_url"], expected["event_id"]
        result = {"name": event_id, "source_url": url, "expected": expected,
                  "observed_at": datetime.now(timezone.utc).isoformat()}
        if stopped or monotonic() >= deadline - 5:
            result.update(status="not_attempted", error="publisher_audit_stopped" if stopped else "audit_deadline")
            report["pages"].append(result)
            continue
        try:
            # One existing guarded request per exact manifest URL. Neither the
            # parser nor this diagnostic follows registration or image links.
            html = fetch_publisher(url, "text/html", respect_robots=True,
                                   deadline_at=min(deadline, monotonic() + 45),
                                   allowed_hosts=("www.dcr.virginia.gov",))
            raw = html.encode("utf-8")
            if len(raw) > MAX_BODY or total_bytes + len(raw) > MAX_CAPTURE_BYTES:
                raise ValueError("audit_html_oversized")
            total_bytes += len(raw)
            html_name = event_id + ".html.gz"
            (raw_dir / html_name).write_bytes(gzip.compress(raw, mtime=0))
            result.update(status="captured", bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                          html_file="raw/" + html_name)
            soup = BeautifulSoup(html, "html.parser")
            main = soup.select_one("main") or soup.select_one("article") or soup.body
            if main is not None:
                fragment = str(main).encode("utf-8")
                main_name = event_id + ".main.html.gz"
                (raw_dir / main_name).write_bytes(gzip.compress(fragment, mtime=0))
                result.update(main_file="raw/" + main_name, main_bytes=len(fragment),
                              main_sha256=hashlib.sha256(fragment).hexdigest())
        except (PreviewError, ValueError, OSError) as exc:
            result.update(status="failed", error=safe_error_code(exc))
            # A publisher denial, outage or transport-policy failure is never
            # retried through another page, client, credential or proxy.
            stopped = True
        else:
            try:
                park_code = expected["source_key"].removeprefix("virginia_state_parks_")
                record = parse_event(html, url, parks[park_code])
                result.update(status="complete", record=record, eligible=record is not None)
                if record is not None:
                    matches = {
                        "provider_event_id": record["id"] == "vsp:" + park_code + ":" + parse_qs(urlparse(url).query)["id"][0],
                        "event_url": record["event_url"] == url,
                        "title": record["title"] == expected["title"],
                        "starts_at": _utc(record["starts_at"]) == _utc(expected["starts_at"]),
                        "ends_at": (_utc(record["ends_at"]) if record.get("ends_at") else None)
                            == (_utc(expected["ends_at"]) if expected["ends_at"] else None),
                    }
                    result.update(matches=matches, identity_and_schedule_match=all(matches.values()))
            except (ValueError, TypeError, KeyError, OverflowError) as exc:
                # An individual changed/unsupported event is review evidence;
                # it does not justify a blind repair or hide the other pages.
                result.update(status="parse_failed", error=safe_error_code(exc))
        report["pages"].append(result)
        report["response_bytes"] = total_bytes
        _write_report(output_dir, report)
        print(json.dumps({"event": len(report["pages"]), "total": report["requested_events"],
                          "event_id": event_id, "status": result["status"],
                          "identity_and_schedule_match": result.get("identity_and_schedule_match")}), flush=True)
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    report["response_bytes"] = total_bytes
    _write_report(output_dir, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path,
                        help="Reviewed known-event manifest; omit for the two fixed photo examples")
    parser.add_argument("--overall-timeout", type=int, default=MAX_CAPTURE_SECONDS,
                        help="Manifest capture deadline, 30 to 1200 seconds")
    args = parser.parse_args()
    try:
        report = (capture_manifest(args.output_dir, args.manifest, overall_timeout=args.overall_timeout)
                  if args.manifest else capture(args.output_dir))
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": safe_error_code(exc)}))
        return 1
    print(json.dumps({"scope": report["scope"], "pages": [
        {key: page[key] for key in ("name", "status", "error", "bytes", "image_count", "selected_candidate") if key in page}
        for page in report["pages"]]}))
    return 0 if all(page["status"] == "complete" for page in report["pages"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
