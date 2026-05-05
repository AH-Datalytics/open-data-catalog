"""
Comprehensive Socrata Discovery API dump — ALL asset types, US + EU endpoints.

Domain-discovery strategies (Phase 1, concurrent):
  A. Multi-sort sweeps (5 sort orders × 10K each) on BOTH US and EU endpoints
  B. Category-based sweeps (top 100 categories, 3 pages each) on US endpoint
  C. Search-term sweeps (~30 common terms, 3 pages each) on US endpoint
  D. Probe known state/city domain patterns against the API
  E. Per-type sweeps (maps, charts, files, links, stories, filters) on US + EU

Phase 2: Per-domain extraction — for every discovered domain, fetch ALL items
          (no type filter) via offset pagination. Concurrent via ThreadPoolExecutor.

Phase 3: Dedup by (domain, resource_id) → CSV.
"""

import csv, json, time, sys, os, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import urlopen, Request
from urllib.parse import urlencode, quote
from urllib.error import HTTPError

US_API = "https://api.us.socrata.com/api/catalog/v1"
EU_API = "https://api.eu.socrata.com/api/catalog/v1"
PAGE = 1000
MAX_OFFSET = 10000
DISCOVERY_WORKERS = 8
DOMAIN_WORKERS = 16
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "socrata_all_assets.csv")

CSV_COLS = [
    "dataset_id", "name", "description", "domain", "type", "provenance",
    "category", "attribution", "license", "permalink", "created_at",
    "data_updated_at", "page_views_total", "download_count", "columns_count",
    "owner_name", "tags", "api_endpoint",
]

SORT_ORDERS = [
    {},
    {"order": "updated_at"},
    {"order": "created_at"},
    {"order": "name"},
    {"order": "dataset_id"},
]

ASSET_TYPES = ["datasets", "maps", "charts", "files", "links", "stories", "filters"]

SEARCH_TERMS = [
    "police", "crime", "health", "budget", "tax", "water", "traffic",
    "education", "housing", "election", "permit", "fire", "census",
    "employment", "environment", "energy", "transit", "land", "park",
    "restaurant", "building", "salary", "contract", "airport", "hospital",
    "school", "library", "weather", "agriculture", "population",
]

# All 50 US states + DC + territories
US_STATES = [
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new-hampshire", "new-jersey", "new-mexico", "new-york",
    "north-carolina", "north-dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode-island", "south-carolina", "south-dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west-virginia", "wisconsin", "wyoming",
]

KNOWN_DOMAIN_PATTERNS = (
    # data.{state}.gov
    [f"data.{s.replace('-', '')}.gov" for s in US_STATES]
    + [f"data.{s}.gov" for s in US_STATES if "-" in s]  # hyphenated too
    # Major cities
    + [
        "data.cityofchicago.org", "data.cityofnewyork.us", "data.sfgov.org",
        "data.lacity.org", "data.seattle.gov", "data.austintexas.gov",
        "data.boston.gov", "data.detroitmi.gov", "data.nashville.gov",
        "data.cityofmadison.com", "data.sandiego.gov", "data.sanjoseca.gov",
        "data.baltimorecity.gov", "data.jacksonville.gov", "data.kcmo.org",
        "data.louisvilleky.gov", "data.milwaukee.gov", "data.memphis.gov",
        "data.raleighnc.gov", "data.tucsonaz.gov", "data.denvergov.org",
        "data.fortworthtexas.gov", "data.cityoforlando.net",
        "data.oaklandca.gov", "data.providenceri.gov", "data.nola.gov",
        "data.honolulu.gov", "data.brla.gov", "data.bloomington.in.gov",
        "data.cambridgema.gov", "data.cincinnati-oh.gov",
        "data.montgomerycountymd.gov", "data.princegeorgescountymd.gov",
        "data.countyofriverside.us", "data.cookcounty.gov",
    ]
    # Federal
    + [
        "data.cdc.gov", "data.cms.gov", "data.medicare.gov",
        "data.bts.gov", "data.ed.gov", "data.hrsa.gov",
        "healthdata.gov", "data.healthcare.gov",
    ]
    # Canadian
    + [
        "data.edmonton.ca", "data.calgary.ca", "data.winnipeg.ca",
        "data.novascotia.ca", "data.ontario.ca", "open.toronto.ca",
        "open.canada.ca",
    ]
    # Other known
    + [
        "opendata.utah.gov", "opendata.maryland.gov",
        "controllerdata.lacity.org", "explore.data.gov",
        "datacatalog.cookcountyil.gov", "mydata.iowa.gov",
        "datahub.austintexas.gov", "datahub.hhs.gov",
    ]
)

