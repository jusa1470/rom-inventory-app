import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "inventory.db")

DEFAULT_API_VERSION = "2025-01"
SHOPFY_PAGE_SIZE = 25
DEFAULT_PAGE_SIZE = 50