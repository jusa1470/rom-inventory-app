#!/usr/bin/env python3
"""
Split Shopify product CSV rows into:
  - products.csv: one base product per artist/title/type group
  - variants.csv: one variant row per source product
  - review.csv: matches needing human verification

Usage:
  python shopify_product_variant_split.py input.csv --out-dir output

Uses only Python's standard library.
"""

import argparse
import csv
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

_COLORS = {
    "black", "white", "red", "blue", "green", "yellow", "orange", "purple",
    "pink", "clear", "gold", "silver", "grey", "gray", "brown", "cream",
    "teal", "turquoise", "violet", "maroon", "burgundy", "magenta",
    "lavender", "mint", "aqua", "tan", "beige", "ivory", "zoetrope",
    "picture disc", "copper", "emerald", "sapphire", "ruby", "opal", "bone",
    "pearl", "bronze", "platinum", "chrome", "brass",
}
_COLOR_MODS = {
    "crystal", "baby", "light", "dark", "neon", "bright", "sky", "hot",
    "pastel", "opaque", "translucent", "transparent", "and", "marble",
    "marbled", "splatter", "swirl", "smoke", "metallic",
}
_EDITIONS = {
    "deluxe", "anniversary", "remastered", "reissue", "expanded", "special",
    "collectors", "remaster", "edition", "version", "indie", "ie", "iex",
    "indie exclusive", "limited", "ltd", "exclusive", "stereo", "mono",
    "rhino", "series", "collection", "redux", "rsd", "rsd bf", "wm", "target",
}
_ATTRS = {
    "import", "poster", "signed", "autographed", "gatefold", "2lp", "3lp",
    "numbered", "booklet", "bonus", "obi", "180g", "180gm", "180 g",
    "180 gm", "180 gram", "180-gram", "140g", "140gm", "140 g", "140 gm",
    "gatefold lp jacket", "lithograph",
}
_ALIASES = {
    "indie": "Indie Exclusive",
    "iex": "Indie Exclusive",
    "ie": "Indie Exclusive",
    "wm": "Walmart Exclusive",
    "target": "Target Exclusive",
}

# Add exact title-character substitutions here only after confirming each rule.
# Example format: {"&": "and"} -- intentionally empty by default.
HANDLE_REPLACEMENTS = {}


def norm_space(value):
    return re.sub(r"\s+", " ", (value or "")).strip()


def slugify(value):
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    for old, new in HANDLE_REPLACEMENTS.items():
        value = value.replace(old, new)
    value = value.lower()
    value = re.sub(r"['’]", "", value)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def word_pattern(term):
    # Treat spaces and common 140/180 g spellings consistently.
    escaped = re.escape(term.strip())
    escaped = escaped.replace(r"\ ", r"[\s-]*")
    return re.compile(r"(?<![A-Za-z0-9])" + escaped + r"(?![A-Za-z0-9])", re.I)


def in_parentheses(text, start, end):
    depth = 0
    inside = False
    for i, char in enumerate(text[:start]):
        if char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
    inside = depth > 0
    return inside


def suffix_context(text, start):
    """True when match is in parentheses or follows a colon/dash separator."""
    if in_parentheses(text, start, start):
        return True
    prefix = text[:start]
    # A delimiter must occur before the keyword; do not treat a hyphen inside
    # an ordinary word as a suffix delimiter.
    return bool(re.search(r"[:–—-]\s*[^:–—-]*$", prefix))


def anniversary_replacements(title):
    # Normalize numeric anniversary forms only; do not infer missing numbers.
    def ordinal(n):
        n = int(n)
        if 10 <= n % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix} Anniversary"

    patterns = [
        re.compile(r"\b(\d+)\s*[- ]?\s*year\s+anniversary\b", re.I),
        re.compile(r"\b(\d+)(?:st|nd|rd|th)?\s*[- ]?\s*anniversary\b", re.I),
    ]
    result = title
    for pattern in patterns:
        result = pattern.sub(lambda m: ordinal(m.group(1)), result)
    return result


