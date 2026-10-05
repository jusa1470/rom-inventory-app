"""
Webami product scraper.
Adapted from the user's existing scraper with the same public API.
All DB calls go through db.database; session through webami.session.
"""

import json
import logging
import re
from typing import Optional

from bs4 import BeautifulSoup, Tag
from requests import Response

import config
import db.database as db
from webami.session import authenticated_get, authenticated_post, _worker_tag

logger = logging.getLogger(__name__)

ALLOWED_MUSIC_FORMATS: set[str] = {"lp", "12\" single", "7\" single", "cd", "cassette"}
ALLOWED_ITEM_FORMATS: set[str] = {
    "headphones", "vinyl accessories", "bags / sleeves",
    "turntables", "apparel", "media player accessories", "speaker & components",
}

_SEARCH_THRESHOLD = 0.68

_LP_FAMILY  = {'lp', 'lp vinyl', 'vinyl', '12" single', '12" vinyl', '12" lp', '7" single', '7" vinyl', '7" lp', 'lp album', 'album', 'lp/ep'}
_CD_FAMILY  = {'cd', 'compact disc', 'cd album'}
_CAS_FAMILY = {'cassette', 'cassette tape', 'tape'}
_7_FAMILY   = {'7" single', '7"', '7 inch', '7" ep'}
_12_FAMILY  = {'12" single', '12"', '12 inch'}

_PAREN_RE = re.compile(r'\s*\([^)]*\)\s*')


def _title_variants(title: str) -> list[str]:
    variants = [title]
    stripped = _PAREN_RE.sub(' ', title).strip()
    if stripped and stripped != title:
        variants.append(stripped)
    return variants

def _fmt_family(fmt: str) -> Optional[str]:
    f = fmt.lower().strip()
    if f in _LP_FAMILY:  return 'lp'
    if f in _CD_FAMILY:  return 'cd'
    if f in _CAS_FAMILY: return 'cassette'
    if f in _7_FAMILY:   return 'lp'
    if f in _12_FAMILY:  return 'lp'
    return None

def _formats_match(a: str, b: str) -> bool:
    if not a or not b: return True
    fa, fb = _fmt_family(a), _fmt_family(b)
    if fa is None or fb is None: return True   # unknown — don't filter
    return fa == fb


# ─────────────────────────────────────────────
# Core helpers
# ─────────────────────────────────────────────

def _get_primaryinfo(soup: BeautifulSoup) -> Optional[Tag]:
    return soup.find(id="product-primaryinfo")


# ─────────────────────────────────────────────
# Field extractors
# ─────────────────────────────────────────────

def get_title(soup: BeautifulSoup, upc: str) -> Optional[str]:
    el = soup.select_one(".aec-main-title h2")
    if el and el.text:
        text = el.text.strip()
        if "[" in text and "]" in text:
            text = text.split("[")[0].strip()
        return text
    logger.warning(f"{_worker_tag()} UPC {upc}: title not found")
    return None


def get_artist(soup: BeautifulSoup, upc: str) -> Optional[str]:
    el = soup.select_one(".aec-main-artist a")
    if el and el.text:
        return el.text.strip()
    logger.debug(f"{_worker_tag()} UPC {upc}: artist not found")
    return None


def get_images(soup: BeautifulSoup, upc: str) -> Optional[list[str]]:
    urls: list[str] = []
    for el in soup.select(".thumb-gallery-container img, .thumb-gallery-container a.chocolat-image"):
        url = (el.get("data-zoom") or el.get("data-zoom-image")) if el.name == "img" else el.get("href")
        if url:
            urls.append(str(url))
    if not urls:
        main = soup.select_one(".main-cover img")
        if main:
            url = main.get("data-zoom") or main.get("data-zoom-image") or main.get("src")
            if url and "no_image" not in url:
                urls.append(str(url))
    if urls:
        return list(dict.fromkeys(urls))
    logger.debug(f"{_worker_tag()} UPC {upc}: no images found")
    return None


