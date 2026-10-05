"""
Thread-safe Webami session manager.
Exposes: authenticated_get(), authenticated_post(), _worker_tag()
Call configure() after login to inject credentials.
"""

import hashlib
import logging
import threading

import requests
from bs4 import BeautifulSoup, Tag
import urllib3

import config

logger = logging.getLogger(__name__)

_local       = threading.local()
_creds: dict = {}
_creds_hash  = ""
_lock        = threading.Lock()

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def configure(base_url: str, username: str, password: str) -> None:
    global _creds, _creds_hash
    new_hash = hashlib.sha256(f"{base_url}|{username}|{password}".encode()).hexdigest()
    with _lock:
        if new_hash == _creds_hash:
            return
        _creds = {"base_url": base_url.rstrip("/"), "webami_username": username, "webami_password": password}
        _creds_hash = new_hash
    if hasattr(_local, "session"):
        _local.session = None


def authenticated_get(url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", 30)
    resp = _session().get(url, **kwargs)
    if _redirected_to_login(resp, url):
        _local.session = None
        resp = _session().get(url, **kwargs)
    return resp


def authenticated_post(url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", 30)
    return _session().post(url, **kwargs)


def _worker_tag() -> str:
    return f"[W{threading.get_ident() % 99999:05d}]"


# ─────────────────────────────────────────────
# Internal
# ─────────────────────────────────────────────

def _session() -> requests.Session:
    if not getattr(_local, "session", None):
        _local.session = _build_and_login()
    return _local.session


def _build_session() -> requests.Session:
    session = requests.Session()
    session.verify = False
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36"
        ),
        "Content-Type": "application/json",
    })
    return session


def _login(session: requests.Session) -> None:
    tag = _worker_tag()
    base_url = _creds.get("base_url") or config.WEBAMI_BASE_URL
    logger.info(f"{tag} Logging in to Webami at {base_url}")

    resp = session.get(f"https://webami.aent.com/webami/logon")
    soup = BeautifulSoup(resp.text, "html.parser")
    token_input: Tag | None = soup.find("input", {"name": "__RequestVerificationToken"})
    if not token_input:
        raise RuntimeError("No __RequestVerificationToken found on logon page")
    header_token = str(token_input["value"])
    logger.debug(f"{tag} Got CSRF token: {header_token[:20]}…")

    response = session.post(
        f"{base_url}/api/authentication/authenticate",
        json={
            "EmailAddress": _creds.get("webami_username"),
            "Password":     _creds.get("webami_password"),
            "ConsumerMode": False,
        },
        headers={"__RequestVerificationToken": header_token},
    )

    if response.status_code not in (200, 201):
        raise RuntimeError(f"Webami login failed - HTTP {response.status_code}")

    logger.info(f"{tag} Webami session established")


def _build_and_login() -> requests.Session:
    if not _creds.get("webami_username"):
        raise RuntimeError("Webami credentials not configured - log in to the app first")
    sess = _build_session()
    _login(sess)
    return sess


def _redirected_to_login(resp: requests.Response, original_url: str) -> bool:
    return bool(resp.url and "logon" in resp.url.lower() and "logon" not in original_url.lower())
