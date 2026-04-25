"""
Webami order discovery and parsing.
"""

import logging
import re
import threading
from typing import Optional
from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

import config
from db.models import WebamiOrder
from webami.session import authenticated_get

logger = logging.getLogger(__name__)


def parse_webami_datetime(value: str | None):
    if not value:
        return None
    dt = datetime.strptime(value, "%m/%d/%Y %H:%M")
    dt = dt.replace(tzinfo=ZoneInfo("America/Denver"))
    return dt.astimezone(ZoneInfo("UTC"))


def parse_order_row(tr) -> WebamiOrder | None:
    checkbox = tr.find("input", {"name": "checkedRecords"})
    if not checkbox:
        return None

    guid = checkbox.get("value")
    tds = tr.find_all("td")

    order_link = tr.select_one("a.aec-showorder-a")
    order_number = order_link.text.strip() if order_link else None

    order_name = tds[2].get_text(strip=True) if len(tds) > 2 else None

    order_date_raw = tds[4].get_text(strip=True) if len(tds) > 4 else None
    order_date = parse_webami_datetime(order_date_raw)

    return WebamiOrder(
        guid=guid,
        order_number=order_number,
        order_name=order_name,
        order_date=order_date,
    )


def parse_orders_from_soup(soup: BeautifulSoup) -> list[WebamiOrder]:
    items_grid = soup.find(id="Grid")
    if not items_grid:
        logger.warning("No orders Grid found")
        return []

    orders = []
    for tr in items_grid.find_all("tr"):
        order = parse_order_row(tr)
        if order:
            orders.append(order)

    return orders


def get_all_orders() -> list[WebamiOrder]:
    orders: list[WebamiOrder] = []

    resp = authenticated_get(f"{config.WEBAMI_BASE_URL}/webami/submittedorders")
    soup = BeautifulSoup(resp.text, "html.parser")

    orders.extend(parse_orders_from_soup(soup))

    # pagination
    total = 0
    pager = soup.find(class_="k-pager-info")
    if pager:
        m = re.search(r"of (\d+) items", pager.text)
        if m:
            total = int(m.group(1))

    page_size = 25
    total_pages = max(1, (total + page_size - 1) // page_size)

    logger.info(f"Order pages: {total_pages}, total orders: {total}")

    for page in range(2, total_pages + 1):
        resp = authenticated_get(
            f"{config.WEBAMI_BASE_URL}/webami/submittedorders",
            params={"Grid-page": page},
        )
        soup = BeautifulSoup(resp.text, "html.parser")

        before = len(orders)
        orders.extend(parse_orders_from_soup(soup))

        logger.info(f"Page {page}: {len(orders)}/{total}")

        if len(orders) == before:
            break

    return orders


def get_recent_orders(max_pages: int = -1) -> list[WebamiOrder]:
    if max_pages <= 0:
        max_pages = config.WEBAMI_ORDERS_INCREMENTAL_PAGES

    orders: list[WebamiOrder] = []

    for page in range(1, max_pages + 1):
        params = {} if page == 1 else {"Grid-page": page}

        resp = authenticated_get(
            f"{config.WEBAMI_BASE_URL}/webami/submittedorders",
            params=params,
        )
        soup = BeautifulSoup(resp.text, "html.parser")

        orders.extend(parse_orders_from_soup(soup))

    return orders


def parse_order_page(guid: str) -> list[str]:
    """
    Fetch and parse a single order page.
    Returns (upcs, order_date) where upcs = [str].
    """
    resp = authenticated_get(f"{config.WEBAMI_BASE_URL}/webami/vieworder/{guid}")
    soup = BeautifulSoup(resp.text, "html.parser")

    upcs: list[str] = []
    items_grid = soup.find(id="ItemsGrid")
    if not items_grid:
        logger.warning(f"Order {guid}: no ItemsGrid found")
        return upcs

    for tr in items_grid.find_all("tr"):
        tds = tr.find_all("td")
        if not tds or len(tds) < 5:
            continue
        item_td = tds[0]
        if not item_td.find("b"):
            continue

        lines = [
            line.strip()
            for line in item_td.get_text(separator="\n").split("\n")
            if line.strip()
        ]
        upc = ""
        if len(lines) > 2 and "/" in lines[2]:
            upc = lines[2].split("/")[-1].strip()

        if upc:
            upcs.append(upc)

    return upcs


def parse_order_page_worker(guid: str) -> tuple[str, list[str]]:
    """
    Worker-safe wrapper around parse_order_page.
    Returns (guid, upcs, order_date) so the caller knows which guid
    each future result belongs to. Logs include the thread name.
    """
    name = threading.current_thread().name
    tag  = f"[W{name.rsplit('_',1)[-1]}]" if "_" in name else f"[{name}]"
    logger.debug(f"{tag} Fetching order {guid}")
    upcs = parse_order_page(guid)
    logger.info(f"{tag} Order {guid}: {len(upcs)} item(s)")
    return guid, upcs