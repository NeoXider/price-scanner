"""Детектор аномальных цен.

Два независимых правила (порог каждого настраивается):

1. `below_median` — цена <= 20% медианы своей категории.
2. `price_drop`  — падение >= 80% относительно прошлой цены этого же товара.

Медиана считается строго внутри категории: смешаешь телевизоры с ноутбуками —
получишь мусор.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Anomaly, Product
from .stats import median as compute_median

DEFAULT_MEDIAN_RATIO = 0.20
DEFAULT_DROP_RATIO = 0.80
DEFAULT_MIN_PRICE = 1000.0


@dataclass
class AnomalyConfig:
    """Пороги детектора.

    median_ratio: цена <= median * ratio считается аномалией.
    drop_ratio:   падение >= ratio от прошлой цены считается аномалией.
    min_price:    отсекает аксессуары и мусорные позиции по 1 ₽.
    min_points:   сколько цен нужно в категории, чтобы медиане можно было верить.
    """

    median_ratio: float = DEFAULT_MEDIAN_RATIO
    drop_ratio: float = DEFAULT_DROP_RATIO
    min_price: float = DEFAULT_MIN_PRICE
    min_points: int = 5


def detect(
    products: list[Product],
    previous_prices: dict[str, float] | None = None,
    config: AnomalyConfig | None = None,
) -> list[Anomaly]:
    """Ищет аномалии в свежем срезе товаров.

    products:         товары одного скана (могут быть из разных категорий).
    previous_prices:  product_key -> последняя известная цена из истории.
    """
    cfg = config or AnomalyConfig()
    previous_prices = previous_prices or {}

    medians = _category_medians(products, cfg)
    found: list[Anomaly] = []

    for product in products:
        if not product.price or product.price < cfg.min_price:
            continue

        cat_median = medians.get(product.category)
        if cat_median and product.price <= cat_median * cfg.median_ratio:
            found.append(
                Anomaly(
                    product=product,
                    rule="below_median",
                    detail=(
                        f"{product.price:.0f} ₽ <= {cfg.median_ratio:.0%} медианы "
                        f"категории «{product.category}» ({cat_median:.0f} ₽)"
                    ),
                    median=cat_median,
                )
            )

        prev = previous_prices.get(product.product_key)
        if prev and prev > 0 and product.price < prev:
            drop = 1 - product.price / prev
            # Сравниваем умножением, а не `drop >= ratio`: 1 - 80000/100000 в
            # double даёт 0.19999999999999996 и ровно пороговое падение теряется.
            if product.price <= prev * (1 - cfg.drop_ratio):
                found.append(
                    Anomaly(
                        product=product,
                        rule="price_drop",
                        detail=(
                            f"{prev:.0f} -> {product.price:.0f} ₽ "
                            f"(-{drop:.0%}, порог -{cfg.drop_ratio:.0%})"
                        ),
                        previous_price=prev,
                        drop_pct=round(drop * 100, 1),
                    )
                )

    return found


def _category_medians(products: list[Product], cfg: AnomalyConfig) -> dict[str, float]:
    """Медиана по каждой категории, где точек хватает для доверия."""
    buckets: dict[str, list[float]] = {}
    for product in products:
        if product.price and product.price >= cfg.min_price:
            buckets.setdefault(product.category, []).append(product.price)

    medians: dict[str, float] = {}
    for category, prices in buckets.items():
        if len(prices) >= cfg.min_points:
            value = compute_median(prices)
            if value:
                medians[category] = value
    return medians
