import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def safe_get(d: Any, *keys: str, default: Any = None) -> Any:
    current = d

    for k in keys:
        if not isinstance(current, dict):
            return default
        try:
            current = current[k]
        except (KeyError, TypeError):
            return default

    return current if current is not None else default


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception as e:
        logger.warning(f"Invalid datetime: {value} ({e})")
        return None


def safe_float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default