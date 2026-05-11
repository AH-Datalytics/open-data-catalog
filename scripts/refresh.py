"""
Monthly refresh: scrape all sources, build JSON, compress, inject into index.html.

Usage: python scripts/refresh.py
  (run from repo root)
"""

import gzip, base64, json, os, sys, subprocess, time

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
    print(f"\n{'='*60}", flush=True)
    print(f"Running {name} scraper: {filename}", flush=True)
    print(f"{'='*60}", flush=True)
    t0 = time.time()
    result = subprocess.run(
        [sys.executable, path],
        cwd=SCRIPT_DIR,
        timeout=3600,  # 1 hour max per scraper
    )
    elapsed = time.time() - t0
    if result.returncode != 0:
        print(f"WARNING: {name} scraper exited with code {result.returncode} ({elapsed:.0f}s)", flush=True)
    else:
        print(f"{name} scraper done ({elapsed:.0f}s)", flush=True)


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

    # Run all scrapers (continue even if one fails)
    for name, filename in SCRAPERS:
        try:
            run_script(name, filename)
        except Exception as e:
            print(f"ERROR: {name} scraper failed: {e}", flush=True)

    # Build unified JSON
    build_json()

    # Compress and inject into index.html
    compress_and_inject()

    print(f"\nDone!", flush=True)


if __name__ == "__main__":
    main()
