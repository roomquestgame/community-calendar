#!/usr/bin/env python3
"""Read-only capture of two reviewed public DCR pages using production guards.

No arbitrary URL input, database access, image requests, credentials, or network
fallback. The saved responses are publisher HTML, not synthetic test fixtures.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bs4 import BeautifulSoup, Tag
from roomquest.collector_errors import safe_error_code
from roomquest.preview_worker import MAX_BODY, PreviewError, fetch_publisher
from roomquest.virginia_state_parks import IMAGE_EXTRACTOR_VERSION, event_photo_candidate

PAGES = (
    ("archery-club", "https://www.dcr.virginia.gov/state-parks/event?id=2026-10-25-09-24-08-914874-7iv"),
    ("widewater-volunteers", "https://www.dcr.virginia.gov/state-parks/event?id=2026-09-08-13-24-45-158426-gse"),
)


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = capture(args.output_dir)
    print(json.dumps({"scope": report["scope"], "pages": [
        {key: page[key] for key in ("name", "status", "error", "bytes", "image_count", "selected_candidate") if key in page}
        for page in report["pages"]]}))
    return 0 if all(page["status"] == "complete" for page in report["pages"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
