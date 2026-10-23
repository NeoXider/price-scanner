"""Отчёты: md / json / csv собираются из одной структуры и не падают."""

from __future__ import annotations

import csv
import io
import json

import pytest

from pricescanner import report as report_mod
from pricescanner import stats
from pricescanner.anomaly import detect
from pricescanner.models import Placement, Product, StoreResult


def make_product(price: float = 69_999, product_id: str = "a") -> Product:
    return Product(
        store="dns",
        title=f"Ноутбук {product_id}",
        price=price,
        url=f"https://example.test/{product_id}",
        product_id=product_id,
        category="noutbuki",
        old_price=price + 10_000,
        available=True,
        city="Екатеринбург",
        placement=Placement(store="DNS", city="Екатеринбург", branch_count=24, stock_note="в 24 магазинах"),
        captured_at="2026-10-23T10:00:00+00:00",
    )


@pytest.fixture
def filled_report():
    products = [make_product(100_000, f"n{i}") for i in range(5)] + [make_product(15_000, "cheap")]
    results = [
        StoreResult(store="dns", category="noutbuki", status="ok", products=products, url="https://dns.test"),
        StoreResult(
            store="ozon",
            category="noutbuki",
            status="unreachable",
            reason="в ответе маркер антибота: qrator",
            url="https://ozon.test",
        ),
    ]
    anomalies = detect(products)
    assert anomalies, "фикстура должна содержать хотя бы одну аномалию"
    return report_mod.build(results, anomalies, {"noutbuki": stats.compute(p.price for p in products)})


# --- build --------------------------------------------------------------


def test_build_counts_stores_and_products(filled_report):
    summary = filled_report["summary"]

    assert summary["stores_scanned"] == 2
    assert summary["stores_ok"] == 1  # недоступный магазин в ok не попадает
    assert summary["products_found"] == 6
    assert summary["anomalies"] == 1
    assert filled_report["generated_at"]


def test_build_keeps_unreachable_reason(filled_report):
    ozon = next(s for s in filled_report["stores"] if s["store"] == "ozon")

    assert ozon["status"] == "unreachable"
    assert "qrator" in ozon["reason"]
    assert ozon["found"] == 0


def test_build_on_empty_input():
    empty = report_mod.build([])

    assert empty["summary"] == {
        "stores_scanned": 0,
        "stores_ok": 0,
        "products_found": 0,
        "anomalies": 0,
    }
    assert empty["products"] == []
    assert empty["anomalies"] == []


# --- markdown -----------------------------------------------------------


def test_to_markdown_contains_all_sections(filled_report):
    text = report_mod.to_markdown(filled_report)

    assert text.startswith("# Отчёт price-scanner")
    assert "## Магазины" in text
    assert "## Статистика по категориям" in text
    assert "## Аномалии" in text
    assert "| dns | noutbuki | ok | 6 |" in text
    assert "qrator" in text  # причина недоступности видна в отчёте
    assert "below_median" in text
    assert text.endswith("\n")


def test_to_markdown_without_anomalies_says_so():
    text = report_mod.to_markdown(report_mod.build([]))

    assert "Аномалий не найдено." in text


def test_to_markdown_of_empty_report_does_not_raise():
    assert report_mod.to_markdown(report_mod.build([]))


# --- json ---------------------------------------------------------------


def test_to_json_round_trips(filled_report):
    parsed = json.loads(report_mod.to_json(filled_report))

    assert parsed["summary"]["products_found"] == 6
    assert parsed["category_stats"]["noutbuki"]["count"] == 6
    assert parsed["products"][0]["product_key"] == "dns:n0"
    assert parsed["products"][0]["placement"]["branch_count"] == 24
    assert parsed["anomalies"][0]["rule"] == "below_median"


def test_to_json_keeps_cyrillic_readable(filled_report):
    assert "Ноутбук" in report_mod.to_json(filled_report)


# --- csv ----------------------------------------------------------------


def test_to_csv_has_header_and_row_per_product(filled_report):
    rows = list(csv.DictReader(io.StringIO(report_mod.to_csv(filled_report))))

    assert len(rows) == 6
    assert list(rows[0]) == report_mod.CSV_COLUMNS
    assert rows[0]["store"] == "dns"
    assert rows[0]["price"] == "100000"
    # вложенный placement в CSV разворачивается в читаемую строку
    assert "city=Екатеринбург" in rows[0]["placement"]
    assert "branch=unknown" not in rows[0]["placement"]


def test_to_csv_of_empty_report_is_header_only():
    text = report_mod.to_csv(report_mod.build([]))

    assert text.strip() == ",".join(report_mod.CSV_COLUMNS)


# --- write / stdout -----------------------------------------------------


@pytest.mark.parametrize("fmt,marker", [("md", "# Отчёт"), ("json", '"summary"'), ("csv", "store,title")])
def test_write_creates_file_in_each_format(filled_report, tmp_path, fmt, marker):
    path = report_mod.write(filled_report, tmp_path / "out" / f"report.{fmt}", fmt)

    assert path.is_file()
    assert marker in path.read_text(encoding="utf-8")


def test_write_rejects_unknown_format(filled_report, tmp_path):
    with pytest.raises(ValueError):
        report_mod.write(filled_report, tmp_path / "report.xml", "xml")


def test_stdout_summary_lists_stores_and_anomalies(filled_report):
    text = report_mod.stdout_summary(filled_report)

    assert "магазинов: 1/2 ok" in text
    assert "[ok] dns/noutbuki: 6" in text
    assert "[unreachable] ozon/noutbuki: 0 — в ответе маркер антибота: qrator" in text
    assert text.count("  ! ") == 1


def test_format_price_is_readable():
    assert report_mod.format_price(69999) == "69 999"
    assert report_mod.format_price(1234567.4) == "1 234 567"
    assert report_mod.format_price(None) == "—"
