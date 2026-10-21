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


SYMBOLS = "&$+@%#"


def sym_key(ch: str, text: str) -> str:
    return f"~sym:{ch}|{(text or '').strip().lower()}"


def _sym_rule(rules, ch: str, text: str) -> Optional[str]:
    r = (rules or {}).get(sym_key(ch, text))
    return r["value"] if r and r["kind"] == "default" and r["value"] else None


def slug(s: str, rules: Optional[dict] = None) -> str:
    t = fold(s).lower()
    for ch in SYMBOLS:
        if ch in t:
            v = _sym_rule(rules, ch, s)
            rep = "" if v in (None, "drop") else (f" {v.lower()} " if len(v) > 1 else v.lower())
            t = t.replace(ch, rep)
    t = re.sub(r"[^a-z0-9\s]", "", t)
    return re.sub(r"\s+", "-", t.strip())


FORMAT_SLUGS = {"music cds": "cd", "music cassette tapes": "cassette"}


def format_slug(label: str) -> str:
    return FORMAT_SLUGS.get(norm(label), slug(label))


# ── title splitting ──────────────────────────────────────────────────

_BRACKET = re.compile(r"[\(\[][^()\[\]]*[\)\]]")
_DASH = re.compile(r"\s+[-–—]\s*|\s*[-–—]\s+")   # dash with a space on at least one side

def _split_remainder(rem: str) -> list[tuple[str, str]]:
    """Bracket groups and the loose text between/after them, each as its own segment."""
    segs: list[tuple[str, str]] = []
    pos = 0
    for m in _BRACKET.finditer(rem):
        loose = rem[pos:m.start()].strip()
        if loose:
            segs.append((" " + loose, loose))
        segs.append((" " + m.group(0), m.group(0)[1:-1].strip()))
        pos = m.end()
    tail = rem[pos:].strip()
    if tail:
        segs.append((" " + tail, tail))
    return segs


