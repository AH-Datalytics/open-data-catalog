"""
Scrape data.gov catalog for all datasets.

API: catalog.data.gov/search (new April 2026 API)
- Cursor-based pagination (no offset — must use `after` token)
- No total count returned — paginate until no more `after`
- ~532K datasets expected
- No API key required

Strategy: paginate through all results with per_page=100, following
cursor tokens. Shard by organization to parallelize.
"""

import csv, json, time, sys, os, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import urlopen, Request
from urllib.parse import urlencode, quote
from urllib.error import HTTPError

API = "https://catalog.data.gov"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "datagov_catalog.csv")

CSV_COLS = [
    "id", "name", "description", "organization", "org_type", "publisher",
    "keywords", "themes", "has_spatial", "popularity",
    "last_harvested", "source_platform",
]

_lock = threading.Lock()
_seen_ids = set()
_all_rows = []


def api_get(path: str, params: dict = None, retries: int = 5) -> dict:
    url = f"{API}{path}"
    if params:
        url += "?" + urlencode(params, doseq=True)
    for attempt in range(retries):
        try:
            req = Request(url, headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (open-data-catalog)",
            })
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except HTTPError as e:
            if e.code in (400, 404):
                return {}
            if e.code in (429, 500, 502, 503, 504):
                wait = min(2 ** (attempt + 1), 30)
                time.sleep(wait)
                continue
            raise
        except Exception:
            if attempt < retries - 1:
                time.sleep(min(2 ** (attempt + 1), 15))
                continue
            return {}
    return {}


def extract_row(item: dict) -> dict:
    org = item.get("organization", {}) or {}
    keywords = item.get("keyword", []) or []
    themes = item.get("theme", []) or []
    return {
        "id": item.get("identifier", item.get("slug", "")),
        "name": (item.get("title") or "").replace("\n", " ").strip(),
        "description": (item.get("description") or "").replace("\n", " ").strip()[:500],
        "organization": org.get("name", "") if isinstance(org, dict) else str(org),
        "org_type": org.get("organization_type", "") if isinstance(org, dict) else "",
        "publisher": (item.get("publisher") or "").replace("\n", " ").strip(),
        "keywords": "; ".join(keywords) if isinstance(keywords, list) else str(keywords),
        "themes": "; ".join(themes) if isinstance(themes, list) else str(themes),
        "has_spatial": item.get("has_spatial", ""),
        "popularity": item.get("popularity", ""),
        "last_harvested": item.get("last_harvested_date", ""),
        "source_platform": "data.gov",
    }


def scrape_org(org_slug: str, org_name: str):
    """Paginate through all datasets for one organization."""
    local_new = 0
    after = None
    pages = 0

    while True:
        params = {"per_page": "100", "org_slug": org_slug}
        if after:
            params["after"] = after

        data = api_get("/search", params)
        results = data.get("results", [])
        if not results:
            break

        batch = []
        for item in results:
            iid = item.get("identifier", item.get("slug", ""))
            if iid:
                with _lock:
                    if iid not in _seen_ids:
                        _seen_ids.add(iid)
                        batch.append(extract_row(item))

        if batch:
            with _lock:
                _all_rows.extend(batch)
            local_new += len(batch)

        after = data.get("after")
        if not after:
            break
        pages += 1
        time.sleep(0.1)

    with _lock:
        total = len(_all_rows)
    if local_new > 0:
        print(f"  {org_name[:50]:50s} [{org_slug}]: +{local_new:>6} ({total:>7} total)", flush=True)


def scrape_unaffiliated():
    """Paginate through datasets not tied to a specific org."""
    local_new = 0
    after = None

    while True:
        params = {"per_page": "100", "q": "*"}
        if after:
            params["after"] = after

        data = api_get("/search", params)
        results = data.get("results", [])
        if not results:
            break

        batch = []
        for item in results:
            iid = item.get("identifier", item.get("slug", ""))
            if iid:
                with _lock:
                    if iid not in _seen_ids:
                        _seen_ids.add(iid)
                        batch.append(extract_row(item))

        if batch:
            with _lock:
                _all_rows.extend(batch)
            local_new += len(batch)

        after = data.get("after")
        if not after:
            break
        time.sleep(0.1)

    print(f"  Catch-all pass: +{local_new} new", flush=True)


def main():
    t0 = time.time()

    # Step 1: Get all organizations
    print("Fetching organizations...", flush=True)
    data = api_get("/api/organizations")
    orgs = data.get("organizations", [])
    orgs.sort(key=lambda o: -o.get("dataset_count", 0))
    total_expected = sum(o.get("dataset_count", 0) for o in orgs)
    print(f"Found {len(orgs)} orgs, {total_expected:,} expected datasets\n", flush=True)

    # Step 2: Scrape each org (concurrent, but gentle)
    print("Scraping by organization (4 workers)...\n", flush=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(scrape_org, o["slug"], o["name"]): o["slug"]
            for o in orgs
        }
        for f in as_completed(futures):
            f.result()

    print(f"\nAfter org scrape: {len(_all_rows)} items", flush=True)

    # Step 3: Catch-all pass for anything not in an org
    print("\nRunning catch-all pass...", flush=True)
    scrape_unaffiliated()

    print(f"\nTotal: {len(_all_rows)} items", flush=True)

    # Write CSV
    _all_rows.sort(key=lambda r: (r["organization"], r["name"].lower()))
    print(f"Writing to {OUT}...", flush=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS)
        w.writeheader()
        w.writerows(_all_rows)

    # Stats
    from collections import Counter
    org_counts = Counter(r["organization"] for r in _all_rows)
    org_types = Counter(r["org_type"] or "(none)" for r in _all_rows)

    print(f"\nOrg types:")
    for t, c in org_types.most_common():
        print(f"  {c:>8}  {t}")
    print(f"\nTop 20 organizations:")
    for o, c in org_counts.most_common(20):
        print(f"  {c:>8}  {o[:60]}")

    print(f"\nDone in {time.time()-t0:.0f}s ({(time.time()-t0)/60:.1f}m)", flush=True)


if __name__ == "__main__":
    main()
