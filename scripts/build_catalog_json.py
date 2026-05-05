"""
Normalize Socrata, data.gov, and OpenDataSoft catalogs into compact JSON
for the standalone HTML explorer. ArcGIS Hub will be added when it finishes.

Output: open_data_catalog.json (loaded by the HTML explorer)
"""

import csv, json, os, sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(SCRIPT_DIR, "open_data_catalog.json")

def load_socrata():
    path = os.path.join(SCRIPT_DIR, "socrata_all_assets.csv")
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "n": (r["name"] or "")[:120],
                "d": (r["description"] or "")[:150],
                "s": "Socrata",
                "o": r.get("domain") or r.get("owner_name") or "",
                "ot": "",  # no org_type in socrata
                "c": r.get("category") or "",
                "t": r.get("type") or "dataset",
                "k": (r.get("tags") or "")[:200],
                "p": int(r["page_views_total"]) if r.get("page_views_total") and r["page_views_total"].isdigit() else 0,
                "dl": int(r["download_count"]) if r.get("download_count") and r["download_count"].isdigit() else 0,
                "u": r.get("permalink") or "",
                "dt": (r.get("data_updated_at") or r.get("created_at") or "")[:10],
            })
    return rows

def load_datagov():
    path = os.path.join(SCRIPT_DIR, "datagov_catalog.csv")
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "n": (r["name"] or "")[:120],
                "d": (r["description"] or "")[:150],
                "s": "data.gov",
                "o": (r.get("organization") or r.get("publisher") or "")[:80],
                "ot": r.get("org_type") or "",
                "c": (r.get("themes") or "")[:80],
                "t": "dataset",
                "k": (r.get("keywords") or "")[:200],
                "p": int(float(r["popularity"])) if r.get("popularity") and r["popularity"].replace(".","",1).isdigit() else 0,
                "dl": 0,
                "u": "",  # data.gov doesn't give direct URLs in search results
                "dt": (r.get("last_harvested") or "")[:10],
            })
    return rows

def load_ods():
    path = os.path.join(SCRIPT_DIR, "opendatasoft_catalog.csv")
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "n": (r["name"] or "")[:120],
                "d": (r["description"] or "")[:150],
                "s": "OpenDataSoft",
                "o": (r.get("publisher") or r.get("domain") or "")[:80],
                "ot": "",
                "c": (r.get("themes") or "")[:80],
                "t": "dataset",
                "k": (r.get("keywords") or "")[:200],
                "p": int(r["records_count"]) if r.get("records_count") and r["records_count"].isdigit() else 0,
                "dl": 0,
                "u": "",
                "dt": (r.get("modified") or r.get("created") or "")[:10],
            })
    return rows

def load_arcgis():
    path = os.path.join(SCRIPT_DIR, "arcgis_hub_catalog.csv")
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "n": (r["name"] or "")[:120],
                "d": (r.get("description") or "")[:150],
                "s": "ArcGIS Hub",
                "o": (r.get("org_name") or r.get("owner") or "")[:80],
                "ot": r.get("sector") or "",
                "c": "",
                "t": r.get("type") or "dataset",
                "k": (r.get("tags") or "")[:200],
                "p": int(r["record_count"]) if r.get("record_count") and r["record_count"].isdigit() else 0,
                "dl": 0,
                "u": r.get("url") or "",
                "dt": (r.get("modified") or r.get("created") or "")[:10],
            })
    return rows

def main():
    print("Loading sources...", flush=True)
    socrata = load_socrata()
    print(f"  Socrata: {len(socrata):,}", flush=True)
    datagov = load_datagov()
    print(f"  data.gov: {len(datagov):,}", flush=True)
    ods = load_ods()
    print(f"  OpenDataSoft: {len(ods):,}", flush=True)
    arcgis = load_arcgis()
    print(f"  ArcGIS Hub: {len(arcgis):,}", flush=True)

    all_rows = socrata + datagov + ods + arcgis
    print(f"\nTotal: {len(all_rows):,}", flush=True)

    # Build summary stats
    from collections import Counter
    sources = Counter(r["s"] for r in all_rows)
    org_types = Counter(r["ot"] for r in all_rows if r["ot"])
    top_orgs = Counter(r["o"] for r in all_rows if r["o"]).most_common(100)
    top_cats = Counter(r["c"] for r in all_rows if r["c"]).most_common(100)
    types = Counter(r["t"] for r in all_rows if r["t"])

    stats = {
        "total": len(all_rows),
        "sources": dict(sources.most_common()),
        "org_types": dict(org_types.most_common()),
        "top_orgs": top_orgs,
        "top_categories": top_cats,
        "types": dict(types.most_common(30)),
    }

    output = {"stats": stats, "data": all_rows}

    print(f"Writing JSON...", flush=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(output, f, separators=(",", ":"), ensure_ascii=False)

    size_mb = os.path.getsize(OUT) / (1024 * 1024)
    print(f"Done: {OUT} ({size_mb:.1f} MB)", flush=True)

if __name__ == "__main__":
    main()
