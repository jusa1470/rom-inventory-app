"""
Optimized Webami scraper

Goals:
- Single HTTP request per product
- Minimal DOM traversal
- Prefer structured data when reliable
- Deterministic + thread-safe
"""

import json
import logging
from typing import Optional

from bs4 import BeautifulSoup, Tag
from bs4.element import AttributeValueList
from requests import Response

import config
from webami.session import authenticated_get, authenticated_post, _worker_tag

logger = logging.getLogger(__name__)

ALLOWED_MUSIC_FORMATS: set[str] = {"lp", "12\" single", "7\" single", "cd", "cassette"}
ALLOWED_ITEM_FORMATS: set[str] = {"headphones", "vinyl accessories", "bags / sleeves", "turntables", "apparel", "media player accessories", "speaker & components"}

# ─────────────────────────────────────────────
# Core helpers
# ─────────────────────────────────────────────

def _get_json_ld(soup: BeautifulSoup) -> dict | None:
    script: Tag | None = soup.select_one("script.ProductPageStrData")
    if not script or not script.string:
        return None
    try:
        return json.loads(script.string)
    except Exception:
        return None

def _get_primaryinfo(soup: BeautifulSoup) -> Tag | None:
    return soup.find(id="product-primaryinfo")

# ─────────────────────────────────────────────
# Field extractors
# ─────────────────────────────────────────────

def get_title(soup: BeautifulSoup, upc: str) -> Optional[str]:
    el: Tag | None = soup.select_one(".aec-main-title h2")
    if el and el.text:
        text = el.text.strip()
        if "[" in text and "]" in text:
            text = text.split("[")[0].strip()
        return text

    logger.warning(f"{_worker_tag()} UPC {upc}: title not found")
    return None

def get_artist(soup: BeautifulSoup, upc: str) -> Optional[str]:
    el: Tag | None = soup.select_one(".aec-main-artist a")
    if el and el.text:
        return el.text.strip()

    logger.debug(f"{_worker_tag()} UPC {upc}: artist not found")
    return None

def get_images(soup: BeautifulSoup, upc: str) -> Optional[list[str]]:
    urls: list[str] = []

    for el in soup.select(".thumb-gallery-container img, .thumb-gallery-container a.chocolat-image"):
        if el.name == "img":
            url: str | AttributeValueList | None = el.get("data-zoom") or el.get("data-zoom-image")
        else:
            url = el.get("href")
        if url:
            urls.append(str(url))

    if not urls:
        main: Tag | None = soup.select_one(".main-cover img")
        if main:
            url = main.get("data-zoom") or main.get("data-zoom-image") or main.get("src")
            if url and "no_image" not in url:
                urls.append(str(url))

    if urls:
        return list(dict.fromkeys(urls))

    logger.debug(f"{_worker_tag()} UPC {upc}: no images found")
    return None

def get_features(soup: BeautifulSoup) -> Optional[list[str]]:
    el: Tag | None = soup.select_one(".aec-main-desc")
    if el and el.text:
        text = el.text.strip().strip("()")
        return [f.strip() for f in text.split(",") if f.strip()]
    return None

def get_format(soup: BeautifulSoup, upc: str) -> Optional[str]:
    el: Tag | None = soup.select_one(".aec-attr")
    if el:
        text_nodes: list[str] = [t.strip() for t in el.find_all(string=True, recursive=False)]
        for t in text_nodes:
            if t:
                return t

    logger.warning(f"{_worker_tag()} UPC {upc}: format not found")
    return None

def get_weight(primary: Tag | None, upc: str) -> Optional[float]:
    if not primary:
        return None

    for li in primary.find_all("li"):
        span: Tag | None = li.find("span")
        if span and "Weight:" in span.text:
            raw = li.text.replace("Weight:", "").strip()
            return _convert_weight_to_grams(raw)

    logger.debug(f"{_worker_tag()} UPC {upc}: weight not found")
    return None

def _convert_weight_to_grams(raw: str) -> Optional[float]:
    try:
        if "lb" in raw:
            return round(float(raw.replace("lbs", "").replace("lb", "").strip()) * 453.592, 2)
        if "kg" in raw:
            return round(float(raw.replace("kg", "").strip()) * 1000, 2)
        if "oz" in raw:
            return round(float(raw.replace("oz", "").strip()) * 28.3495, 2)
        if "g" in raw:
            return float(raw.replace("g", "").strip())
    except Exception:
        return None
    return None

def get_genres(primary: Tag | None) -> Optional[list[str]]:
    if not primary:
        return None

    for li in primary.find_all("li"):
        span: Tag | None = li.find("span")
        if span and "Genre:" in span.text:
            return [a.text.strip() for a in li.find_all("a") if a.text.strip()]

    return None

def get_brand(soup: BeautifulSoup, primary: Tag | None) -> Optional[str]:
    data = _get_json_ld(soup)
    if data and data.get("brand"):
        return data["brand"].strip()

    if primary:
        for li in primary.find_all("li"):
            span: Tag | None = li.find("span")
            if span and "Brand:" in span.text:
                a: Tag | None = li.find("a")
                if a:
                    return a.text.strip()

    return None

def get_cost(upc: str) -> Optional[float]:
    """
    Fetch cost via the fast /ajax/priceavail endpoint.
    Used for price-only syncs where a full page scrape is not needed.
    """
    try:
        resp: Response = authenticated_post(
            f"{config.WEBAMI_BASE_URL}/ajax/priceavail",
            data={"ids": upc},
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": config.WEBAMI_BASE_URL,
            },
        )
        data = resp.json()
        if data and data[0].get("Price"):
            return float(data[0]["Price"].replace("$", "").strip())
    except Exception:
        logger.exception(f"{_worker_tag()} UPC {upc}: failed to retrieve cost from API")
    return None

# ─────────────────────────────────────────────
# Main scraper
# ─────────────────────────────────────────────

def scrape_product_page(upc: str) -> Optional[dict]:
    tag: str = _worker_tag()
    logger.debug(f"{tag} Scraping UPC {upc}")

    try:
        resp: Response = authenticated_get(
            f"{config.WEBAMI_BASE_URL}/{upc}",
            allow_redirects=True,
        )
    except Exception:
        logger.exception(f"{tag} UPC {upc}: request failed")
        return None

    soup = BeautifulSoup(resp.content, "lxml")

    if not soup.select_one(".aec-main-title"):
        logger.error(f"{tag} UPC {upc}: product page not found")
        with open("upcs_not_found.txt", "a") as f:
            f.write(upc + "\n")
        return None

    primary: Tag | None = _get_primaryinfo(soup)
    format: str | None = get_format(soup, upc)

    base = {
        "upc": upc,
        "title": get_title(soup, upc),
        "image_urls": get_images(soup, upc),
        "weight_grams": get_weight(primary, upc),
        "cost": get_cost(upc),
        "format": format,
    }

    if format and format.lower() in ALLOWED_MUSIC_FORMATS:
        base.update({
            "artist": get_artist(soup, upc),
            "features": get_features(soup),
            "genres": get_genres(primary),
        })
        return base

    if format and format.lower() in ALLOWED_ITEM_FORMATS:
        base.update({
            "brand": get_brand(soup, primary),
        })
        return base

    logger.error(f"{tag} UPC {upc}: unknown format {format!r}")
    return None