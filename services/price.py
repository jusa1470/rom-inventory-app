"""Price helpers."""


def suggested_price(cost: float, margin: float) -> float:
    """Return price that achieves target gross margin. margin is 0–1 (e.g. 0.34)."""
    if not cost or not margin or margin >= 1:
        return 0.0
    return round(cost / (1.0 - margin), 2)


def actual_margin(cost: float, price: float) -> float:
    if not price or price == 0:
        return 0.0
    return round((price - cost) / price, 4)


def format_price(value: float) -> str:
    return f"{value:.2f}"
