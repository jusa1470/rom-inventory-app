from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app import db
from app.auth import require_session

router = APIRouter(
    prefix="/api/products", tags=["products"], dependencies=[Depends(require_session)]
)


@router.get("")
def list_products(
    q: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int | None = Query(None, ge=1, le=200),
    sort: str = "title",
    direction: Literal["asc", "desc"] = Query("asc", alias="dir"),
    title: str | None = None,
    vendor: str | None = None,
    status: list[str] | None = Query(None),
    category: list[str] | None = Query(None),
    product_type: list[str] | None = Query(None, alias="type"),
    genres: list[str] | None = Query(None),
    tags: list[str] | None = Query(None),
):
    per_page = per_page or db.get_config().get("page_size", 100)
    candidates = {
        "title": [title.strip()] if title and title.strip() else None,
        "vendor": [vendor.strip()] if vendor and vendor.strip() else None,
        "status": status,
        "category": category,
        "type": product_type,
        "genres": genres,
        "tags": tags,
    }
    filters = {k: v for k, v in candidates.items() if v}
    result = db.list_products(
        q.strip() if q else "", page, per_page, sort, direction, filters
    )
    return {
        "items": result["items"],
        "total": result["total"],
        "page": page,
        "per_page": per_page,
    }


@router.get("/filter-options")
def filter_options():
    return db.get_filter_options()


@router.get("/{product_id}")
def get_product_detail(product_id: str):
    product = db.get_product_detail(product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    return product
