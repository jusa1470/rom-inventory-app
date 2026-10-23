#!/usr/bin/env python3
"""
Price tools (use webami_data.csv from webami_fetch.py - it keeps the OLD cost from before webami_push.py).

1) report: compare Webami cost (new_cost) with the previous Shopify cost per item (old_cost)
     python price_tools.py report --data webami_data.csv
   -> price_increases.csv, price_decreases.csv (sorted by % change) with a blank `new_price` column.
2) apply: fill `new_price` for the rows you want (delete or blank the others), then
     python price_tools.py apply --file price_increases.csv            # dry run
     python price_tools.py apply --file price_increases.csv --apply    # real
   Only rows with a new_price are updated. Add --test for the test store.
"""
import argparse, csv, os
from pull_shopify_data import gql

HDR = ["shopify_product_id", "shopify_variant_id", "vendor", "product_title", "sku", "webami_upc", "match_method",
       "old_cost", "new_cost", "change", "pct", "current_price", "margin_at_new_cost", "new_price"]
Q = "mutation($id:ID!,$v:[ProductVariantsBulkInput!]!){ productVariantsBulkUpdate(productId:$id, variants:$v){ userErrors{ field message } } }"


def num(x):
    try: return float(x)
    except (TypeError, ValueError): return None


def report(a):
    up, down = [], []
    for r in csv.DictReader(open(a.data, encoding="utf-8")):
        o, n, p = num(r["old_cost"]), num(r["cost"]), num(r["old_price"])
        if r["status"] != "ok" or o is None or n is None or round(n - o, 2) == 0: continue
        row = {**r, "new_cost": n, "change": round(n - o, 2), "pct": round((n - o) / o * 100, 1) if o else "",
               "current_price": p if p is not None else "", "new_price": "",
               "margin_at_new_cost": round((p - n) / p * 100, 1) if p else ""}
        (up if n > o else down).append(row)
    for name, rows, rev in (("price_increases.csv", up, True), ("price_decreases.csv", down, False)):
        rows.sort(key=lambda r: abs(r["pct"] or 0), reverse=True)
        with open(name, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, HDR, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
        print(f"{name}: {len(rows)}")


def apply(a):
    pre = "TEST_" if a.test else ""
    shop = (os.environ[pre + "SHOPIFY_STORE"], os.environ[pre + "SHOPIFY_TOKEN"])
    groups = {}
    for r in csv.DictReader(open(a.file, encoding="utf-8")):
        if num(r.get("new_price")) is not None:
            groups.setdefault(r["shopify_product_id"], []).append({"id": r["shopify_variant_id"], "price": f"{num(r['new_price']):.2f}"})
    n = sum(len(v) for v in groups.values())
    print(("APPLY" if a.apply else "DRY RUN") + f": {n} prices on {len(groups)} products")
    if not a.apply: return
    for pid, v in groups.items():
        e = gql(*shop, Q, {"id": pid, "v": v})["productVariantsBulkUpdate"]["userErrors"]
        if e: print("ERR", pid, e)
    print("done")


ap = argparse.ArgumentParser()
sub = ap.add_subparsers(dest="cmd", required=True)
r = sub.add_parser("report"); r.add_argument("--data", default="webami_data.csv")
p = sub.add_parser("apply"); p.add_argument("--file", required=True); p.add_argument("--apply", action="store_true"); p.add_argument("--test", action="store_true")
a = ap.parse_args()
report(a) if a.cmd == "report" else apply(a)
