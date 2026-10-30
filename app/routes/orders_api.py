from fastapi import APIRouter, Depends, HTTPException, Query

from app import db
from app.auth import require_session

router = APIRouter(
    prefix="/api/orders", tags=["orders"], dependencies=[Depends(require_session)]
)


@router.get("")
def list_orders(
    q: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    res = db.list_webami_orders(q.strip() if q else "", page, per_page)
    return {**res, "page": page, "per_page": per_page}


@router.get("/{guid}")
def get_order(guid: str):
    order = db.get_webami_order(guid)
    if not order:
        raise HTTPException(404, "Order not found")
    return order


@router.get("/products/{product_id}")
def get_product(product_id: int):
    p = db.get_webami_product(product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    return p