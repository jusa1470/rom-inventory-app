#!/usr/bin/env python3
"""
List Shopify products that are NOT in the plan (never classified). Read-only.
  python find_unplanned.py --variants plan_variants.csv [--test]
Writes unplanned_products.csv (product_id,title,vendor,tags,category_name,upc_metafield,status) - same columns as the original exports,
so it can be classified like the earlier batches.
Only these categories: Vinyl, Music CDs, Music Cassette Tapes. Excluded: tag "Used" or title ending "- U", ids in the plan (source or duplicate ids, including skipped rows), plan keepers, products tagged delete-later.
"""
import argparse, csv, json, os, re, time
from push_plan_to_shopify import read_table
from pull_shopify_data import gql, SESSION

BULK = """{ products { edges { node { id handle title vendor status tags category{ fullName }
  upc: metafield(namespace:"custom", key:"upc"){ value } } } } }"""

CATS = {"Media > Music & Sound Recordings > Vinyl", "Media > Music & Sound Recordings > Music CDs",
        "Media > Music & Sound Recordings > Music Cassette Tapes"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", required=True); ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    pre = "TEST_" if a.test else ""
    shop = (os.environ[pre + "SHOPIFY_STORE"], os.environ[pre + "SHOPIFY_TOKEN"])
    planned, handles = set(), set()
    for r in read_table(a.variants):
        planned.add(str(r.get("source_product_id") or "").strip())
        planned |= {d.strip() for d in str(r.get("duplicate_product_ids") or "").split(",") if d.strip()}
        if r.get("handle"): handles.add(r["handle"])
    d = gql(*shop, "mutation($q:String!){ bulkOperationRunQuery(query:$q){ userErrors{ message } } }", {"q": BULK})
    if d["bulkOperationRunQuery"]["userErrors"]: raise RuntimeError(d["bulkOperationRunQuery"]["userErrors"])
    while True:
        time.sleep(3)
        op = gql(*shop, "{ currentBulkOperation(type: QUERY){ status url objectCount } }")["currentBulkOperation"]
        print(f"  bulk: {op['status']} ({op.get('objectCount')})", flush=True)
        if op["status"] == "COMPLETED": break
        if op["status"] in ("FAILED", "CANCELED", "EXPIRED"): raise RuntimeError(op["status"])
    out, total = [], 0
    for line in SESSION.get(op["url"], timeout=300).text.splitlines() if op.get("url") else []:
        if not line: continue
        o = json.loads(line); total += 1
        pid = o["id"].rsplit("/", 1)[1]
        if pid in planned or o["handle"] in handles or "delete-later" in (o.get("tags") or []): continue
        if (o.get("category") or {}).get("fullName") not in CATS: continue
        if "Used" in (o.get("tags") or []) or re.search(r"-\s*U$", o["title"].strip()): continue
        out.append({"product_id": pid, "title": o["title"], "vendor": o["vendor"], "tags": ", ".join(o.get("tags") or []),
                    "category_name": (o.get("category") or {}).get("fullName", ""), "upc_metafield": (o.get("upc") or {}).get("value", ""),
                    "status": o["status"], "handle": o["handle"]})
    with open("unplanned_products.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["product_id", "title", "vendor", "tags", "category_name", "upc_metafield", "status", "handle"])
        w.writeheader(); w.writerows(out)
    print(f"{total} Shopify products, {len(out)} not in plan -> unplanned_products.csv")


if __name__ == "__main__":
    main()