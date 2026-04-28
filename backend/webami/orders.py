"""
Webami order discovery and parsing.
"""

import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag
from bs4.element import AttributeValueList
from requests import Response

import config
from db.models import WebamiOrder
from webami.session import authenticated_get, _worker_tag

logger: logging.Logger = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────

def _parse_webami_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    dt: datetime = datetime.strptime(value, "%m/%d/%Y %H:%M")
    dt: datetime = dt.replace(tzinfo=ZoneInfo("America/Denver"))
    return dt.astimezone(ZoneInfo("UTC"))

# ── Order list parsing ────────────────────────────────────────────────

def _parse_order_row(tr) -> WebamiOrder | None:
    checkbox = tr.find("input", {"name": "checkedRecords"})
    if not checkbox:
        return None

    guid: str = checkbox.get("value")
    tds = tr.find_all("td")

    order_link = tr.select_one("a.aec-showorder-a")
    order_number = order_link.text.strip() if order_link else None
    order_name = tds[2].get_text(strip=True) if len(tds) > 2 else None
    order_date_raw = tds[4].get_text(strip=True) if len(tds) > 4 else None

    return WebamiOrder(
        guid=guid,
        order_number=order_number,
        order_name=order_name,
        order_date=_parse_webami_datetime(order_date_raw),
        number_of_products=0,  # populated later when order page is parsed
    )

def _parse_orders_from_soup(soup: BeautifulSoup) -> list[WebamiOrder]:
    items_grid: Tag | None = soup.find(id="Grid")
    if not items_grid:
        logger.warning("No orders Grid found")
        return []

    orders = []
    for tr in items_grid.find_all("tr"):
        order: WebamiOrder | None = _parse_order_row(tr)
        if order:
            orders.append(order)

    return orders

def _fetch_orders_page(page: int) -> BeautifulSoup:
    params: dict[str, int] = {} if page == 1 else {"Grid-page": page}
    resp: Response = authenticated_get(
        f"{config.WEBAMI_BASE_URL}/webami/submittedorders",
        params=params,
    )
    return BeautifulSoup(resp.text, "lxml")

# ── Public: Order list ────────────────────────────────────────────────

def get_all_orders() -> list[WebamiOrder]:
    soup: BeautifulSoup = _fetch_orders_page(1)
    orders: list[WebamiOrder] = _parse_orders_from_soup(soup)

    total = 0
    pager: Tag | None = soup.find(class_="k-pager-info")
    if pager:
        m: re.Match[str] | None = re.search(r"of (\d+) items", pager.text)
        if m:
            total = int(m.group(1))

    page_size = 25
    total_pages: int = max(1, (total + page_size - 1) // page_size)
    logger.info(f"Order pages: {total_pages}, total orders: {total}")

    for page in range(2, total_pages + 1):
        before: int = len(orders)
        orders.extend(_parse_orders_from_soup(_fetch_orders_page(page)))
        logger.info(f"Page {page}: {len(orders)}/{total}")
        if len(orders) == before:
            break

    return orders

def get_recent_orders(max_pages: int = -1) -> list[WebamiOrder]:
    if max_pages <= 0:
        max_pages = config.WEBAMI_ORDERS_INCREMENTAL_PAGES

    orders: list[WebamiOrder] = []
    for page in range(1, max_pages + 1):
        orders.extend(_parse_orders_from_soup(_fetch_orders_page(page)))

    return orders

# ── Public: Order detail ──────────────────────────────────────────────

def parse_order_page(guid: str) -> list[dict]:
    """
    Fetch a single order page and return its items as {upc, quantity} dicts.
    UPC is parsed from the product link href — more reliable than text parsing.
    """
    resp: Response = authenticated_get(f"{config.WEBAMI_BASE_URL}/webami/vieworder/{guid}")
    soup = BeautifulSoup(resp.text, "lxml")

    items = []
    items_grid: Tag | None = soup.find(id="ItemsGrid")
    if not items_grid:
        logger.warning(f"Order {guid}: no ItemsGrid found")
        return items

    for tr in items_grid.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue

        link: Tag | None = tds[0].select_one("b a")
        if not link:
            continue

        href: str | AttributeValueList | None = link.get("href")
        if not href or not isinstance(href, str):
            continue
        upc: str = href.rstrip("/").split("/")[-1]
        if not upc:
            continue

        try:
            quantity = int(tds[1].get_text(strip=True))
        except ValueError:
            continue

        if quantity > 0:
            items.append({
                "upc": upc,
                "quantity": quantity,
                "title": link.text.strip(),
                "format": tds[4].get_text(strip=True),
                "cost": float(tds[5].get_text(strip=True).replace("$", "").strip()),
            })

    return items

def parse_order_page_worker(guid: str) -> tuple[str, list[dict]]:
    """Worker-safe wrapper — returns (guid, items) for use with ThreadPoolExecutor."""
    tag: str = _worker_tag()
    logger.debug(f"{tag} Fetching order {guid}")
    items = parse_order_page(guid)
    logger.debug(f"{tag} Order {guid}: {len(items)} item(s)")
    return guid, items