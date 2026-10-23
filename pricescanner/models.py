"""Базовые структуры данных price-scanner."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

UNKNOWN = "unknown"


def utcnow() -> str:
    """Время снимка в ISO-8601 UTC — единый формат для БД и отчётов."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Placement:
    """«Где в магазине» — всё, что магазин реально отдал о месте товара.

    Ничего не придумываем: если магазин не отдаёт филиал, остаётся `unknown`.
    """

    store: str
    city: str = UNKNOWN
    branch: str = UNKNOWN
    branch_address: str = UNKNOWN
    branch_available: str | None = None
    branches_url: str | None = None
    branch_count: int | None = None
    department: str = UNKNOWN
    stock_note: str = UNKNOWN

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        """Человекочитаемая строка для отчёта."""
        bits = [self.store]
        if self.city != UNKNOWN:
            bits.append(self.city)
        if self.branch != UNKNOWN:
            bits.append(self.branch)
        elif self.branch_count:
            bits.append(f"{self.branch_count} маг.")
        else:
            bits.append("branch: unknown")
        if self.branch_address != UNKNOWN:
            bits.append(self.branch_address)
        if self.stock_note != UNKNOWN:
            bits.append(self.stock_note)
        return " / ".join(bits)


@dataclass
class Product:
    """Один товар в одном магазине на момент снимка."""

    store: str
    title: str
    price: float
    url: str
    product_id: str
    category: str
    old_price: float | None = None
    available: bool | None = None
    city: str = UNKNOWN
    placement: Placement | None = None
    captured_at: str = field(default_factory=utcnow)

    @property
    def product_key(self) -> str:
        """Стабильный ключ товара для истории цен: магазин + его собственный id."""
        return f"{self.store}:{self.product_id}"

    @property
    def discount_pct(self) -> float | None:
        """Скидка в процентах от старой цены, если магазин отдал старую цену."""
        if not self.old_price or self.old_price <= 0 or self.price > self.old_price:
            return None
        return round((1 - self.price / self.old_price) * 100, 1)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["product_key"] = self.product_key
        data["discount_pct"] = self.discount_pct
        return data


@dataclass
class StoreResult:
    """Итог обхода одного магазина. Падение магазина не роняет весь скан."""

    store: str
    category: str
    status: str  # ok | unreachable | empty
    products: list[Product] = field(default_factory=list)
    reason: str | None = None
    url: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass
class Anomaly:
    """Сработавшее правило аномалии по конкретному товару."""

    product: Product
    rule: str  # below_median | price_drop
    detail: str
    median: float | None = None
    previous_price: float | None = None
    drop_pct: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.product.as_dict(),
            "rule": self.rule,
            "detail": self.detail,
            "median": self.median,
            "previous_price": self.previous_price,
            # Строкой, а не объектом: в отчёте место читается глазами. Ключ
            # перекрывает `placement` товара, поэтому идёт после распаковки.
            "placement": self.product.placement.summary() if self.product.placement else UNKNOWN,
        }


class StoreUnreachable(Exception):
    """Магазин недоступен (антибот, сеть, разметка изменилась)."""

    def __init__(self, store: str, reason: str) -> None:
        super().__init__(f"{store}: {reason}")
        self.store = store
        self.reason = reason


_PRICE_JUNK = re.compile(r"[^\d,.]")


def parse_price(raw: str | int | float | None) -> float | None:
    """'69 999\xa0₽' -> 69999.0. Возвращает None, если числа нет.

    Русские витрины пишут цену с неразрывными пробелами, валютой и иногда
    с копейками через запятую — всё это нужно пережить.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw) or None
    text = raw.replace("\xa0", "").replace(" ", "").replace(" ", "")
    text = _PRICE_JUNK.sub("", text)
    if not text:
        return None
    # Запятая в русской вёрстке — десятичный разделитель, точка-тысячи не бывает.
    text = text.replace(",", ".")
    if text.count(".") > 1:
        head, _, tail = text.rpartition(".")
        text = head.replace(".", "") + "." + tail
    try:
        value = float(text)
    except ValueError:
        return None
    return value or None
