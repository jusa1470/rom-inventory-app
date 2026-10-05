"""Encrypted credential vault. Key is derived from the app password (scrypt),
data is sealed with AES-GCM. A wrong password fails authentication."""

import base64
import json
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

VAULT_PATH = Path(__file__).resolve().parent.parent / "vault.enc"
_N, _R, _P = 2**15, 8, 1


class VaultError(Exception):
    pass


def _key(password: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=_N, r=_R, p=_P).derive(password.encode())


def seal(password: str, data: dict) -> bytes:
    salt, nonce = os.urandom(16), os.urandom(12)
    ct = AESGCM(_key(password, salt)).encrypt(nonce, json.dumps(data).encode(), None)
    return json.dumps({
        "v": 1,
        "salt": base64.b64encode(salt).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ct": base64.b64encode(ct).decode(),
    }).encode()


def unseal(password: str, blob: bytes) -> dict:
    try:
        o = json.loads(blob)
        salt, nonce, ct = (base64.b64decode(o[k]) for k in ("salt", "nonce", "ct"))
        return json.loads(AESGCM(_key(password, salt)).decrypt(nonce, ct, None))
    except (InvalidTag, KeyError, ValueError):
        raise VaultError("Incorrect password")


def open_vault(password: str) -> dict:
    if not VAULT_PATH.exists():
        raise VaultError("vault.enc not found")
    return unseal(password, VAULT_PATH.read_bytes())
