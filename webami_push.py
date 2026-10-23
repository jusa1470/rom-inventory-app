#!/usr/bin/env python3
"""
Step 2: push webami_data.csv into Shopify. PRICE IS NEVER TOUCHED.
Per variant: custom.upc, custom.description, custom.release_date, cost per item, weight.
Per product: custom.genres, tags (+ Webami features), images (only if the product has none), optional --body.
custom.upc is only overwritten when matched by UPC or when the variant had none. Barcode is never touched.

  python webami_push.py --data webami_data.csv --offset 0 --limit 25            # dry run
  python webami_push.py --data webami_data.csv --offset 0 --limit 25 --apply    # real   (then --offset 1, 2, ...)
Options: --body (also set product description from Webami), --test, --workers 4, --log webami_push_log.csv
"""
import argparse, csv, json, os
from concurrent.futures import ThreadPoolExecutor
from pull_shopify_data import gql

UNITS = {"g": "GRAMS", "kg": "KILOGRAMS", "oz": "OUNCES", "lb": "POUNDS"}
Q_UPD = "mutation($p:ProductUpdateInput!){ productUpdate(product:$p){ userErrors{ field message } } }"
Q_VAR = "mutation($id:ID!,$v:[ProductVariantsBulkInput!]!){ productVariantsBulkUpdate(productId:$id, variants:$v){ userErrors{ field message } } }"
Q_IMG = "mutation($id:ID!,$m:[CreateMediaInput!]!){ productCreateMedia(productId:$id, media:$m){ mediaUserErrors{ field message } } }"


def mf(k, t, v): return {"namespace": "custom", "key": k, "type": t, "value": v}
def num(x):
    try: return float(x)
    except (TypeError, ValueError): return None


def variant_input(r):
    v = {"id": r["shopify_variant_id"]}
    trust = r["match_method"] == "upc" or not r["old_upc"]
    inv = {}
    if num(r["cost"]) is not None: inv["cost"] = str(r["cost"])
    if num(r["weight_grams"]) is not None: inv["measurement"] = {"weight": {"value": num(r["weight_grams"]), "unit": "GRAMS"}}
    if inv: v["inventoryItem"] = inv
    m = []
    if r["release_date"]: m.append(mf("release_date", "single_line_text_field", r["release_date"]))
    if r["description"]: m.append(mf("description", "multi_line_text_field", r["description"]))
    if r["webami_upc"] and trust: m.append(mf("upc", "single_line_text_field", r["webami_upc"]))
    if m: v["metafields"] = m
    return v


def process(shop, pid, rows, apply, body):
    log = []
    try:
        p = {"id": pid}
        tags = json.loads(rows[0]["tags"] or "[]")
        feats = [f for r in rows for f in json.loads(r["features"] or "[]")]
        new_tags = list(dict.fromkeys(tags + feats))
        if new_tags != tags: p["tags"] = new_tags
        genres = next((json.loads(r["genres"]) for r in rows if json.loads(r["genres"] or "[]")), [])
        if genres: p["metafields"] = [mf("genres", "list.single_line_text_field", json.dumps(genres))]
        if body:
            d = next((r["description"] for r in rows if r["description"]), "")
            if d: p["descriptionHtml"] = "<p>" + d.replace("\n", "<br>") + "</p>"
        vin = [variant_input(r) for r in rows]
        imgs = next((json.loads(r["image_urls"]) for r in rows if json.loads(r["image_urls"] or "[]")), [])
        add_img = int(rows[0]["media_count"] or 0) == 0 and imgs
        if apply:
            if len(p) > 1:
                e = gql(*shop, Q_UPD, {"p": p})["productUpdate"]["userErrors"]
                if e: raise RuntimeError(f"productUpdate {e}")
            e = gql(*shop, Q_VAR, {"id": pid, "v": vin})["productVariantsBulkUpdate"]["userErrors"]
            if e: raise RuntimeError(f"variants {e}")
            if add_img:
                e = gql(*shop, Q_IMG, {"id": pid, "m": [{"originalSource": u, "mediaContentType": "IMAGE"} for u in imgs[:10]]})["productCreateMedia"]["mediaUserErrors"]
                if e: raise RuntimeError(f"media {e}")
        log.append((pid, len(vin), "updated" if apply else "dry-run", f"images={len(imgs) if add_img else 0}"))
    except Exception as ex:
        log.append((pid, len(rows), "ERROR", str(ex)[:300]))
    return log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="webami_data.csv"); ap.add_argument("--log", default="webami_push_log.csv")
    ap.add_argument("--offset", type=int, default=0); ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--workers", type=int, default=4); ap.add_argument("--apply", action="store_true")
    ap.add_argument("--body", action="store_true"); ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    pre = "TEST_" if a.test else ""
    shop = (os.environ[pre + "SHOPIFY_STORE"], os.environ[pre + "SHOPIFY_TOKEN"])
    groups = {}
    for r in csv.DictReader(open(a.data, encoding="utf-8")):
        if r["status"] == "ok": groups.setdefault(r["shopify_product_id"], []).append(r)
    items = list(groups.items())
    if a.limit: items = items[a.offset * a.limit: (a.offset + 1) * a.limit]
    print(("APPLY" if a.apply else "DRY RUN") + f": {len(items)} products")
    with ThreadPoolExecutor(a.workers) as ex:
        res = [l for lg in ex.map(lambda kv: process(shop, kv[0], kv[1], a.apply, a.body), items) for l in lg]
    with open(a.log, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["product_id", "variants", "result", "note"]); w.writerows(res)
    print(f"done; {sum(1 for r in res if r[2] == 'ERROR')} errors -> {a.log}")


if __name__ == "__main__":
    main()