def build_terms():
    # Longest terms first prevents shorter terms from splitting known phrases.
    all_terms = []
    for category, terms in (
        ("color", _COLORS),
        ("edition", _EDITIONS),
        ("attribute", _ATTRS),
    ):
        all_terms.extend((term, category) for term in terms)

    # Recognize common modifier + color combinations while preserving their wording.
    modifiers = _COLOR_MODS - {"and"}
    for color in _COLORS:
        for modifier in modifiers:
            all_terms.append((f"{modifier} {color}", "color"))
            all_terms.append((f"{color} {modifier}", "color"))
    for first in _COLORS:
        for second in _COLORS:
            if first != second:
                all_terms.append((f"{first} and {second}", "color"))
    return sorted(set(all_terms), key=lambda item: len(item[0]), reverse=True)


TERMS = build_terms()


def term_key(value):
    return re.sub(r"[\s-]+", " ", value.casefold()).strip()


# One compiled alternation replaces thousands of per-keyword scans per title.
# Longest-first ordering preserves the original preference for specific phrases.
_TERM_LOOKUP = {}
_TERM_ALTERNATIVES = []
for _term, _category in TERMS:
    _key = term_key(_term)
    _TERM_LOOKUP.setdefault(_key, (_term, _category))
    _escaped = re.escape(_term.strip()).replace(r"\ ", r"[\s-]+")
    _TERM_ALTERNATIVES.append(_escaped)
_TERM_REGEX = re.compile(
    r"(?<![A-Za-z0-9])(?:" + "|".join(_TERM_ALTERNATIVES) + r")(?![A-Za-z0-9])",
    re.I,
)
_ANNIVERSARY_PATTERN = re.compile(
    r"\b\d+(?:st|nd|rd|th)?\s*[- ]?\s*(?:year\s+)?anniversary\b", re.I
)
_WEIGHT_PATTERN = re.compile(r"\b(?:140|180)\s*[- ]?\s*(?:g|gm|gram|grams)\b", re.I)
_PAREN_PATTERN = re.compile(r"\(([^()]*)\)")
_SUFFIX_PATTERN = re.compile(r"(?::|\s[-–—]\s)([^:–—]+)$")


def find_matches(title):
    """Scan each title once for known terms, preferring longer phrases."""
    matches = []
    occupied = []

    def add_match(term, category, match):
        start, end = match.span()
        if any(start < old_end and end > old_start for old_start, old_end in occupied):
            return
        if category == "color":
            if not in_parentheses(title, start, end) and not re.search(
                r"[-–—]\s*[^()]*$", title[:start]
            ):
                return
        occupied.append((start, end))
        matches.append({
            "term": term,
            "category": category,
            "start": start,
            "end": end,
            "text": match.group(0),
            "review": category in {"edition", "attribute"}
                      and not suffix_context(title, start),
        })

    for match in _ANNIVERSARY_PATTERN.finditer(title):
        add_match(anniversary_replacements(match.group(0)), "edition", match)

    for match in _WEIGHT_PATTERN.finditer(title):
        add_match(match.group(0), "attribute", match)

    for match in _TERM_REGEX.finditer(title):
        key = term_key(match.group(0))
        found = _TERM_LOOKUP.get(key)
        if found is None:
            continue
        term, category = found
        if key == "anniversary":
            continue
        add_match(term, category, match)

    return sorted(matches, key=lambda m: m["start"])



def unclassified_fragments(title, matches):
    """Return residual parenthetical and colon/dash-suffix text for review."""
    spans = [(m["start"], m["end"]) for m in matches]
    fragments = []
    candidates = []
    candidates.extend((m.start(1), m.end(1), m.group(1), "Unclassified text inside parentheses")
                      for m in _PAREN_PATTERN.finditer(title))
    suffix = _SUFFIX_PATTERN.search(title)
    if suffix:
        candidates.append((suffix.start(1), suffix.end(1), suffix.group(1),
                           "Unclassified text after colon/dash"))
    for start, end, fragment, reason in candidates:
        local_spans = [(max(a, start) - start, min(b, end) - start)
                       for a, b in spans if a < end and b > start]
        residual = fragment
        for a, b in sorted(local_spans, reverse=True):
            residual = residual[:a] + " " + residual[b:]
        residual = re.sub(r"[\s,;:/–—-]+", " ", residual).strip()
        if residual:
            fragments.append((residual, reason))
    return fragments

