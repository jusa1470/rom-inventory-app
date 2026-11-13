import html
import json
import logging
import re
import threading
from datetime import datetime
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app import config
from app.webami.webami_helper import norm, simplify
from app.webami.limiter import AdaptiveLimiter

logger = logging.getLogger(__name__)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
FORMATS = {
    "LP": "LP Vinyl",
    "CD": "CD",
    "Cassette": "Cassette",
}  # order-line format -> search format; add others as found


def _txt(el) -> str:
    return el.get_text(" ", strip=True).replace("\xa0", " ").strip() if el else ""


def _money(s: str):
    try:
        return float(s.replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def _weight(s):
    m = re.search(r"([\d.]+)\s*(lbs?|oz|kg|g)\b", s or "", re.I)
    return (float(m.group(1)), m.group(2).lower()) if m else (None, None)


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


def _genres(soup):
    for li in soup.select("#product-primaryinfo li"):
        sp = li.find("span")
        if sp and sp.get_text(strip=True).rstrip(":").lower() == "genre":
            skip = {"box sets", "enhanced cd", "misc product"}
            out = {}
            for a in li.find_all("a"):
                g = a.get_text(strip=True)
                if g and g.lower() not in skip:
                    out.setdefault(g.lower(), g)
            return ",".join(out.values()) or None
    return None


def _val(page, id_):
    m = re.search(rf'<input[^>]*id="{id_}"[^>]*value="([^"]*)"', page)
    return html.unescape(m.group(1)) if m else None


def _description(page: str):
    m = re.search(r'class="aec-desc-review[^"]*"[^>]*>(.*?)</div>', page, re.S)
    return _txt(BeautifulSoup(m.group(1), "lxml")) if m else None


def _abs(u):
    if not u:
        return None
    return u if u.startswith("http") else (
        "https:" + u if u.startswith("//") else config.WEBAMI_BASE_URL.rstrip("/") + "/" + u.lstrip("/"))


def _page_image(page: str):
    full = BeautifulSoup(page, "lxml")
    m = full.select_one('meta[property="og:image"], meta[name="og:image"], link[rel="image_src"]')
    if m and (m.get("content") or m.get("href")):
        return m.get("content") or m.get("href")
    for i in full.select("img"):
        s = i.get("src") or i.get("data-src") or i.get("data-original") or ""
        if s and not re.search(r"logo|icon|sprite|blank|spacer|\.svg", s, re.I) \
                and re.search(r"cover|product|image|upc|\d{8,}", s, re.I):
            return s
    return None


def parse_product(page: str) -> dict:
    head = page.find('class="main-title')
    end = page.find('id="aec-product-description"')
    soup = BeautifulSoup(page[max(head, 0):end if end > 0 else len(page)], "lxml")
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
    
    music = (fmt or "").strip().lower() in ("lp", "cd", "cassette")
    artist = None
    if music:
        for li in soup.select("li"):
            sp = li.find("span")
            if sp and sp.get_text(strip=True).rstrip(":").lower() == "artist":
                a = li.find("a")
                artist = _txt(a) if a else li.get_text(" ", strip=True)[len(sp.get_text(strip=True)):].strip()
                break
        artist = artist or _val(page, "artist")
    wt, wu = _weight(_info(soup, "Weight"))
    return {
        "title": _txt(soup.select_one("h2.title-h2")) or _val(page, "album"),
        "artist": artist,
        "vendor": artist if music else ld.get("brand"),
        "features": _txt(soup.select_one(".aec-main-desc")) or None,
        "product_type": fmt,
        "upc": _info(soup, "UPC") or _val(page, "upc_cd"),
        "sku": _info(soup, "Product ID"),
        "price": None,
        "your_price": None,
        "wmsid": _val(page, "wmsid"),
        "description": _description(page),
        "release_date": _info(soup, "Release Date"),
        "genres": _genres(soup),
        "weight": wt,
        "weight_unit": wu,
        "image_url": _abs(
            (soup.select_one(".main-cover img") or {}).get("src")
            or (ld.get("image") or [None])[0]
            or _page_image(page)),
    }


def parse_search(page: str) -> list[dict]:
    soup = BeautifulSoup(page, "lxml")
    return [{
        "upc": a["href"].strip("/").rsplit("/", 1)[-1],
        "title": _txt(a.select_one(".aec-gstitle")),
        "artist": _txt(a.select_one(".aec-gspersonname")),
        "format": _txt(a.select_one(".aec-gsformat")),
    } for a in soup.select("a.aec-gsitemsearch")]


def find_match(results: list[dict], title: str, artist: str, fmt: str) -> str | None:
    t, a, f = norm(simplify(title)), norm(artist), norm(FORMATS.get(fmt, fmt))
    hits = [r for r in results
            if norm(simplify(r["title"])) == t and norm(r["artist"]) == a
            and (not f or f in norm(r["format"]) or norm(r["format"]) in f)]
    return hits[0]["upc"] if len(hits) == 1 else None  # ambiguous = no match


class WebamiClient:
    def __init__(self, base_url: str, username: str, password: str):
        self.base = base_url.rstrip("/")
        self._user, self._pw = username, password
        self._local = threading.local()
        self.limiter = AdaptiveLimiter(
            config.WEBAMI_WORKERS_START, config.WEBAMI_WORKERS_MIN, config.WEBAMI_WORKERS_MAX)

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
        for _ in range(4):
            with self.limiter:
                try:
                    start = time.monotonic()
                    r = self._session().get(path if path.startswith("http") else f"{self.base}{path}", params=params, timeout=30)
                except requests.Timeout:
                    self.limiter.throttled()
                    continue
            if r.status_code in (429, 503):
                self.limiter.throttled(float(r.headers.get("Retry-After", 0) or 0))
                continue
            if "logon" in r.url.lower():
                self._local.s = None
                continue
            r.raise_for_status()
            self.limiter.success(time.monotonic() - start)
            return r.text
        raise RuntimeError("WebAMI: throttled or session rejected")

    def list_new_orders(self, known: set[str], redo: set[str] = frozenset()) -> list[dict]:
        """Newest-first pages; stops once a page has nothing new."""
        size, page, out = config.WEBAMI_PAGE_SIZE, 1, []
        while True:
            rows = parse_order_list(self._get(
                "/webami/submittedorders", {"Grid-page": page, "Grid-pageSize": size}))
            out += [r for r in rows if r["guid"] not in known or r["guid"] in redo]
            if len(rows) < size:
                return out
            page += 1

    def get_order_items(self, guid: str) -> list[dict]:
        return parse_order_items(self._get(f"/webami/vieworder/{guid}"))

    def fetch_product(self, href: str) -> dict:
        data = parse_product(self._get(href))
        if data.get("upc"):
            try:
                data["price"] = data["your_price"] = self.fetch_price(data["upc"])
            except Exception:
                logger.warning("priceavail failed for %s", data["upc"], exc_info=True)
        return data
    
    def fetch_price(self, upc: str) -> float | None:
        with self.limiter:
            start = time.monotonic()
            r = self._session().post(
                f"{self.base}/ajax/priceavail",
                data={"ids": upc},
                headers={
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-Requested-With": "XMLHttpRequest",
                    "Origin": self.base,
                }, timeout=30)
        if r.status_code in (429, 503):
            self.limiter.throttled(float(r.headers.get("Retry-After", 0) or 0))
            return None
        r.raise_for_status()
        self.limiter.success(time.monotonic() - start)
        data = r.json()
        if data and data[0].get("Price"):
            return _money(str(data[0]["Price"]))
        return None
    
    def search_upc(self, upc: str) -> list[dict]:
        return parse_search(self._get(
            "https://ac.aent-m.com/api/s24ac", {"q": upc, "mod": "AP", "tid": 1}))

    def search_site(self, title: str, artist: str, fmt: str, extra: str = "") -> list[dict]:
        return parse_search(self._get("/search", {
            "mod": "AP", "q": f"{simplify(title)} {artist} {extra}".strip(),
            "ft": FORMATS.get(fmt, fmt)}))