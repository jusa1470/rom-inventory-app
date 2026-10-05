from flask import Blueprint, jsonify, request, session

import db.database as db
import config

import re as _re

from services.feature_parser import apply_features, build_title
from services.price import suggested_price, actual_margin, format_price
from shopify.client import ShopifyClient
from webami.scraper import scrape_product, get_cost

bp = Blueprint("products", __name__)


def _auth():
    if not session.get("authenticated"):
        return jsonify({"error": "Not authenticated"}), 401
    return None


# ── List ──────────────────────────────────────────────────────────────────────

@bp.get("/api/products")
def list_products():
    err = _auth()
    if err: return err
    result = db.get_shopify_products(
        page          = int(request.args.get("page", 1)),
        per_page      = min(int(request.args.get("per_page", 50)), 200),
        search        = request.args.get("q", "").strip(),
        status_filter = request.args.get("status", "").strip(),
        mapped_filter = request.args.get("mapped", "").strip(),
        format_filter = request.args.get("format", "").strip(),
        sort          = request.args.get("sort", "title_asc"),
        title_filter    = request.args.get("title", "").strip(),
        vendor_filter   = request.args.get("vendor", "").strip(),
        upc_filter      = request.args.get("upc", "").strip(),
        category_filter = request.args.get("category", "").strip(),
        ptype_filter    = request.args.get("ptype", "").strip(),
        tags_filter     = request.args.get("tags", "").strip(),
        genres_filter   = request.args.get("genres", "").strip(),
    )
    margin = session.get("target_margin") or 0.34
    for item in result["items"]:
        cost  = float(item.get("webami_cost") or item.get("cost") or 0)
        price = float(item.get("price") or 0)
        item["suggested_price"] = format_price(suggested_price(cost, margin)) if cost else None
        item["actual_margin"]   = actual_margin(cost, price) if cost and price else None
    return jsonify(result)


@bp.get("/api/products/filter-options")
def filter_options():
    err = _auth()
    if err: return err
    return jsonify({
        "categories": db.get_distinct_categories(),
        "product_types": db.get_distinct_product_types(),
    })


# ── Detail - query param avoids GID slash routing issues ──────────────────────

@bp.get("/api/products/detail")
def get_product():
    err = _auth()
    if err: return err
    product_id = request.args.get("id", "").strip()
    if not product_id:
        return jsonify({"error": "id required"}), 400
    product = db.get_shopify_product_detail(product_id)
    if not product:
        return jsonify({"error": "Not found"}), 404
    margin = session.get("target_margin") or 0.34

    m = product.get("mapping")
    if m and m.get("weight_grams"):
        m["weight"] = round(float(m["weight_grams"]) / 453.592, 4)
        m["weight_unit"] = "POUNDS"

    for v in product.get("variants", []):
        if m:
            cost  = float(m.get("wcost") or 0)
            price = float(v.get("price") or 0)
            v["suggested_price"] = format_price(suggested_price(cost, margin)) if cost else None
            v["actual_margin"]   = actual_margin(cost, price) if cost and price else None
    return jsonify(product)


# ── Webami scraping ───────────────────────────────────────────────────────────

@bp.get("/api/webami/product/<upc>")
def get_webami_product(upc: str):
    err = _auth()
    if err: return err
    cached = db.get_webami_product(upc)
    if cached:
        return jsonify(cached)
    try:
        result = scrape_product(upc)
        return jsonify(result) if result else (jsonify({"error": "Not found"}), 404)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.get("/api/webami/search")
def search_webami():
    err = _auth()
    if err: return err
    title  = request.args.get("title", "").strip()
    artist = request.args.get("artist", "").strip()
    fmt    = request.args.get("format", "").strip() or None
    if not title:
        return jsonify({"error": "title required"}), 400
    from webami.scraper import search_for_replacement_upc
    upc = search_for_replacement_upc("", title, artist, fmt=fmt)
    if not upc:
        return jsonify({"error": "No match found"}), 404
    result = scrape_product(upc, title=title, artist=artist, fmt=fmt)
    return jsonify(result) if result else (jsonify({"error": "Not found"}), 404)


