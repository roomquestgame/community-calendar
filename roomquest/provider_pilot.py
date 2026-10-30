"""Manual three-source release verification; leases must be granted by an operator."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import md5
from time import monotonic
from roomquest.preview_worker import _process_claimed_source


def pilot_sources():
    sources = [{"source_key": "municipal_chambermaster_orangeburg_sc",
                "feed_url": "https://business.orangeburgchamber.com/api/events",
                "platform_adapter": "growthzone", "kind": "xml",
                "timezone": "America/New_York"}]
    for url, tz in [("https://fraziermuseum.org/calendar?format=json", "America/Kentucky/Louisville"),
                    ("https://missiongarden.org/events?format=json", "America/Phoenix")]:
        sources.append({"source_key": "municipal_" + md5(url.lower().encode()).hexdigest()[:24],
                        "feed_url": url, "platform_adapter": "squarespace", "kind": "json", "timezone": tz})
    return sources


def collect_pilot():
    # No claim RPC, settings write, geocoder call or publication. The existing
    # staging RPC refuses sources without a live, operator-created source lease.
    deadline = monotonic() + 45
    sources = pilot_sources()
    def run(source):
        return {"source_key": source["source_key"],
                **_process_claimed_source(source, deadline_at=deadline)}
    with ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(run, sources))
    return {"sources": rows, "complete": sum(r["complete"] for r in rows),
            "failed": sum(r["failed"] for r in rows), "staged": sum(r["staged"] for r in rows)}