def split_title(title: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (base_title, segments); each segment is (original_text, inner_text).
    The base is the text before the first ' - ' and before the first bracket group that is not at the
    very start (a leading '(…)' is part of the title). Everything after is a segment: every ' - ' part,
    every (...) / [...] group, and loose text around them."""
    text = (title or "").strip()
    parts = _DASH.split(text)
    head, dash_parts = parts[0], parts[1:]
    segments: list[tuple[str, str]] = []
    first = next((m for m in _BRACKET.finditer(head) if m.start() > 0), None)
    if first:
        segments.extend(_split_remainder(head[first.start():]))
        head = head[:first.start()]
    for part in dash_parts:
        if _BRACKET.search(part):
            sub = _split_remainder(part)
            segments.append((" - " + sub[0][0].strip(), sub[0][1]))
            segments.extend(sub[1:])
        else:
            segments.append((" - " + part, part))
    return head.strip(), segments


# ── rules ────────────────────────────────────────────────────────────

def load_rules(conn) -> dict[str, dict]:
    return {r["term"]: {"kind": r["kind"], "value": r["value"] or ""}
            for r in conn.execute("SELECT term, kind, value FROM term_rules")}


_WEIGHT_UNITS = {"g", "gm", "gram", "grams"}


def _builtin(words: list[str], i: int) -> Optional[tuple[str, str, int]]:
    """Patterns that are always attributes: weight (180g, 180-g, 180 gram, 140gm…) and LP count
    (2LP, 4 LPs, LP4, 4xLP…). Returns (kind, value, words consumed)."""
    w = words[i]
    nxt = words[i + 1] if i + 1 < len(words) else ""
    m = re.fullmatch(r"(\d{2,3})(?:g|gm|gram|grams)", w)
    if m:
        return "attribute", f"{int(m.group(1))}g", 1
    if re.fullmatch(r"\d{2,3}", w) and nxt in _WEIGHT_UNITS:
        return "attribute", f"{int(w)}g", 2
    m = re.fullmatch(r"(\d{1,2})x?lps?", w) or re.fullmatch(r"lps?(\d{1,2})", w)
    if m:
        return "attribute", f"{int(m.group(1))}Lp's", 1
    if re.fullmatch(r"\d{1,2}x?", w) and nxt in ("lp", "lps"):
        return "attribute", f"{int(w.rstrip('x'))}Lp's", 2
    return None


def parse_phrase(inner: str, rules: dict) -> tuple[list[tuple[str, str]], list[str]]:
    """Greedy longest-phrase match. Returns (matches[(kind,value)], unknown phrases)."""
    words = norm(inner).split()
    out: list[tuple[str, str]] = []
    unknown: list[str] = []
    run: list[str] = []
    i = 0
    while i < len(words):
        b = _builtin(words, i)
        if b:
            if run:
                unknown.append(" ".join(run))
                run = []
            out.append((b[0], b[1]))
            i += b[2]
            continue
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


MEDIA_LABELS = {"vinyl records", "vinyl", "records", "music cds", "cds", "cd", "music cassette tapes", "cassette tapes", "cassettes", "cassette"}


def is_media(p: dict) -> bool:
    cat = (p.get("category_name") or "").split(">")[-1]
    return norm(cat or p.get("product_type") or "") in MEDIA_LABELS


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
        r = rules.get(k)
        if not (r and r["kind"] == "default" and r["value"] in ("ok", "mismatch")):
            unknown.append(k)
        elif r["value"] == "mismatch":      # user said they disagree: leave unclassified until fixed in Shopify
            return None, label, [f"category “{label}” and product type “{p.get('product_type')}” disagree — fix in Shopify"], []
    return format_slug(label), label, [], unknown


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
    if editions:
        edition = ", ".join(editions)
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
    elif ignored_only and not (fmt and (rules.get(f"~no-color:{fmt}") or {}).get("value", "").strip().lower() == "none"):
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

    for txt in (p.get("vendor") or "", base):
        for ch in SYMBOLS:
            if ch in txt and not _sym_rule(rules, ch, txt):
                unknown.append(sym_key(ch, txt))

    unknown = _uniq(unknown)
    ready = not unknown and not reasons and None not in (edition, color, attributes)
    return {
        "base": base, "format": fmt, "format_label": fmt_label, "edition": edition, "color": color,
        "attributes": attributes, "unknown": unknown, "reasons": reasons, "ready": ready,
    }


# ── suggestions (never applied automatically) ────────────────────────

_COLORS = {"black", "white", "red", "blue", "green", "yellow", "orange", "purple", "pink", "clear",
           "gold", "silver", "grey", "gray", "brown", "cream", "teal", "turquoise", "violet",
           "maroon", "burgundy", "magenta", "lavender", "mint", "aqua", "tan", "beige", "ivory", "zoetrope",
           "picture disc", "copper", "emerald", "sapphire", "ruby", "opal", "pearl", "bronze", "platinum", "chrome", "brass"}
_COLOR_MODS = {"crystal","baby", "light", "dark", "neon", "bright", "sky", "hot", "pastel", "opaque",
               "translucent", "transparent", "and", "marble", "marbled", "splatter", "swirl", "smoke", "metallic"}
_IGNORE = {"vinyl", "lp", "colored", "coloured", "color", "colour", "record", "records", "lps"}
_EDITIONS = {"deluxe", "anniversary", "remastered", "reissue", "expanded", "special", "collectors",
             "remaster", "edition", "version", "indie", "iex", "indie exclusive", "limited", "ltd", "exclusive", "stereo", "mono"}
_ATTRS = {"import", "poster", "signed", "autographed", "picture", "disc", "gatefold",
          "2lp", "3lp", "numbered", "booklet", "bonus", "obi", "180g", "180gm", "180 g", "180 gm", "180 gram",
          "180-gram", "140g", "140gm", "140 g", "140 gm", "gatefold lp jacket", "lithograph"}
_ALIASES = {"iex": "Indie Exclusive", "ie": "Indie Exclusive"}
_ORDINAL = re.compile(r"\d+(st|nd|rd|th)")
_CLASSES = (("color", _COLORS), ("edition", _EDITIONS), ("attribute", _ATTRS))


def smart_title(text: str) -> str:
    """Title-case words; ordinals stay lowercase (20th), number+letters uppercase (2LP), 'and' lowercase."""
    out = []
    for w in text.split():
        if _ORDINAL.fullmatch(w.lower()):
            out.append(w.lower())
        elif re.match(r"\d", w):
            out.append(w.upper())
        elif w.lower() == "and":
            out.append("and")
        else:
            out.append(w.capitalize())
    return " ".join(out)


def _color_words(words: list[str]) -> Optional[list[str]]:
    out, found, i = [], False, 0
    while i < len(words):
        two = " ".join(words[i:i + 2])
        if len(words[i:i + 2]) == 2 and two in _COLORS:
            out.append(two)
            found = True
            i += 2
            continue
        w = words[i]
        if w in _COLORS:
            found = True
        elif w not in _COLOR_MODS:
            return None
        out.append(w)
        i += 1
    return out if found else None


def _suggest_chunk(words: list[str]) -> Optional[dict]:
    """A run of unexplained words → one suggested rule, only if all words belong to ONE class."""
    chunk = " ".join(words)
    cw = _color_words(words)
    if cw is not None:
        hue = [w in _COLORS for w in cw]
        if sum(hue) > 1:
            n = sum(hue)
            if not all(hue[:n]):
                return None
            label = smart_title(" & ".join(cw[:n]) + (" " + " ".join(cw[n:]) if cw[n:] else ""))
        else:
            label = smart_title(" ".join(cw))
        return {"term": chunk, "kind": "color",
                "value": label if label.lower().endswith("picture disc") else label + " Vinyl"}
    if all(w in _EDITIONS or _ORDINAL.fullmatch(w) for w in words) and any(w in _EDITIONS for w in words):
        return {"term": chunk, "kind": "edition", "value": _ALIASES.get(chunk, smart_title(chunk))}
    if all(w in _ATTRS for w in words) or chunk in _ATTRS:
        return {"term": chunk, "kind": "attribute", "value": _ALIASES.get(chunk, smart_title(chunk))}
    return None


def suggest(term: str) -> Optional[list[dict]]:
    """Suggested WORD rules for an unknown segment (the user must click to accept)."""
    if term.startswith("~no-color:"):
        return [{"term": term, "kind": "default", "value": "Black" if term.endswith("vinyl") else "None"}]
    if term == NO_ATTRS:
        return [{"term": term, "kind": "default", "value": "None"}]
    if term == NO_EDITION:
        return [{"term": term, "kind": "default", "value": "Standard"}]
    if term.startswith(("~ptype:", "~sym:")):
        return None     # never suggested: the user must answer yes or no
    words = term.split()
    rules: list[dict] = []
    run: list[str] = []

    def flush() -> bool:
        nonlocal run
        if run:
            r = _suggest_chunk(run)
            if not r:
                return False
            rules.append(r)
            run = []
        return True

    i = 0
    while i < len(words):
        b = _builtin(words, i)
        if b:                                   # weight / LP count are built in, no rule needed
            if not flush():
                return None
            i += b[2]
            continue
        hit = None
        for n in (4, 3, 2):
            ph = " ".join(words[i:i + n])
            if len(words[i:i + n]) == n:
                kind = next((k for k, st in _CLASSES if ph in st), None)
                if kind and kind != "color":    # multi-word colors are handled with their modifiers
                    hit = (kind, ph, n)
                    break
        if hit:
            if not flush():
                return None
            rules.append({"term": hit[1], "kind": hit[0], "value": _ALIASES.get(hit[1], smart_title(hit[1]))})
            i += hit[2]
            continue
        if words[i] in _IGNORE:
            if not flush():
                return None
            rules.append({"term": words[i], "kind": "ignore", "value": ""})
        else:
            run.append(words[i])
        i += 1
    if not flush():
        return None
    return rules or None


def term_label(term: str) -> str:
    if term.startswith("~no-color:"):
        return f"Color to use when none is stated ({term[10:]})"
    if term.startswith("~sym:"):
        ch, _, txt = term[5:].partition("|")
        return f"“{txt}” contains “{ch}” — what should it be in the URL handle?"
    if term.startswith("~ptype:"):
        cat, _, pt = term[7:].partition("|")
        return f"Is product type “{pt}” the same as category “{cat}”? (confirm to proceed)"
    if term == NO_ATTRS:
        return "Attributes value to use when none are stated"
    if term == NO_EDITION:
        return "Edition value to use when none is stated"
    return term


def allowed_kinds(term: str) -> list[str]:
    if term.startswith(("~no-color:", "~ptype:", "~sym:")) or term in (NO_ATTRS, NO_EDITION):
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
        for old, new in (("music-cds", "cd"), ("music-cassette-tapes", "cassette")):   # renamed format slugs
            conn.execute("UPDATE OR IGNORE term_rules SET term=? WHERE term=?", (f"~no-color:{new}", f"~no-color:{old}"))
            for r in conn.execute("SELECT id, handle FROM plan_products WHERE new_product_id IS NULL AND handle LIKE ?",
                                  (f"%-{old}",)).fetchall():
                nh = r["handle"][:-len(old)] + new
                if not conn.execute("SELECT 1 FROM plan_products WHERE handle=?", (nh,)).fetchone():
                    conn.execute("UPDATE plan_products SET handle=? WHERE id=?", (nh, r["id"]))
        conn.execute("UPDATE OR IGNORE term_rules SET term='~sym:$|'||substr(term,9) WHERE term LIKE '~dollar:%'")
        rules = load_rules(conn)
        for r in conn.execute("SELECT id, handle, vendor, title, format FROM plan_products WHERE new_product_id IS NULL").fetchall():
            nh = f"{slug(r['vendor'] or 'unknown', rules)}-{slug(r['title'], rules)}" + (f"-{format_slug(r['format'])}" if r["format"] else "")
            if nh != r["handle"] and not conn.execute("SELECT 1 FROM plan_products WHERE handle=?", (nh,)).fetchone():
                conn.execute("UPDATE plan_products SET handle=? WHERE id=?", (nh, r["id"]))   # re-slug existing groups
        rules = load_rules(conn)
        ign_p = {r[0] for r in conn.execute("SELECT product_id FROM plan_ignored_products")}
        ign_c = {r[0] for r in conn.execute("SELECT category_id FROM plan_ignored_categories")}
        products = conn.execute(
            """SELECT product_id, title, vendor, category_id, category_name, product_type, tags
               FROM shopify_products WHERE status != 'ARCHIVED'""").fetchall()
        variants = defaultdict(list)
        for v in conn.execute("SELECT variant_id, product_id FROM shopify_variants"):
            variants[v["product_id"]].append(v["variant_id"])
        existing = {r["source_variant_id"]: r for r in conn.execute(
            "SELECT id, plan_product_id, source_variant_id, manual, status, new_variant_id, edition, color, attributes FROM plan_variants")}

        live: set[str] = set()
        group_cache: dict[str, int] = {}
        counts = {"products": 0, "ready": 0, "needs_review": 0, "skipped_frozen": 0, "excluded_used": 0, "ignored": 0}

        for p in products:
            vids = variants.get(p["product_id"], [])
            if not vids:
                continue
            if p["product_id"] in ign_p or (p["category_id"] and p["category_id"] in ign_c):
                counts["ignored"] += 1
                continue
            if is_excluded(p["title"], p["tags"]) or not is_media(dict(p)):
                counts["excluded_used"] += 1
                continue
            c = classify(dict(p), rules, n_variants=len(vids))
            handle = f"{slug(p['vendor'] or 'unknown', rules)}-{slug(c['base'], rules)}" + (f"-{c['format']}" if c["format"] else "")
            counts["products"] += 1
            gcat = p["category_id"] if c["format"] else None     # unclassified products never join a category
            for vid in vids:
                live.add(vid)
                ex = existing.get(vid)
                if ex and (ex["manual"] or ex["new_variant_id"]):
                    counts["skipped_frozen"] += 1
                    continue
                gkey = f"{handle}|{gcat}"
                gid = group_cache.get(gkey)
                if gid is None:
                    h = handle
                    row = conn.execute("SELECT id, category_id FROM plan_products WHERE handle=?", (h,)).fetchone()
                    if row and row["category_id"] != gcat:   # same name, different category: never merge
                        h = f"{handle}-{slug((gcat or 'none').split('/')[-1])}"
                        row = conn.execute("SELECT id, category_id FROM plan_products WHERE handle=?", (h,)).fetchone()
                    if row:
                        gid = row["id"]
                    else:
                        gid = conn.execute(
                            """INSERT INTO plan_products(handle,title,vendor,product_type,category_id,category_name,format)
                               VALUES (?,?,?,?,?,?,?)""",
                            (h, c["base"], p["vendor"], p["product_type"], gcat,
                             p["category_name"], c["format_label"] or None),
                        ).lastrowid
                    group_cache[gkey] = gid
                status = "ready" if c["ready"] else "needs_review"
                counts["ready" if c["ready"] else "needs_review"] += 1
                args = (gid, p["product_id"], vid, c["edition"] or "", c["color"], c["attributes"],
                        1.0 if c["ready"] else 0.0, status,
                        json.dumps(c["unknown"]) if c["unknown"] else None,
                        "; ".join(c["reasons"]) or None)
                if ex and ex["status"] == "approved":
                    if (ex["plan_product_id"], ex["edition"], ex["color"], ex["attributes"]) == (gid, args[3], args[4], args[5]) and c["ready"]:
                        continue
                    conn.execute("UPDATE plan_products SET status='draft' WHERE id IN (?,?) AND new_product_id IS NULL",
                                 (ex["plan_product_id"], gid))
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


def reset_group(group_id: int) -> None:
    with db.connect() as conn:
        conn.execute("UPDATE plan_variants SET manual=0, status='needs_review' WHERE plan_product_id=? AND new_variant_id IS NULL", (group_id,))
        conn.execute("UPDATE plan_products SET status='draft' WHERE id=? AND new_product_id IS NULL", (group_id,))
    build_plan()


def recheck_conflicts(conn) -> None:
    """Two variants of one group may not share Edition + Color + Attributes."""
    conn.execute("""UPDATE plan_variants SET status='needs_review', duplicate_of=NULL
                    WHERE status='duplicate' AND (duplicate_of IS NULL OR duplicate_of NOT IN (SELECT id FROM plan_variants))""")
    conn.execute("""UPDATE plan_variants SET status='ready', reason=NULL
                    WHERE status='needs_review' AND reason='duplicate variant combination'
                      AND unknown_terms IS NULL""")
    dups = conn.execute(
        """SELECT plan_product_id g, lower(edition) e, lower(color) c, lower(attributes) a
           FROM plan_variants WHERE edition != '' AND color IS NOT NULL AND attributes IS NOT NULL
             AND status != 'duplicate'
           GROUP BY 1,2,3,4 HAVING COUNT(*) > 1""").fetchall()
    for d in dups:
        conn.execute(
            """UPDATE plan_variants SET status='needs_review', reason='duplicate variant combination'
               WHERE plan_product_id=? AND lower(edition)=? AND lower(color)=? AND lower(attributes)=?
                 AND status NOT IN ('approved','applied','duplicate')""",
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
                """SELECT v.id, v.edition, v.color, v.attributes, v.status, v.reason, v.manual, v.duplicate_of,
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
            conn.execute("UPDATE plan_variants SET status='approved' WHERE plan_product_id=? AND status != 'duplicate'", (group_id,))
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
        if conn.execute("SELECT 1 FROM plan_variants WHERE duplicate_of=?", (variant_id,)).fetchone():
            raise ValueError("this variant has duplicates marked — undo those first")
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
            handle = f"{slug(src['vendor'] or 'unknown', load_rules(conn))}-{slug(title, load_rules(conn))}" + (
                f"-{format_slug(src['format'])}" if src["format"] else "")
            if conn.execute("SELECT 1 FROM plan_products WHERE handle=?", (handle,)).fetchone():
                raise ValueError(f"group {handle} already exists — move into it instead")
            gid = conn.execute(
                """INSERT INTO plan_products(handle,title,vendor,product_type,category_id,category_name,format)
                   VALUES (?,?,?,?,?,?,?)""",
                (handle, title, src["vendor"], src["product_type"], src["category_id"],
                 src["category_name"], src["format"])).lastrowid
        conn.execute("UPDATE plan_variants SET plan_product_id=?, manual=1, duplicate_of=NULL, "
                     "status=CASE WHEN status IN ('approved','duplicate') THEN 'ready' ELSE status END, "
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


# ── ignore (no variants needed, e.g. gift cards) ─────────────────────

def _purge_ignored(conn) -> None:
    conn.execute("""DELETE FROM plan_variants WHERE new_variant_id IS NULL AND (
        source_product_id IN (SELECT product_id FROM plan_ignored_products)
        OR plan_product_id IN (SELECT id FROM plan_products WHERE category_id IN
                               (SELECT category_id FROM plan_ignored_categories)))""")
    conn.execute("""DELETE FROM plan_products WHERE new_product_id IS NULL
                    AND id NOT IN (SELECT DISTINCT plan_product_id FROM plan_variants)""")
    recheck_conflicts(conn)


def ignore_variants(variant_ids: list[int], scope: str = "product") -> None:
    if not variant_ids:
        raise ValueError("nothing selected")
    marks = ",".join("?" * len(variant_ids))
    with db.connect() as conn:
        rows = conn.execute(
            f"""SELECT v.source_product_id pid, v.new_variant_id, g.category_id, g.category_name, g.new_product_id
                FROM plan_variants v JOIN plan_products g ON g.id=v.plan_product_id WHERE v.id IN ({marks})""",
            variant_ids).fetchall()
        if not rows:
            raise LookupError("variant not found")
        if any(r["new_variant_id"] or r["new_product_id"] for r in rows):
            raise PermissionError("already created in Shopify")
        if scope == "category":
            for r in rows:
                if not r["category_id"]:
                    raise ValueError("no category to ignore")
                conn.execute("INSERT OR IGNORE INTO plan_ignored_categories(category_id, category_name) VALUES (?,?)",
                             (r["category_id"], r["category_name"]))
        else:
            for r in rows:
                conn.execute("INSERT OR IGNORE INTO plan_ignored_products(product_id) VALUES (?)", (r["pid"],))
        _purge_ignored(conn)


def list_ignored() -> dict:
    with db.connect() as conn:
        prods = conn.execute(
            """SELECT i.product_id, sp.title, sp.vendor FROM plan_ignored_products i
               LEFT JOIN shopify_products sp ON sp.product_id=i.product_id ORDER BY sp.title""").fetchall()
        cats = conn.execute("SELECT category_id, category_name FROM plan_ignored_categories ORDER BY category_name").fetchall()
    return {"products": [dict(r) for r in prods], "categories": [dict(r) for r in cats]}


def unignore(product_id: str = "", category_id: str = "") -> dict:
    with db.connect() as conn:
        if product_id:
            conn.execute("DELETE FROM plan_ignored_products WHERE product_id=?", (product_id,))
        if category_id:
            conn.execute("DELETE FROM plan_ignored_categories WHERE category_id=?", (category_id,))
    return build_plan()


# ── mark true duplicate products ─────────────────────────────────────

def keep_duplicates(keeper_id: int) -> int:
    """Keep this variant; every other variant in the group with the same Edition/Color/Attributes
    is a duplicate listing of the same item (merged into the keeper: stock is summed on create)."""
    with db.connect() as conn:
        v = conn.execute("SELECT * FROM plan_variants WHERE id=?", (keeper_id,)).fetchone()
        if not v:
            raise LookupError("variant not found")
        if conn.execute("SELECT new_product_id FROM plan_products WHERE id=?", (v["plan_product_id"],)).fetchone()[0]:
            raise PermissionError("already created in Shopify")
        if v["status"] == "duplicate":
            raise ValueError("this variant is itself marked as a duplicate")
        others = conn.execute(
            """SELECT id FROM plan_variants WHERE plan_product_id=? AND id != ? AND status != 'duplicate'
               AND lower(edition)=lower(?) AND lower(color)=lower(?) AND lower(attributes)=lower(?)
               AND new_variant_id IS NULL""",
            (v["plan_product_id"], keeper_id, v["edition"], v["color"], v["attributes"])).fetchall()
        if not others:
            raise ValueError("no other variant with the same Edition / Color / Attributes")
        for o in others:
            conn.execute("""UPDATE plan_variants SET status='duplicate', duplicate_of=?, manual=1, reason=NULL,
                            unknown_terms=NULL, updated_at=datetime('now') WHERE id=?""", (keeper_id, o["id"]))
        conn.execute("UPDATE plan_products SET status='draft' WHERE id=? AND status='approved'", (v["plan_product_id"],))
        conn.execute("UPDATE plan_variants SET status='ready' WHERE plan_product_id=? AND status='approved'", (v["plan_product_id"],))
        recheck_conflicts(conn)
        return len(others)


def unmark_duplicate(variant_id: int) -> None:
    with db.connect() as conn:
        v = conn.execute("SELECT * FROM plan_variants WHERE id=?", (variant_id,)).fetchone()
        if not v or v["status"] != "duplicate":
            raise LookupError("not a marked duplicate")
        if v["new_variant_id"]:
            raise PermissionError("already created in Shopify")
        conn.execute("UPDATE plan_variants SET status='ready', duplicate_of=NULL, reason=NULL WHERE id=?", (variant_id,))
        conn.execute("UPDATE plan_products SET status='draft' WHERE id=? AND status='approved'", (v["plan_product_id"],))
        conn.execute("UPDATE plan_variants SET status='ready' WHERE plan_product_id=? AND status='approved'", (v["plan_product_id"],))
        recheck_conflicts(conn)
