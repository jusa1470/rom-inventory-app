"""
Batch product matcher and Shopify duplicate detector.
FIX #5: batch-inserts all mappings in one transaction instead of one connection per row.
"""

import logging
import re
from typing import Optional

from rapidfuzz import fuzz

import config
import db.database as db
from db.database import db_conn
from services import jobs
from webami.scraper import scrape_product, _title_variants

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Title normalization
# ─────────────────────────────────────────────

_STRIP_PARENS = re.compile(r"[()]+")
_PUNCT        = re.compile(r"[^\w\s]")
_WHITESPACE   = re.compile(r"\s+")

_ARTIST_MATCH_THRESHOLD = 0.80
_COST_TOLERANCE = 0.05  # 5%


def normalize(title: str) -> str:
    if not title:
        return ""
    t = title.lower()
    t = _STRIP_PARENS.sub(" ", t)
    t = re.sub(r"^the\s+", "", t)
    t = _PUNCT.sub(" ", t)
    t = _WHITESPACE.sub(" ", t).strip()
    return t


def similarity(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    ts = fuzz.token_sort_ratio(na, nb) / 100.0
    pr = fuzz.partial_ratio(na, nb)   / 100.0
    len_ratio = min(len(na), len(nb)) / max(len(na), len(nb))
    return max(ts, pr * 0.88 * len_ratio)


# ─────────────────────────────────────────────
# Main batch matching job
# ─────────────────────────────────────────────
# Pass 3: fuzzy title
def run_matcher(job_id: str) -> dict:
    jobs.update(job_id, message="Loading Shopify variants…")

    with db_conn() as conn:
        variants = db._rows(conn.execute(
            """SELECT sp.product_id, sp.title, sp.vendor, sp.upc, sp.category_name, sv.cost
               FROM shopify_products sp
               LEFT JOIN shopify_variants sv ON sv.product_id=sp.product_id
               LEFT JOIN product_mappings pm
                     ON pm.product_id=sp.product_id AND pm.status IN ('active','rejected')
               WHERE pm.id IS NULL
                 AND sp.product_id NOT IN (SELECT product_id FROM unmatched_ignores)
               GROUP BY sp.product_id""").fetchall())

        webami_all = db._rows(conn.execute(
            "SELECT upc, title, artist, format FROM webami_products").fetchall())

    webami_by_upc = {w["upc"]: w for w in webami_all}

    # Scrape any Shopify UPCs not yet in Webami cache
    missing_upcs = [
        p["upc"] for p in variants
        if p.get("upc") and p["upc"].strip() not in webami_by_upc
    ]
    jobs.update(job_id, message=f"Scraping {len(missing_upcs)} missing UPCs from Webami…")
    for upc in missing_upcs:
        try:
            wp = scrape_product(upc)
            if wp:
                webami_by_upc[wp["upc"]] = wp
                webami_all.append({"upc": wp["upc"], "title": wp.get("title"), "artist": wp.get("artist")})
        except Exception:
            pass
        
    order_candidates = db.get_order_item_candidates()
    order_by_upc = {oc["upc"]: oc for oc in order_candidates}

    total  = len(variants)
    auto   = 0
    review = 0
    unmatched = 0

    jobs.update(job_id, total=total, message=f"Matching {total} variants…")

    to_insert: list[tuple] = []   # (variant_id, webami_upc, confidence, score, status)
    _BATCH_SIZE = 100

    def _flush_batch():
        nonlocal to_insert
        if not to_insert:
            return
        with db_conn() as conn:
            conn.executemany(
                """INSERT INTO product_mappings
                   (product_id,webami_upc,confidence,score,status,updated_at)
                   VALUES (?,?,?,?,?,datetime('now'))
                   ON CONFLICT(product_id) DO UPDATE SET
                     webami_upc=excluded.webami_upc, confidence=excluded.confidence,
                     score=excluded.score, status=excluded.status, updated_at=excluded.updated_at""",
                to_insert,
            )
        to_insert = []

    for i, v in enumerate(variants):
        if jobs.is_cancelled(job_id):
            logger.info("Matcher cancelled")
            break
        if i % 50 == 0:
            jobs.update(job_id, progress=i,
                        message=f"Matched {i}/{total} - auto:{auto} review:{review} unmatched:{unmatched}")
        if i > 0 and i % _BATCH_SIZE == 0:
            _flush_batch()

        product_id = v["product_id"]
        upc        = (v.get("upc") or "").strip()
        title      = v.get("title") or ""

        # Pass 1: exact UPC (cached webami_products)
        if upc and upc in webami_by_upc:
            to_insert.append((product_id, upc, "exact_upc", 1.0, "active"))
            auto += 1
            continue

        # Pass 2: alias UPC
        if upc:
            resolved = _resolve_alias(upc, webami_by_upc)
            if resolved != upc and resolved in webami_by_upc:
                to_insert.append((product_id, resolved, "alias_upc", 1.0, "active"))
                auto += 1
                continue

        # Pass 3: fuzzy title against order-item history first
        matched_upc   = None
        matched_score = 0.0
        matched_conf  = None
        if title and order_candidates:
            oc_score, oc_upc = _best_fuzzy(title, v.get("vendor",""), v.get("category_name",""),
                                            order_candidates, variant_cost=v.get("cost"))
            if oc_upc and oc_score >= config.MATCH_REVIEW_THRESHOLD:
                matched_upc, matched_score = oc_upc, oc_score
                matched_conf = "order_item"

        # Pass 4: fuzzy title against webami_products cache (if no order-item match)
        if not matched_upc and title:
            wp_score, wp_upc = _best_fuzzy(title, v.get("vendor",""), v.get("category_name",""),
                                            webami_all, variant_cost=v.get("cost"))
            if wp_upc and wp_score >= config.MATCH_REVIEW_THRESHOLD:
                matched_upc, matched_score = wp_upc, wp_score
                matched_conf = "fuzzy"

        if not matched_upc:
            unmatched += 1
            continue

        # Try to enrich with real webami product data regardless of which pass matched
        if not db.get_webami_product(matched_upc):
            try:
                wp = scrape_product(matched_upc)
                if wp:
                    webami_by_upc[wp["upc"]] = wp
            except Exception:
                wp = None
        else:
            wp = db.get_webami_product(matched_upc)

        confidence = "fuzzy_auto" if matched_score >= config.MATCH_AUTO_THRESHOLD else matched_conf
        if not wp:
            # No real webami product found — fall back to order-item data
            if matched_score >= config.MATCH_AUTO_THRESHOLD:
                to_insert.append((product_id, matched_upc, "order_item_fallback_auto", matched_score, "active"))
                auto += 1
            else:
                to_insert.append((product_id, matched_upc, "order_item_fallback", matched_score, "pending"))
                review += 1
            continue

        if matched_score >= config.MATCH_AUTO_THRESHOLD:
            to_insert.append((product_id, matched_upc, confidence, matched_score, "active"))
            auto += 1
        else:
            to_insert.append((product_id, matched_upc, confidence, matched_score, "pending"))
            review += 1

    # ── Final flush ──────────────────────────────────
    _flush_batch()

    # ── Duplicate detection ────────────────────────────────────────
    jobs.update(job_id, message="Detecting Shopify duplicates…")
    dups = detect_shopify_duplicates()

    from datetime import datetime, timezone
    db.upsert_config(last_matcher_run=datetime.now(timezone.utc).isoformat())
    db.log_sync("matcher", "done",
                f"auto:{auto} review:{review} unmatched:{unmatched} dups:{dups}")
    jobs.update(job_id, progress=total,
                message=f"Done - {auto} auto, {review} review, {unmatched} unmatched, {dups} dup groups")

    return {"auto": auto, "review": review, "unmatched": unmatched, "duplicates": dups}


def _resolve_alias(upc: str, webami_by_upc: dict) -> str:
    row = db.get_alias(upc)
    if row:
        active = row["active_upc"]
        if active in webami_by_upc:
            return active
    return upc


def _cost_compatible(variant_cost, webami_cost) -> bool:
    if not webami_cost or not variant_cost:
        return False
    try:
        vc, wc = float(variant_cost), float(webami_cost)
    except (TypeError, ValueError):
        return True
    if wc == 0:
        return True
    return abs(vc - wc) / wc <= _COST_TOLERANCE


def _best_fuzzy(title: str, vendor: str, category: str, candidates: list[dict],
                 variant_cost=None) -> tuple[float, Optional[str]]:
    best_score = 0.0
    best_upc   = None
    for w in candidates:
        if not w.get("title"):
            continue
        if not config.formats_compatible(category, w.get("format", "")):
            continue
        try:
            if "cost" in w and float(variant_cost) != float(w.get("cost")):
                continue
        except (TypeError, ValueError):
            continue
        title_score = max(similarity(t, w["title"]) for t in _title_variants(title))
        if vendor and w.get("artist"):
            artist_score = similarity(vendor, w["artist"])
            score = title_score * 0.6 + artist_score * 0.4
        else:
            score = title_score
        if score > best_score:
            best_score = score
            best_upc   = w["upc"]
    return best_score, best_upc


# ─────────────────────────────────────────────
# Duplicate detection
# ─────────────────────────────────────────────

def detect_shopify_duplicates() -> int:
    from db.database import db_conn
    with db_conn() as conn:
        products = db._rows(conn.execute(
            """SELECT sp.product_id, sp.title, sp.vendor, sp.category_name,
                    COALESCE(wp.artist, sp.vendor, '') AS artist,
                    COALESCE(wp.format, '') AS format,
                    COALESCE(wp.cost, sv.cost) AS cost
            FROM shopify_products sp
            LEFT JOIN product_mappings pm ON pm.product_id=sp.product_id AND pm.status='active'
            LEFT JOIN webami_products wp ON wp.upc=pm.webami_upc
            LEFT JOIN shopify_variants sv ON sv.product_id=sp.product_id
            WHERE sp.title IS NOT NULL
            GROUP BY sp.product_id""").fetchall())

    groups: dict[str, list[dict]] = {}
    for p in products:
        key = normalize(p["title"])
        if key:
            groups.setdefault(key, []).append(p)

    dup_groups = []
    for key, prods in groups.items():
        if len(prods) < 2:
            continue

        # Partition group by category/format compatibility AND artist similarity
        used = [False] * len(prods)
        for i in range(len(prods)):
            if used[i]:
                continue
            cluster = [prods[i]]
            used[i] = True
            for j in range(i + 1, len(prods)):
                if used[j]:
                    continue
                a, b = prods[i], prods[j]
                if (a.get("category_name") or "") != (b.get("category_name") or ""):
                    continue
                if (a.get("format") or "") != (b.get("format") or ""):
                    continue
                if similarity(a.get("artist") or "", b.get("artist") or "") < _ARTIST_MATCH_THRESHOLD:
                    continue
                if not _cost_compatible(a.get("cost"), b.get("cost")):
                    continue
                cluster.append(b)
                used[j] = True
            if len(cluster) >= 2:
                dup_groups.append({"key": key, "product_ids": [p["product_id"] for p in cluster]})

    return db.save_duplicate_groups(dup_groups)