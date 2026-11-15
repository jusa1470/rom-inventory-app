import csv
import io
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("RECORDSYNC_DB", BASE_DIR / "inventory.db"))

SHOPIFY_API_VERSION = "2026-10"
SHOPIFY_BULK_POLL_SECONDS = 2

WEBAMI_BASE_URL = os.environ.get("RECORDSYNC_WEBAMI_URL", "https://webami.aent.com")
WEBAMI_PAGE_SIZE = 250
WEBAMI_WORKERS_START = 4
WEBAMI_WORKERS_MIN = 1
WEBAMI_WORKERS_MAX = 20
WEBAMI_MATCH_MIN = 0.7

# Must exactly match a redirect URL registered on the Shopify app.
OAUTH_REDIRECT_URI = os.environ.get(
    "RECORDSYNC_OAUTH_REDIRECT", "http://localhost:8000/api/auth/callback"
)


_CATS_CSV = """type,product_type,shopify_category_name,shopify_category_id,webami_formats
Vinyl,Vinyl,Media > Music & Sound Recordings > Vinyl,gid://shopify/TaxonomyCategory/me-3-6,"LP,12"" Single,7"" Single,10"" Single"
CD,CD,Media > Music & Sound Recordings > Music CDs,gid://shopify/TaxonomyCategory/me-3-3,CD
Cassette,Cassette,Media > Music & Sound Recordings > Music Cassette Tapes,gid://shopify/TaxonomyCategory/me-3-2,Cassette
Turntable Accessories,Turntable Accessories,Electronics > Audio > Audio Accessories > Turntable Accessories,gid://shopify/TaxonomyCategory/el-2-1-9,Vinyl Accessories
Coasters,Coasters,Home & Garden > Kitchen & Dining > Barware > Coasters,gid://shopify/TaxonomyCategory/hg-11-1-8,Collectibles
Notebooks,Notebooks,Office Supplies > General Office Supplies > Paper Products > Notebooks & Notepads,gid://shopify/TaxonomyCategory/os-4-9-9,Collectibles
Gift Cards,Gift Cards,Gift Cards,gid://shopify/TaxonomyCategory/gc,
Turntables,Turntables,Electronics > Audio > Audio Players & Recorders > Turntables & Record Players,gid://shopify/TaxonomyCategory/el-2-3-10,Turntables
Apparel,Apparel,Apparel & Accessories,gid://shopify/TaxonomyCategory/aa,Apparel
Ornaments,Ornaments,Home & Garden > Decor > Seasonal & Holiday Decorations > Holiday Ornaments,gid://shopify/TaxonomyCategory/hg-3-58-7,Collectibles
Speakers,Speakers,Electronics > Audio > Audio Components > Speakers,gid://shopify/TaxonomyCategory/el-2-2-10,Speaker & Components
Media Storage,Media Storage,Furniture > Cabinets & Storage > Media Storage Cabinets & Racks,gid://shopify/TaxonomyCategory/fr-4-10,Vinyl Accessories
Stickers,Stickers,Arts & Entertainment > Hobbies & Creative Arts > Arts & Crafts > Art & Crafting Materials > Embellishments & Trims > Decorative Stickers,gid://shopify/TaxonomyCategory/ae-2-1-2-8-4,Collectibles
Record Cleaning Kits,Record Cleaning Kits,Electronics > Audio > Audio Accessories > Turntable Accessories > Record Cleaning Kits,gid://shopify/TaxonomyCategory/el-2-1-9-2,Vinyl Accessories
Record Sleeves,Record Sleeves,Electronics > Audio > Audio Accessories > Turntable Accessories > Record Sleeves,gid://shopify/TaxonomyCategory/el-2-1-9-7,"Bags / Sleeves,Vinyl Accessories"
Headphones,Headphones,Electronics > Audio > Audio Components > Headphones & Headsets > Headphones,gid://shopify/TaxonomyCategory/el-2-2-7-1,Headphones
Media Players,Media Players,Electronics > Audio > Audio Players & Recorders,gid://shopify/TaxonomyCategory/el-2-3,Media Player Accessories
Other,Other,Uncategorized,gid://shopify/TaxonomyCategory/na,*
"""

PRODUCT_CATEGORIES = [
    {"name": r["type"], "product_type": r["product_type"],
     "category": r["shopify_category_name"],
     "category_id": r["shopify_category_id"].rsplit("/", 1)[-1],
     "formats": [f for f in r["webami_formats"].split(",") if f],
     "media": r["type"] in ("Vinyl", "CD", "Cassette")}
    for r in csv.DictReader(io.StringIO(_CATS_CSV))
]


def category(name: str):
    """Match by type name, full category path, or last path segment."""
    return next((c for c in PRODUCT_CATEGORIES
                 if name in (c["name"], c["category"], c["category"].split(" > ")[-1])), None)


def type_for_format(fmt: str | None):
    f = (fmt or "").strip().lower()
    return next((c["name"] for c in PRODUCT_CATEGORIES
                 if c["media"] and f in [x.lower() for x in c["formats"]]), None)




