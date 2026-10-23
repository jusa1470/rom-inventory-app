#!/usr/bin/env python3
"""
Push the plan to Shopify: for each plan product, update the EXISTING keeper product (title, vendor,
handle + redirect, product type, single option "Edition | Color | Attributes") and add/update its plan variants.

Keeper = source_product_id of the first variant row of the handle. That product keeps its id, images, metafields,
collections and sales history. Every other variant row is created as a NEW variant on the keeper (price, barcode, cost,
weight, quantity copied from the plan file). Run pull_shopify_data.py first so those columns are filled.

Setup:   pip install requests openpyxl
         export SHOPIFY_STORE=your-store.myshopify.com
         (optional) export TEST_SHOPIFY_STORE=... TEST_SHOPIFY_TOKEN=...   and add --test to use them
         export SHOPIFY_TOKEN=shpat_xxx   (scopes: read/write_products, read/write_inventory, read_locations)

Usage:   python push_plan_to_shopify.py --products plan_products.csv --variants plan_variants.csv --offset 0 --limit 25          # dry run
         python push_plan_to_shopify.py --products plan_products.csv --variants plan_variants.csv --offset 0 --limit 25 --apply  # real
         next set:  --offset 1 --limit 25 --apply   (then 2, 3, ...)

--limit = plan products per run; --offset = which set (0, 1, 2, ...), start = offset x limit. Plan products are rows of
the products file (skipped rows ignored). Dry run is the default.
Safe to re-run: products already converted are detected and only missing variants are created.
Old source products (the non-keeper ones) are listed in push_log.csv; --retire-sources archive|delete acts on them
(default none). Zero/transfer their stock first.
Metafields copied from the plan file: product custom.genres (list) + custom.type; variant custom.release_date,
custom.description, custom.upc.
Speed: --workers products in parallel (default 4), one reused connection, and update calls are skipped for products/variants
that already match the plan (so re-runs are fast).
If the keeper product no longer exists in Shopify, a NEW product is created from the plan (image_url, tags, product_type
if present in the plan file) with status --new-status (default DRAFT).
"""
import argparse, csv, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import requests

SESSION = requests.Session()   # one reused connection = faster

API_VERSION = "2025-01"
OPTION_NAME = "Edition | Color | Attributes"
UNITS = {"g": "GRAMS", "kg": "KILOGRAMS", "oz": "OUNCES", "lb": "POUNDS"}


def variant_value(r):
    """Option value shown for a variant, e.g. 'Standard | Black Vinyl | None'. Edit here to change the naming."""
    return " | ".join([(r.get("edition") or "Standard").strip(), (r.get("color") or "None").strip(), (r.get("attributes") or "None").strip()])


# ---------- file io ----------
def read_table(path):
    if path.lower().endswith(".csv"):
        with open(path, newline="", encoding="utf-8-sig") as f:
            r = csv.DictReader(f)
            return [dict(x) for x in r]
    import openpyxl
    rows = list(openpyxl.load_workbook(path).active.iter_rows(values_only=True))
    hdr = [str(h) for h in rows[0]]
    return [{h: ("" if v is None else v) for h, v in zip(hdr, r)} for r in rows[1:]]


# ---------- shopify ----------
class Shop:
    def __init__(self, store, token):
        self.url = f"https://{store}/admin/api/{API_VERSION}/graphql.json"
        self.h = {"X-Shopify-Access-Token": token}

    def gql(self, query, variables=None):
        for attempt in range(6):
            r = SESSION.post(self.url, json={"query": query, "variables": variables or {}}, headers=self.h, timeout=60)
            if r.status_code in (429, 502, 503):
                time.sleep(2 * (attempt + 1)); continue
            if not r.ok:
                print("Status:", r.status_code)
                print("Response:", r.text)
                r.raise_for_status()
            j = r.json()
            errs = j.get("errors") or []
            if any("THROTTLED" in json.dumps(e) for e in errs):
                time.sleep(2 * (attempt + 1)); continue
            if errs:
                raise RuntimeError(json.dumps(errs)[:600])
            ts = (j.get("extensions", {}).get("cost", {}) or {}).get("throttleStatus", {})
            if ts and ts.get("currentlyAvailable", 1000) < 200:
                time.sleep(max(1, (200 - ts["currentlyAvailable"]) / max(ts.get("restoreRate", 50), 1)))
            return j["data"]
        raise RuntimeError("throttled too long")

    def mutate(self, query, variables, key):
        d = self.gql(query, variables)[key]
        ue = d.get("userErrors") or []
        if ue:
            raise RuntimeError(f"{key}: " + "; ".join(f"{'.'.join(map(str, e.get('field') or []))} {e['message']}" for e in ue))
        return d


