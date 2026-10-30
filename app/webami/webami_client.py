import html
import json
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
        a = tds[0].find("a")
        items.append({
            "position": len(items),
            "title": html.unescape(lines[0]),
            "artist": html.unescape(lines[1]) if len(lines) >= 3 else "",
            "sku": lines[-1].rsplit("/", 1)[0] if "/" in lines[-1] else None,
            "href": a["href"] if a else None,
            "format": _txt(tds[4]),
            "upc": lines[-1].rsplit("/", 1)[-1],
            "quantity": int(_txt(tds[1]) or 0),
            "price": _money(_txt(tds[5])),
        })
    return items


def _info(soup, label):
    for li in soup.select("#product-primaryinfo li"):
        sp = li.find("span")
        if sp and sp.get_text(strip=True).rstrip(":").lower() == label.lower():
            return li.get_text(" ", strip=True)[len(sp.get_text(strip=True)):].strip() or None
    return None


def _val(soup, id_):
    el = soup.find("input", id=id_)
    return el.get("value") if el else None


def parse_product(page: str) -> dict:
    soup = BeautifulSoup(page, "lxml")
    ld = {}
    s = soup.select_one("script.ProductPageStrData")
    if s:
        try:
            ld = json.loads(s.string or s.get_text())
        except ValueError:
            pass
    fmt = None
    for li in soup.select(".aec-product-title li"):
        sp = li.find("span")
        if sp and sp.get_text(strip=True) == "Format:":
            fmt = li.get_text(" ", strip=True)[len("Format:"):].strip()
            break
    price = (ld.get("offers") or {}).get("price") or _txt(soup.select_one(".aec-listing-price"))
    new = soup.select_one(".aec-new-price strong")
    return {
        "title": _txt(soup.select_one("h2.title-h2")) or _val(soup, "album"),
        "artist": _val(soup, "artist"),
        "vendor": _info(soup, "Label") or ld.get("brand"),
        "product_type": fmt,
        "upc": _info(soup, "UPC") or _val(soup, "upc_cd"),
        "sku": _info(soup, "Product ID"),
        "price": _money(str(price)) if price else None,
        "your_price": _money(_txt(new)) if new else None,
        "wmsid": _val(soup, "wmsid"),
    }


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

    def get_product(self, href: str) -> dict:
        return parse_product(self._get(href))