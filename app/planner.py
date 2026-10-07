"""Catalog planner: turns existing Shopify products into proposed
product/variant structure (Edition | Color | Attributes).

Principle: classify automatically ONLY when every word of a title is explained
by a rule the user has taught the app. Anything unexplained is reported as an
unknown term; the user answers once and the rule applies from then on.
Suggestions are offered but never applied without the user's confirmation.
"""

import json
import re
import unicodedata
from collections import defaultdict
from typing import Optional

from app import db

MAX_PHRASE = 6
WORD_KINDS = {"edition", "color", "attribute", "ignore"}
ALL_KINDS = WORD_KINDS | {"title", "segment", "default"}
NO_ATTRS = "~no-attributes"
NO_EDITION = "~no-edition"
_USED_TITLE = re.compile(r"\s-\s*U\s*$", re.I)
FROZEN = ("approved", "applied")

# ── text helpers ─────────────────────────────────────────────────────

def fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()


def norm(s: str) -> str:
    s = fold(s).lower().replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def slug(s: str) -> str:
    return norm(s).replace(" ", "-")


# ── title splitting ──────────────────────────────────────────────────

_TRAIL = re.compile(r"\s*([\(\[])([^()\[\]]*)[\)\]]\s*$")
_DASH = re.compile(r"\s+[-–—]\s+")


