from typing import Literal
from fastapi import APIRouter, Depends, Query
from app import db
from app.auth import require_session

router = APIRouter(prefix="/api/missing", tags=["missing"], dependencies=[Depends(require_session)])


@router.get("")
def missing(kind: Literal["products", "variants"] = "products", q: str | None = None,
            fields: list[str] | None = Query(None), page: int = Query(1, ge=1),
            per_page: int = Query(50, ge=1, le=200)):
    res = db.list_missing(kind, fields or [], q.strip() if q else "", page, per_page)
    return {**res, "page": page, "per_page": per_page}