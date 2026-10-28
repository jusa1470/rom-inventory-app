import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("RECORDSYNC_DB", BASE_DIR / "inventory.db"))

DEFAULT_API_VERSION = "2025-01"
SHOPIFY_PAGE_SIZE = 10
SHOPIFY_VARIANT_PAGE_SIZE = 5
SHOPIFY_BULK_POLL_SECONDS = 2
DEFAULT_PAGE_SIZE = 50

# Must exactly match a redirect URL registered on the Shopify app.
OAUTH_REDIRECT_URI = os.environ.get(
    "RECORDSYNC_OAUTH_REDIRECT", "http://localhost:8000/api/auth/callback"
)