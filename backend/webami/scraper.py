"""
Webami page scrapers.
 
All log lines are prefixed with a worker tag (e.g. [W2]) via
session._worker_tag() so you can see exactly which thread each
request came from in the terminal output.
 
scrape_product_page() fetches the product page AND the cost in a
single worker call, keeping both requests on the same thread and
eliminating inter-thread coordination overhead.
"""

import logging
from typing import Optional

from bs4 import BeautifulSoup

import config as config
from webami.session import authenticated_get, authenticated_post, _worker_tag

logger = logging.getLogger(__name__)

ALLOWED_FORMATS = {"lp", "12\" single", "7\" single", "cd", "cassette"}


# ── Field scrapers (accept pre-parsed soup) ──────────────────────────

def get_album(soup: BeautifulSoup, upc: str) -> Optional[str]:
    elem = soup.find(class_="aec-main-title")
    if elem:
        h2 = elem.find("h2")
        if h2:
            text = h2.text.strip()
            if "[" in text and "]" in text:
                text = text.split("[")[0].strip()
            return text
    logger.warning(f"{_worker_tag()} UPC {upc}: album name not found")
    return None


def get_artist(soup: BeautifulSoup, upc: str) -> Optional[str]:
    elem = soup.find(class_="aec-main-artist")
    if elem:
        a = elem.find("a")
        if a:
            return a.text.strip()
    logger.warning(f"{_worker_tag()} UPC {upc}: artist not found")
    return None


def get_images(soup: BeautifulSoup, upc: str) -> Optional[list[str]]:
    image_urls = []

    thumb_container = soup.select_one(".thumb-gallery-container")
    if thumb_container:
        for el in thumb_container.find_all(["img", "a"]):
            url = None
            if el.name == "img":
                url = el.get("data-zoom") or el.get("data-zoom-image")
            elif el.name == "a" and "chocolat-image" in (el.get("class") or []):
                url = el.get("href")
            if url:
                image_urls.append(url)
    else:
        main_img = soup.select_one(".main-cover img")
        if main_img:
            url = (
                main_img.get("data-zoom")
                or main_img.get("data-zoom-image")
                or main_img.get("src")
            )
            if url and "no_image" not in url:
                image_urls.append(url)

    if image_urls:
        return list(dict.fromkeys(image_urls))
    logger.warning(f"{_worker_tag()} UPC {upc}: no images found")
    return None


def get_features(soup: BeautifulSoup, upc: str) -> Optional[list[str]]:
    features = soup.find(class_="aec-title-featurelist aec-main-desc")
    if features:
        # remove outer ()
        features = features.text.strip()
        if features.startswith("(") and features.endswith(")"):
            features = features[1:-1]
        return [f.strip() for f in features.split(",") if f.strip()]
    logger.debug(f"{_worker_tag()} UPC {upc}: no features found")
    return None


def get_format(soup: BeautifulSoup, upc: str) -> Optional[str]:
    for li in soup.find_all(class_="aec-title-featurelist"):
        span = li.find("span")
        if span and span.text.strip() == "Format:":
            return li.text.replace("Format:", "").strip()
    logger.warning(f"{_worker_tag()} UPC {upc}: format not found")
    return None


def get_weight(soup: BeautifulSoup, upc: str) -> Optional[float]:
    primaryinfo = soup.find(id="product-primaryinfo")
    if primaryinfo:
        for item in primaryinfo.find_all("li"):
            span = item.find("span")
            if span and "Weight:" in span.text:
                raw = item.text.replace("Weight:", "").strip()
                grams = _convert_weight_to_grams(raw)
                if grams is not None:
                    return grams
                logger.warning(f"{_worker_tag()} UPC {upc}: unexpected weight format: {raw!r}")
                return None
    logger.warning(f"{_worker_tag()} UPC {upc}: weight not found")
    return None


def _convert_weight_to_grams(raw: str) -> Optional[float]:
    try:
        if "lbs" in raw or "lb" in raw:
            return round(float(raw.replace("lbs", "").replace("lb", "").strip()) * 453.592, 2)
        elif "kg" in raw:
            return round(float(raw.replace("kg", "").strip()) * 1000, 2)
        elif "oz" in raw:
            return round(float(raw.replace("oz", "").strip()) * 28.3495, 2)
        elif "g" in raw:
            return float(raw.replace("g", "").strip())
    except ValueError:
        pass
    return None


# ── HTTP-level scrapers ──────────────────────────────────────────────

def get_cost(upc: str) -> Optional[float]:
    """Hits the fast JSON price endpoint — no full page parse needed."""
    try:
        resp = authenticated_post(
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
        logger.exception(f"{_worker_tag()} UPC {upc}: failed to retrieve cost")
    return None


def scrape_product_page(upc: str):
    """
    Fetch the product detail page AND the price in a single worker call.
    Both HTTP requests run on the same thread using that thread's session,
    so all WEBAMI_SCRAPE_WORKERS workers are fully utilised concurrently.
 
    Logs include [WN] worker tag so you can confirm parallelism in the terminal.
    """

    tag = _worker_tag()
    logger.debug(f"{tag} Scraping UPC {upc}")

    try:
        resp = authenticated_get(
            f"{config.WEBAMI_BASE_URL}/{upc}",
            allow_redirects=True,
        )
    except Exception:
        logger.exception(f"{tag} UPC {upc}: request failed")
        return None

    soup = BeautifulSoup(resp.content, "html.parser")

    if not soup.find(class_="aec-main-title"):
        logger.error(f"{tag} UPC {upc}: product page not found")
        return None
    
    format = get_format(soup, upc)
    if format and format.lower() not in ALLOWED_FORMATS:
        print(format, format.lower())
        logger.error(f"{tag} UPC {upc}: unrecognized format: {format!r}")
        return None

    return {
        "upc": upc,
        "album": get_album(soup, upc),
        "artist": get_artist(soup, upc),
        "image_urls": get_images(soup, upc),
        "features": get_features(soup, upc),
        "weight_grams": get_weight(soup, upc),
        "cost": get_cost(upc),
        "format": format
    }