# ── Thread-safe state ───────────────────────────────────────────────

_lock = threading.Lock()
_seen_ids: set = set()       # (domain, resource_id)
_all_rows: list = []
_domains: dict = {}          # domain -> which API endpoint (US or EU)

_rate_lock = threading.Lock()
_last_request = [0.0]
MIN_GAP = 0.05  # 20 req/s max


def _throttle():
    with _rate_lock:
        now = time.monotonic()
        gap = MIN_GAP - (now - _last_request[0])
        if gap > 0:
            time.sleep(gap)
        _last_request[0] = time.monotonic()


def api_get(base_url: str, params: dict, retries: int = 4) -> dict:
    url = f"{base_url}?{urlencode(params, doseq=True)}"
    for attempt in range(retries):
        _throttle()
        try:
            req = Request(url, headers={"Accept": "application/json"})
            with urlopen(req, timeout=45) as resp:
                return json.loads(resp.read())
        except HTTPError as e:
            if e.code == 429 or e.code >= 500:
                wait = 2 ** (attempt + 1)
                print(f"  HTTP {e.code}, retrying in {wait}s...", flush=True)
                time.sleep(wait)
                continue
            if e.code in (400, 403, 404):
                return {"results": [], "resultSetSize": 0}
            raise
        except Exception:
            if attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            raise
    return {"results": [], "resultSetSize": 0}


def extract_row(item: dict, endpoint: str) -> dict:
    r = item.get("resource", {})
    c = item.get("classification", {})
    m = item.get("metadata", {})
    o = item.get("owner", {})
    pv = r.get("page_views", {})
    cols = r.get("columns_name", [])
    tags = c.get("domain_tags", []) or c.get("tags", [])
    return {
        "dataset_id": r.get("id", ""),
        "name": (r.get("name") or "").replace("\n", " ").strip(),
        "description": (r.get("description") or "").replace("\n", " ").strip()[:500],
        "domain": m.get("domain", ""),
        "type": r.get("type", ""),
        "provenance": r.get("provenance", ""),
        "category": c.get("domain_category", ""),
        "attribution": (r.get("attribution") or "").replace("\n", " ").strip(),
        "license": m.get("license", ""),
        "permalink": item.get("permalink", ""),
        "created_at": r.get("createdAt", ""),
        "data_updated_at": r.get("data_updated_at", ""),
        "page_views_total": pv.get("page_views_total", ""),
        "download_count": r.get("download_count", ""),
        "columns_count": len(cols) if cols else "",
        "owner_name": o.get("display_name", ""),
        "tags": "; ".join(tags) if tags else "",
        "api_endpoint": "EU" if "eu.socrata" in endpoint else "US",
    }


def _collect_items(results: list, endpoint: str) -> int:
    """Add items to global state, return count of new items."""
    new = 0
    batch = []
    for item in results:
        did = item.get("resource", {}).get("id", "")
        domain = item.get("metadata", {}).get("domain", "")
        if domain:
            with _lock:
                if domain not in _domains:
                    _domains[domain] = endpoint
        key = (domain, did)
        if did and key not in _seen_ids:
            with _lock:
                if key not in _seen_ids:
                    _seen_ids.add(key)
                    batch.append(extract_row(item, endpoint))
                    new += 1
    if batch:
        with _lock:
            _all_rows.extend(batch)
    return new


