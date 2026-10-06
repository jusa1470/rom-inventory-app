from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "recordsync.db"

SHOPIFY_API_VERSION = "2026-04"
SHOPIFY_PAGE_SIZE = 20        # products per request; pacing adapts to the reported query cost
SHOPIFY_VARIANTS_INLINE = 5   # variants fetched inline; extra pages fetched per product
