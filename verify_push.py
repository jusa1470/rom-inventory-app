#!/usr/bin/env python3
"""
Find plan products that were missed / half-done in Shopify. Read-only.
  python verify_push.py --products plan_products.csv --variants plan_variants.csv [--test]
Writes push_missed.csv (handle, issue, detail) and redo_handles.txt.
Fix: python push_plan_to_shopify.py --products ... --variants ... --only-handles redo_handles.txt --apply
Issues: missing_product | missing_variant | old_none_format | source_not_tagged
"""
import argparse, csv, json, os, sys, time
from push_plan_to_shopify import read_table, variant_value, OPTION_NAME
from pull_shopify_data import gql, SESSION

BULK = """{ products { edges { node { id handle tags
  variants { edges { node { id selectedOptions{ name value } } } } } } } }"""


def shopify_products(shop):
    d = gql(*shop, "mutation($q:String!){ bulkOperationRunQuery(query:$q){ userErrors{ message } } }", {"q": BULK})
    if d["bulkOperationRunQuery"]["userErrors"]: raise RuntimeError(d["bulkOperationRunQuery"]["userErrors"])
    while True:
        time.sleep(3)
        op = gql(*shop, "{ currentBulkOperation(type: QUERY){ status url objectCount } }")["currentBulkOperation"]
        print(f"  bulk: {op['status']} ({op.get('objectCount')})", flush=True)
        if op["status"] == "COMPLETED": break
        if op["status"] in ("FAILED", "CANCELED", "EXPIRED"): raise RuntimeError(op["status"])
    prods = {}
    if op.get("url"):
        for line in SESSION.get(op["url"], timeout=300).text.splitlines():
            if not line: continue
            o = json.loads(line)
            if "__parentId" in o:
                prods[o["__parentId"]]["vals"] += [s["value"] for s in o["selectedOptions"] if s["name"] == OPTION_NAME]
            else:
                o["vals"] = []; prods[o["id"]] = o
    return {p["id"].rsplit("/", 1)[1]: p for p in prods.values()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--products", required=True); ap.add_argument("--variants", required=True)
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    pre = "TEST_" if a.test else ""
    shop = (os.environ[pre + "SHOPIFY_STORE"], os.environ[pre + "SHOPIFY_TOKEN"])
    byh = {}
    for r in read_table(a.variants):
        if r.get("status") != "skipped" and r.get("handle") and str(r.get("source_product_id", "")).strip():
            byh.setdefault(r["handle"], []).append(r)
    live = shopify_products(shop)
    by_handle = {p["handle"]: p for p in live.values()}
    issues = []
    for p in read_table(a.products):
        h = p["handle"]; rows = byh.get(h)
        if not rows: continue
        sp = by_handle.get(h)
        if not sp: issues.append((h, "missing_product", "")); continue
        have = set(sp["vals"])
        for r in rows:
            if variant_value(r) not in have: issues.append((h, "missing_variant", variant_value(r)))
        if any(v.endswith("| None") for v in have): issues.append((h, "old_none_format", ""))
        src = {str(r["source_product_id"]).strip() for r in rows} | {d.strip() for r in rows for d in str(r.get("duplicate_product_ids") or "").split(",") if d.strip()}
        for sid in src - {sp["id"].rsplit("/", 1)[1]}:
            if sid in live and "delete-later" not in live[sid]["tags"]: issues.append((h, "source_not_tagged", sid))
    with open("push_missed.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["handle", "issue", "detail"]); w.writerows(issues)
    hs = list(dict.fromkeys(i[0] for i in issues))
    open("redo_handles.txt", "w").write("\n".join(hs))
    print(f"{len(issues)} issues on {len(hs)} handles -> push_missed.csv, redo_handles.txt")


if __name__ == "__main__":
    main()