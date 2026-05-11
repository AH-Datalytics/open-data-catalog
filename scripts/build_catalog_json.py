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
                "u": r.get("id", "") if (r.get("id", "").startswith("http")) else "",
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
                "u": f"https://{r['id'].split('@',1)[1]}.opendatasoft.com/explore/dataset/{r['id'].split('@',1)[0]}/" if "@" in r.get("id","") else "",
                "dt": (r.get("modified") or r.get("created") or "")[:10],
            })
    return rows

def load_noaa():
    path = os.path.join(SCRIPT_DIR, "noaa_catalog.csv")
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "n": (r["name"] or "")[:120],
                "d": (r["description"] or "")[:150],
                "s": "NOAA",
                "o": (r.get("organization") or "NOAA")[:80],
                "ot": "Federal",
                "c": "",
                "t": "dataset",
                "k": (r.get("keywords") or "")[:200],
                "p": 0,
                "dl": 0,
                "u": r.get("url") or "",
                "dt": (r.get("modified") or "")[:10],
            })
    return rows

def load_nasa():
    path = os.path.join(SCRIPT_DIR, "nasa_catalog.csv")
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "n": (r["name"] or "")[:120],
                "d": (r["description"] or "")[:150],
                "s": "NASA",
                "o": (r.get("organization") or "NASA")[:80],
                "ot": "Federal",
                "c": "",
                "t": "dataset",
                "k": (r.get("tags") or "")[:200],
                "p": int(r["page_views"]) if r.get("page_views") and r["page_views"].isdigit() else 0,
                "dl": 0,
                "u": r.get("url") or "",
                "dt": (r.get("modified") or "")[:10],
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
    nasa = load_nasa()
    print(f"  NASA: {len(nasa):,}", flush=True)
    noaa = load_noaa()
    print(f"  NOAA: {len(noaa):,}", flush=True)
    arcgis = load_arcgis()
    print(f"  ArcGIS Hub: {len(arcgis):,}", flush=True)

    all_rows = socrata + datagov + ods + nasa + noaa + arcgis
    print(f"\nTotal before dedup: {len(all_rows):,}", flush=True)

    # Cross-source dedup with fuzzy matching and link preference
    import re

    def normalize(s):
        """Aggressive normalization for fuzzy matching."""
        s = (s or "").lower()
        # Strip version numbers, years in parens, trailing dates
        s = re.sub(r'\s*\(?(v\d+[\.\d]*|version\s*\d+|fy\s*\d{4})\)?', '', s)
        s = re.sub(r',?\s*\d{4}[-–]\d{2,4}$', '', s)  # trailing date ranges
        s = re.sub(r',?\s*\d{4}$', '', s)  # trailing year
        # Strip all non-alphanumeric
        s = re.sub(r'[^a-z0-9]', '', s)
        return s

    def dedup_key(r):
        return normalize(r["n"]) + "|" + normalize(r["o"])

    # Pass 1: group by key, keep the best version (prefer ones with URLs)
    from collections import defaultdict
    groups = defaultdict(list)
    for r in all_rows:
        groups[dedup_key(r)].append(r)

    deduped = []
    for key, candidates in groups.items():
        # Pick the one with a URL, or the one with the most metadata
        best = None
        for c in candidates:
            if best is None:
                best = c
            elif c.get("u") and not best.get("u"):
                best = c  # prefer linked
            elif c.get("u") and best.get("u") and (c.get("p", 0) or 0) > (best.get("p", 0) or 0):
                best = c  # both linked, prefer more popular
            elif not c.get("u") and not best.get("u") and len(c.get("k", "")) > len(best.get("k", "")):
                best = c  # neither linked, prefer more keywords
        deduped.append(best)

    exact_removed = len(all_rows) - len(deduped)
    print(f"Fuzzy dedup: removed {exact_removed:,} duplicates", flush=True)

    # Pass 2: drop linkless entries when we already have plenty
    # Keep linkless only if no linked version of similar name exists
    linked_names = set(normalize(r["n"]) for r in deduped if r.get("u"))
    before_link_filter = len(deduped)
    deduped = [r for r in deduped if r.get("u") or normalize(r["n"]) not in linked_names]
    link_removed = before_link_filter - len(deduped)
    print(f"Linkless dedup: removed {link_removed:,} entries with linked equivalents", flush=True)

    all_rows = deduped
    print(f"Total after dedup: {len(all_rows):,}", flush=True)

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