# ── Phase 1: Domain Discovery ──────────────────────────────────────

def _sweep_sort_order(endpoint: str, extra_params: dict, label: str):
    """10K sweep with one sort order, no type filter."""
    total_new = 0
    for offset in range(0, MAX_OFFSET, PAGE):
        params = {"limit": PAGE, "offset": offset, **extra_params}
        data = api_get(endpoint, params)
        results = data.get("results", [])
        if not results:
            break
        total_new += _collect_items(results, endpoint)
        if len(results) < PAGE:
            break
    ep_tag = "EU" if "eu" in endpoint else "US"
    with _lock:
        dom_count = len(_domains)
    print(f"  [{ep_tag}|{label}] +{total_new} items, {dom_count} domains total", flush=True)


def _sweep_type(endpoint: str, asset_type: str):
    """10K sweep for a specific asset type."""
    total_new = 0
    for offset in range(0, MAX_OFFSET, PAGE):
        params = {"only": asset_type, "limit": PAGE, "offset": offset}
        data = api_get(endpoint, params)
        results = data.get("results", [])
        if not results:
            break
        total_new += _collect_items(results, endpoint)
        if len(results) < PAGE:
            break
    ep_tag = "EU" if "eu" in endpoint else "US"
    with _lock:
        dom_count = len(_domains)
    print(f"  [{ep_tag}|type={asset_type}] +{total_new} items, {dom_count} domains", flush=True)


def _sweep_category(endpoint: str, category: str):
    """3-page sweep for a category (just for domain discovery)."""
    for offset in range(0, 3000, PAGE):
        params = {"categories": category, "limit": PAGE, "offset": offset}
        data = api_get(endpoint, params)
        results = data.get("results", [])
        if not results:
            break
        _collect_items(results, endpoint)
        if len(results) < PAGE:
            break


def _sweep_search(endpoint: str, term: str):
    """3-page sweep for a search term (domain discovery)."""
    for offset in range(0, 3000, PAGE):
        params = {"q": term, "limit": PAGE, "offset": offset}
        data = api_get(endpoint, params)
        results = data.get("results", [])
        if not results:
            break
        _collect_items(results, endpoint)
        if len(results) < PAGE:
            break


def _probe_domain(domain: str):
    """Check if a domain exists on US or EU endpoint."""
    for endpoint in [US_API, EU_API]:
        params = {"domains": domain, "limit": 1}
        data = api_get(endpoint, params)
        if data.get("resultSetSize", 0) > 0:
            with _lock:
                if domain not in _domains:
                    _domains[domain] = endpoint
            return


