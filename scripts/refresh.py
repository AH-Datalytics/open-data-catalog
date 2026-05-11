"""
Monthly refresh: scrape all sources, build JSON, compress, inject into index.html.

Usage: python scripts/refresh.py
  (run from repo root)
"""

import gzip, base64, json, os, sys, subprocess, time
from concurrent.futures import ThreadPoolExecutor, as_completed

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
INDEX_HTML = os.path.join(REPO_ROOT, "index.html")

SCRAPERS = [
    ("Socrata", "scrape_socrata.py"),
    ("data.gov", "scrape_datagov.py"),
    ("OpenDataSoft", "scrape_opendatasoft.py"),
    ("NASA", "scrape_nasa.py"),
    ("NOAA", "scrape_noaa.py"),
    ("ArcGIS Hub", "scrape_arcgis_hub.py"),
]

def run_script(name, filename):
    path = os.path.join(SCRIPT_DIR, filename)
    t0 = time.time()
    print(f"[START] {name} scraper: {filename}", flush=True)
    try:
        result = subprocess.run(
            [sys.executable, path],
            cwd=SCRIPT_DIR,
            timeout=7200,  # 2 hours max per scraper
        )
        elapsed = time.time() - t0
        if result.returncode != 0:
            print(f"[WARN]  {name} exited with code {result.returncode} ({elapsed:.0f}s)", flush=True)
        else:
            print(f"[DONE]  {name} done ({elapsed:.0f}s)", flush=True)
    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        print(f"[TIMEOUT] {name} timed out after {elapsed:.0f}s", flush=True)
    except Exception as e:
        elapsed = time.time() - t0
        print(f"[ERROR] {name} failed after {elapsed:.0f}s: {e}", flush=True)


def build_json():
    print(f"\n{'='*60}", flush=True)
    print("Building catalog JSON...", flush=True)
    print(f"{'='*60}", flush=True)
    path = os.path.join(SCRIPT_DIR, "build_catalog_json.py")
    subprocess.run([sys.executable, path], cwd=SCRIPT_DIR, check=True)


def compress_and_inject():
    print(f"\n{'='*60}", flush=True)
    print("Compressing and injecting into index.html...", flush=True)
    print(f"{'='*60}", flush=True)

    json_path = os.path.join(SCRIPT_DIR, "open_data_catalog.json")
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Convert to compact array format matching the HTML's expected schema:
    # [name, source, org, org_type, category, type, keywords, downloads, page_views, url, date, country]
    compact = []
    for r in data["data"]:
        compact.append([
            r["n"], r["s"], r["o"], r.get("ot", ""), r.get("c", ""),
            r.get("t", ""), r.get("k", ""), r.get("dl", 0), r.get("p", 0),
            r.get("u", ""), r.get("dt", ""), "",  # country placeholder
        ])

    payload = {"data": compact}
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    b64 = base64.b64encode(gzip.compress(raw, compresslevel=9)).decode("ascii")
    print(f"  Compressed: {len(raw)/1024/1024:.1f} MB -> {len(b64)/1024/1024:.1f} MB (b64)", flush=True)

    # Read current index.html and replace the data blob
    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        html = f.read()

    marker_start = '<script id="catalog-data" type="text/plain">'
    marker_end = '</script>\n</body>'

    i_start = html.index(marker_start) + len(marker_start)
    i_end = html.index(marker_end, i_start)

    new_html = html[:i_start] + "\n" + b64 + "\n" + html[i_end:]

    with open(INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(new_html)

    size_mb = os.path.getsize(INDEX_HTML) / (1024 * 1024)
    print(f"  Updated index.html ({size_mb:.1f} MB)", flush=True)
    print(f"  Total datasets: {len(compact):,}", flush=True)


def main():
    print("Open Data Catalog — Monthly Refresh", flush=True)
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}", flush=True)

    # Run all scrapers in parallel
    print(f"\nStarting {len(SCRAPERS)} scrapers in parallel...\n", flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=len(SCRAPERS)) as pool:
        futures = {pool.submit(run_script, name, fn): name for name, fn in SCRAPERS}
        for f in as_completed(futures):
            f.result()  # propagate exceptions if any

    print(f"\nAll scrapers finished in {(time.time()-t0)/60:.1f}m", flush=True)

    # Build unified JSON
    build_json()

    # Compress and inject into index.html
    compress_and_inject()

    print(f"\nDone!", flush=True)


if __name__ == "__main__":
    main()
