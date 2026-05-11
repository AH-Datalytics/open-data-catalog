"""
Scrape NOAA's OneStop catalog (data.noaa.gov).

API: OneStop search/collection — POST-based with offset pagination.
~114K collections, no API key required.
"""

import csv, json, time, sys, os
from urllib.request import urlopen, Request
from urllib.error import HTTPError

API = "https://data.noaa.gov/onestop/api/search/search/collection"
PAGE = 100
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "noaa_catalog.csv")

CSV_COLS = [
    "id", "name", "description", "organization", "keywords",
    "data_formats", "num_links", "url", "modified",
]


def api_post(body: dict, retries: int = 5) -> dict:
    raw = json.dumps(body).encode()
    for attempt in range(retries):
        try:
            req = Request(API, data=raw, headers={
                "Content-Type": "application/json",
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


def extract_row(item: dict) -> dict:
    attrs = item.get("attributes", {})
    orgs = attrs.get("organizationNames", []) or []
    org = orgs[0] if orgs else "NOAA"
    # Truncate verbose org names
    if len(org) > 80:
        org = org[:77] + "..."
    keywords = attrs.get("keywords", []) or []
    formats = [f.get("name", "") for f in (attrs.get("dataFormats") or [])]
    links = [l for l in (attrs.get("links") or []) if l.get("linkUrl")]
    file_id = attrs.get("fileIdentifier", item.get("id", ""))
    return {
        "id": file_id,
        "name": (attrs.get("title") or "").replace("\n", " ").strip(),
        "description": (attrs.get("description") or "").replace("\n", " ").strip()[:500],
        "organization": org,
        "keywords": "; ".join(keywords)[:200],
        "data_formats": "; ".join(formats),
        "num_links": len(links),
        "url": links[0]["linkUrl"] if links else "",
        "modified": "",  # OneStop doesn't expose a clean modified date
    }


def main():
    t0 = time.time()

    # Get total count
    data = api_post({
        "queries": [], "filters": [],
        "page": {"max": 1, "offset": 0}, "facets": False, "summary": False,
    })
    if not data or "data" not in data:
        print("ERROR: initial API call failed", flush=True)
        sys.exit(1)

    total = data.get("meta", {}).get("total", 0)
    print(f"NOAA OneStop: {total:,} collections to fetch\n", flush=True)

    all_rows = []
    offset = 0

    while offset < total:
        body = {
            "queries": [], "filters": [],
            "page": {"max": PAGE, "offset": offset},
            "facets": False, "summary": False,
        }
        data = api_post(body)
        if not data or "data" not in data:
            print(f"  Failed at offset {offset}, skipping batch", flush=True)
            offset += PAGE
            continue

        results = data.get("data", [])
        if not results:
            break

        batch = [extract_row(item) for item in results]
        all_rows.extend(batch)

        print(f"  {len(all_rows):>7,} / {total:,}  (offset {offset})", flush=True)
        offset += PAGE
        time.sleep(0.3)

    # Dedup by id
    seen = set()
    deduped = []
    for r in all_rows:
        if r["id"] and r["id"] not in seen:
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
