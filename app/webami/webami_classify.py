"""Keyword matching and edition/color/attribute suggestions from WebAMI product data.
Pure functions; imports only the helper."""
import re

from app.webami.webami_helper import (
    _ATTR_SET, _COLOR_ONLY, _COLOR_WORDS, _ED_SET, _FEAT, _IGNORE_KW, norm)


# ── keyword matching (Shopify variant vs WebAMI product) ─────────────

def _kn(f: str) -> str:
    return re.sub(r"\s+vinyl$", "", norm(f))


def kws(text) -> set[str]:
    return {k for k in (_kn(f) for f in _FEAT.findall(text or "")) if k and k not in _IGNORE_KW}


def variant_kws(vtitle) -> set[str]:
    out: set[str] = set()
    for part in re.split(r"\s*\|\s*|\s+/\s+", vtitle or ""):
        found = _FEAT.findall(part)
        out |= {_kn(f) for f in found} if found else {_kn(part)}
    return out - _IGNORE_KW - {""}


def kw_eval(p: dict, w: dict) -> tuple[list[str], list[str]]:
    """(missing, extra): variant keywords absent from WebAMI; WebAMI title/features keywords not in variant."""
    if p.get("variant_title") is None:
        return [], []
    need = variant_kws(p["variant_title"])
    strict = kws(w.get("title")) | kws(w.get("features"))
    have = strict | kws(w.get("description"))
    return sorted(need - have), sorted(strict - need)


# ── edition / color / attributes suggestion ──────────────────────────

_ORD = re.compile(r"\b(\d+(?:st|nd|rd|th)|\d+\s+year)\s+anniversary(\s+edition)?\b", re.I)
_FINISH = {"splatter", "marble", "marbled", "swirl", "smoke", "smoky", "glitter", "metallic",
           "opaque", "translucent", "transparent", "milky", "neon", "pastel", "crystal",
           "galaxy", "coke bottle"}
_CV = {x for c in _COLOR_WORDS for x in c.split()} | {"&", "and"}
_COUNTRY = {"united kingdom": "UK", "united states": "US", "europe": "EU", "japan": "Japan"}
_ALIAS = {"iex": "Indie Exclusive", "ie": "Indie Exclusive"}
_SKIP_BR = re.compile(r"explicit|soundtrack|\bost\b|\bvol\b|\bpart\b|\bfeat", re.I)
_EXP = re.compile(r"[\[\(]?\s*explicit(?:\s+(?:content|cover|lyrics|version|artwork))*\s*[\]\)]?", re.I)


def _cap(s: str) -> str:
    return re.sub(r"(^|[\s\-])([a-z])", lambda m: m.group(1) + m.group(2).upper(), s)


def _suffix(words: list[str]) -> list[str]:
    out: list[str] = []
    for x in reversed(words):
        if x.lower() not in _CV:
            break
        out.insert(0, x)
    return out


def _desc_color(d: str):
    """(color phrase, is_bio) from the description. Quoted marketing names are ignored."""
    m = re.search(r"bio-?vinyl\s+((?:[A-Za-z&]+\s*)+)", d, re.I)
    if m:
        ws = []
        for x in m.group(1).split():
            if x.lower() not in _CV:
                break
            ws.append(x)
        if ws:
            return " ".join(ws), True
    for m in re.finditer(r"((?:[A-Za-z&\-]+\s+){1,5})vinyl\b", d, re.I):
        ws = _suffix([x for x in m.group(1).split() if x.lower() != "colored"])
        if ws:
            return " ".join(ws), False
    return None, False


def _join(cols: list[str], hint: str = ""):
    eco = any("ecorecord" in x.lower() for x in cols)
    toks = [re.sub(r"(?i)\s*vinyl$", "", re.sub(r"(?i)\s*ecorecord\s*", " ", x)).strip() for x in cols]
    toks = [x for x in toks if x]
    hw = [w for w in re.split(r"[\s+&/]+", re.sub(r"(?i)\bvinyl\b", "", hint)) if w]
    fin = [x for x in toks if x.lower() in _FINISH]
    have = {x.lower() for x in fin}
    fin += [w for w in hw if w.lower() in _FINISH and w.lower() not in have]
    fin.sort(key=lambda x: next((i for i, w in enumerate(hw) if w.lower() == x.lower()), 99))
    base = [x for x in toks if x.lower() not in _FINISH]
    ws = lambda x: set(x.lower().split())
    base = [x for i, x in enumerate(base) if not any(
        ws(x) < ws(y) or (ws(x) == ws(y) and j < i) for j, y in enumerate(base) if j != i)]
    jb = ", ".join(base[:-1]) + " & " + base[-1] if len(base) > 2 else " & ".join(base)
    if eco:
        base = [x for x in base if x.lower() != "clear"]
    res = " ".join(x for x in (jb, *fin) if x)
    if eco:
        return (res + " EcoRecord").strip()
    return res or None


