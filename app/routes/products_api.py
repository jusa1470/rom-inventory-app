from fastapi import APIRouter, Depends, HTTPException

from app import db
from app.auth import require_session


router = APIRouter(
    prefix="/api/products", tags=["products"], dependencies=[Depends(require_session)]
)


@router.get("")
def list_products(q: str | None = None, page: int = 1, per_page: int | None = None):
    if page < 1:
        page = 1
    per_page = per_page or db.get_config().get("page_size", 100)
    if per_page < 1:
        per_page = 1
    elif per_page > 200:
        per_page = 200
    
    result = db.list_products(q.strip() if q else None, page, per_page)
    return {
        "items": result["items"],
        "total": result["total"],
        "page": page,
        "per_page": per_page,
    }


@router.get("/{product_id}")
def get_product_detail(product_id: str):
    product = db.get_product_detail(product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    return product