Q_PRODUCT = """query($id:ID!){ product(id:$id){ id handle title vendor productType category{ id }
  g: metafield(namespace:"custom", key:"genres"){ value }
  t: metafield(namespace:"custom", key:"type"){ value }
  options{ id name position optionValues{ id name } }
  variants(first:30){ nodes{ id price barcode selectedOptions{ name value }
    inventoryItem{ id unitCost{ amount } measurement{ weight{ value unit } } }
    rd: metafield(namespace:"custom", key:"release_date"){ value }
    ds: metafield(namespace:"custom", key:"description"){ value }
    up: metafield(namespace:"custom", key:"upc"){ value } } } } }"""
Q_LOC = "{ locations(first:1){ nodes{ id name } } }"
M_UPDATE = """mutation($p:ProductUpdateInput!){ productUpdate(product:$p){ product{ id handle } userErrors{ field message } } }"""
M_OPTION = """mutation($pid:ID!,$opt:OptionUpdateInput!,$vals:[OptionValueUpdateInput!]){
  productOptionUpdate(productId:$pid, option:$opt, optionValuesToUpdate:$vals){ product{ id } userErrors{ field message } } }"""
M_VUPDATE = """mutation($pid:ID!,$v:[ProductVariantsBulkInput!]!){
  productVariantsBulkUpdate(productId:$pid, variants:$v){ productVariants{ id } userErrors{ field message } } }"""
M_VCREATE = """mutation($pid:ID!,$v:[ProductVariantsBulkInput!]!){
  productVariantsBulkCreate(productId:$pid, variants:$v){ productVariants{ id } userErrors{ field message } } }"""
M_STATUS = """mutation($p:ProductUpdateInput!){ productUpdate(product:$p){ product{ id } userErrors{ field message } } }"""
M_SET = """mutation($input:ProductSetInput!){ productSet(input:$input, synchronous:true){ product{ id } userErrors{ field message } } }"""
NEW_STATUS = "DRAFT"
M_DELETE = """mutation($i:ProductDeleteInput!){ productDelete(input:$i){ deletedProductId userErrors{ field message } } }"""


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def mf(key, type_, value):
    return {"namespace": "custom", "key": key, "type": type_, "value": value}


def first_nonblank(col, p, vrows):
    for src in [p] + list(vrows):
        v = str(src.get(col) or "").strip()
        if v: return v
    return ""


def product_metafields(p, vrows):
    """custom.genres (list of single line text) and custom.type (single line text) - product level."""
    out = []
    g = first_nonblank("genres", p, vrows)
    if g:
        if not g.startswith("["): g = json.dumps([x.strip() for x in g.split(",") if x.strip()])
        out.append(mf("genres", "list.single_line_text_field", g))
    t = first_nonblank("type", p, vrows)
    if t: out.append(mf("type", "single_line_text_field", t))
    return out


def variant_metafields(r):
    """custom.release_date, custom.description (multi line), custom.upc - variant level."""
    out = []
    for key, typ in (("release_date", "single_line_text_field"), ("description", "multi_line_text_field"), ("upc", "single_line_text_field")):
        val = str(r.get(key) or "").strip()
        if val: out.append(mf(key, typ, val))
    return out


def variant_input(r, loc=None, existing=False):
    """Plan variant row -> ProductVariantsBulkInput (blank values are left out)."""
    v = {}
    if num(r.get("price")) is not None: v["price"] = str(r["price"])
    if str(r.get("upc") or "").strip(): v["barcode"] = str(r["upc"]).strip()
    inv = {"tracked": True}
    if num(r.get("cost_per_item")) is not None: inv["cost"] = str(r["cost_per_item"])
    if num(r.get("weight")) is not None and UNITS.get(str(r.get("weight_unit")).strip()):
        inv["measurement"] = {"weight": {"value": num(r["weight"]), "unit": UNITS[str(r["weight_unit"]).strip()]}}
    v["inventoryItem"] = inv
    if variant_metafields(r): v["metafields"] = variant_metafields(r)
    if not existing and loc and num(r.get("quantity")) is not None:
        v["inventoryQuantities"] = [{"availableQuantity": int(num(r["quantity"])), "locationId": loc}]
    return v


