#!/usr/bin/env python3
"""
Step 1: match every Shopify variant to Webami (UPC -> your Webami orders -> title) and save details to webami_data.csv.
Nothing is changed in Shopify or your DB.

Put this file in your repo root (next to pull_shopify_data.py; needs config, webami.session, services.matcher).
Env: SHOPIFY_STORE, SHOPIFY_TOKEN  (or TEST_ versions + --test)

  python webami_fetch.py --offset 0 --limit 100 --out webami_data.csv     # set 0 of 100 products
  python webami_fetch.py --limit 0 --out webami_data.csv                  # everything
Resumable: variants already in --out are skipped (use --redo to refetch). start = offset x limit (products).
"""
import argparse, csv, datetime, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
from pull_shopify_data import gql, SESSION
import webami.scraper as S          # <-- product scraper (change module name if different)
import webami.orders as O           # <-- order parser (scrape_all_orders / scrape_order_detail); change name if different
from services.matcher import similarity

BULK = """{ products { edges { node {
  id title vendor productType tags category{ fullName } mediaCount{ count }
  pupc: metafield(namespace:"custom", key:"upc"){ value }
  variants { edges { node { id sku price
    vupc: metafield(namespace:"custom", key:"upc"){ value }
    inventoryItem{ id unitCost{ amount } measurement{ weight{ value unit } } } } } }
} } } }"""

COLS = ["shopify_product_id", "shopify_variant_id", "inventory_item_id", "product_title", "vendor", "variant_title", "sku",
        "category", "media_count", "tags", "old_upc", "old_cost", "old_price", "old_weight", "old_weight_unit",
        "status", "match_method", "webami_upc", "webami_sku", "webami_title", "webami_artist", "format", "description", "release_date",
        "features", "genres", "weight_grams", "cost", "image_urls", "fetched_at"]


def run_bulk(shop):
    d = gql(*shop, "mutation($q:String!){ bulkOperationRunQuery(query:$q){ userErrors{ message } } }", {"q": BULK})
    if d["bulkOperationRunQuery"]["userErrors"]: raise RuntimeError(d["bulkOperationRunQuery"]["userErrors"])
    while True:
        time.sleep(3)
        op = gql(*shop, "{ currentBulkOperation(type: QUERY){ status url objectCount } }")["currentBulkOperation"]
        print(f"  shopify bulk: {op['status']} ({op.get('objectCount')})", flush=True)
        if op["status"] == "COMPLETED": break
        if op["status"] in ("FAILED", "CANCELED", "EXPIRED"): raise RuntimeError(op["status"])
    prods = {}
    if not op.get("url"): return []
    for line in SESSION.get(op["url"], timeout=300).text.splitlines():
        if not line: continue
        o = json.loads(line)
        if "__parentId" in o: prods[o["__parentId"]]["_v"].append(o)
        else: o["_v"] = []; prods[o["id"]] = o
    return list(prods.values())


def flat_rows(prods):
    rows = []
    for p in prods:
        for v in p["_v"]:
            ii = v.get("inventoryItem") or {}
            w = (ii.get("measurement") or {}).get("weight") or {}
            rows.append({
                "shopify_product_id": p["id"], "shopify_variant_id": v["id"], "inventory_item_id": ii.get("id", ""),
                "product_title": p["title"], "vendor": p["vendor"], "variant_title": "", "sku": v.get("sku") or "",
                "category": (p.get("category") or {}).get("fullName", ""), "media_count": (p.get("mediaCount") or {}).get("count", 0),
                "tags": json.dumps(p.get("tags") or []), "old_upc": next((x for x in [(v.get("vupc") or {}).get("value"), (p.get("pupc") or {}).get("value")] if x), ""),
                "old_cost": (ii.get("unitCost") or {}).get("amount", ""), "old_price": v.get("price", ""),
                "old_weight": w.get("value", ""), "old_weight_unit": w.get("unit", ""),
                "_upcs": [x for x in [(v.get("vupc") or {}).get("value"), (p.get("pupc") or {}).get("value")] if x]})
    return rows


# ---------- extra Webami extractors ----------
def _label(primary, *labels):
    if primary:
        for li in primary.find_all("li"):
            sp = li.find("span")
            if sp and any(l in sp.text for l in labels):
                return li.text.replace(sp.text, "", 1).strip()
    return None


def get_release_date(primary): return _label(primary, "Release Date:")


def get_description(soup):
    el = soup.select_one("#aec-product-description .aec-desc-review")
    if el and el.get_text(strip=True):
        return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", el.get_text("\n", strip=True))).strip()
    sc = soup.select_one("script.ProductPageStrData")
    try: return json.loads(sc.string).get("description") if sc and sc.string else None
    except Exception: return None


def get_webami_sku(primary): return _label(primary, "Product ID")


def get_page_cost(soup):
    el = soup.select_one(".aec-new-price strong")
    try: return float(el.get_text(strip=True)) if el else None
    except ValueError: return None


