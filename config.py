import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "inventory.db")
SESSION_DIR = os.path.join(BASE_DIR, ".sessions")
SECRET_KEY_PATH = os.path.join(BASE_DIR, ".secret_key")

# Webami - overwritten at runtime from DB
WEBAMI_BASE_URL = "https://webami.aent.com"

# Shopify
SHOPIFY_API_VERSION = "2025-01"
SHOPIFY_PAGE_SIZE   = 50

# Matching thresholds
MATCH_AUTO_THRESHOLD   = 0.95   # score >= this → auto-map, no review
MATCH_REVIEW_THRESHOLD = 0.70   # score >= this → queued for review

# Security
BCRYPT_ROUNDS      = 12
PBKDF2_ITERATIONS  = 260_000

# Defaults (overwritten from DB)
TARGET_MARGIN = 0.34

ALLOWED_CATEGORIES = [
  ("Apparel & Accessories", "gid://shopify/TaxonomyCategory/aa"),
  ("Home & Garden > Kitchen & Dining > Barware > Coasters", "gid://shopify/TaxonomyCategory/hg-11-1-8"),
  ("Arts & Entertainment > Hobbies & Creative Arts > Arts & Crafts > Art & Crafting Materials > Embellishments & Trims > Decorative Stickers", "gid://shopify/TaxonomyCategory/ae-2-1-2-8-4"),
  ("Gift Cards", "gid://shopify/TaxonomyCategory/gc"),
  ("Home & Garden > Decor > Seasonal & Holiday Decorations > Holiday Ornaments", "gid://shopify/TaxonomyCategory/hg-3-58-7"),
  ("Furniture > Cabinets & Storage > Media Storage Cabinets & Racks", "gid://shopify/TaxonomyCategory/fr-4-10"),
  ("Media > Music & Sound Recordings > Music CDs", "gid://shopify/TaxonomyCategory/me-3-3"),
  ("Media > Music & Sound Recordings > Music Cassette Tapes", "gid://shopify/TaxonomyCategory/me-3-2"),
  ("Office Supplies > General Office Supplies > Paper Products > Notebooks & Notepads", "gid://shopify/TaxonomyCategory/os-4-9-9"),
  ("Home & Garden > Smoking Accessories", "gid://shopify/TaxonomyCategory/hg-19"),
  ("Electronics > Audio > Audio Components > Speakers", "gid://shopify/TaxonomyCategory/el-2-2-10"),
  ("Electronics > Audio > Audio Accessories > Turntable Accessories", "gid://shopify/TaxonomyCategory/el-2-1-9"),
  ("Electronics > Audio > Audio Players & Recorders > Turntables & Record Players", "gid://shopify/TaxonomyCategory/el-2-3-10"),
  ("Media > Music & Sound Recordings > Vinyl", "gid://shopify/TaxonomyCategory/me-3-6")
]

def formats_compatible(shopify_category: str, webami_format: str) -> bool:
    """True if Shopify category is compatible with Webami format, or either is unknown."""
    if not shopify_category or not webami_format:
        return True
    cat = shopify_category.lower()
    fmt = webami_format.lower().strip()
    if "vinyl" in cat and "accessor" not in cat:
        return fmt in {"lp", '12" single', '7" single'}
    if "music cd" in cat or "cds" in cat:
        return fmt == "cd"
    if "cassette" in cat:
        return fmt == "cassette"
    if "accessor" in cat:
        return fmt not in {"lp", '12" single', '7" single', "cd", "cassette"}
    return True