CATEGORY_IDS = {"vinyl": "gid://shopify/TaxonomyCategory/me-3-6", "cd": "gid://shopify/TaxonomyCategory/me-3-3",
                "cassette": "gid://shopify/TaxonomyCategory/me-3-2"}


CAT_PREFIX = "Media > Music & Sound Recordings > "
CATEGORY_BY_NAME = {CAT_PREFIX + "Vinyl": CATEGORY_IDS["vinyl"], CAT_PREFIX + "Music CDs": CATEGORY_IDS["cd"],
                    CAT_PREFIX + "Music Cassette Tapes": CATEGORY_IDS["cassette"]}


def category_id(p):
    """Taxonomy category from the plan (format column, else category name with or without the full prefix).
    Needed so metafield definitions constrained to a category accept the product."""
    c = str(p.get("category") or "").strip()
    if c and not c.startswith("Media >"): c = CAT_PREFIX + c
    return CATEGORY_IDS.get(str(p.get("format") or "").strip().lower()) or CATEGORY_BY_NAME.get(c)


def same(a, b):
    return str(a or "").strip() == str(b or "").strip()


def same_num(a, b):
    na, nb = num(a), num(b)
    return na is not None and nb is not None and abs(na - nb) < 1e-9


def product_unchanged(prod, p, vrows):
    """True when the product already has the plan's title/handle/vendor/type/category/metafields (skip the update call)."""
    if not (same(prod["title"], p["title"]) and same(prod["handle"], p["handle"]) and same(prod["vendor"], p["vendor"])):
        return False
    if str(p.get("product_type") or "").strip() and not same(prod["productType"], p["product_type"]): return False
    cid = category_id(p)
    if cid and (prod.get("category") or {}).get("id") != cid: return False
    for m in product_metafields(p, vrows):
        cur = (prod.get("g") if m["key"] == "genres" else prod.get("t")) or {}
        cv = cur.get("value") or ""
        if m["key"] == "genres":
            try: same_val = json.loads(cv) == json.loads(m["value"])
            except ValueError: same_val = False
        else:
            same_val = same(cv, m["value"])
        if not same_val: return False
    return True


def variant_unchanged(node, r):
    """True when the existing variant already has every value the plan row would set (skip the update call)."""
    if num(r.get("price")) is not None and not same_num(node.get("price"), r["price"]): return False
    if str(r.get("upc") or "").strip() and not same(node.get("barcode"), r["upc"]): return False
    inv = node.get("inventoryItem") or {}
    if num(r.get("cost_per_item")) is not None and not same_num((inv.get("unitCost") or {}).get("amount"), r["cost_per_item"]): return False
    w = (inv.get("measurement") or {}).get("weight") or {}
    if num(r.get("weight")) is not None and UNITS.get(str(r.get("weight_unit")).strip()):
        if not (same_num(w.get("value"), r["weight"]) and w.get("unit") == UNITS[str(r["weight_unit"]).strip()]): return False
    for key, alias in (("release_date", "rd"), ("description", "ds"), ("upc", "up")):
        if str(r.get(key) or "").strip() and not same((node.get(alias) or {}).get("value"), r[key]): return False
    return True


