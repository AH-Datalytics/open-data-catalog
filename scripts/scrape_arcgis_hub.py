"""
ArcGIS Hub scraper — fast version.
Quick discovery to get all orgs, then 8 concurrent workers scraping per-org.
Incremental CSV writes. Resume-capable via progress file.
"""

import csv, json, time, sys, os, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import urlopen, Request
from urllib.parse import urlencode
from urllib.error import HTTPError

SEARCH_API = "https://hub.arcgis.com/api/v3/search"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "arcgis_hub_catalog.csv")
PROGRESS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "arcgis_hub_progress.json")

CSV_COLS = [
    "id", "name", "description", "org_name", "owner", "type",
    "sector", "region", "tags", "url", "record_count",
    "created", "modified", "geometry_type", "has_api",
    "open_data", "source_platform",
]

FIELDS = "name,owner,orgName,sector,region,tags,type,url,recordCount,created,modified,geometryType,hasApi,openData,searchDescription"
WORKERS = 8

_lock = threading.Lock()
_csv_lock = threading.Lock()
_seen_ids = set()
_total_written = 0


def fetch_url(url, retries=2):
    for attempt in range(retries):
        try:
            req = Request(url, headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (open-data-catalog)",
            })
            with urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except HTTPError as e:
            if e.code in (400, 403, 404):
                return {"data": [], "meta": {}}
            if attempt < retries - 1:
                time.sleep(2)
                continue
            return {"data": [], "meta": {}}
        except Exception:
            if attempt < retries - 1:
                time.sleep(2)
                continue
            return {"data": [], "meta": {}}
    return {"data": [], "meta": {}}


def extract_row(item):
    a = item.get("attributes", {})
    tags = a.get("tags", []) or []
    return {
        "id": a.get("id", item.get("id", "")),
        "name": (a.get("name") or "").replace("\n", " ").strip(),
        "description": (a.get("searchDescription") or "").replace("\n", " ").strip()[:500],
        "org_name": a.get("orgName") or "",
        "owner": a.get("owner") or "",
        "type": a.get("type") or "",
        "sector": a.get("sector") or "",
        "region": a.get("region") or "",
        "tags": "; ".join(tags) if isinstance(tags, list) else str(tags),
        "url": a.get("url") or "",
        "record_count": a.get("recordCount") or "",
        "created": a.get("created") or "",
        "modified": a.get("modified") or "",
        "geometry_type": a.get("geometryType") or "",
        "has_api": a.get("hasApi") or "",
        "open_data": a.get("openData") or "",
        "source_platform": "ArcGIS Hub",
    }


def build_url(q="*"):
    # Only include datasets modified in the last 5 years to cut scrape time in half
    from datetime import datetime
    cutoff_year = datetime.now().year - 5
    date_filter = f" modified:[{cutoff_year}-01-01 TO 2099-12-31]"
    params = {
        "q": q + date_filter,
        "fields[datasets]": FIELDS,
        "filter[region]": "US",
        "filter[openData]": "true",
    }
    return f"{SEARCH_API}?{urlencode(params, doseq=True)}"


def append_csv(rows):
    global _total_written
    if not rows:
        return
    with _csv_lock:
        write_header = not os.path.exists(OUT) or os.path.getsize(OUT) == 0
        with open(OUT, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CSV_COLS)
            if write_header:
                w.writeheader()
            w.writerows(rows)
        _total_written += len(rows)


def scrape_org(org):
    """Scrape all datasets for one org. Returns count of new items."""
    url = build_url(f'orgName:"{org}"')
    rows = []
    pages = 0
    while url and pages < 500:
        data = fetch_url(url)
        for item in data.get("data", []):
            iid = item.get("id", "")
            if iid:
                with _lock:
                    if iid in _seen_ids:
                        continue
                    _seen_ids.add(iid)
                rows.append(extract_row(item))
        next_url = data.get("meta", {}).get("next")
        if not next_url or next_url == url:
            break
        url = next_url
        pages += 1
        time.sleep(0.15)
    append_csv(rows)
    return len(rows)


def load_progress():
    if os.path.exists(PROGRESS):
        with open(PROGRESS) as f:
            return json.load(f)
    return {"done_orgs": [], "all_orgs": []}


def save_progress(done_orgs, all_orgs):
    with open(PROGRESS, "w") as f:
        json.dump({"done_orgs": done_orgs, "all_orgs": all_orgs}, f)


def main():
    t0 = time.time()
    prog = load_progress()
    done_set = set(prog["done_orgs"])

    if prog["all_orgs"]:
        all_orgs = prog["all_orgs"]
        print(f"Resuming: {len(all_orgs)} orgs, {len(done_set)} done", flush=True)
        if os.path.exists(OUT):
            with open(OUT, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    _seen_ids.add(r.get("id", ""))
            global _total_written
            _total_written = len(_seen_ids)
            print(f"Loaded {len(_seen_ids)} existing IDs", flush=True)
    else:
        # Quick discovery
        print("Discovery sweep...", flush=True)
        orgs = set()
        url = build_url("*")
        pages = 0
        disc_rows = []
        while url and pages < 500:
            data = fetch_url(url)
            for item in data.get("data", []):
                a = item.get("attributes", {})
                org = a.get("orgName")
                if org:
                    orgs.add(org)
                iid = item.get("id", "")
                if iid and iid not in _seen_ids:
                    _seen_ids.add(iid)
                    disc_rows.append(extract_row(item))
            next_url = data.get("meta", {}).get("next")
            if not next_url or next_url == url:
                break
            url = next_url
            pages += 1
            if pages % 50 == 0:
                print(f"  Page {pages}: {len(_seen_ids)} items, {len(orgs)} orgs", flush=True)
            time.sleep(0.15)

        if os.path.exists(OUT):
            os.remove(OUT)
        append_csv(disc_rows)
        all_orgs = sorted(orgs)
        save_progress([], all_orgs)
        print(f"Discovery done: {len(_seen_ids)} items, {len(all_orgs)} orgs\n", flush=True)

    # Per-org scraping with concurrent workers
    remaining = [o for o in all_orgs if o not in done_set]
    print(f"Scraping {len(remaining)} orgs with {WORKERS} workers...\n", flush=True)

    done_orgs = list(done_set)
    completed = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(scrape_org, org): org for org in remaining}
        for f in as_completed(futures):
            org = futures[f]
            new = f.result()
            completed += 1
            done_orgs.append(org)

            if new > 0:
                print(f"  [{completed}/{len(remaining)}] {org[:50]}: +{new} ({_total_written} total)", flush=True)
            elif completed % 50 == 0:
                print(f"  [{completed}/{len(remaining)}] progress ({_total_written} total)", flush=True)

            if completed % 20 == 0:
                save_progress(done_orgs, all_orgs)

    save_progress(done_orgs, all_orgs)

    # Stats
    print(f"\nTotal: {_total_written} items in {OUT}", flush=True)
    if os.path.exists(OUT):
        from collections import Counter
        types, org_counts = Counter(), Counter()
        with open(OUT, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                types[r.get("type", "")] += 1
                org_counts[r.get("org_name", "")] += 1
        print(f"\nTop 15 types:")
        for t, c in types.most_common(15):
            print(f"  {c:>8}  {t}")
        print(f"\nTop 20 orgs:")
        for o, c in org_counts.most_common(20):
            print(f"  {c:>8}  {o}")

    print(f"\nDone in {time.time()-t0:.0f}s ({(time.time()-t0)/60:.1f}m)", flush=True)


if __name__ == "__main__":
    main()