def split_title(title: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (base_title, segments). Each segment is (original_text, inner_text).
    Segments come from every ' - ' part after the first, plus trailing (...) / [...] groups."""
    text = (title or "").strip()
    brackets: list[tuple[str, str]] = []
    while True:
        m = _TRAIL.search(text)
        if not m:
            break
        brackets.insert(0, (m.group(0).strip(), m.group(2).strip()))
        text = text[:m.start()].rstrip()
    segments: list[tuple[str, str]] = []
    parts = _DASH.split(text)
    if len(parts) > 1:
        text = parts[0].rstrip()
        segments.extend((" - " + part, part) for part in parts[1:])
    segments.extend(brackets)
    return text, segments


# ── rules ────────────────────────────────────────────────────────────

def load_rules(conn) -> dict[str, dict]:
    return {r["term"]: {"kind": r["kind"], "value": r["value"] or ""}
            for r in conn.execute("SELECT term, kind, value FROM term_rules")}


def parse_phrase(inner: str, rules: dict) -> tuple[list[tuple[str, str]], list[str]]:
    """Greedy longest-phrase match. Returns (matches[(kind,value)], unknown phrases)."""
    words = norm(inner).split()
    out: list[tuple[str, str]] = []
    unknown: list[str] = []
    run: list[str] = []
    i = 0
    while i < len(words):
        for n in range(min(MAX_PHRASE, len(words) - i), 0, -1):
            r = rules.get(" ".join(words[i:i + n]))
            if r and r["kind"] in WORD_KINDS:
                if run:
                    unknown.append(" ".join(run))
                    run = []
                out.append((r["kind"], r["value"]))
                i += n
                break
        else:
            run.append(words[i])
            i += 1
    if run:
        unknown.append(" ".join(run))
    return out, unknown


def _uniq(items: list[str]) -> list[str]:
    seen, res = set(), []
    for x in items:
        if x.lower() not in seen:
            seen.add(x.lower())
            res.append(x)
    return res


def is_excluded(title: str, tags_json: str) -> bool:
    """Used items ("... - U" titles or a 'Used' tag) have no explicit variants."""
    if _USED_TITLE.search(title or ""):
        return True
    try:
        tags = json.loads(tags_json or "[]")
    except ValueError:
        tags = []
    return any(str(t).strip().lower() == "used" for t in tags)


def format_of(p: dict, rules: dict) -> tuple[Optional[str], str, list[str], list[str]]:
    """Format comes from the Shopify category (last path segment). Product type, if it differs
    from that, must be confirmed once per (category, type) pair. Returns (slug, label, reasons, unknown)."""
    cat = (p.get("category_name") or "").strip()
    if not cat:
        pt = (p.get("product_type") or "").strip()
        return None, "", ["no category" + (f" (product type: {pt})" if pt else "")], []
    label = cat.split(">")[-1].strip()
    unknown = []
    pt = norm(p.get("product_type") or "")
    if pt and pt != norm(label):
        k = f"~ptype:{norm(cat)}|{pt}"
        if not (rules.get(k) or {}).get("kind") == "default":
            unknown.append(k)
    return slug(label), label, [], unknown


def _segment_rule(r: dict) -> dict:
    try:
        return json.loads(r["value"] or "{}")
    except ValueError:
        return {}


def classify(p: dict, rules: dict, n_variants: int = 1) -> dict:
    """p: title, vendor, category_name, product_type. Anything not fully explained by a rule
    the user taught is returned in `unknown` / `reasons` and never guessed."""
    base, segments = split_title(p.get("title") or "")
    editions: list[str] = []
    colors: list[str] = []
    attrs: list[str] = []
    unknown: list[str] = []
    reasons: list[str] = []
    ignored_only = 0

    for original, inner in segments:
        key = norm(inner)
        if not key:
            continue
        r = rules.get(key)
        if r and r["kind"] == "title":      # user said this text is part of the title
            base += original if original.startswith(" ") else " " + original
            continue
        if r and r["kind"] == "ignore":
            ignored_only += 1
            continue
        if r and r["kind"] == "segment":
            v = _segment_rule(r)
            if v.get("edition"):
                editions.append(v["edition"])
            if v.get("color"):
                colors.append(v["color"])
            attrs.extend(a.strip() for a in (v.get("attributes") or "").split(",") if a.strip())
            continue
        matches, unk = parse_phrase(inner, rules)
        kinds = [k for k, _ in matches]
        if unk or kinds.count("color") > 1 or kinds.count("edition") > 1:
            unknown.append(key)             # whole segment must be explained, or the user decides
            continue
        if matches and all(k == "ignore" for k in kinds):
            ignored_only += 1
        for kind, value in matches:
            if kind == "edition" and value:
                editions.append(value)
            elif kind == "color" and value:
                colors.append(value)
            elif kind == "attribute" and value:
                attrs.append(value)

    base = base.strip()
    if not base:
        base = (p.get("title") or "").strip()
        reasons.append("empty base title")
    if not (p.get("vendor") or "").strip():
        reasons.append("no vendor (artist)")

    fmt, fmt_label, fmt_reasons, fmt_unknown = format_of(p, rules)
    reasons += fmt_reasons
    unknown += fmt_unknown

    editions = _uniq(editions)
    if len(editions) > 1:
        edition = None
        reasons.append("multiple editions: " + ", ".join(editions))
    elif editions:
        edition = editions[0]
    else:
        r = rules.get(NO_EDITION)
        if r and r["kind"] == "default" and r["value"]:
            edition = r["value"]
        else:
            edition = None
            unknown.append(NO_EDITION)

    colors = _uniq(colors)
    if len(colors) > 1:
        color = None
        reasons.append("multiple colors: " + ", ".join(colors))
    elif colors:
        color = colors[0]
    elif ignored_only:
        color = None
        reasons.append("color not stated (title has only generic descriptors)")
    elif fmt:
        r = rules.get(f"~no-color:{fmt}")
        if r and r["kind"] == "default" and r["value"]:
            color = r["value"]
        else:
            color = None
            unknown.append(f"~no-color:{fmt}")
    else:
        color = None

    attrs = sorted(_uniq(attrs), key=str.lower)
    if attrs:
        attributes = ", ".join(attrs)
    else:
        r = rules.get(NO_ATTRS)
        if r and r["kind"] == "default" and r["value"]:
            attributes = r["value"]
        else:
            attributes = None
            unknown.append(NO_ATTRS)

    if n_variants > 1:
        reasons.append(f"source product has {n_variants} variants")

    unknown = _uniq(unknown)
    ready = not unknown and not reasons and None not in (edition, color, attributes)
    return {
        "base": base, "format": fmt, "format_label": fmt_label, "edition": edition, "color": color,
        "attributes": attributes, "unknown": unknown, "reasons": reasons, "ready": ready,
    }


# ── suggestions (never applied automatically) ────────────────────────

_COLORS = {"black", "white", "red", "blue", "green", "yellow", "orange", "purple", "pink", "clear",
           "gold", "silver", "grey", "gray", "brown", "cream", "teal", "turquoise", "violet",
           "maroon", "burgundy", "magenta", "lavender", "mint", "aqua", "tan", "beige", "ivory"}
_COLOR_MODS = {"baby", "light", "dark", "neon", "bright", "sky", "hot", "pastel", "opaque",
               "translucent", "transparent", "and", "marble", "marbled", "splatter"}
_IGNORE = {"vinyl", "lp", "colored", "coloured", "color", "colour", "record", "records", "lps"}
_EDITIONS = {"deluxe", "anniversary", "remastered", "reissue", "expanded", "special", "collectors",
             "remaster", "edition", "version"}
_ATTRS = {"import", "poster", "signed", "autographed", "picture", "disc", "gatefold", "exclusive",
          "indie", "iex", "2lp", "3lp", "limited", "numbered", "booklet", "bonus", "obi"}


def smart_title(text: str) -> str:
    """Title-case words; ordinals stay lowercase (20th), number+letters uppercase (2LP)."""
    out = []
    for w in text.split():
        if re.fullmatch(r"\d+(st|nd|rd|th)", w, re.I):
            out.append(w.lower())
        elif re.match(r"\d", w):
            out.append(w.upper())
        else:
            out.append(w.capitalize())
    return " ".join(out)


def _suggest_chunk(words: list[str]) -> Optional[dict]:
    chunk = " ".join(words)
    if any(w in _COLORS for w in words) and all(w in _COLORS | _COLOR_MODS for w in words):
        return {"term": chunk, "kind": "color",
                "value": smart_title(" ".join(w for w in words if w != "and")) + " Vinyl"}
    if any(w in _EDITIONS for w in words):
        return {"term": chunk, "kind": "edition", "value": smart_title(chunk)}
    if any(w in _ATTRS for w in words):
        return {"term": chunk, "kind": "attribute", "value": smart_title(chunk)}
    return None


def suggest(term: str) -> Optional[list[dict]]:
    """Suggested WORD rules for an unknown segment (the user must click to accept)."""
    if term.startswith("~no-color:"):
        return [{"term": term, "kind": "default", "value": "Black" if term.endswith("vinyl") else "None"}]
    if term == NO_ATTRS:
        return [{"term": term, "kind": "default", "value": "None"}]
    if term == NO_EDITION:
        return [{"term": term, "kind": "default", "value": "Standard"}]
    if term.startswith("~ptype:"):
        return [{"term": term, "kind": "default", "value": "ok"}]
    rules: list[dict] = []
    chunk: list[str] = []
    for w in term.split() + [None]:
        if w is None or w in _IGNORE:
            if chunk:
                r = _suggest_chunk(chunk)
                if not r:
                    return None
                rules.append(r)
                chunk = []
            if w is not None:
                rules.append({"term": w, "kind": "ignore", "value": ""})
        else:
            chunk.append(w)
    return rules or None


def term_label(term: str) -> str:
    if term.startswith("~no-color:"):
        return f"Color to use when none is stated ({term[10:]})"
    if term.startswith("~ptype:"):
        cat, _, pt = term[7:].partition("|")
        return f"Is product type “{pt}” the same as category “{cat}”? (confirm to proceed)"
    if term == NO_ATTRS:
        return "Attributes value to use when none are stated"
    if term == NO_EDITION:
        return "Edition value to use when none is stated"
    return term


def allowed_kinds(term: str) -> list[str]:
    if term.startswith(("~no-color:", "~ptype:")) or term in (NO_ATTRS, NO_EDITION):
        return ["default"]
    return ["segment", "title", "ignore"]


def prefill(term: str, rules: dict) -> dict:
    """What the existing word rules already explain about a segment (display only)."""
    if term.startswith("~"):
        return {}
    matches, _ = parse_phrase(term, rules)
    out = {"edition": "", "color": "", "attributes": ""}
    attrs = []
    for kind, value in matches:
        if kind == "edition":
            out["edition"] = value
        elif kind == "color":
            out["color"] = value
        elif kind == "attribute":
            attrs.append(value)
    out["attributes"] = ", ".join(attrs)
    return out


# ── build ────────────────────────────────────────────────────────────

def build_plan() -> dict:
    """(Re)classify every Shopify product into the plan. User-edited and
    approved rows are never touched."""
    with db.connect() as conn:
        rules = load_rules(conn)
        products = conn.execute(
            """SELECT product_id, title, vendor, category_id, category_name, product_type, tags
               FROM shopify_products WHERE status != 'ARCHIVED'""").fetchall()
        variants = defaultdict(list)
        for v in conn.execute("SELECT variant_id, product_id FROM shopify_variants"):
            variants[v["product_id"]].append(v["variant_id"])
        existing = {r["source_variant_id"]: r for r in conn.execute(
            "SELECT id, source_variant_id, manual, status, new_variant_id FROM plan_variants")}

        live: set[str] = set()
        group_cache: dict[str, int] = {}
        counts = {"products": 0, "ready": 0, "needs_review": 0, "skipped_frozen": 0, "excluded_used": 0}

        for p in products:
            vids = variants.get(p["product_id"], [])
            if not vids:
                continue
            if is_excluded(p["title"], p["tags"]):
                counts["excluded_used"] += 1
                continue
            c = classify(dict(p), rules, n_variants=len(vids))
            handle = f"{slug(p['vendor'] or 'unknown')}-{slug(c['base'])}" + (f"-{c['format']}" if c["format"] else "")
            counts["products"] += 1
            for vid in vids:
                live.add(vid)
                ex = existing.get(vid)
                if ex and (ex["manual"] or ex["status"] in FROZEN or ex["new_variant_id"]):
                    counts["skipped_frozen"] += 1
                    continue
                gkey = f"{handle}|{p['category_id']}"
                gid = group_cache.get(gkey)
                if gid is None:
                    h = handle
                    row = conn.execute("SELECT id, category_id FROM plan_products WHERE handle=?", (h,)).fetchone()
                    if row and row["category_id"] != p["category_id"]:   # same name, different category: never merge
                        h = f"{handle}-{slug((p['category_id'] or 'none').split('/')[-1])}"
                        row = conn.execute("SELECT id, category_id FROM plan_products WHERE handle=?", (h,)).fetchone()
                    if row:
                        gid = row["id"]
                    else:
                        gid = conn.execute(
                            """INSERT INTO plan_products(handle,title,vendor,product_type,category_id,category_name,format)
                               VALUES (?,?,?,?,?,?,?)""",
                            (h, c["base"], p["vendor"], p["product_type"], p["category_id"],
                             p["category_name"], c["format_label"] or None),
                        ).lastrowid
                    group_cache[gkey] = gid
                status = "ready" if c["ready"] else "needs_review"
                counts["ready" if c["ready"] else "needs_review"] += 1
                args = (gid, p["product_id"], vid, c["edition"] or "", c["color"], c["attributes"],
                        1.0 if c["ready"] else 0.0, status,
                        json.dumps(c["unknown"]) if c["unknown"] else None,
                        "; ".join(c["reasons"]) or None)
                if ex:
                    conn.execute(
                        """UPDATE plan_variants SET plan_product_id=?, source_product_id=?,
                           source_variant_id=?, edition=?, color=?, attributes=?, confidence=?,
                           status=?, unknown_terms=?, reason=?, updated_at=datetime('now')
                           WHERE id=?""", (*args, ex["id"]))
                else:
                    conn.execute(
                        """INSERT INTO plan_variants(plan_product_id,source_product_id,source_variant_id,
                           edition,color,attributes,confidence,status,unknown_terms,reason)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""", args)

        # drop plan rows whose source no longer exists (unless already applied)
        for vid, ex in existing.items():
            if vid not in live and not ex["new_variant_id"]:
                conn.execute("DELETE FROM plan_variants WHERE id=?", (ex["id"],))
        conn.execute("""DELETE FROM plan_products WHERE new_product_id IS NULL
                        AND id NOT IN (SELECT DISTINCT plan_product_id FROM plan_variants)""")
        recheck_conflicts(conn)
    return counts


def recheck_conflicts(conn) -> None:
    """Two variants of one group may not share Edition + Color + Attributes."""
    conn.execute("""UPDATE plan_variants SET status='ready', reason=NULL
                    WHERE status='needs_review' AND reason='duplicate variant combination'
                      AND unknown_terms IS NULL""")
    dups = conn.execute(
        """SELECT plan_product_id g, lower(edition) e, lower(color) c, lower(attributes) a
           FROM plan_variants WHERE edition != '' AND color IS NOT NULL AND attributes IS NOT NULL
           GROUP BY 1,2,3,4 HAVING COUNT(*) > 1""").fetchall()
    for d in dups:
        conn.execute(
            """UPDATE plan_variants SET status='needs_review', reason='duplicate variant combination'
               WHERE plan_product_id=? AND lower(edition)=? AND lower(color)=? AND lower(attributes)=?
                 AND status NOT IN ('approved','applied')""",
            (d["g"], d["e"], d["c"], d["a"]))


# ── queries used by the API ──────────────────────────────────────────

def unknown_terms() -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT pv.source_product_id pid, pv.unknown_terms ut, sp.title
               FROM plan_variants pv JOIN shopify_products sp ON sp.product_id = pv.source_product_id
               WHERE pv.unknown_terms IS NOT NULL AND pv.status = 'needs_review'""").fetchall()
    seen: dict[str, dict] = {}
    for r in rows:
        for term in json.loads(r["ut"]):
            e = seen.setdefault(term, {"pids": set(), "examples": []})
            if r["pid"] not in e["pids"]:
                e["pids"].add(r["pid"])
                if len(e["examples"]) < 3:
                    e["examples"].append(r["title"])
    with db.connect() as conn:
        rules = load_rules(conn)
    out = [{"term": t, "label": term_label(t), "count": len(e["pids"]), "examples": e["examples"],
            "kinds": allowed_kinds(t), "suggestion": suggest(t), "prefill": prefill(t, rules)}
           for t, e in seen.items()]
    out.sort(key=lambda x: (-x["count"], x["term"]))
    return out