def create_product(shop, p, vrows, loc):
    """Keeper product not found in Shopify -> create a brand-new product with all plan variants."""
    tags = p.get("tags") or ""
    try:
        tags = json.loads(tags) if str(tags).startswith("[") else [t.strip() for t in str(tags).split(",") if t.strip()]
    except ValueError:
        tags = []
    vs = []
    for r in vrows:
        vi = variant_input(r)
        v = {"optionValues": [{"optionName": OPTION_NAME, "name": variant_value(r)}], "inventoryItem": vi["inventoryItem"]}
        for k in ("price", "barcode", "metafields"):
            if k in vi: v[k] = vi[k]
        if loc and num(r.get("quantity")) is not None:
            v["inventoryQuantities"] = [{"locationId": loc, "name": "available", "quantity": int(num(r["quantity"]))}]
        vs.append(v)
    inp = {"title": p["title"], "handle": p["handle"], "vendor": p["vendor"], "status": NEW_STATUS, "tags": tags,
           "productOptions": [{"name": OPTION_NAME, "values": [{"name": variant_value(r)} for r in vrows]}], "variants": vs}
    if str(p.get("product_type") or "").strip(): inp["productType"] = p["product_type"]
    if category_id(p): inp["category"] = category_id(p)
    if product_metafields(p, vrows): inp["metafields"] = product_metafields(p, vrows)
    if str(p.get("image_url") or "").strip():
        inp["files"] = [{"originalSource": p["image_url"], "contentType": "IMAGE"}]
    res = shop.mutate(M_SET, {"input": inp}, "productSet")
    return res["product"]["id"].rsplit("/", 1)[1]