@bp.post("/api/webami/scrape")
def scrape_webami():
    err = _auth()
    if err: return err
    data   = request.get_json(silent=True) or {}
    upc    = (data.get("upc") or "").strip()
    title  = (data.get("title") or "").strip()
    artist = (data.get("artist") or "").strip()
    fmt    = (data.get("format") or "").strip() or None
    if not upc:
        return jsonify({"error": "UPC required"}), 400

    # If UPC isn't a real barcode, try to resolve the actual Webami UPC
    if not _re.fullmatch(r'\d{8,14}', upc):
        original_upc = upc
        # 1. Check alias table
        alias = db.get_alias(upc)
        if alias:
            upc = alias["active_upc"]
        else:
            # 2. Check order items / webami cache by title
            found = db.find_webami_upc_by_title(title)
            if found:
                if _re.fullmatch(r'\d{6,14}', original_upc):
                    db.upsert_product_alias(original_upc, found, "resolved via title match in orders")
                upc = found
            # 3. Fall through to scrape_product which will do its own search fallback

    try:
        result = scrape_product(upc, title=title, artist=artist, fmt=fmt)
        return jsonify(result) if result else (jsonify({"error": "Not found on Webami"}), 404)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.post("/api/webami/cost/<upc>")
def refresh_cost(upc: str):
    err = _auth()
    if err: return err
    try:
        cost = get_cost(upc)
        if cost is not None:
            db.upsert_webami_product({"upc": upc, "cost": cost})
            return jsonify({"upc": upc, "cost": cost})
        return jsonify({"error": "Cost not available"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Mapping - all use body/query to avoid GID in URL path ────────────────────

@bp.post("/api/products/map")
def map_product():
    err = _auth()
    if err: return err
    data       = request.get_json(silent=True) or {}
    product_id = (data.get("product_id") or "").strip()
    webami_upc = (data.get("webami_upc") or "").strip()
    if not product_id or not webami_upc:
        return jsonify({"error": "variant_id and webami_upc required"}), 400
    db.confirm_mapping(product_id, webami_upc)
    return jsonify({"ok": True})


@bp.post("/api/products/unmap")
def unmap_product():
    err = _auth()
    if err: return err
    data       = request.get_json(silent=True) or {}
    product_id = (data.get("product_id") or "").strip()
    if not product_id:
        return jsonify({"error": "product_id required"}), 400
    db.delete_mapping(product_id)
    return jsonify({"ok": True})


@bp.post("/api/products/force-map")
def force_map():
    err = _auth()
    if err: return err
    data       = request.get_json(silent=True) or {}
    product_id = (data.get("product_id") or "").strip()
    webami_upc = (data.get("webami_upc") or "").strip()
    if not product_id or not webami_upc:
        return jsonify({"error": "product_id and webami_upc required"}), 400
    db.force_map_product(product_id, webami_upc)
    return jsonify({"ok": True})


# ── Matching queue ────────────────────────────────────────────────────────────

@bp.get("/api/matching/queue")
def review_queue():
    err = _auth()
    if err: return err
    return jsonify(db.get_review_queue(
        page=int(request.args.get("page", 1)),
        per_page=min(int(request.args.get("per_page", 20)), 100),
        hide_dash_u=request.args.get("hide_dash_u", "0") == "1"
    ))


@bp.post("/api/matching/confirm")
def confirm_match():
    err = _auth()
    if err: return err
    data       = request.get_json(silent=True) or {}
    product_id = (data.get("product_id") or "").strip()
    webami_upc = (data.get("webami_upc") or "").strip()
    if not product_id or not webami_upc:
        return jsonify({"error": "variant_id and webami_upc required"}), 400
    if not db.get_webami_product(webami_upc):
        try: scrape_product(webami_upc)
        except Exception: pass
    db.confirm_mapping(product_id, webami_upc)
    return jsonify({"ok": True})


@bp.post("/api/matching/reject")
def reject_match():
    err = _auth()
    if err: return err
    data       = request.get_json(silent=True) or {}
    product_id = (data.get("product_id") or "").strip()
    if not product_id:
        return jsonify({"error": "product_id required"}), 400
    db.reject_mapping(product_id)
    return jsonify({"ok": True})


@bp.get("/api/matching/duplicates")
def list_duplicates():
    err = _auth()
    if err: return err
    return jsonify(db.get_duplicate_groups(
        page=int(request.args.get("page", 1)),
        per_page=min(int(request.args.get("per_page", 20)), 100)
    ))


@bp.post("/api/matching/duplicates/<int:group_id>/resolve")
def resolve_duplicate(group_id: int):
    err = _auth()
    if err: return err
    data   = request.get_json(silent=True) or {}
    action = data.get("action") or "dismissed"
    if action not in ("merged", "dismissed"):
        return jsonify({"error": "action must be merged or dismissed"}), 400
    db.resolve_duplicate_group(group_id, action)
    return jsonify({"ok": True})


@bp.get("/api/matching/missing-fields")
def missing_fields():
    err = _auth()
    if err: return err
    return jsonify(db.get_products_with_missing_fields(
        page=int(request.args.get("page",1)),
        per_page=min(int(request.args.get("per_page",20)),100),
        field_filter=request.args.get("field",""),
        sort=request.args.get("sort","title_asc"),
        q_title=request.args.get("q_title","").strip(),
        q_vendor=request.args.get("q_vendor","").strip(),
        status_filter=request.args.get("status","").strip(),
        q_category=request.args.get("q_category","").strip(),
    ))


@bp.get("/api/matching/unmatched")
def unmatched_queue():
    err = _auth()
    if err: return err
    return jsonify(db.get_unmatched_queue(
        page=int(request.args.get("page", 1)),
        per_page=min(int(request.args.get("per_page", 20)), 100),
        q_title=request.args.get("q_title", "").strip(),
        q_vendor=request.args.get("q_vendor", "").strip(),
        q_category=request.args.get("q_category", "").strip(),
        sort=request.args.get("sort", "title_asc"),
    ))


@bp.post("/api/products/ignore-unmatched")
def ignore_unmatched():
    err = _auth()
    if err: return err
    data = request.get_json(silent=True) or {}
    product_id = (data.get("product_id") or "").strip()
    notes = (data.get("notes") or "").strip() or None
    if not product_id:
        return jsonify({"error": "product_id required"}), 400
    db.ignore_unmatched(product_id, notes)
    return jsonify({"ok": True})


@bp.post("/api/products/unignore-unmatched")
def unignore_unmatched():
    err = _auth()
    if err: return err
    data = request.get_json(silent=True) or {}
    product_id = (data.get("product_id") or "").strip()
    if not product_id:
        return jsonify({"error": "product_id required"}), 400
    db.unignore_unmatched(product_id)
    return jsonify({"ok": True})


@bp.get("/api/matching/variances")
def field_variances():
    err = _auth()
    if err: return err
    fields = request.args.get("fields", "title,artist,cost").split(",")
    return jsonify(db.get_field_variances(
        fields,
        page=int(request.args.get("page", 1)),
        per_page=min(int(request.args.get("per_page", 20)), 100),
        q_title=request.args.get("q_title", "").strip(),
        hide_u=request.args.get("hide_u", "1") == "1",
    ))


@bp.post("/api/matching/variances/ignore")
def ignore_variance_field():
    err = _auth()
    if err: return err
    data = request.get_json(silent=True) or {}
    product_id = (data.get("product_id") or "").strip()
    field      = (data.get("field") or "").strip()
    old_value  = data.get("old_value")
    new_value  = data.get("new_value")
    if not product_id or not field:
        return jsonify({"error": "product_id and field required"}), 400
    db.ignore_variance(product_id, field, old_value, new_value)
    return jsonify({"ok": True})


@bp.post("/api/products/push-variance-fields")
def push_variance_fields():
    err = _auth()
    if err: return err
    data = request.get_json(silent=True) or {}
    updates = data.get("updates") or []  # [{product_id, variant_id, fields: {title, artist, cost, weight}}]
    if not updates:
        return jsonify({"error": "No updates provided"}), 400
    if db.is_dry_run():
        return jsonify({"ok": True, "dry_run": True, "would_update": len(updates)})
    store = session.get("shopify_store"); token = session.get("shopify_token")
    if not store or not token:
        return jsonify({"error": "Shopify not configured"}), 400
    client = ShopifyClient(store, token)
    results = []
    for u in updates:
        pid = u.get("product_id"); vid = u.get("variant_id"); fields = u.get("fields") or {}
        try:
            prod_input = {"id": pid}
            if "title" in fields:  prod_input["title"] = fields["title"]
            if "artist" in fields: prod_input["vendor"] = fields["artist"]
            if "tags" in fields:   prod_input["tags"] = [t.strip() for t in fields["tags"].split(",") if t.strip()]
            if len(prod_input) > 1:
                client.update_product(prod_input)
                db.upsert_shopify_product({"product_id": pid, **prod_input})
            if vid and "cost" in fields:
                v = next((x for x in db.get_shopify_product_detail(pid).get("variants", [])
                          if x["variant_id"] == vid), None)
                if v and v.get("inventory_item_id"):
                    client.update_inventory_item_cost(v["inventory_item_id"], float(fields["cost"]))
            if vid and "weight" in fields:
                client.update_variant_bulk(pid, vid, weight=float(fields["weight"]), weight_unit="POUNDS")
            results.append({"product_id": pid, "ok": True})
        except Exception as e:
            results.append({"product_id": pid, "ok": False, "error": str(e)})
    return jsonify({"ok": True, "results": results})


@bp.post("/api/products/title-override")
def set_title_override():
    err = _auth()
    if err: return err
    data = request.get_json(silent=True) or {}
    product_id = (data.get("product_id") or "").strip()
    title = (data.get("correct_title") or "").strip()
    if not product_id or not title:
        return jsonify({"error": "product_id and correct_title required"}), 400
    db.set_title_override(product_id, title)
    return jsonify({"ok": True})


@bp.post("/api/products/update-fields")
def update_product_fields():
    err = _auth()
    if err: return err
    data = request.get_json(silent=True) or {}
    product_id = (data.get("product_id") or "").strip()
    variant_id = (data.get("variant_id") or "").strip()
    if not product_id:
        return jsonify({"error": "product_id required"}), 400
    if db.is_dry_run():
        return jsonify({"ok": True, "dry_run": True})
    store = session.get("shopify_store"); token = session.get("shopify_token")
    if not store or not token:
        return jsonify({"error": "Shopify not configured"}), 400
    client = ShopifyClient(store, token)
    results = {}; errors = []
    prod_input = {"id": product_id}
    if "title" in data:        prod_input["title"] = data["title"]
    if "vendor" in data:       prod_input["vendor"] = data["vendor"]
    if "product_type" in data: prod_input["productType"] = data["product_type"]
    if "upc" in data:
        cfg = db.get_config() or {}
        client.set_metafields(product_id, [{
            "namespace": cfg.get("shopify_upc_ns", "custom"),
            "key": cfg.get("shopify_upc_key", "upc"),
            "value": data["upc"],
            "type": "single_line_text_field",
        }])
        db.upsert_shopify_product({"product_id": product_id, "upc": data["upc"]})
        results["upc"] = "updated"
    if len(prod_input) > 1:
        try: 
            client.update_product(prod_input); results["product"] = "updated"
            db.upsert_shopify_product({"product_id": product_id, **prod_input})
        except Exception as e: errors.append(f"product: {e}")
    if "category_name" in data:
        try:
            cat_map = dict(config.ALLOWED_CATEGORIES)
            gid = cat_map.get(data["category_name"])
            if gid:
                client.update_product({"id": product_id, "category": gid})
                db.upsert_shopify_product({"product_id": product_id, "category_name": data["category_name"],
                                            "category_id": gid})
                results["category"] = "updated"
            else:
                db.upsert_shopify_product({"product_id": product_id, "category_name": data["category_name"]})
                results["category"] = "updated locally (invalid category, not pushed)"
        except Exception as e: errors.append(f"category: {e}")
    if variant_id and any(k in data for k in ("price","weight","weight_unit")):
        try:
            client.update_variant_bulk(product_id, variant_id,
                price=str(data["price"]) if "price" in data else None,
                weight=float(data["weight"]) if "weight" in data else None,
                weight_unit=data.get("weight_unit"))
            results["variant"] = "updated"
        except Exception as e: errors.append(f"variant: {e}")
    if variant_id and "cost" in data:
        try:
            product = db.get_shopify_product_detail(product_id)
            v = next((x for x in product.get("variants", []) if x["variant_id"] == variant_id), None)
            if v and v.get("inventory_item_id"):
                client.update_inventory_item_cost(v["inventory_item_id"], float(data["cost"]))
                results["cost"] = "updated"
        except Exception as e: errors.append(f"cost: {e}")
    return jsonify({"ok": not errors, "results": results, "errors": errors})


@bp.post("/api/products/push-all-upcs")
def push_all_upcs():
    err = _auth()
    if err: return err

    rows = db.get_active_mapped_products_with_upc()
    dry  = db.is_dry_run()

    if dry:
        return jsonify({"ok": True, "dry_run": True, "would_push": len(rows), "items": rows})

    store = session.get("shopify_store"); token = session.get("shopify_token")
    if not store or not token:
        return jsonify({"error": "Shopify not configured"}), 400
    cfg = db.get_config() or {}
    client = ShopifyClient(store, token)

    pushed = 0; errors = []
    for row in rows:
        try:
            client.set_metafields(row["product_id"], [{
                "namespace": cfg.get("shopify_upc_ns", "custom"),
                "key": cfg.get("shopify_upc_key", "upc"),
                "value": row["webami_upc"],
                "type": "single_line_text_field",
            }])
            pushed += 1
        except Exception as e:
            errors.append(f"{row['product_id']}: {e}")
    return jsonify({"ok": not errors, "pushed": pushed, "errors": errors})


# ── Push price ────────────────────────────────────────────────────────────────

@bp.post("/api/products/push-price")
def push_price():
    if db.is_dry_run():
        return jsonify({"ok": True, "dry_run": True, "message": "Dry run mode: price update skipped"})
    err = _auth()
    if err: return err
    data       = request.get_json(silent=True) or {}
    product_id = (data.get("product_id") or "").strip()
    variant_id = (data.get("variant_id") or "").strip()
    price      = data.get("price")
    if not product_id or not variant_id or price is None:
        return jsonify({"error": "product_id, variant_id, price required"}), 400
    store = session.get("shopify_store"); token = session.get("shopify_token")
    if not store or not token:
        return jsonify({"error": "Shopify not configured"}), 400
    try:
        ShopifyClient(store, token).update_variant_price(
            product_id, variant_id, format_price(float(price)))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Push Webami data to Shopify ───────────────────────────────────────────────

@bp.post("/api/products/push-webami-data")
def push_webami_data():
    err = _auth()
    if err: return err
    data       = request.get_json(silent=True) or {}
    product_id = (data.get("product_id") or "").strip()
    push_flags = data.get("push", {})

    if not product_id:
        return jsonify({"error": "product_id required"}), 400

    if db.is_dry_run():
        return jsonify({"ok": True, "dry_run": True, "results": {}, "message": "Dry run mode: Webami push skipped"})

    product = db.get_shopify_product_detail(product_id)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    mapping = product.get("mapping")
    if not mapping or mapping.get("status") != "active":
        return jsonify({"error": "No active Webami mapping"}), 400
    
    variant = (product.get("variants") or [{}])[0]
    variant_id = variant.get("variant_id")

    wp = db.get_webami_product(mapping["webami_upc"])
    if not wp:
        try: wp = scrape_product(mapping["webami_upc"])
        except Exception as e: return jsonify({"error": f"Webami fetch failed: {e}"}), 500
    if not wp:
        return jsonify({"error": "Webami product not found"}), 404

    store  = session.get("shopify_store"); token = session.get("shopify_token")
    margin = session.get("target_margin") or 0.34
    if not store or not token:
        return jsonify({"error": "Shopify not configured"}), 400

    client  = ShopifyClient(store, token)
    results = {}; errors = []

    # Title
    if push_flags.get("title", True) and wp.get("features"):
        new_title = build_title(wp.get("title") or product["title"], apply_features(wp["features"]))
    else:
        new_title = wp.get("title") or product["title"]

    product_input: dict = {"id": product_id}
    if push_flags.get("title", True): product_input["title"] = new_title
    if push_flags.get("vendor", True):
        artist = db.resolve_artist(wp.get("artist") or wp.get("brand") or "")
        if artist: product_input["vendor"] = artist
    if len(product_input) > 1:
        try: client.update_product(product_input); results["product"] = "updated"
        except Exception as e: errors.append(f"product: {e}")

    # Metafields
    cfg = db.get_config() or {}
    metafields = []
    if push_flags.get("upc", True) and wp.get("upc"):
        metafields.append({"namespace": cfg.get("shopify_upc_ns","custom"),
                           "key": cfg.get("shopify_upc_key","upc"),
                           "value": wp["upc"], "type": "single_line_text_field"})
    if push_flags.get("genres", True) and wp.get("genres"):
        import json as _j
        genres = wp["genres"][:3] if isinstance(wp["genres"], list) else []
        if genres:
            metafields.append({"namespace": cfg.get("shopify_genres_ns","custom"),
                               "key": cfg.get("shopify_genres_key","genres"),
                               "value": _j.dumps(genres), "type": "list.single_line_text_field"})
    if metafields:
        try: client.set_metafields(product_id, metafields); results["metafields"] = "updated"
        except Exception as e: errors.append(f"metafields: {e}")

    # Variant
    vupdate: dict = {}
    if push_flags.get("weight", True) and wp.get("weight_grams"):
        vupdate["weight"] = round(wp["weight_grams"] / 453.592, 4)
        vupdate["weight_unit"] = "POUNDS"
    if push_flags.get("price", True) and wp.get("cost"):
        vupdate["price"] = format_price(suggested_price(wp["cost"], margin))
    if vupdate:
        try:
            client.update_variant_bulk(product_id, variant_id,
                price=vupdate.get("price"), weight=vupdate.get("weight"),
                weight_unit=vupdate.get("weight_unit"))
            results["variant"] = "updated"
        except Exception as e: errors.append(f"variant: {e}")

    # Images — dedup by numeric ID in filename
    if push_flags.get("images", True) and wp.get("image_urls"):
        import re as _re, urllib.parse as _up
        def _img_nums(u):
            return set(_re.findall(r'\d{6,}', _up.urlparse(u or '').path))
        existing = db.get_conn().execute(
            "SELECT url FROM shopify_images WHERE product_id=?", (product_id,)).fetchall()
        ex_num_sets = [_img_nums(r[0]) for r in existing]
        new_urls = []
        for u in (wp["image_urls"] or [])[:3]:
            nums = _img_nums(u)
            if nums and any(nums & ex for ex in ex_num_sets if ex):
                continue
            new_urls.append(u)
        if new_urls:
            try: client.create_media_from_urls(product_id, new_urls); results["images"] = f"{len(new_urls)} uploaded"
            except Exception as e: errors.append(f"images: {e}")
        else:
            results["images"] = "already up to date"

    return jsonify({"ok": not errors, "results": results, "errors": errors})
