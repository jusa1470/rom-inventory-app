"""
Parse Webami HTML pages into structured dicts.

parse_orders_list(html)  → list of order headers from /webami/submittedorders
parse_order_detail(html) → order with full item list from /webami/vieworder/{guid}

Also provides scrape_* helpers that hit the live site via the authenticated session.
"""

import logging
import re
from typing import Optional

from bs4 import BeautifulSoup, Tag

import config
from webami.session import authenticated_get

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Orders list  (/webami/submittedorders)
# ─────────────────────────────────────────────

def parse_orders_list(html: str) -> list[dict]:
    """
    Returns list of:
      { guid, order_number, order_name, order_date, num_skus }
    """
    soup   = BeautifulSoup(html, "html.parser")
    orders = []

    for row in soup.select("tbody tr"):
        cells = row.find_all("td")
        if not cells:
            continue

        checkbox = row.find("input", {"name": "checkedRecords"})
        guid     = str(checkbox["value"]) if checkbox else None

        link         = row.find("a", class_="aec-showorder-a")
        order_number = link.get_text(strip=True) if link else None

        hidden = row.find_all("td", class_="aec-col-hidden")
        order_name = hidden[0].get_text(strip=True) if hidden else None
        order_name = order_name if order_name and order_name.strip() != "\xa0" else None

        # Visible cells (excluding hidden): checkbox | order_number | date | #skus
        visible = [c for c in cells if "aec-col-hidden" not in c.get("class", [])]
        order_date = visible[2].get_text(strip=True) if len(visible) > 2 else None
        num_skus_raw = visible[3].get_text(strip=True) if len(visible) > 3 else "0"
        try:
            num_skus = int(num_skus_raw)
        except ValueError:
            num_skus = 0

        if guid and order_number:
            orders.append({
                "guid":         guid,
                "order_number": order_number,
                "order_name":   order_name or "",
                "order_date":   order_date,
                "num_skus":     num_skus,
            })

    return orders


# ─────────────────────────────────────────────
# Order detail  (/webami/vieworder/{guid})
# ─────────────────────────────────────────────

def parse_order_detail(html: str) -> dict:
    """
    Returns:
      {
        order_number, order_date,
        invoice_number, ship_date, tracking,
        items: [ { title, artist, webami_upc, format,
                   unit_cost, total_cost,
                   quantity_ordered, quantity_in_stock, quantity_backordered } ]
      }
    """
    soup = BeautifulSoup(html, "html.parser")

    # ── Header ──────────────────────────────
    h1 = soup.find("h1")
    order_number = None
    if h1:
        text = h1.get_text(strip=True)
        order_number = text.replace("WebAMI Submitted Order", "").strip() or None

    order_date = None
    for li in soup.select("ul li"):
        if "Order Submitted:" in li.text:
            order_date = li.get_text(strip=True).replace("Order Submitted:", "").strip()
            break

    # ── Invoice block ────────────────────────
    invoice_number = None
    ship_date      = None
    tracking       = None
    invoice_grid   = soup.find(id="InvoiceGrid")
    if invoice_grid:
        rows = invoice_grid.select("tbody tr")
        if rows:
            cells = rows[0].find_all("td")
            if cells:
                # Invoice cell may have a PDF link - strip it
                inv_cell = cells[0]
                for tag in inv_cell.find_all(["a", "img"]):
                    tag.decompose()
                invoice_number = inv_cell.get_text(strip=True) or None
            if len(cells) > 1:
                ship_date = cells[1].get_text(strip=True) or None
            if len(cells) > 3:
                a = cells[3].find("a")
                tracking = a.get_text(strip=True) if a else cells[3].get_text(strip=True) or None

    # ── Items ────────────────────────────────
    items      = []
    items_grid = soup.find(id="ItemsGrid")
    if items_grid:
        for row in items_grid.select("tbody tr"):
            cells = row.find_all("td")
            if len(cells) < 7:
                continue

            title, artist, upc = _parse_item_cell(cells[0])
            format = cells[4].get_text(strip=True)
            if format.lower() in ("lp", "cd", "cassette") and artist is None:
                artist = title

            items.append({
                "title":                title,
                "artist":               artist,
                "webami_upc":           upc,
                "quantity_ordered":     _int(cells[1].get_text(strip=True)),
                "quantity_in_stock":    _int(cells[2].get_text(strip=True)),
                "quantity_backordered": _int(cells[3].get_text(strip=True)),
                "format":               cells[4].get_text(strip=True),
                "unit_cost":            _price(cells[5].get_text(strip=True)),
                "total_cost":           _price(cells[6].get_text(strip=True)),
            })

    return {
        "order_number":   order_number,
        "order_date":     order_date,
        "invoice_number": invoice_number,
        "ship_date":      ship_date,
        "tracking":       tracking,
        "items":          items,
    }