def phase1():
    print("=" * 70, flush=True)
    print("PHASE 1: Domain Discovery", flush=True)
    print("=" * 70, flush=True)

    # 1A: Multi-sort sweeps on US + EU (no type filter)
    print("\n[1A] Multi-sort sweeps (US + EU, all types)...", flush=True)
    labels = ["popularity", "updated_at", "created_at", "name", "dataset_id"]
    tasks = []
    for endpoint in [US_API, EU_API]:
        for extra, label in zip(SORT_ORDERS, labels):
            tasks.append((endpoint, extra, label))

    with ThreadPoolExecutor(max_workers=DISCOVERY_WORKERS) as pool:
        futures = [pool.submit(_sweep_sort_order, ep, ex, lb) for ep, ex, lb in tasks]
        for f in as_completed(futures):
            f.result()

    print(f"  After 1A: {len(_seen_ids)} items, {len(_domains)} domains", flush=True)

    # 1B: Per-type sweeps on US + EU
    print("\n[1B] Per-type sweeps (maps, charts, files, links, stories, filters)...", flush=True)
    tasks = []
    for endpoint in [US_API, EU_API]:
        for atype in ASSET_TYPES:
            tasks.append((endpoint, atype))

    with ThreadPoolExecutor(max_workers=DISCOVERY_WORKERS) as pool:
        futures = [pool.submit(_sweep_type, ep, at) for ep, at in tasks]
        for f in as_completed(futures):
            f.result()

    print(f"  After 1B: {len(_seen_ids)} items, {len(_domains)} domains", flush=True)

    # 1C: Category sweeps (US)
    print("\n[1C] Category sweeps (top categories)...", flush=True)
    cats_data = api_get(US_API, {})  # get categories from domain_categories
    cats_resp = api_get(US_API.replace("/v1", "/v1/domain_categories"), {})
    categories = [item.get("domain_category", "") for item in cats_resp.get("results", [])]
    if not categories:
        # Fallback hardcoded top categories
        categories = [
            "Earth Science", "NIH", "Health", "Government", "Public Safety",
            "Education", "Transportation", "Environment", "Finance",
            "Demographics", "Business", "Recreation", "Social Services",
            "Housing & Development", "Human Services", "Census",
            "Energy & Environment", "City Government",
        ]

    with ThreadPoolExecutor(max_workers=DISCOVERY_WORKERS) as pool:
        futures = [pool.submit(_sweep_category, US_API, cat) for cat in categories]
        for f in as_completed(futures):
            f.result()

    print(f"  After 1C: {len(_seen_ids)} items, {len(_domains)} domains", flush=True)

    # 1D: Search-term sweeps (US + EU)
    print(f"\n[1D] Search-term sweeps ({len(SEARCH_TERMS)} terms)...", flush=True)
    with ThreadPoolExecutor(max_workers=DISCOVERY_WORKERS) as pool:
        futures = []
        for term in SEARCH_TERMS:
            futures.append(pool.submit(_sweep_search, US_API, term))
            futures.append(pool.submit(_sweep_search, EU_API, term))
        for f in as_completed(futures):
            f.result()

    print(f"  After 1D: {len(_seen_ids)} items, {len(_domains)} domains", flush=True)

    # 1E: Probe known domain patterns
    print(f"\n[1E] Probing {len(KNOWN_DOMAIN_PATTERNS)} known domain patterns...", flush=True)
    new_before = len(_domains)
    with ThreadPoolExecutor(max_workers=DOMAIN_WORKERS) as pool:
        futures = [pool.submit(_probe_domain, d) for d in KNOWN_DOMAIN_PATTERNS
                   if d not in _domains]
        for f in as_completed(futures):
            f.result()

    new_found = len(_domains) - new_before
    print(f"  Probing found {new_found} new domains", flush=True)
    print(f"\n  PHASE 1 TOTAL: {len(_seen_ids)} items, {len(_domains)} domains", flush=True)


# ── Phase 2: Per-domain extraction ──────────────────────────────────

ALL_TYPES = [
    "datasets", "maps", "charts", "files", "links", "stories",
    "filters", "hrefs", "measures", "calendars",
]


def _paginate_query(endpoint: str, params_base: dict) -> list:
    """Paginate a query up to 10K, returning new rows."""
    rows = []
    offset = 0
    while True:
        params = {**params_base, "limit": PAGE, "offset": offset}
        data = api_get(endpoint, params)
        results = data.get("results", [])
        if not results:
            break
        for item in results:
            did = item.get("resource", {}).get("id", "")
            dom = item.get("metadata", {}).get("domain", params_base.get("domains", ""))
            key = (dom, did)
            if did:
                with _lock:
                    if key not in _seen_ids:
                        _seen_ids.add(key)
                        rows.append(extract_row(item, endpoint))
        if len(results) < PAGE:
            break
        offset += PAGE
        if offset >= MAX_OFFSET:
            return rows  # signal caller to shard further
    return rows


