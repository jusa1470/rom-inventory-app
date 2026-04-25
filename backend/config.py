"""
Non-sensitive configuration values.
Credentials are stored in the OS keychain — see credentials.py.
"""

# --- Webami ---
WEBAMI_BASE_URL = "https://webami.aent.com"
WEBAMI_SCRAPE_WORKERS = 10          # concurrent product scrape threads
WEBAMI_ORDER_WORKERS = 4
WEBAMI_PRICE_SYNC_INTERVAL_HOURS = 168
WEBAMI_ORDERS_INCREMENTAL_PAGES = 2  # pages to check on incremental order sync

# --- Shopify ---
SHOPIFY_SHOP = "gtsiqj-1p.myshopify.com"
SHOPIFY_API_VERSION = "2026-04"
SHOPIFY_GRAPHQL_URL = f"https://{SHOPIFY_SHOP}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
SHOPIFY_PAGE_SIZE = 25

# --- Test ---
IS_TEST_MODE = False
TEST_SHOPIFY_SHOP = "rom-test-fkrtrxxf.myshopify.com"
TEST_SHOPIFY_GRAPHQL_URL = f"https://{TEST_SHOPIFY_SHOP}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"

# --- Pricing ---
MARGIN = 0.34
FORMAT_NAMES = {"LP": "Vinyl", "CD": "CD", "Cassette": "Cassette"}

# --- App ---
DB_PATH = "app_data.db"
LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
APP_NAME = "RecordsOnMainInventory"   # used as keychain service namespace
