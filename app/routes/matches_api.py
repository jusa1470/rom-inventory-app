from fastapi import APIRouter, Depends, Query

from app import db
from app.auth import require_session

router = APIRouter(
    prefix="/api/matches", tags=["matches"], dependencies=[Depends(require_session)]
)


@router.get("")
def list_matches(q: str | None = None, page: int = Query(1, ge=1),
                 per_page: int = Query(25, ge=1, le=100), only_suggested: bool = False):
    res = db.list_unmatched_variants(page, per_page, q.strip() if q else "", only_suggested)
    return {**res, "page": page, "per_page": per_page}


@router.post("/{product_id}/ignore")
def ignore(product_id: str):
    db.ignore_product(product_id)
    return {"ok": True}