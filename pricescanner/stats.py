"""Статистика цен: min / max / average / median / p10 / p90 / число точек."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Iterable, Sequence


@dataclass
class PriceStats:
    count: int
    min: float | None = None
    max: float | None = None
    average: float | None = None
    median: float | None = None
    p10: float | None = None
    p90: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def percentile(values: Sequence[float], q: float) -> float | None:
    """Процентиль методом линейной интерполяции (как numpy.percentile по умолчанию).

    q задаётся долей: 0.5 -> медиана, 0.1 -> p10.
    """
    if not values:
        return None
    if not 0.0 <= q <= 1.0:
        raise ValueError("q должен быть в диапазоне [0, 1]")
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pos = q * (len(ordered) - 1)
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    frac = pos - low
    return float(ordered[low] + (ordered[high] - ordered[low]) * frac)


def median(values: Sequence[float]) -> float | None:
    """Медиана. Отдельная функция — ею пользуется детектор аномалий."""
    return percentile(values, 0.5)


def compute(values: Iterable[float]) -> PriceStats:
    """Полная сводка по набору цен. Нули и None отбрасываются как мусор витрин."""
    clean = [float(v) for v in values if v]
    if not clean:
        return PriceStats(count=0)
    return PriceStats(
        count=len(clean),
        min=min(clean),
        max=max(clean),
        average=round(sum(clean) / len(clean), 2),
        median=median(clean),
        p10=percentile(clean, 0.10),
        p90=percentile(clean, 0.90),
    )