def save_rule(term: str, kind: str, value: str = "") -> None:
    if kind not in ALL_KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    term = term.strip().lower() if term.startswith("~") else norm(term)
    if not term:
        raise ValueError("empty term")
    value = (value or "").strip()
    if kind in ("edition", "color", "attribute", "default") and not value:
        raise ValueError(f"{kind} rules need a value")
    if kind == "segment":
        try:
            v = json.loads(value)
        except ValueError:
            raise ValueError("segment rule needs JSON value")
        v = {k: str(v.get(k) or "").strip() for k in ("edition", "color", "attributes")}
        if not any(v.values()):
            raise ValueError("fill at least one of Edition / Color / Attributes")
        value = json.dumps(v)
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO term_rules(term,kind,value) VALUES (?,?,?)
               ON CONFLICT(term) DO UPDATE SET kind=excluded.kind, value=excluded.value""",
            (term, kind, value))


def delete_rule(term: str) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM term_rules WHERE term=?", (term,))


def list_rules() -> list[dict]:
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT term, kind, value FROM term_rules ORDER BY kind, term")]


def list_groups(flt: str = "all", q: str = "", limit: int = 25, offset: int = 0) -> dict:
    having = {"all": "1=1",
              "review": "g.status='draft' AND SUM(v.status='needs_review') > 0",
              "ready": "g.status='draft' AND SUM(v.status='needs_review') = 0",
              "approved": "g.status IN ('approved','applied')",
              "unclassified": "g.category_id IS NULL"}.get(flt, "1=1")
    like = f"%{q.strip()}%"
    where = "WHERE (:q='' OR g.title LIKE :like OR g.vendor LIKE :like OR g.handle LIKE :like)"
    params = {"q": q.strip(), "like": like, "limit": limit, "offset": offset}
    with db.connect() as conn:
        summary = dict(conn.execute(
            """SELECT COUNT(*) total,
                      SUM(g.status='draft' AND nr=0) ready,
                      SUM(g.status='draft' AND nr>0) review,
                      SUM(g.status IN ('approved','applied')) approved,
                      SUM(g.category_id IS NULL) unclassified
               FROM (SELECT g.id, g.status, g.category_id, (SELECT COUNT(*) FROM plan_variants v
                     WHERE v.plan_product_id=g.id AND v.status='needs_review') nr
                     FROM plan_products g) g""").fetchone())
        groups = conn.execute(
            f"""SELECT g.id, g.handle, g.title, g.vendor, g.status, g.new_product_id, g.format, g.category_name,
                       g.category_id, COUNT(v.id) n, SUM(v.status='needs_review') nr
                FROM plan_products g JOIN plan_variants v ON v.plan_product_id=g.id
                {where} GROUP BY g.id HAVING {having}
                ORDER BY nr DESC, g.title LIMIT :limit OFFSET :offset""", params).fetchall()
        total = conn.execute(
            f"""SELECT COUNT(*) FROM (SELECT g.id FROM plan_products g
                JOIN plan_variants v ON v.plan_product_id=g.id {where}
                GROUP BY g.id HAVING {having})""", params).fetchone()[0]
        result = []
        for g in groups:
            vs = conn.execute(
                """SELECT v.id, v.edition, v.color, v.attributes, v.status, v.reason, v.manual,
                          v.source_product_id, sp.title source_title, sv.price, sv.inventory_quantity qty, sv.barcode
                   FROM plan_variants v
                   LEFT JOIN shopify_products sp ON sp.product_id=v.source_product_id
                   LEFT JOIN shopify_variants sv ON sv.variant_id=v.source_variant_id
                   WHERE v.plan_product_id=? ORDER BY v.edition, v.color, v.attributes""",
                (g["id"],)).fetchall()
            result.append({**dict(g), "variants": [dict(x) for x in vs]})
    return {"summary": summary, "total": total, "groups": result}


def edit_variant(variant_id: int, fields: dict) -> None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM plan_variants WHERE id=?", (variant_id,)).fetchone()
        if not row:
            raise LookupError("variant not found")
        if row["new_variant_id"]:
            raise PermissionError("already created in Shopify")
        vals = {k: (fields.get(k, row[k]) or "").strip() for k in ("edition", "color", "attributes")}
        status = "ready" if all(vals.values()) else "needs_review"
        conn.execute(
            """UPDATE plan_variants SET edition=?, color=?, attributes=?, status=?, manual=1,
               unknown_terms=NULL, reason=?, updated_at=datetime('now') WHERE id=?""",
            (vals["edition"], vals["color"] or None, vals["attributes"] or None, status,
             None if status == "ready" else "missing value", variant_id))
        conn.execute("UPDATE plan_products SET status='draft' WHERE id=? AND status='approved'",
                     (row["plan_product_id"],))
        recheck_conflicts(conn)


def set_group_approved(group_id: int, approve: bool) -> None:
    with db.connect() as conn:
        g = conn.execute("SELECT status, new_product_id FROM plan_products WHERE id=?", (group_id,)).fetchone()
        if not g:
            raise LookupError("group not found")
        if g["new_product_id"]:
            raise PermissionError("already created in Shopify")
        if approve:
            bad = conn.execute(
                "SELECT COUNT(*) FROM plan_variants WHERE plan_product_id=? AND status='needs_review'",
                (group_id,)).fetchone()[0]
            if not conn.execute("SELECT category_id FROM plan_products WHERE id=?", (group_id,)).fetchone()[0]:
                raise ValueError("no category — fix in Shopify, sync, rebuild")
            if bad:
                raise ValueError(f"{bad} variant(s) still need review")
            conn.execute("UPDATE plan_variants SET status='approved' WHERE plan_product_id=?", (group_id,))
            conn.execute("UPDATE plan_products SET status='approved' WHERE id=?", (group_id,))
        else:
            conn.execute("UPDATE plan_variants SET status='ready' WHERE plan_product_id=? AND status='approved'",
                         (group_id,))
            conn.execute("UPDATE plan_products SET status='draft' WHERE id=?", (group_id,))


# ── add / remove variants of a group ─────────────────────────────────

def _drop_if_empty(conn, group_id: int) -> None:
    conn.execute("""DELETE FROM plan_products WHERE id=? AND new_product_id IS NULL
                    AND id NOT IN (SELECT DISTINCT plan_product_id FROM plan_variants)""", (group_id,))


def move_variant(variant_id: int, group_id: Optional[int] = None, new_title: str = "") -> int:
    """Move a plan variant into another group (same category only), or out into a new group of its own."""
    with db.connect() as conn:
        v = conn.execute("SELECT * FROM plan_variants WHERE id=?", (variant_id,)).fetchone()
        if not v:
            raise LookupError("variant not found")
        src = conn.execute("SELECT * FROM plan_products WHERE id=?", (v["plan_product_id"],)).fetchone()
        if v["new_variant_id"] or src["new_product_id"]:
            raise PermissionError("already created in Shopify")
        if group_id:
            dst = conn.execute("SELECT * FROM plan_products WHERE id=?", (group_id,)).fetchone()
            if not dst:
                raise LookupError("target group not found")
            if dst["new_product_id"]:
                raise PermissionError("target already created in Shopify")
            if dst["category_id"] != src["category_id"]:
                raise ValueError("different category — products must share a category to be grouped")
            gid = dst["id"]
        else:
            title = (new_title or "").strip()
            if not title:
                raise ValueError("new product title required")
            handle = f"{slug(src['vendor'] or 'unknown')}-{slug(title)}" + (
                f"-{slug(src['format'])}" if src["format"] else "")
            if conn.execute("SELECT 1 FROM plan_products WHERE handle=?", (handle,)).fetchone():
                raise ValueError(f"group {handle} already exists — move into it instead")
            gid = conn.execute(
                """INSERT INTO plan_products(handle,title,vendor,product_type,category_id,category_name,format)
                   VALUES (?,?,?,?,?,?,?)""",
                (handle, title, src["vendor"], src["product_type"], src["category_id"],
                 src["category_name"], src["format"])).lastrowid
        conn.execute("UPDATE plan_variants SET plan_product_id=?, manual=1, "
                     "status=CASE WHEN status='approved' THEN 'ready' ELSE status END, "
                     "updated_at=datetime('now') WHERE id=?", (gid, variant_id))
        for g in {src["id"], gid}:
            conn.execute("UPDATE plan_products SET status='draft' WHERE id=? AND status='approved'", (g,))
            conn.execute("UPDATE plan_variants SET status='ready' WHERE plan_product_id=? AND status='approved'", (g,))
        _drop_if_empty(conn, src["id"])
        recheck_conflicts(conn)
        return gid


def search_addable(group_id: int, q: str = "", limit: int = 15) -> list[dict]:
    """Plan variants in the same category, from other groups, that could be added to this group."""
    with db.connect() as conn:
        g = conn.execute("SELECT category_id FROM plan_products WHERE id=?", (group_id,)).fetchone()
        if not g:
            raise LookupError("group not found")
        rows = conn.execute(
            """SELECT v.id, sp.title, sp.vendor, p.handle group_handle, v.edition, v.color, v.attributes
               FROM plan_variants v JOIN plan_products p ON p.id=v.plan_product_id
               JOIN shopify_products sp ON sp.product_id=v.source_product_id
               WHERE p.id != ? AND p.category_id IS ? AND v.new_variant_id IS NULL AND p.new_product_id IS NULL
                 AND (sp.title LIKE ? OR sp.vendor LIKE ?) ORDER BY sp.title LIMIT ?""",
            (group_id, g["category_id"], f"%{q.strip()}%", f"%{q.strip()}%", limit)).fetchall()
        return [dict(r) for r in rows]
