"""
Feature parsing engine with regex capture group support.

apply_features(features, rules) → {
  title_suffixes, title_prefixes, tags, description, unknown
}

Regex rules support $1, $2 substitution in action_value:
  match_text = r"^(Red|Blue|Clear)\s+Vinyl$"
  action_value = " - $1"
  "Red Vinyl" → " - Red"
"""

import re
from typing import Optional

import db.database as db


_COLOR_WORDS = ["Red","Blue","Green","Yellow","White","Black","Purple","Orange",
                "Pink","Gold","Silver","Clear","Translucent","Brown","Violet","Gray","Grey"]

_SPECIAL_ED_RE = re.compile(
    r'\b(\d+(?:st|nd|rd|th)\s+Anniversary(?:\s+(?:Deluxe|Limited|Expanded|Collector\'?s?))?(?:\s+Edition)?|'
    r'Anniversary(?:\s+(?:Deluxe|Limited|Expanded|Collector\'?s?))?(?:\s+Edition)?|'
    r'(?:Deluxe|Limited|Expanded|Collector\'?s?)\s+Anniversary(?:\s+Edition)?|'
    r'Limited Edition|Deluxe Edition|Expanded Edition|Reissue)\b', re.IGNORECASE)

_IEX_EDITION_RE = re.compile(r'\[IE\s+([A-Za-z]+)\s+Edition\]', re.IGNORECASE)

_COLOR_RE = re.compile(
    r'\(?\s*\b((?:[A-Z][\w\'\.]*\s+){0,2}(?:' + '|'.join(_COLOR_WORDS) + r'))\b(?:\s+Colored)?(?:\s+Vinyl)?\s*\)?', re.IGNORECASE)

_MINOR_WORDS = {"a","an","the","of","and","or","but","nor","in","on","at","to","for","from","by","as","with"}

_OST_RE  = re.compile(r'\(Original\s+Soundtrack\)', re.IGNORECASE)
_OMPS_RE = re.compile(r'\(Original\s+Motion\s+Picture\s+Soundtrack\)', re.IGNORECASE)


def _normalize_title_case(title: str) -> str:
    words = title.split(" ")
    out = []
    for i, w in enumerate(words):
        if i > 0 and w.lower() in _MINOR_WORDS:
            out.append(w.lower())
        else:
            out.append(w)
    return " ".join(out)


def _clean_title_spacing(title: str) -> str:
    title = re.sub(r'\(\s*\)', '', title)
    title = re.sub(r'\s{2,}', ' ', title)
    title = re.sub(r'\s+\)', ')', title)
    title = re.sub(r'\(\s+', '(', title)
    return title.strip()


def _match(feature: str, rule: dict) -> tuple[bool, dict]:
    """Returns (matched, capture_groups_dict)."""
    text = rule["match_text"]
    mt   = rule["match_type"]

    if mt == "exact":
        return feature == text, {}
    if mt == "iexact":
        return feature.lower() == text.lower(), {}
    if mt == "contains":
        return text in feature, {}
    if mt == "icontains":
        return text.lower() in feature.lower(), {}
    if mt == "regex":
        m = re.search(text, feature, re.IGNORECASE)
        if m:
            groups = {str(i + 1): (g or "") for i, g in enumerate(m.groups())}
            return True, groups
        return False, {}
    return False, {}


def _sub(value: str, groups: dict) -> str:
    """Substitute $1, $2 … with regex capture groups."""
    for k, v in groups.items():
        value = value.replace(f"${k}", v)
    return value


def apply_features(features: list[str], rules: Optional[list[dict]] = None) -> dict:
    if rules is None:
        rules = db.get_feature_rules(enabled_only=True)

    result = {
        "title_suffixes": [],
        "title_prefixes": [],
        "tags":           [],
        "description":    [],
        "unknown":        [],
    }

    for feature in (features or []):
        matched_any = False
        for rule in rules:   # sorted by priority DESC from DB
            ok, groups = _match(feature, rule)
            if not ok:
                continue
            matched_any = True
            action = rule["action_type"]
            value  = _sub(rule.get("action_value") or "", groups)

            if action == "drop":
                pass
            elif action == "title_suffix":
                result["title_suffixes"].append(value)
            elif action == "title_prefix":
                result["title_prefixes"].append(value)
            elif action == "add_tag":
                result["tags"].append(value)
            elif action == "description":
                result["description"].append(feature)

        if not matched_any:
            result["unknown"].append(feature)
            db.log_unknown_feature(feature)

    return result


def build_title(base_title: str, feature_result: dict) -> str:
    title = base_title or ""
    for prefix in feature_result["title_prefixes"]:
        title = prefix + title
    for suffix in feature_result["title_suffixes"]:
        title = title + suffix
    return title.strip()


def suggest_title(shopify_title: str, webami_title: str) -> str:
    """
    Build a normalized title combining base title with special-edition/anniversary
    text in parens and color as ' - Color' suffix, regardless of which side had it.
    Returns shopify_title unchanged if no special-edition/color pattern is found,
    or if the pattern already appears in the correct normalized position.
    """
    shopify_title = shopify_title or ""
    webami_title  = webami_title or ""
    combined_text = f"{shopify_title} {webami_title}"

    iex_match     = _IEX_EDITION_RE.search(combined_text)
    special_match = _SPECIAL_ED_RE.search(combined_text)
    color_match   = _COLOR_RE.search(combined_text)

    if iex_match:
        iex_name = iex_match.group(1).capitalize()

        def _strip_iex(t):
            t = _IEX_EDITION_RE.sub('', t)
            t = re.sub(r'\(IEX?\)', '', t, flags=re.IGNORECASE)
            t = re.sub(r'\s{2,}', ' ', t)
            t = re.sub(r'\s+([-)])', r'\1', t)
            return t.strip()

        base = _strip_iex(shopify_title) or _strip_iex(webami_title)
        title = f"{base} (IEX) - {iex_name}"
        result = _clean_title_spacing(title)
        if result.strip() == shopify_title.strip():
            return shopify_title
        return result

    if not special_match and not color_match:
        wt = webami_title.strip()
        wt = re.sub(r'\(IE\)', '(IEX)', wt)
        wt = _OMPS_RE.sub('(OMPS)', wt)
        wt = _OST_RE.sub('(OST)', wt)
        if wt and _normalize_title_case(wt) != _normalize_title_case(shopify_title.strip()):
            return wt
        return shopify_title

    def _strip_annotations(t):
        t = _SPECIAL_ED_RE.sub('', t)
        t = _COLOR_RE.sub('', t)
        t = re.sub(r'\(\s*\)', '', t)
        t = re.sub(r'\s*-\s*$', '', t)
        t = re.sub(r'\s{2,}', ' ', t)
        t = re.sub(r'\s+\)', ')', t)
        return t.strip()

    base = _strip_annotations(webami_title) or _strip_annotations(shopify_title)

    title = base
    if special_match:
        special_text = special_match.group(0).strip()
        title = f"{title} ({special_text})"
    if color_match:
        color = color_match.group(1).strip()
        title = f"{title} - {color}"

    result = _clean_title_spacing(title)
    result = re.sub(r'\(IE\)', '(IEX)', result)
    result = _OMPS_RE.sub('(OMPS)', result)
    result = _OST_RE.sub('(OST)', result)

    if result.strip() == shopify_title.strip():
        return shopify_title

    return result