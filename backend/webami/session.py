"""
Webami session management.

One authenticated requests.Session per thread via threading.local().
requests.Session is NOT thread-safe — sharing one session across the
ThreadPoolExecutor workers causes connection-pool contention and
effectively serialises requests despite having multiple workers.

Each worker thread gets its own session on first use, logs in once,
and reuses it for all subsequent requests on that thread.
"""

import logging
import threading
import requests

import config
from credentials import CredentialStore

logger = logging.getLogger(__name__)

_creds = CredentialStore()
_local = threading.local()   # thread-local storage


def _worker_tag() -> str:
    """Short identifier for the current thread, e.g. '[W3]'."""
    name = threading.current_thread().name
    # ThreadPoolExecutor names threads 'ThreadPoolExecutor-0_N'
    if "_" in name:
        idx = name.rsplit("_", 1)[-1]
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
    tag = _worker_tag()
    logger.info(f"{tag} Logging in to Webami")
    response = session.post(
        f"{config.WEBAMI_BASE_URL}/api/authentication/authenticate",
        json={
            "EmailAddress": _creds.get("webami_username"),
            "Password": _creds.get("webami_password"),
            "ConsumerMode": False,
        },
    )
    response.raise_for_status()
    data = response.json()
    if data.get("errors") != []:
        logger.warning(f"{tag} Webami login warning: {data.get('errors')}")
    else:
        logger.info(f"{tag} Webami login successful")


def get_session() -> requests.Session:
    """
    Return this thread's authenticated session, creating and logging
    in if this is the first request on the current thread.
    """
    if not hasattr(_local, "session") or _local.session is None:
        _local.session = _build_session()
        _login(_local.session)
    return _local.session


def reset_session() -> None:
    """Force a fresh login on the next get_session() call for this thread."""
    _local.session = None
    logger.info(f"{_worker_tag()} Webami session reset")


def authenticated_get(url: str, **kwargs) -> requests.Response:
    """GET with automatic re-auth on session expiry."""
    resp = get_session().get(url, **kwargs)
    if resp.status_code == 401:
        reset_session()
        resp = get_session().get(url, **kwargs)
    resp.raise_for_status()
    return resp


def authenticated_post(url: str, **kwargs) -> requests.Response:
    """POST with automatic re-auth on session expiry."""
    resp = get_session().post(url, **kwargs)
    if resp.status_code == 401:
        reset_session()
        resp = get_session().post(url, **kwargs)
    resp.raise_for_status()
    return resp