# ---------- Webami orders index (item upcs from your submitted orders) ----------
def build_order_index(cache, refresh):
    if os.path.exists(cache) and not refresh: return json.load(open(cache, encoding="utf-8"))
    items = {}
    for o in O.scrape_all_orders():
        for it in O.scrape_order_detail(o["guid"])["items"]:
            if it.get("webami_upc"): items[it["webami_upc"]] = {k: it.get(k) for k in ("webami_upc", "title", "artist", "format")}
    out = list(items.values()); json.dump(out, open(cache, "w", encoding="utf-8")); print(f"  order index: {len(out)} items")
    return out


def match_order(r, fmt):
    best, bu = 0.0, None
    for it in ORDER_INDEX:
        if fmt and it["format"] and not S._formats_match(fmt, it["format"]): continue
        ts = max((similarity(t, it["title"] or "") for t in S._title_variants(r["product_title"])), default=0)
        sc = ts * 0.6 + similarity(r["vendor"], it["artist"] or "") * 0.4
        if sc > best: best, bu = sc, it["webami_upc"]
    return bu if best >= S._SEARCH_THRESHOLD else None


ORDER_INDEX = []


def fmt_hint(category):
    c = (category or "").lower()
    return "lp" if "vinyl" in c else "cd" if "cd" in c else "cassette" if "cassette" in c else None


def page_for(u, fmt):
    for cand in [u] + ([u.lstrip("0")] if u.startswith("0") and len(u) > 1 else []):
        soup = S._fetch_product_page(cand)
        if soup is not None and (not fmt or S._formats_match(fmt, S.get_format(soup, cand))):
            return soup, cand
    return None, None


def find(r):
    fmt = fmt_hint(r["category"])
    tried = set()
    for u in r["_upcs"]:                                          # 1) UPC
        u = re.sub(r"\D", "", u)
        if u and u not in tried:
            tried.add(u)
            soup, got = page_for(u, fmt)
            if soup is not None: return "upc", soup, got
    if ORDER_INDEX:                                               # 2) your Webami orders
        u = match_order(r, fmt)
        if u:
            soup, got = page_for(u, fmt)
            if soup is not None: return "order", soup, got
    q = f"{r['vendor']} {r['product_title']}".strip()             # 3) title
    u = S.search_for_replacement_upc(q, r["product_title"], r["vendor"], fmt=fmt)
    if u:
        soup, got = page_for(u, fmt)
        if soup is not None: return "title", soup, got
    return None, None, None


def work(r):
    out = {k: r.get(k, "") for k in COLS}
    out["fetched_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        method, soup, u = find(r)
        if soup is None:
            out["status"] = "not_found"; return out
        primary = S._get_primaryinfo(soup)
        out.update(status="ok", match_method=method, webami_upc=u, webami_sku=get_webami_sku(primary) or "", webami_title=S.get_title(soup, u) or "",
                   webami_artist=S.get_artist(soup, u) or "", format=S.get_format(soup, u) or "",
                   description=get_description(soup) or "", release_date=get_release_date(primary) or "",
                   features=json.dumps(S.get_features(soup) or []), genres=json.dumps(S.get_genres(primary) or []),
                   weight_grams=S.get_weight(primary, u) or "", cost=S.get_cost(u) or get_page_cost(soup) or "",
                   image_urls=json.dumps(S.get_images(soup, u) or []))
    except Exception as e:
        out["status"] = f"error: {str(e)[:150]}"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="webami_data.csv")
    ap.add_argument("--offset", type=int, default=0); ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--workers", type=int, default=4); ap.add_argument("--redo", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--orders-cache", default="webami_orders_cache.json"); ap.add_argument("--refresh-orders", action="store_true")
    ap.add_argument("--dump", help="UPC: save its Webami page to webami_dump.html and exit (to fix selectors)")
    a = ap.parse_args()
    if a.dump:
        soup = S._fetch_product_page(a.dump); open("webami_dump.html", "w").write(str(soup)); print("saved webami_dump.html"); return
    pre = "TEST_" if a.test else ""
    shop = (os.environ[pre + "SHOPIFY_STORE"], os.environ[pre + "SHOPIFY_TOKEN"])
    global ORDER_INDEX
    ORDER_INDEX = build_order_index(a.orders_cache, a.refresh_orders)
    prods = run_bulk(shop)
    if a.limit: prods = prods[a.offset * a.limit: (a.offset + 1) * a.limit]
    rows = flat_rows(prods)
    done = set()
    if os.path.exists(a.out) and not a.redo:
        done = {r["shopify_variant_id"] for r in csv.DictReader(open(a.out, encoding="utf-8"))}
    todo = [r for r in rows if r["shopify_variant_id"] not in done]
    print(f"{len(prods)} products, {len(rows)} variants, {len(todo)} to fetch")
    new = a.redo or not os.path.exists(a.out)
    with open(a.out, "w" if new else "a", newline="", encoding="utf-8") as f, ThreadPoolExecutor(a.workers) as ex:
        w = csv.DictWriter(f, COLS, extrasaction="ignore")
        if new: w.writeheader()
        for i, o in enumerate(ex.map(work, todo), 1):
            w.writerow(o); f.flush()
            if i % 25 == 0 or i == len(todo): print(f"  {i}/{len(todo)}", flush=True)


if __name__ == "__main__":
    main()