def get_features(soup: BeautifulSoup) -> Optional[list[str]]:
    el = soup.select_one(".aec-main-desc")
    if el and el.text:
        text = el.text.strip().strip("()")
        return [f.strip() for f in text.split(",") if f.strip()]
    return None


def get_format(soup: BeautifulSoup, upc: str) -> Optional[str]:
    el = soup.select_one(".aec-attr")
    if el:
        text_nodes = [t.strip() for t in el.find_all(string=True, recursive=False)]
        for t in text_nodes:
            if t:
                return t
    logger.warning(f"{_worker_tag()} UPC {upc}: format not found")
    return None


def get_weight(primary: Optional[Tag], upc: str) -> Optional[float]:
    if not primary:
        return None
    for li in primary.find_all("li"):
        span = li.find("span")
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


def get_genres(primary: Optional[Tag]) -> Optional[list[str]]:
    if not primary:
        return None
    for li in primary.find_all("li"):
        span = li.find("span")
        if span and "Genre:" in span.text:
            return [a.text.strip() for a in li.find_all("a") if a.text.strip()]
    return None


def get_brand(soup: BeautifulSoup, primary: Optional[Tag]) -> Optional[str]:
    script = soup.select_one("script.ProductPageStrData")
    if script and script.string:
        try:
            data = json.loads(script.string)
            if data.get("brand"):
                return data["brand"].strip()
        except Exception:
            pass
    if primary:
        for li in primary.find_all("li"):
            span = li.find("span")
            if span and "Brand:" in span.text:
                a = li.find("a")
                if a:
                    return a.text.strip()
    return None


# ─────────────────────────────────────────────
# UPC search fallback
# ─────────────────────────────────────────────

