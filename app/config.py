import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("RECORDSYNC_DB", BASE_DIR / "inventory.db"))

DEFAULT_API_VERSION = "2026-10"
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

# media=True enables the media flow; category = Shopify taxonomy name
PRODUCT_CATEGORIES = [
    {"name": "Vinyl", "media": True, "category": ""},
    {"name": "CD", "media": True, "category": ""},
    {"name": "Cassette", "media": True, "category": ""},
    {"name": "Other", "media": False, "category": ""},
]




