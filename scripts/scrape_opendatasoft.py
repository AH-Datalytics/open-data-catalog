"""
Scrape OpenDataSoft global catalog for all datasets.

API: data.opendatasoft.com/api/explore/v2.1/catalog/datasets
- Offset cap at 30,000 — must shard by language to get full 57K
- ~57K datasets expected

Strategy: shard by language (fr, en, de, nl, etc.) + a catch-all,
each shard under 30K, then dedup.
"""

import csv, json, time, sys, os
from urllib.request import urlopen, Request
from urllib.parse import urlencode, quote
from urllib.error import HTTPError

API = "https://data.opendatasoft.com/api/explore/v2.1/catalog/datasets"
PAGE = 100
MAX_OFFSET = 29900
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "opendatasoft_catalog.csv")

CSV_COLS = [
    "id", "name", "description", "domain", "publisher", "language",
    "keywords", "themes", "license", "records_count", "fields_count",
    "created", "modified", "has_geo", "source_platform",
]

# Shard by language to stay under 30K per shard
LANG_SHARDS = ["fr", "en", "de", "nl", "es", "it", "sv", "pt", "ca", "eu", "da", "fi", "no", "ro", "pl"]


def api_get(params: dict, retries: int = 4) -> dict:
    url = f"{API}?{urlencode(params)}"
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
                return {"total_count": 0, "results": []}
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(2 ** (attempt + 1))
                continue
            raise
        except Exception:
            if attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            return {"total_count": 0, "results": []}
    return {"total_count": 0, "results": []}


def extract_row(item: dict) -> dict:
    ds = item.get("dataset", item)
    metas = ds.get("metas", {})
    default = metas.get("default", {})
    keywords = default.get("keyword", []) or []
    themes = default.get("theme", []) or []
    fields = ds.get("fields", []) or []
    has_geo = any(f.get("type") in ("geo_point_2d", "geo_shape") for f in fields)

    return {
        "id": ds.get("dataset_id", ds.get("datasetid", "")),
        "name": (default.get("title") or ds.get("dataset_id", "")).replace("\n", " ").strip(),
        "description": (default.get("description") or "").replace("\n", " ").replace("\r", " ").strip()[:500],
        "domain": ds.get("catalog_domain_url", ds.get("domain", "")),
        "publisher": (default.get("publisher") or "").replace("\n", " ").strip(),
        "language": default.get("language") or "",
        "keywords": "; ".join(keywords) if isinstance(keywords, list) else str(keywords),
        "themes": "; ".join(themes) if isinstance(themes, list) else str(themes),
        "license": default.get("license") or "",
        "records_count": default.get("records_count") or ds.get("nb_hits", ""),
        "fields_count": len(fields),
        "created": default.get("created") or "",
        "modified": default.get("modified") or "",
        "has_geo": has_geo,
        "source_platform": "OpenDataSoft",
    }


def paginate_shard(where_clause: str, label: str, seen: set) -> list:
    """Paginate one shard, return new rows."""
    rows = []
    offset = 0
    data = api_get({"limit": 0, "where": where_clause})
    total = data.get("total_count", 0)

    while offset <= min(total, MAX_OFFSET):
        params = {"limit": PAGE, "offset": offset, "where": where_clause}
        data = api_get(params)
        results = data.get("results", [])
        if not results:
            break
        for item in results:
            ds = item.get("dataset", item)
            did = ds.get("dataset_id", ds.get("datasetid", ""))
            if did and did not in seen:
                seen.add(did)
                rows.append(extract_row(item))
        offset += PAGE
        time.sleep(0.1)

    print(f"  {label}: {total} total, {len(rows)} new", flush=True)
    return rows


def main():
    t0 = time.time()
    seen = set()
    all_rows = []

    # Get total
    data = api_get({"limit": 0})
    total = data.get("total_count", 0)
    print(f"Total datasets in catalog: {total:,}\n", flush=True)

    # Shard by language
    for lang in LANG_SHARDS:
        where = f'default.language="{lang}"'
        rows = paginate_shard(where, f"lang={lang}", seen)
        all_rows.extend(rows)

    # Catch-all for datasets with no language or unlisted languages
    # Use "NOT IN" filter
    lang_conditions = " AND ".join(f'default.language!="{l}"' for l in LANG_SHARDS)
    rows = paginate_shard(lang_conditions, "other languages", seen)
    all_rows.extend(rows)

    # Also try with no language filter to catch anything missed
    rows = paginate_shard("*", "catch-all", seen)
    all_rows.extend(rows)

    print(f"\nTotal fetched: {len(all_rows)}", flush=True)

    # Write CSV
    all_rows.sort(key=lambda r: (r["domain"], r["name"].lower()))
    print(f"Writing to {OUT}...", flush=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS)
        w.writeheader()
        w.writerows(all_rows)

    # Stats
    from collections import Counter
    domains = Counter(r["domain"] for r in all_rows)
    langs = Counter(r["language"] or "(none)" for r in all_rows)
    geo = sum(1 for r in all_rows if r["has_geo"])

    print(f"\nUnique domains: {len(domains)}")
    print(f"With geo data: {geo:,}")
    print(f"\nLanguages:")
    for l, c in langs.most_common(15):
        print(f"  {c:>6}  {l}")
    print(f"\nTop 20 domains:")
    for d, c in domains.most_common(20):
        print(f"  {c:>6}  {d}")
    print(f"\nDone in {time.time()-t0:.0f}s ({(time.time()-t0)/60:.1f}m)", flush=True)


if __name__ == "__main__":
    main()
