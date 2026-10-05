"""
Password hashing (bcrypt) and credential encryption (Fernet / PBKDF2).

Stored credentials (Shopify token, Webami username/password) are encrypted
with a key derived from the user's password so they are unreadable on disk
without knowing the password.
"""

import base64
import os

import bcrypt
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

import config

# Fixed salt - this is an internal tool, not a multi-user web service.
# A fixed salt is acceptable here; what matters is the password itself.
_SALT = b"inventory_app_v1_salt_2024"


# ─────────────────────────────────────────────
# Password
# ─────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=config.BCRYPT_ROUNDS)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False


# ─────────────────────────────────────────────
# Credential encryption
# ─────────────────────────────────────────────

def _derive_key(password: str) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        iterations=config.PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))


def encrypt(password: str, plaintext: str) -> str:
    """Encrypt a credential value using the user's password as key material."""
    if not plaintext:
        return ""
    return Fernet(_derive_key(password)).encrypt(plaintext.encode()).decode()


def decrypt(password: str, ciphertext: str) -> str:
    """Decrypt a credential value."""
    if not ciphertext:
        return ""
    return Fernet(_derive_key(password)).decrypt(ciphertext.encode()).decode()


# ─────────────────────────────────────────────
# Flask secret key persistence
# ─────────────────────────────────────────────

def get_secret_key() -> bytes:
    path = config.SECRET_KEY_PATH
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    key = os.urandom(32)
    with open(path, "wb") as f:
        f.write(key)
    return key
