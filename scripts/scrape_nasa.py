"""
Scrape NASA's CKAN open data catalog (data.nasa.gov).

API: CKAN package_search — offset pagination with rows/start.
~35K datasets, no API key required.
"""

import csv, json, time, sys, os
from urllib.request import urlopen, Request
from urllib.error import HTTPError

API = "https://data.nasa.gov/api/3/action/package_search"
ROWS = 1000
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nasa_catalog.csv")

CSV_COLS = [
    "id", "name", "description", "organization", "tags",
    "num_resources", "page_views", "url", "modified",
]


def api_get(params: dict, retries: int = 5) -> dict:
    url = API + "?" + "&".join(f"{k}={v}" for k, v in params.items())
    for attempt in range(retries):
        try:
            req = Request(url, headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (open-data-catalog)",
            })
            with urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())
        except HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                wait = min(2 ** (attempt + 1), 30)
                print(f"  HTTP {e.code}, retrying in {wait}s...", flush=True)
                time.sleep(wait)
                continue
            raise
        except Exception:
            if attempt < retries - 1:
                time.sleep(min(2 ** (attempt + 1), 15))
                continue
            return {}
    return {}


def extract_row(pkg: dict) -> dict:
    org = pkg.get("organization") or {}
    tags = [t.get("display_name", "") for t in (pkg.get("tags") or [])]
    tracking = pkg.get("tracking_summary") or {}
    name = pkg.get("name", "")
    return {
        "id": pkg.get("id", ""),
        "name": (pkg.get("title") or "").replace("\n", " ").strip(),
        "description": (pkg.get("notes") or "").replace("\n", " ").strip()[:500],
        "organization": (org.get("title") or org.get("name") or "").strip(),
        "tags": "; ".join(tags),
        "num_resources": pkg.get("num_resources", 0),
        "page_views": tracking.get("total", 0),
        "url": f"https://data.nasa.gov/dataset/{name}" if name else "",
        "modified": (pkg.get("metadata_modified") or "")[:10],
    }


def main():
    t0 = time.time()

    # Get total count
    data = api_get({"rows": "1", "start": "0"})
    if not data or not data.get("success"):
        print("ERROR: initial API call failed", flush=True)
        sys.exit(1)

    total = data["result"]["count"]
    print(f"NASA CKAN: {total:,} datasets to fetch\n", flush=True)

    all_rows = []
    start = 0

    while start < total:
        data = api_get({"rows": str(ROWS), "start": str(start)})
        if not data or not data.get("success"):
            print(f"  Failed at offset {start}, skipping batch", flush=True)
            start += ROWS
            continue

        results = data["result"]["results"]
        if not results:
            break

        batch = [extract_row(pkg) for pkg in results]
        all_rows.extend(batch)

        print(f"  {len(all_rows):>6,} / {total:,}  (offset {start})", flush=True)
        start += ROWS
        time.sleep(0.2)

    # Dedup by id
    seen = set()
    deduped = []
    for r in all_rows:
        if r["id"] not in seen:
            seen.add(r["id"])
            deduped.append(r)
    all_rows = deduped

    print(f"\nTotal after dedup: {len(all_rows):,}", flush=True)

    # Write CSV
    all_rows.sort(key=lambda r: (r["organization"], r["name"].lower()))
    print(f"Writing to {OUT}...", flush=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS)
        w.writeheader()
        w.writerows(all_rows)

    # Stats
    from collections import Counter
    org_counts = Counter(r["organization"] for r in all_rows)
    print(f"\nTop 20 organizations:")
    for o, c in org_counts.most_common(20):
        print(f"  {c:>8}  {o[:60]}")

    print(f"\nDone in {time.time()-t0:.0f}s ({(time.time()-t0)/60:.1f}m)", flush=True)


if __name__ == "__main__":
    main()
