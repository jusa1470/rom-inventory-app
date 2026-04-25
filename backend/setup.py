"""
One-time setup script. Run this before launching the app for the first time.
Stores credentials in the OS keychain — nothing is written to disk.

Usage:
    python setup.py
"""

import getpass
import sys
import keyring
import keyring.errors

from credentials import CredentialStore, CredentialError
from config import APP_NAME


def check_keychain_available():
    """
    Verify the OS keychain is actually writable before we start.
    On Linux without a running keyring daemon this will fail.
    """
    test_service = f"{APP_NAME}_test"
    test_key = "_setup_check"
    try:
        keyring.set_password(test_service, test_key, "ok")
        keyring.delete_password(test_service, test_key)
    except keyring.errors.NoKeyringError:
        print(
            "\n❌  No keychain backend found.\n"
            "    On Linux, install and unlock one of:\n"
            "      sudo apt install gnome-keyring   (GNOME)\n"
            "      sudo apt install kwalletmanager  (KDE)\n"
            "    Then log out and back in, and re-run this script.\n"
        )
        sys.exit(1)
    except Exception as e:
        print(f"\n❌  Keychain test failed: {e}\n")
        sys.exit(1)


def main():
    print(f"\n{'=' * 50}")
    print(f"  {APP_NAME} — First-Time Setup")
    print(f"{'=' * 50}\n")
    print("Credentials will be stored in your OS keychain.")
    print("Nothing is written to any file.\n")

    check_keychain_available()

    store = CredentialStore()

    if not store.is_first_run():
        print("⚠️  Credentials are already configured.")
        overwrite = input("Overwrite existing credentials? [y/N]: ").strip().lower()
        if overwrite != "y":
            print("Setup cancelled.")
            sys.exit(0)

    # ── App master password ──────────────────────────────────────────
    print("Create a master password for this app.")
    print("This is what you'll enter when opening the app.\n")
    while True:
        pw = getpass.getpass("Master password: ")
        pw2 = getpass.getpass("Confirm master password: ")
        if pw == pw2:
            break
        print("Passwords don't match, try again.\n")
    store.set_app_password(pw)
    print("✅  Master password set.\n")

    # ── Webami credentials ───────────────────────────────────────────
    print("Webami login credentials:")
    store.set("webami_username", input("  Email: ").strip())
    store.set("webami_password", getpass.getpass("  Password: "))
    print("✅  Webami credentials saved.\n")

    # ── Shopify token ────────────────────────────────────────────────
    print("Shopify Admin API token:")
    print("  (starts with shpat_...)")
    store.set("shopify_token", getpass.getpass("  Token: "))
    print("✅  Shopify token saved.\n")

    # ── Test Shopify token ────────────────────────────────────────────────
    print("Test Shopify Admin API token:")
    print("  (starts with shpat_...)")
    store.set("test_shopify_token", getpass.getpass("  Token: "))
    print("✅  Test Shopify token saved.\n")

    print("=" * 50)
    print(f"  Setup complete. You can now launch {APP_NAME}.")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    main()