def process(shop, p, vrows, loc, apply, log):
    handle = p["handle"]
    keeper_id = str(vrows[0]["source_product_id"]).strip()
    kgid = f"gid://shopify/Product/{keeper_id}"
    others = sorted(({str(r["source_product_id"]).strip() for r in vrows[1:]} |
                     {d.strip() for r in vrows for d in str(r.get("duplicate_product_ids") or "").split(",") if d.strip()}) - {keeper_id})
    plan = f"{handle}: keeper {keeper_id}, {len(vrows)} variant(s), retire {others or '-'}"
    if not apply:
        print("DRY", plan)
        for r in vrows: print("     ", variant_value(r), "|", r.get("price"), "|", r.get("upc"))
        log.append([handle, keeper_id, "dry-run", "", ""]); return
    prod = shop.gql(Q_PRODUCT, {"id": kgid})["product"]
    if not prod:
        new_id = create_product(shop, p, vrows, loc)
        log.append([handle, new_id, "created", f"keeper {keeper_id} not found; new product with {len(vrows)} variant(s)", ";".join(others)])
        print("NEW", plan, "->", new_id)
        return
    # 1) title / vendor / handle / type (+301 redirect from old handle) - skipped when already identical
    upd = {"id": kgid, "title": p["title"], "handle": handle, "vendor": p["vendor"], "redirectNewHandle": True}
    if str(p.get("product_type") or "").strip(): upd["productType"] = p["product_type"]
    if category_id(p): upd["category"] = category_id(p)
    if product_metafields(p, vrows): upd["metafields"] = product_metafields(p, vrows)
    if not product_unchanged(prod, p, vrows):
        shop.mutate(M_UPDATE, {"p": upd}, "productUpdate")
    # 2) option: rename the default option and set the keeper variant's value
    opts = prod["options"]
    names = [o["name"] for o in opts]
    first_val = variant_value(vrows[0])
    if OPTION_NAME not in names:
        if len(opts) != 1:
            raise RuntimeError(f"keeper has {len(opts)} options {names}; convert manually")
        o = opts[0]
        shop.mutate(M_OPTION, {"pid": kgid, "opt": {"id": o["id"], "name": OPTION_NAME},
                               "vals": [{"id": o["optionValues"][0]["id"], "name": first_val}]}, "productOptionUpdate")
        if len(prod["variants"]["nodes"]) == 1:   # single default variant: no need to re-read
            prod["variants"]["nodes"][0]["selectedOptions"] = [{"name": OPTION_NAME, "value": first_val}]
        else:
            prod = shop.gql(Q_PRODUCT, {"id": kgid})["product"]
    existing = {next((s["value"] for s in v["selectedOptions"] if s["name"] == OPTION_NAME), None): v for v in prod["variants"]["nodes"]}
    # 3) update keeper variant, 4) create the missing ones
    ups, news = [], []
    for r in vrows:
        val = variant_value(r)
        if val in existing:
            if not variant_unchanged(existing[val], r):
                ups.append({"id": existing[val]["id"], **variant_input(r, loc, existing=True)})
        else:
            news.append({"optionValues": [{"optionName": OPTION_NAME, "name": val}], **variant_input(r, loc)})
    if ups: shop.mutate(M_VUPDATE, {"pid": kgid, "v": ups}, "productVariantsBulkUpdate")
    created = ""
    if news:
        res = shop.mutate(M_VCREATE, {"pid": kgid, "v": news}, "productVariantsBulkCreate")
        created = ",".join(x["id"].rsplit("/", 1)[1] for x in res["productVariants"])
    log.append([handle, keeper_id, "ok", f"updated {len(ups)}, created {len(news)}", ";".join(others)])
    print("OK ", plan, f"(updated {len(ups)}, created {len(news)})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--products", required=True)
    ap.add_argument("--variants", required=True)
    ap.add_argument("--offset", type=int, default=0, help="which set to push (0, 1, 2, ...); starts at offset x limit")
    ap.add_argument("--limit", type=int, default=0, help="how many plan products to push (0 = all)")
    ap.add_argument("--apply", action="store_true", help="actually write to Shopify (default is dry run)")
    ap.add_argument("--location-id", default="", help="inventory location gid; default = first location")
    ap.add_argument("--new-status", choices=["DRAFT", "ACTIVE"], default="DRAFT", help="status for products created because the source wasn't found")
    ap.add_argument("--retire-sources", choices=["none", "archive", "delete"], default="none")
    ap.add_argument("--test", action="store_true", help="use TEST_SHOPIFY_STORE / TEST_SHOPIFY_TOKEN instead of the live store")
    ap.add_argument("--workers", type=int, default=4, help="products pushed in parallel (1 = one at a time)")
    ap.add_argument("--log", default="push_log.csv")
    a = ap.parse_args()
    pre = "TEST_" if a.test else ""
    store, token = os.environ.get(pre + "SHOPIFY_STORE"), os.environ.get(pre + "SHOPIFY_TOKEN")
    if a.apply and (not store or not token):
        sys.exit(f"Set {pre}SHOPIFY_STORE and {pre}SHOPIFY_TOKEN environment variables.")
    if a.test: print("TEST STORE:", store)

    prods = [r for r in read_table(a.products) if r.get("status") != "skipped" and r.get("handle")]
    byh = {}
    for r in read_table(a.variants):
        if r.get("status") != "skipped" and r.get("handle") and str(r.get("source_product_id", "")).strip():
            byh.setdefault(r["handle"], []).append(r)
    prods = [p for p in prods if p["handle"] in byh]
    start = a.offset * a.limit if a.limit else 0
    sel = prods[start: (start + a.limit) if a.limit else None]
    print(f"{len(prods)} plan products; pushing {len(sel)} (set {a.offset}, starting at #{start}) - {'APPLY' if a.apply else 'DRY RUN'}")

    global NEW_STATUS
    NEW_STATUS = a.new_status
    shop = Shop(store, token) if a.apply else None
    loc = None
    if a.apply:
        loc = a.location_id or shop.gql(Q_LOC)["locations"]["nodes"][0]["id"]
    def work(p):
        rows = []
        try:
            process(shop, p, byh[p["handle"]], loc, a.apply, rows)
        except Exception as e:
            # print("ERR", p["handle"], e, flush=True)
            rows.append([p["handle"], str(byh[p["handle"]][0]["source_product_id"]), "error", str(e)[:300], ""])
        return rows
    log = []
    with ThreadPoolExecutor(max_workers=max(1, a.workers) if a.apply else 1) as ex:
        for rows in ex.map(work, sel):
            log.extend(rows)
    if a.apply and a.retire_sources != "none":
        for row in log:
            if row[2] not in ("ok", "created"): continue
            for pid in [x for x in row[4].split(";") if x]:
                gid = f"gid://shopify/Product/{pid}"
                try:
                    if a.retire_sources == "archive": shop.mutate(M_STATUS, {"p": {"id": gid, "status": "ARCHIVED"}}, "productUpdate")
                    else: shop.mutate(M_DELETE, {"i": {"id": gid}}, "productDelete")
                    print("retired", pid)
                except Exception as e:
                    print("ERR retire", pid, e)
                    None
    new = not os.path.exists(a.log)
    with open(a.log, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new: w.writerow(["handle", "keeper_product_id", "result", "detail", "source_products_to_retire"])
        w.writerows(log)
    print("log ->", a.log)


if __name__ == "__main__":
    main()