def _fetch_domain_full(domain: str, endpoint: str) -> tuple:
    """Fetch ALL items for one domain. If it exceeds 10K, shard by type."""
    # First try unfiltered
    rows = []
    offset = 0
    hit_cap = False
    while True:
        params = {"domains": domain, "limit": PAGE, "offset": offset}
        data = api_get(endpoint, params)
        results = data.get("results", [])
        if not results:
            break
        for item in results:
            did = item.get("resource", {}).get("id", "")
            dom = item.get("metadata", {}).get("domain", domain)
            key = (dom, did)
            if did:
                with _lock:
                    if key not in _seen_ids:
                        _seen_ids.add(key)
                        rows.append(extract_row(item, endpoint))
        if len(results) < PAGE:
            break
        offset += PAGE
        if offset >= MAX_OFFSET:
            hit_cap = True
            break

    if hit_cap:
        # Shard by asset type to get past the 10K cap
        print(f"  [SHARD] {domain} hit 10K, sharding by type...", flush=True)
        for atype in ALL_TYPES:
            type_rows = _paginate_query(endpoint, {"domains": domain, "only": atype})
            rows.extend(type_rows)

    return domain, rows


def phase2():
    print("\n" + "=" * 70, flush=True)
    print("PHASE 2: Per-domain extraction", flush=True)
    print("=" * 70, flush=True)

    domains_list = sorted(_domains.items())
    print(f"Fetching {len(domains_list)} domains with {DOMAIN_WORKERS} workers...\n", flush=True)

    done = 0
    with ThreadPoolExecutor(max_workers=DOMAIN_WORKERS) as pool:
        futures = {
            pool.submit(_fetch_domain_full, dom, ep): dom
            for dom, ep in domains_list
        }
        for f in as_completed(futures):
            domain, new_rows = f.result()
            done += 1
            if new_rows:
                with _lock:
                    _all_rows.extend(new_rows)
                print(f"  [{done}/{len(domains_list)}] {domain}: +{len(new_rows)} new", flush=True)
            elif done % 50 == 0:
                print(f"  [{done}/{len(domains_list)}] progress... ({len(_all_rows)} total)", flush=True)

    print(f"\nPhase 2 done: {len(_all_rows)} total items", flush=True)


# ── Phase 3: CSV ────────────────────────────────────────────────────

def phase3():
    print("\n" + "=" * 70, flush=True)
    print("PHASE 3: Write CSV", flush=True)
    print("=" * 70, flush=True)

    _all_rows.sort(key=lambda r: (r["domain"], r["type"], r["name"].lower()))

    print(f"Writing {len(_all_rows)} items to {OUT}...", flush=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLS)
        writer.writeheader()
        writer.writerows(_all_rows)

    print(f"Done! {len(_all_rows)} items written.\n", flush=True)

    # Stats
    domain_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    prov_counts: dict[str, int] = {}
    ep_counts: dict[str, int] = {}

    for r in _all_rows:
        domain_counts[r["domain"]] = domain_counts.get(r["domain"], 0) + 1
        type_counts[r["type"]] = type_counts.get(r["type"], 0) + 1
        p = r["provenance"] or "(none)"
        prov_counts[p] = prov_counts.get(p, 0) + 1
        ep_counts[r["api_endpoint"]] = ep_counts.get(r["api_endpoint"], 0) + 1

    print(f"Unique domains: {len(domain_counts)}")
    print(f"API endpoints: {ep_counts}")
    print(f"Provenance: {prov_counts}")
    print(f"\nAsset types:")
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {c:>8}  {t}")

    top = sorted(domain_counts.items(), key=lambda x: -x[1])[:30]
    print(f"\nTop 30 domains:")
    for d, c in top:
        print(f"  {c:>8}  {d}")


def main():
    t0 = time.time()
    phase1()
    phase2()
    phase3()
    elapsed = time.time() - t0
    print(f"\nTotal time: {elapsed:.0f}s ({elapsed/60:.1f}m)", flush=True)


if __name__ == "__main__":
    main()