def _parse_item_cell(cell: Tag) -> tuple[str, Optional[str], Optional[str]]:
    """
    Cell structure:
      <b><a href="/slug/UPC">Title</a></b><br>
      &nbsp;&nbsp;Artist<br>           ← may be blank for accessories
      &nbsp;&nbsp;SKU/UPC
    Returns (title, artist_or_None, upc_or_None)
    """
    b    = cell.find("b")
    a    = b.find("a") if b else None
    title = a.get_text(strip=True) if a else cell.get_text(strip=True)
    href  = (a.get("href") or "") if a else ""

    # Collect text segments separated by <br> tags, ignoring <b>
    segments: list[str] = []
    buf: list[str]      = []
    for child in cell.children:
        if getattr(child, "name", None) == "b":
            continue
        if getattr(child, "name", None) == "br":
            text = "".join(buf).replace("\xa0", "").strip()
            if text:
                segments.append(text)
            buf = []
        else:
            buf.append(str(child))
    leftover = "".join(buf).replace("\xa0", "").strip()
    if leftover:
        segments.append(leftover)

    # For music: segments = ["Noah Kahan", "MRY143908.1/60245594816"]
    # For accessories: segments = ["ADT13869/04200513869"]   (empty artist line got stripped)
    # Distinguish: SKU/UPC line always contains a '/' or is all-numeric
    if segments and ("/" in segments[0] or segments[0].isdigit()):
        artist  = None
        sku_upc = segments[0]
    else:
        artist  = segments[0] if segments else None
        sku_upc = segments[1] if len(segments) > 1 else None

    # UPC: prefer the numeric portion after "/" in the SKU line
    upc = None
    if sku_upc and "/" in sku_upc:
        candidate = sku_upc.split("/")[-1].strip()
        if re.fullmatch(r"\d{8,14}", candidate):
            upc = candidate

    # Fallback: last segment of href
    if not upc and href:
        candidate = href.strip("/").split("/")[-1]
        if re.fullmatch(r"\d{8,14}", candidate):
            upc = candidate

    return (
        title,
        artist if artist and artist.replace("\xa0", "").strip() else None,
        upc,
    )


def _int(v: str) -> int:
    try:
        return int(v)
    except (ValueError, TypeError):
        return 0


def _price(v: str) -> Optional[float]:
    try:
        return float(v.replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return None


# ─────────────────────────────────────────────
# Live-scrape helpers (use authenticated session)
# ─────────────────────────────────────────────

def scrape_orders_list_page(page: int = 1) -> list[dict]:
    base = config.WEBAMI_BASE_URL
    url  = f"{base}/webami/submittedorders"
    if page > 1:
        url += f"?Grid-page={page}"
    resp = authenticated_get(url)
    resp.raise_for_status()
    return parse_orders_list(resp.text)


def scrape_order_detail(guid: str) -> dict:
    base = config.WEBAMI_BASE_URL
    resp = authenticated_get(f"{base}/webami/vieworder/{guid}")
    resp.raise_for_status()
    return parse_order_detail(resp.text)


def scrape_all_orders(job_id: str = None) -> list[dict]:
    """
    Scrape every page of /webami/submittedorders and return all order headers.
    Updates job progress if job_id provided.
    """
    from services import jobs

    all_orders: list[dict] = []
    page = 1
    while True:
        logger.info(f"Scraping orders list page {page}")
        orders = scrape_orders_list_page(page)
        if not orders:
            break
        all_orders.extend(orders)
        if job_id:
            jobs.update(job_id, message=f"Found {len(all_orders)} orders (page {page})…")

        # Check if there's a next page by trying page+1 (simple approach)
        # The HTML has a pager - we'll keep going until we get no new orders
        page += 1
        if page > 50:   # safety cap
            break
        try:
            next_page = scrape_orders_list_page(page)
            if not next_page:
                break
        except Exception:
            break

    return all_orders