def suggest_parts(w: dict) -> dict:
    """Suggested product title, edition, color, attributes from a WebAMI product."""
    t = _EXP.sub(" ", w.get("title") or "")
    d = _EXP.sub(" ", w.get("description") or "")
    ft = _EXP.sub(" ", w.get("features") or "")
    hint = ""
    parts = re.split(r"\s+-\s+", re.sub(r"[\[\(][^\]\)]*[\]\)]", " ", t), maxsplit=1)
    base = re.sub(r"\s+", " ", parts[0]).strip()
    tail = parts[1].strip() if len(parts) > 1 else ""
    ed: list[str] = []
    at: list[str] = []
    cols: list[str] = []
    st = {"imp": False, "cc": None, "col": False, "pic": False, "wt": None,
          "anniv": None, "gen": None}

    def addat(x):
        if x and norm(x) not in {norm(y) for y in at}:
            at.append(x)

    def setann(m):
        if not st["anniv"]:
            st["anniv"] = (re.sub(r"(?i)year", "Year", m.group(1)) + " Anniversary"
                           + (" Edition" if m.group(2) else ""))

    def take(f, raw=False):
        f = f.strip()
        n = norm(f)
        if not n or re.search(r"explicit|parental|oversize|recyclable", f, re.I):
            return
        if n in ("colored vinyl", "coloured vinyl"):
            st["col"] = True
            return
        if re.search(r"picture disc|zoetrope", f, re.I):
            st["pic"] = True
            return
        m = re.match(r"(.*?)\s*-\s*import$", f, re.I)
        if m or n == "import":
            st["imp"] = True
            if m and m.group(1).strip():
                st["cc"] = _COUNTRY.get(norm(m.group(1)), m.group(1).strip())
            return
        m = re.match(r"(\d{3})\s?(?:g|gm|gram)\b", f, re.I)
        if m:
            st["wt"] = st["wt"] or f"{m.group(1)}g"
            return
        if re.match(r"(with\s+)?bonus\s+7", f, re.I):
            addat("Bonus 7-inch Vinyl")
            return
        if n == "bonus lp":
            return
        f = _ALIAS.get(n, f)
        n = norm(f)
        m = _ORD.search(f)
        if m:
            setann(m)
            return
        if n in ("anniversary", "anniversary edition"):
            st["gen"] = f
            return
        if n in ("ep", "extended play"):
            addat("Extended Play")
            return
        if n in _ED_SET or n.endswith("exclusive"):
            ed.append(f)
            return
        if n in _ATTR_SET or n == "boxed set":
            addat(f)
            return
        if _COLOR_ONLY.match(f) or st["col"]:
            cols.append(f)
            return
        if raw:
            ed.append(f)

    # 1. title: brackets, " - tail", inline color before "Vinyl"
    for b in re.findall(r"[\[\(]([^\]\)]+)[\]\)]", t):
        if _SKIP_BR.search(b):
            continue
        b2 = re.sub(r"(?i)\b(vinyl|lp)\b", "", b).strip()
        if b2 and all(x.lower() in _CV for x in re.split(r"[\s+/]+", b2) if x):
            hint += " " + b2
            continue
        take(b, True)
    tc = None
    if tail:
        if norm(tail) in _ED_SET or _ORD.search(tail):
            take(tail)
        else:
            tc = re.sub(r"\s+", " ", re.sub(r"(?i)\b(colored|vinyl)\b", "", tail)).strip()
    if not tc and re.search(r"\svinyl(\s+lp)?$", base, re.I):
        ws = re.sub(r"\s+(colored\s+)?vinyl(\s+lp)?$", "", base, flags=re.I).split()
        k = 0
        while k < len(ws) - 1 and ws[-1 - k].lower() in _CV:
            k += 1
        if k and k < len(ws) - 1:
            k += 1
        tc = " ".join(ws[-k:]) if k else None
        base = " ".join(ws[:-k] if k else ws)

    # 2. features field
    for c in re.split(r"[;,/]", re.sub(r"^\(|\)$", "", ft.strip())):
        take(c)

    # 3. description: editions and colors only (plus a few attribute patterns below)
    if not st["anniv"]:
        m = _ORD.search(d)
        if m:
            setann(m)
    if st["gen"] and not st["anniv"]:
        ed.insert(0, st["gen"])
    if re.match(r"\s*limited\b", d, re.I):
        ed.append("Limited Edition")
    for c in cols:
        if st["col"] and c.lower() != "black" and base.lower().endswith(" " + c.lower()):
            base = base[: -len(c)].strip()

    # color
    nb = lambda x: None if not x or x.lower() == "black" else x
    fcol = nb(_join(cols, hint))
    dcol, bio = _desc_color(d)
    dcol = nb(dcol)
    use_d = False
    if tc:
        c = nb(tc)
    elif fcol and dcol and {x.lower() for x in fcol.split()} <= {x.lower() for x in dcol.split()}:
        c, use_d = dcol, True
    elif fcol:
        c = fcol
    else:
        c, use_d = dcol, True
    hc = nb(re.sub(r"\s+", " ", re.sub(r"\s*\+\s*", " & ", hint)).strip())
    if hc:
        cw = {x.lower() for x in (c or "").split() if x != "&"}
        if not cw or cw <= {x.lower() for x in hc.split() if x != "&"}:
            c = hc
    if c:
        c = re.sub(r"(?i)\s+and\s+", " & ", c)
    if st["pic"]:
        color = "Zoetrope Picture Disc Vinyl" if re.search("zoetrope", t + d, re.I) \
            else "Picture Disc Vinyl"
    elif c:
        color = _cap(c) + (" Bio-Vinyl" if bio and use_d else " Vinyl")
    else:
        color = "None"

    # edition
    ann = st["anniv"]
    seen: set[str] = set()
    ed = [x for x in ed if not (norm(x) in seen or seen.add(norm(x)))]
    ed = [x for x in ed if not any(x is not y and f" {norm(x)} " in f" {norm(y)} " for y in ed)]
    ex = [x for x in ed if re.search(r"exclusive|^rsd", x, re.I)]
    rest = [x for x in ed if x not in ex]
    nr = [norm(x) for x in rest]
    if "deluxe edition" in nr and "limited edition" in nr:
        rest = [x for x in rest if norm(x) not in ("deluxe edition", "limited edition")]
        rest.insert(0, "Deluxe Limited Edition")
    if ann and [norm(x) for x in rest] == ["deluxe edition"]:
        head = [re.sub(r" Edition$", "", ann) + " Deluxe Edition"]
    else:
        if ann and (rest or ex):
            ann = re.sub(r" Edition$", "", ann)
        head = ([ann] if ann else []) + rest
    edition = " - ".join(head + ex) or "Standard"

    # attributes
    m = re.search(r"\b(\d{3})\s?(?:g|gm|gram)\b", d, re.I)
    wt = st["wt"] or (f"{m.group(1)}g" if m else None)
    m = re.search(r"\b(\d)\s*-?\s*x?\s*lp\b|\b(double|triple)\b(?:\s+\w+){0,3}?\s+(?:vinyl|lp)\b",
                  d, re.I)
    n = 0
    if m:
        n = int(m.group(1)) if m.group(1) else {"double": 2, "triple": 3}[m.group(2).lower()]
    extra: list[str] = []
    if re.search(r"digital download with bonus tracks", d, re.I):
        extra.append("Digital Download with Bonus Tracks")
    m = re.search(r"bonus tracks?", d, re.I)
    if m and not any("bonus track" in norm(y) for y in at + extra):
        extra.append(_cap(m.group(0).lower()))
    if re.search(r"laser[- ]etch(?:ing|ed)", d, re.I):
        extra.append("Laser Etched")
    imp = ([f"Import ({st['cc']})" if st["cc"] else "Import"] if st["imp"] else [])
    attrs = ([wt] if wt else []) + ([f"{n}Lp's"] if n >= 2 else []) + at + extra + imp

    return {"title": base, "edition": edition, "color": color,
            "attributes": ", ".join(attrs) or "None"}