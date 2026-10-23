"""Отчёты: markdown / json / csv."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Sequence

from .models import Anomaly, StoreResult, utcnow
from .stats import PriceStats

CSV_COLUMNS = [
    "store",
    "title",
    "price",
    "old_price",
    "discount_pct",
    "available",
    "city",
    "category",
    "product_id",
    "placement",
    "url",
    "captured_at",
]


def build(
    results: Sequence[StoreResult],
    anomalies: Sequence[Anomaly] = (),
    category_stats: dict[str, PriceStats] | None = None,
) -> dict[str, Any]:
    """Единая структура отчёта, из которой рендерятся все форматы."""
    products = [p for r in results for p in r.products]
    return {
        "generated_at": utcnow(),
        "summary": {
            "stores_scanned": len(results),
            "stores_ok": sum(1 for r in results if r.ok),
            "products_found": len(products),
            "anomalies": len(anomalies),
        },
        "stores": [
            {
                "store": r.store,
                "category": r.category,
                "status": r.status,
                "found": len(r.products),
                "reason": r.reason,
                "url": r.url,
            }
            for r in results
        ],
        "category_stats": {k: v.as_dict() for k, v in (category_stats or {}).items()},
        "anomalies": [a.as_dict() for a in anomalies],
        "products": [p.as_dict() for p in products],
    }


def to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)


def to_csv(report: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for product in report["products"]:
        row = dict(product)
        placement = row.get("placement")
        if isinstance(placement, dict):
            # В CSV филиал должен читаться глазами, а не быть вложенным объектом.
            row["placement"] = " / ".join(
                f"{k}={v}" for k, v in placement.items() if v not in (None, "", "unknown")
            )
        writer.writerow(row)
    return buffer.getvalue()


def to_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Отчёт price-scanner",
        "",
        f"Сформирован: {report['generated_at']}",
        "",
        f"- магазинов опрошено: **{summary['stores_scanned']}**, успешно: **{summary['stores_ok']}**",
        f"- товаров собрано: **{summary['products_found']}**",
        f"- аномалий: **{summary['anomalies']}**",
        "",
        "## Магазины",
        "",
        "| Магазин | Категория | Статус | Найдено | Причина |",
        "| --- | --- | --- | --- | --- |",
    ]
    for store in report["stores"]:
        lines.append(
            f"| {store['store']} | {store['category']} | {store['status']} | "
            f"{store['found']} | {store['reason'] or ''} |"
        )

    if report["category_stats"]:
        lines += [
            "",
            "## Статистика по категориям",
            "",
            "| Категория | Точек | min | p10 | median | average | p90 | max |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for category, stat in report["category_stats"].items():
            lines.append(
                f"| {category} | {stat['count']} | {format_price(stat['min'])} | {format_price(stat['p10'])} | "
                f"{format_price(stat['median'])} | {format_price(stat['average'])} | {format_price(stat['p90'])} | "
                f"{format_price(stat['max'])} |"
            )

    lines += ["", "## Аномалии", ""]
    if not report["anomalies"]:
        lines.append("Аномалий не найдено.")
    else:
        for anomaly in report["anomalies"]:
            old = f" (было {format_price(anomaly['old_price'])} ₽)" if anomaly.get("old_price") else ""
            lines += [
                f"### {anomaly['title']}",
                "",
                f"- правило: `{anomaly['rule']}` — {anomaly['detail']}",
                f"- цена: **{format_price(anomaly['price'])} ₽**{old}",
                f"- где: {anomaly['placement']}",
                f"- артикул/ID: `{anomaly['product_id']}`",
                f"- наличие: {_avail(anomaly.get('available'))}",
                f"- ссылка: {anomaly['url']}",
                "",
            ]
    return "\n".join(lines) + "\n"


def write(report: dict[str, Any], path: str | Path, fmt: str) -> Path:
    """Записать отчёт в файл. Возвращает путь."""
    renderers = {"md": to_markdown, "json": to_json, "csv": to_csv}
    if fmt not in renderers:
        raise ValueError(f"неизвестный формат: {fmt}; есть: {', '.join(renderers)}")
    target = Path(path)
    if target.parent and str(target.parent) not in (".", ""):
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(renderers[fmt](report), encoding="utf-8")
    return target


def stdout_summary(report: dict[str, Any]) -> str:
    """Краткая сводка в stdout — максимум по строке на магазин и на аномалию."""
    summary = report["summary"]
    lines = [
        f"магазинов: {summary['stores_ok']}/{summary['stores_scanned']} ok, "
        f"товаров: {summary['products_found']}, аномалий: {summary['anomalies']}"
    ]
    for store in report["stores"]:
        mark = "ok" if store["status"] == "ok" else store["status"]
        tail = f" — {store['reason']}" if store["reason"] else ""
        lines.append(f"  [{mark}] {store['store']}/{store['category']}: {store['found']}{tail}")
    for anomaly in report["anomalies"]:
        lines.append(
            f"  ! {anomaly['store']} | {anomaly['title'][:60]} | "
            f"{format_price(anomaly['price'])} ₽ | {anomaly['detail']} | {anomaly['url']}"
        )
    return "\n".join(lines)


def format_price(value: Any) -> str:
    """Цена для чтения глазами: 69999 -> '69 999'. Публичная — ею пользуется CLI."""
    if value is None:
        return "—"
    return f"{float(value):,.0f}".replace(",", " ")


def _avail(value: Any) -> str:
    if value is None:
        return "unknown"
    return "в наличии" if value else "нет в наличии"