def remove_spans(text, spans):
    for start, end in sorted(spans, reverse=True):
        text = text[:start] + " " + text[end:]
    # Remove empty parentheses and clean separators left by extracted terms.
    text = re.sub(r"\(\s*\)", " ", text)
    text = re.sub(r"\[\s*\]", " ", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,;:])", r"\1", text)
    text = re.sub(r"([(\[])\s+", r"\1", text)
    text = re.sub(r"\s+([)\]])", r"\1", text)
    text = re.sub(r"(?<!\w)[,;:]\s*(?=$)", "", text)
    text = re.sub(r"\s*[-–—:]\s*(?=$)", "", text)
    return text.strip(" \t-–—:;,")


def canonical(term, category):
    key = term.lower()
    if category == "edition":
        if re.search(r"\b\d+(?:st|nd|rd|th) Anniversary\b", term, re.I):
            return term
        if key in _ALIASES:
            return _ALIASES[key]
        if key == "collectors":
            return "Collectors"
        return term.title()
    if category == "color":
        return term.title()
    return term.upper() if key in {"obi", "2lp", "3lp", "180g", "180gm",
                                   "140g", "140gm"} else term.title()


def extract_anniversary(title):
    matches = re.findall(
        r"\b\d+(?:st|nd|rd|th)?\s*[- ]?\s*(?:year\s+)?anniversary\b",
        title, flags=re.I
    )
    return list(dict.fromkeys(norm_space(m) for m in matches))


