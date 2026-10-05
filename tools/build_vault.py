"""Run by the app owner only. Creates vault.enc from credentials.json.

credentials.json:
{"shopify_store": "...", "shopify_token": "...",
 "webami_username": "...", "webami_password": "..."}

Usage: python tools/build_vault.py
"""

import getpass
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.vault import VAULT_PATH, seal  # noqa: E402

src = Path(__file__).resolve().parent.parent / "credentials.json"
if not src.exists():
    sys.exit("Create credentials.json first (it is git-ignored).")

pw = getpass.getpass("App password: ")
if pw != getpass.getpass("Confirm: "):
    sys.exit("Passwords don't match.")

VAULT_PATH.write_bytes(seal(pw, json.loads(src.read_text())))
print(f"Wrote {VAULT_PATH}. You can now delete credentials.json.")