def search_for_replacement_upc(upc: str, title: Optional[str], artist: Optional[str],
                                fmt: Optional[str] = None) -> Optional[str]:
    from services.matcher import similarity
    tag = _worker_tag()
    try:
        resp: Response = authenticated_get(
            "https://ac.aent-m.com/api/s24ac",
            params={"q": upc, "mod": "AP", "tid": "1"},
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        candidates = soup.select("a.aec-gsitemsearch")
        if not candidates:
            logger.warning(f"{tag} UPC {upc}: no search results")
            return None

        best_score, best_upc = 0.0, None

        for a in candidates:
            result_title  = (a.select_one(".aec-gstitle")      or a).get_text(strip=True)
            result_artist = (a.select_one(".aec-gspersonname") or a).get_text(strip=True)
            result_fmt    = (a.select_one(".aec-gsformat")     or a).get_text(strip=True)
            href    = a.get("href", "")
            new_upc = href.strip("/").split("/")[-1]
            if not new_upc or not new_upc.isdigit() or new_upc == upc:
                continue

            if fmt and not _formats_match(fmt, result_fmt):
                logger.debug(f"{tag} skip {new_upc}: format mismatch ({fmt!r} vs {result_fmt!r})")
                continue

            title_score  = max((similarity(t, result_title) for t in _title_variants(title)), default=0.0) if title else 0.0
            artist_score = similarity(artist or "", result_artist) if artist else 0.0

            if title and artist:
                score = title_score * 0.6 + artist_score * 0.4
            elif title:
                score = title_score
            else:
                score = artist_score

            logger.debug(f"{tag} candidate {new_upc}: '{result_title}' / '{result_artist}' / '{result_fmt}' → {score:.2f}")

            if score > best_score:
                best_score = score
                best_upc   = new_upc

        if best_upc and best_score >= _SEARCH_THRESHOLD:
            logger.info(f"{tag} UPC {upc}: replacement → {best_upc!r} (score {best_score:.2f})")
            return best_upc

        logger.warning(f"{tag} UPC {upc}: no candidate met threshold (best {best_score:.2f})")
    except Exception:
        logger.exception(f"{tag} UPC {upc}: search fallback failed")
    return None


# ─────────────────────────────────────────────
# Cost API
# ─────────────────────────────────────────────

def get_cost(upc: str) -> Optional[float]:
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
        logger.exception(f"{_worker_tag()} UPC {upc}: cost fetch failed")
    return None


# ─────────────────────────────────────────────
# Main scraper entry point
# ─────────────────────────────────────────────

def _fetch_product_page(upc: str) -> Optional[BeautifulSoup]:
    tag = _worker_tag()
    try:
        resp: Response = authenticated_get(
            f"{config.WEBAMI_BASE_URL}/{upc}",
            allow_redirects=True,
        )
    except Exception:
        logger.exception(f"{tag} UPC {upc}: request failed")
        return None
    soup = BeautifulSoup(resp.content, "html.parser")
    return soup if soup.select_one(".aec-main-title") else None


def scrape_product(upc: str, title: Optional[str] = None, artist: Optional[str] = None,
                   fmt: Optional[str] = None) -> Optional[dict]:
    """
    Scrape a Webami product page, store it in the DB, and return the data dict.
    Handles retired UPCs automatically via the alias table.
    """
    tag = _worker_tag()
    logger.debug(f"{tag} Scraping UPC {upc}")

    soup = _fetch_product_page(upc)

    if soup is None or (fmt and not _formats_match(fmt, get_format(soup, upc))):
        logger.warning(f"{tag} UPC {upc}: page not found, trying search fallback")
        replacement_upc = search_for_replacement_upc(upc, title, artist, fmt=fmt)

        if not replacement_upc and upc.startswith("0") and len(upc) > 1:
            stripped_upc = upc.lstrip("0")
            logger.info(f"{tag} UPC {upc}: retrying without leading zero → {stripped_upc}")
            stripped_soup = _fetch_product_page(stripped_upc)
            if stripped_soup is not None and (not fmt or _formats_match(fmt, get_format(stripped_soup, stripped_upc))):
                db.upsert_product_alias(upc, stripped_upc)
                logger.info(f"{tag} UPC {upc}: alias created → {stripped_upc}")
                soup = stripped_soup
                upc = stripped_upc
            else:
                replacement_upc = search_for_replacement_upc(stripped_upc, title, artist, fmt=fmt)
                if replacement_upc:
                    db.upsert_product_alias(upc, replacement_upc)
                    logger.info(f"{tag} UPC {upc}: alias created → {replacement_upc}")
                    soup = _fetch_product_page(replacement_upc)
                    upc = replacement_upc

        if soup is None or (fmt and not _formats_match(fmt, get_format(soup, upc))):
            if not replacement_upc:
                logger.error(f"{tag} UPC {upc}: no replacement found")
                return None

            soup = _fetch_product_page(replacement_upc)
            if soup is None:
                logger.error(f"{tag} UPC {upc}: replacement {replacement_upc} also not found")
                return None

            db.upsert_product_alias(upc, replacement_upc)
            logger.info(f"{tag} UPC {upc}: alias created → {replacement_upc}")
            upc = replacement_upc

    primary = _get_primaryinfo(soup)
    fmt = get_format(soup, upc)

    product: dict = {
        "upc":          upc,
        "title":        get_title(soup, upc),
        "image_urls":   get_images(soup, upc),
        "weight_grams": get_weight(primary, upc),
        "cost":         get_cost(upc),
        "format":       fmt,
    }

    if fmt and fmt.lower() in ALLOWED_MUSIC_FORMATS:
        product.update({
            "artist":   get_artist(soup, upc),
            "features": get_features(soup),
            "genres":   get_genres(primary),
        })
    elif fmt and fmt.lower() in ALLOWED_ITEM_FORMATS:
        product["brand"] = get_brand(soup, primary)
    else:
        logger.error(f"{tag} UPC {upc}: unknown format {fmt!r}")
        return None

    db.upsert_webami_product(product)
    return product
