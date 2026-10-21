p = "app/planner.py"
s = open(p).read()
old = s[s.index("def _suggest_chunk("):s.index("def suggest(")]
new = '''def smart_title(text: str) -> str:
    """Title-case words; ordinals stay lowercase (20th), number+letters uppercase (2LP)."""
    out = []
    for w in text.split():
        if re.fullmatch(r"\\d+(st|nd|rd|th)", w, re.I):
            out.append(w.lower())
        elif re.match(r"\\d", w):
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

'''
s = s.replace(old, new)
open(p, "w").write(s)