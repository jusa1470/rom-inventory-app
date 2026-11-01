import re


_COLS = ("title", "artist", "vendor", "features", "product_type", "sku", "upc",
         "price", "your_price", "wmsid", "href")

_EDITIONS = [
    "Indie Exclusive", "RSD Exclusive", "RSD Black Friday 2025", "RSD 2026", "RSD Essential",
    "Rhino Exclusive", "Target Exclusive", "Walmart Exclusive", "Amazon Exclusive",
    "Brick & Mortar Exclusive", "Limited Deluxe Edition", "Deluxe Limited Edition",
    "Expanded Limited Edition", "Limited Edition", "Ultimate Deluxe", "Japanese Deluxe",
    "Deluxe Edition", "Deluxe", "Expanded Edition", "Expanded", "Extended", "Complete",
    "Special Edition", "Legendary Edition", "Legendary", "Redux", "Instrumental", "Unmixed",
    "Remastered Reissue", "Remastered", "Remaster", "Reissue", "Re-issue", "Revinyl",
    "Rhino Reserve", "Rhino High Fidelity", "Rocktober", "Original Jazz Classics Series",
    "Chess Acoustic Sounds Series", "Blue Note Tone Poet", "Blue Note Classic Vinyl",
    "Blue Note Essentials Series", "Verve Vault Series", "Verve By Request Series",
    "Metal Matters Series", "Fueled By Ramen", "Music On Vinyl", "MoFi",
    "Original Master Recording", "Master Recording", "Silver Collection", "One-Step",
]
_ATTRS = [
    "Gatefold LP Jacket", "Gatefold", "7in Box Set", "Box Set", "Booklet",
    "Digital Download Card", "Mask Cover", "Bonus Tracks", "Bonus Track", "Added Track",
    "Bonus LP", "Bonus CD", "Bonus 7-Inch", "Poster", "Lithograph", "Sticker",
    "Signed Polaroid", "Signed Postcard", "Signed", "Alternative Cover", "Alternate Artwork",
    "Import", "Extended Play", "Mono",
]
_COLOR_WORDS = [
    "black", "white", "red", "blue", "green", "yellow", "pink", "orange", "purple", "gold",
    "silver", "brown", "gray", "grey", "cream", "copper", "teal", "aqua", "turquoise",
    "magenta", "violet", "maroon", "navy", "rose", "lime", "olive", "mint", "lavender",
    "tangerine", "apricot", "raspberry", "grape", "rust", "amber", "jade", "ruby", "emerald",
    "cobalt", "iris", "hazel", "denim", "clear", "opaque", "translucent", "transparent",
    "metallic", "glitter", "glow in the dark", "marbled", "marble", "splatter", "swirl",
    "split", "half-half", "solid", "smoky", "smoke", "crystal", "pearls", "pearl", "milky",
    "pastel", "neon", "bright", "dark", "light", "deep", "baby", "ultra", "electric",
    "multi-colored", "mixed", "colored", "tie dye", "galaxy", "rainbow", "coke bottle",
    "apple", "flame", "seablue", "sea", "sky", "canary", "bone", "bubblegum", "splash",
    "custard", "forest", "ice", "sand", "sunrise", "sunset", "sun", "sangria", "candy cane",
    "vanilla", "citrus", "seafoam", "royal", "blush", "ocean", "evergreen", "moonstone",
    "eggshell", "coffee", "heavyweight", "ecorecord", "recycled", "biovinyl",
]
_COLOR_RE = (r"(?:(?:%s)(?:\s+|/|-)?)+\s*(?:vinyl|picture\s+disc)?"
             % "|".join(re.escape(c) for c in sorted(_COLOR_WORDS, key=len, reverse=True)))

def _alt(items):
    return "|".join(re.escape(i) for i in sorted(items, key=len, reverse=True))

_FEAT = re.compile(
    r"(?<![\w])(?:(?:\d+(?:st|nd|rd|th)\s+anniversary(?:\s+(?:deluxe|remaster|reissue))?)|"
    r"(?:\d{4}\s+(?:remaster|reissue|repress|stereo))|(?:\d+\s+year)|"
    r"(?:%s)|(?:%s)|(?:\d{3}\s?g(?:ram)?\s+(?:%s)|\d{3}\s?g(?:ram)?)|"
    r"(?:%s\s+vinyl)|picture\s+disc|zoetrope)(?![\w])"
    % (_alt(_EDITIONS), _alt(_ATTRS), _COLOR_RE, _COLOR_RE), re.I)


def norm(s) -> str:
    s = re.sub(r"[\[\(]\s*explicit( content)?\s*[\]\)]", " ", s or "", flags=re.I)
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()