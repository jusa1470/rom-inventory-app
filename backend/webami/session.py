"""
Webami session management.

One authenticated requests.Session per thread via threading.local().
requests.Session is NOT thread-safe — sharing one session across the
ThreadPoolExecutor workers causes connection-pool contention and
effectively serialises requests despite having multiple workers.

Each worker thread gets its own session on first use, logs in once,
and reuses it for all subsequent requests on that thread.
"""

from _thread import _local
import logging
import threading
import requests
from bs4 import BeautifulSoup, Tag

import config
from credentials import CredentialStore

logger: logging.Logger = logging.getLogger(__name__)

_creds = CredentialStore()
_local_thread: _local = threading.local()   # thread-local storage

def _worker_tag() -> str:
    """Short identifier for the current thread, e.g. '[W3]'."""
    name: str = threading.current_thread().name
    # ThreadPoolExecutor names threads 'ThreadPoolExecutor-0_N'
    if "_" in name:
        idx: str = name.rsplit("_", 1)[-1]
        return f"[W{idx}]"
    return f"[{name}]"

def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36"
        ),
        "Content-Type": "application/json",
    })
    return session

def _login(session: requests.Session) -> None:
    tag: str = _worker_tag()
    logger.info(f"{tag} Logging in to Webami")

    resp: requests.Response = session.get("https://webami.aent.com/webami/logon")
    soup = BeautifulSoup(resp.text, "lxml")
    token_input: Tag | None = soup.find("input", {"name": "__RequestVerificationToken"})
    if not token_input:
        raise RuntimeError("No __RequestVerificationToken input found on logon page")
    header_token = str(token_input["value"])
    logger.debug(f"Got header token: {header_token[:20]}...")

    response: requests.Response = session.post(
        f"{config.WEBAMI_BASE_URL}/api/authentication/authenticate",
        json={
            "EmailAddress": _creds.get("webami_username"),
            "Password": _creds.get("webami_password"),
            "ConsumerMode": False,
        },
        headers={
            "__RequestVerificationToken": header_token
        }
    )
    response.raise_for_status()
    data = response.json()
    errors = data.get("errors")
    if errors:
        logger.warning(f"{tag} Webami login warning: {errors}")
    else:
        logger.info(f"{tag} Webami login successful")

def get_session() -> requests.Session:
    """
    Return this thread's authenticated session, creating and logging
    in if this is the first request on the current thread.
    """
    if not hasattr(_local_thread, "session") or _local_thread.session is None:
        _local_thread.session = _build_session()
        _login(_local_thread.session)
    return _local_thread.session

def reset_session() -> None:
    """Force a fresh login on the next get_session() call for this thread."""
    _local_thread.session = None
    logger.info(f"{_worker_tag()} Webami session reset")

def authenticated_get(url: str, **kwargs) -> requests.Response:
    """GET with automatic re-auth on session expiry."""
    resp: requests.Response = get_session().get(url, **kwargs)
    if resp.status_code == 401:
        reset_session()
        resp = get_session().get(url, **kwargs)
    resp.raise_for_status()
    return resp

def authenticated_post(url: str, **kwargs) -> requests.Response:
    """POST with automatic re-auth on session expiry."""
    resp: requests.Response = get_session().post(url, **kwargs)
    if resp.status_code == 401:
        reset_session()
        resp = get_session().post(url, **kwargs)
    resp.raise_for_status()
    return resp