def parse_tags(value):
    try:
        parsed = json.loads(value or "[]")
        if isinstance(parsed, list):
            return json.dumps(parsed, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        pass
    return value or "[]"


def clean_title(original_title, matches):
    title = anniversary_replacements(original_title)
    # Re-find after anniversary normalization so offsets remain correct.
    matches = find_matches(title)
    spans = [(m["start"], m["end"]) for m in matches]
    # Remove edition/attribute matches everywhere; color matches only qualify
    # when parenthetical or in a dash suffix (already enforced by find_matches).
    cleaned = remove_spans(title, spans)
    return norm_space(cleaned), matches


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv", help="Shopify source product CSV")
    parser.add_argument("--out-dir", default="shopify_split_output")
    parser.add_argument("--encoding", default="utf-8-sig")
    args = parser.parse_args()

    input_path = Path(args.input_csv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with input_path.open("r", encoding=args.encoding, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        source_headers = reader.fieldnames or []

    required = {"product_id", "title", "vendor", "product_type"}
    missing = sorted(required - set(source_headers))
    if missing:
        raise SystemExit("Missing required columns: " + ", ".join(missing))

    groups = {}
    product_records = {}
    variant_records = []
    review_records = []
    seen_handles = defaultdict(list)

    for row_num, row in enumerate(rows, start=2):
        source_id = norm_space(row.get("product_id"))
        original_title = norm_space(row.get("title"))
        vendor = norm_space(row.get("vendor"))
        product_type = norm_space(row.get("product_type"))

        normalized_title = anniversary_replacements(original_title)
        matches = find_matches(normalized_title)
        editions, colors, attrs = [], [], []

        for m in matches:
            value = canonical(m["term"], m["category"])
            if m["category"] == "edition":
                if value not in editions:
                    editions.append(value)
            elif m["category"] == "color":
                if value not in colors:
                    colors.append(value)
            else:
                if value not in attrs:
                    attrs.append(value)

            if m["review"]:
                review_records.append({
                    "source_row": row_num,
                    "product_id": source_id,
                    "original_title": original_title,
                    "matched_text": m["text"],
                    "category": m["category"],
                    "reason": "Edition/attribute keyword not in parentheses or after :, -, or dash",
                })

        for fragment, reason in unclassified_fragments(normalized_title, matches):
            review_records.append({
                "source_row": row_num,
                "product_id": source_id,
                "original_title": original_title,
                "matched_text": fragment,
                "category": "unclassified",
                "reason": reason,
            })

        base_title = remove_spans(
            normalized_title, [(m["start"], m["end"]) for m in matches]
        )
        base_title = norm_space(re.sub(r"\s+", " ", base_title)).strip(" -–—:;,")

        # Build the base product key from vendor + cleaned title + product type.
        key = (vendor.casefold(), base_title.casefold(), product_type.casefold())
        if key not in groups:
            handle = slugify(f"{vendor}-{base_title}-{product_type}")
            groups[key] = {
                "handle": handle,
                "title": base_title,
                "vendor": vendor,
                "product_type": product_type,
                "status": row.get("status", ""),
                "category_id": row.get("category_id", ""),
                "category_name": row.get("category_name", ""),
                "tags": parse_tags(row.get("tags", "[]")),
                "representative_id": source_id,
                "source_ids": [],
            }
            seen_handles[handle].append(key)
        groups[key]["source_ids"].append(source_id)

        # Extract UPC, images, genres from supplied columns.
        # Every variant must have an edition value.
        edition_value = "; ".join(dict.fromkeys(editions)) or "Standard"
        variant_records.append({
            "original_product_id": source_id,
            "product_handle": groups[key]["handle"],
            "edition": edition_value,
            "color": "; ".join(dict.fromkeys(colors)),
            "attributes": "; ".join(dict.fromkeys(attrs)),
            "upc_metafield": row.get("**upc_metafield", row.get("upc_metafield", "")),
            "image_url": row.get("image_urls", ""),
            "genres": row.get("genres", ""),
        })

        # Keep a row-level review when title changed but no known terms explain it.
        if not base_title:
            review_records.append({
                "source_row": row_num,
                "product_id": source_id,
                "original_title": original_title,
                "matched_text": "",
                "category": "",
                "reason": "Cleaned base title is empty; manual review required",
            })

    product_rows = []
    for group in groups.values():
        product_rows.append({
            "original_product_id": group["representative_id"],
            "handle": group["handle"],
            "title": group["title"],
            "vendor": group["vendor"],
            "status": group["status"],
            "product_type": group["product_type"],
            "category_id": group["category_id"],
            "category_name": group["category_name"],
            "tags": group["tags"],
            "source_product_ids": ";".join(group["source_ids"]),
        })

    # Handle collisions are not silently altered.
    for handle, keys in seen_handles.items():
        if len(keys) > 1:
            for key in keys:
                group = groups[key]
                review_records.append({
                    "source_row": "",
                    "product_id": ";".join(group["source_ids"]),
                    "original_title": group["title"],
                    "matched_text": handle,
                    "category": "handle",
                    "reason": "Duplicate generated handle across different product groups",
                })

    def write_csv(path, records, fields):
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)

    write_csv(
        out_dir / "products.csv",
        product_rows,
        ["original_product_id", "handle", "title", "vendor", "status",
         "product_type", "category_id", "category_name", "tags", "source_product_ids"],
    )
    write_csv(
        out_dir / "variants.csv",
        variant_records,
        ["original_product_id", "product_handle", "edition", "color",
         "attributes", "upc_metafield", "image_url", "genres"],
    )
    write_csv(
        out_dir / "review.csv",
        review_records,
        ["source_row", "product_id", "original_title", "matched_text",
         "category", "reason"],
    )

    print(f"Read {len(rows)} source rows.")
    print(f"Wrote {len(product_rows)} base products, {len(variant_records)} variants.")
    print(f"Wrote {len(review_records)} review items.")
    print(f"Output folder: {out_dir.resolve()}")


if __name__ == "__main__":
    main()
