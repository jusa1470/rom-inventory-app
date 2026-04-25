"""
Credential storage via OS keychain (keyring library).
  - macOS  → Keychain Access
  - Windows → Credential Manager
  - Linux   → libsecret / KWallet

Nothing sensitive is written to disk or embedded in the binary.

Usage:
    from credentials import CredentialStore
    store = CredentialStore()

    # First-run setup (called from CLI setup wizard)
    store.set("webami_username", "user@example.com")
    store.set("webami_password", "secret")
    store.set("shopify_token", "shpat_...")
    store.set("test_shopify_token", "shpat_...")
    store.set("app_password", "master-pw")

    # Runtime retrieval
    username = store.get("webami_username")

    # Verify the app master password before granting access
    store.verify_app_password("entered-pw")  # raises if wrong
"""

import hashlib
import os
import keyring
from config import APP_NAME


# Keys stored in the keychain under APP_NAME as the service name
_KEYS = {
    "webami_username",
    "webami_password",
    "shopify_token",
    "test_shopify_token",
    "app_password_hash",
}


class CredentialError(Exception):
    pass


class CredentialStore:
    def __init__(self, service: str = APP_NAME):
        self.service = service

    # ------------------------------------------------------------------
    # Core get / set / delete
    # ------------------------------------------------------------------

    def get(self, key: str) -> str:
        """Retrieve a credential. Raises CredentialError if not found."""
        if key not in _KEYS:
            raise CredentialError(f"Unknown credential key: {key!r}")
        value = keyring.get_password(self.service, key)
        if value is None:
            raise CredentialError(
                f"Credential {key!r} not set. Run the setup wizard first."
            )
        return value

    def set(self, key: str, value: str) -> None:
        """Store a credential in the OS keychain."""
        if key not in _KEYS:
            raise CredentialError(f"Unknown credential key: {key!r}")
        keyring.set_password(self.service, key, value)

    def delete(self, key: str) -> None:
        """Remove a credential from the keychain."""
        try:
            keyring.delete_password(self.service, key)
        except keyring.errors.PasswordDeleteError:
            pass

    def is_set(self, key: str) -> bool:
        try:
            keyring.get_password(self.service, key)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # App master password
    # ------------------------------------------------------------------

    def set_app_password(self, password: str) -> None:
        """Hash and store the app master password."""
        hashed = self._hash(password)
        keyring.set_password(self.service, "app_password_hash", hashed)

    def verify_app_password(self, password: str) -> bool:
        """Return True if password matches stored hash, else raise."""
        stored = keyring.get_password(self.service, "app_password_hash")
        if stored is None:
            raise CredentialError("App password not configured.")
        if self._hash(password) != stored:
            raise CredentialError("Incorrect app password.")
        return True

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    def is_first_run(self) -> bool:
        """True if no credentials have been configured yet."""
        return keyring.get_password(self.service, "app_password_hash") is None

    def reset_all(self) -> None:
        """Wipe all stored credentials. User will need to re-run setup."""
        all_keys = _KEYS | {"app_password_hash"}
        for key in all_keys:
            self.delete(key)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _hash(value: str) -> str:
        salt = APP_NAME.encode()
        return hashlib.sha256(salt + value.encode()).hexdigest()