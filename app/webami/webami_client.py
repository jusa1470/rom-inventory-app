import html
import logging
import threading
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from app import config

logger = logging.getLogger(__name__)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _txt(el) -> str:
    return el.get_text(" ", strip=True).replace("\xa0", " ").strip() if el else ""


def _money(s: str):
    try:
        return float(s.replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def parse_order_list(page: str) -> list[dict]:
    soup = BeautifulSoup(page, "lxml")
    out = []
    for tr in soup.select("#Grid tbody tr"):
        a = tr.select_one("a.aec-showorder-a")
        tds = tr.find_all("td", recursive=False)
        if not a or len(tds) < 6:
            continue
        try:
            dt = datetime.strptime(_txt(tds[4]), "%m/%d/%Y %H:%M").strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            dt = None
        out.append({
            "guid": a["href"].rstrip("/").rsplit("/", 1)[-1],
            "number": _txt(a),
            "name": _txt(tds[2]) or None,
            "submitted_at": dt,
            "sku_count": int(_txt(tds[5]) or 0),
        })
    return out


def parse_order_items(page: str) -> list[dict]:
    soup = BeautifulSoup(page, "lxml")
    items = []
    for tr in soup.select("#ItemsGrid .k-grid-content tbody tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 6:
            continue
        lines = [l.replace("\xa0", " ").strip() for l in tds[0].get_text("\n").split("\n")]
        lines = [l for l in lines if l]
        if len(lines) < 2:
            continue
        # title, [artist], sku/upc
        items.append({
            "position": len(items),
            "title": html.unescape(lines[0]),
            "artist": html.unescape(lines[1]) if len(lines) >= 3 else "",
            "upc": lines[-1].rsplit("/", 1)[-1],
            "quantity": int(_txt(tds[1]) or 0),
            "price": _money(_txt(tds[5])),
        })
    return items


class WebamiClient:
    def __init__(self, base_url: str, username: str, password: str):
        self.base = base_url.rstrip("/")
        self._user, self._pw = username, password
        self._local = threading.local()

    def _login(self) -> requests.Session:
        s = requests.Session()
        s.headers["User-Agent"] = UA
        r = s.get(f"{self.base}/webami/logon", timeout=30)
        tok = BeautifulSoup(r.text, "lxml").find("input", {"name": "__RequestVerificationToken"})
        if not tok:
            raise RuntimeError("WebAMI: no verification token on logon page")
        r = s.post(
            f"{self.base}/api/authentication/authenticate",
            json={"EmailAddress": self._user, "Password": self._pw, "ConsumerMode": False},
            headers={"__RequestVerificationToken": tok["value"]},
            timeout=30,
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(f"WebAMI login failed: HTTP {r.status_code}")
        return s

    def _session(self) -> requests.Session:
        if not getattr(self._local, "s", None):
            self._local.s = self._login()
        return self._local.s

    def _get(self, path: str, params: dict | None = None) -> str:
        for _ in range(2):
            r = self._session().get(f"{self.base}{path}", params=params, timeout=30)
            if "logon" in r.url.lower():
                self._local.s = None
                continue
            r.raise_for_status()
            return r.text
        raise RuntimeError("WebAMI: session rejected")

    def list_new_orders(self, known: set[str]) -> list[dict]:
        """Newest-first pages; stops once a page has nothing new."""
        size, page, out = config.WEBAMI_PAGE_SIZE, 1, []
        while True:
            rows = parse_order_list(self._get(
                "/webami/submittedorders", {"Grid-page": page, "Grid-pageSize": size}))
            out += [r for r in rows if r["guid"] not in known]
            if len(rows) < size or all(r["guid"] in known for r in rows):
                return out
            page += 1

    def get_order_items(self, guid: str) -> list[dict]:
        return parse_order_items(self._get(f"/webami/vieworder/{guid}"))