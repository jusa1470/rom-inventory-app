import sqlite3, os, base64
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

DB = "app.db"

class CredentialError(Exception):
    pass

def _derive_key(password: str, salt: bytes):
    kdf = Scrypt(salt=salt, length=32, n=2**14, r=8, p=1)
    return kdf.derive(password.encode())

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS secrets (k TEXT, v TEXT)")
    conn.commit()
    conn.close()

def store_credentials(password, shopify, webami_user, webami_pass):
    init_db()

    salt = os.urandom(16)
    key = _derive_key(password, salt)
    aes = AESGCM(key)

    def enc(val):
        nonce = os.urandom(12)
        ct = aes.encrypt(nonce, val.encode(), None)
        return base64.b64encode(nonce + ct).decode()

    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("DELETE FROM secrets")

    c.execute("INSERT INTO secrets VALUES (?,?)", ("salt", base64.b64encode(salt).decode()))
    c.execute("INSERT INTO secrets VALUES (?,?)", ("shopify", enc(shopify)))
    c.execute("INSERT INTO secrets VALUES (?,?)", ("webami_user", enc(webami_user)))
    c.execute("INSERT INTO secrets VALUES (?,?)", ("webami_pass", enc(webami_pass)))

    conn.commit()
    conn.close()

def load_credentials(password):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    rows = dict(c.execute("SELECT k,v FROM secrets").fetchall())
    conn.close()

    salt = base64.b64decode(rows["salt"])
    key = _derive_key(password, salt)
    aes = AESGCM(key)

    def dec(val):
        raw = base64.b64decode(val)
        nonce = raw[:12]
        ct = raw[12:]
        return aes.decrypt(nonce, ct, None).decode()

    return {
        "shopify": dec(rows["shopify"]),
        "webami_user": dec(rows["webami_user"]),
        "webami_pass": dec(rows["webami_pass"]),
    }


def check_credentials_exist():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    # Check table exists
    c.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='secrets'
    """)
    if not c.fetchone():
        conn.close()
        raise CredentialError("Secrets table missing")

    # Check required keys exist
    c.execute("SELECT k FROM secrets")
    keys = {row[0] for row in c.fetchall()}
    conn.close()

    required = {"salt", "shopify", "webami_user", "webami_pass"}

    missing = required - keys
    if missing:
        raise CredentialError(f"Missing credentials: {missing}")