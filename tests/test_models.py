"""Разбор цен и базовые структуры данных."""

from __future__ import annotations

import pytest

from pricescanner.models import UNKNOWN, Placement, Product, StoreResult, parse_price, utcnow


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("69 999 ₽", 69999.0),  # обычный пробел
        ("69\xa0999\xa0₽", 69999.0),  # неразрывный — так пишут русские витрины
        ("69 999", 69999.0),  # узкий неразрывный пробел
        ("1 234 567 ₽", 1234567.0),
        ("999,50 ₽", 999.5),  # запятая — десятичный разделитель
        ("от 47 999 руб.", 47999.0),
        (69999, 69999.0),
        (69999.5, 69999.5),
        ("", None),
        ("Цена по запросу", None),
        (None, None),
        (0, None),
        ("0 ₽", None),
    ],
)
def test_parse_price(raw, expected):
    assert parse_price(raw) == expected


def test_product_key_combines_store_and_id():
    product = Product(
        store="dns", title="Ноутбук", price=69999, url="u", product_id="5633157", category="noutbuki"
    )

    assert product.product_key == "dns:5633157"


@pytest.mark.parametrize(
    "price,old_price,expected",
    [
        (47999, 54999, 12.7),
        (50000, 100000, 50.0),
        (69999, None, None),  # магазин не отдал старую цену
        (69999, 0, None),
        (80000, 69999, None),  # «старая» ниже текущей — это не скидка
    ],
)
def test_discount_pct(price, old_price, expected):
    product = Product(
        store="dns", title="t", price=price, old_price=old_price, url="u", product_id="1", category="c"
    )

    assert product.discount_pct == expected


def test_placement_summary_skips_unknown_fields():
    """В отчёт не должно утекать «unknown» там, где магазин просто ничего не сказал."""
    placement = Placement(store="DNS", city="Екатеринбург", branch_count=24, stock_note="в 24 магазинах")
    summary = placement.summary()

    assert summary == "DNS / Екатеринбург / 24 маг. / в 24 магазинах"
    assert "unknown" not in summary


def test_placement_summary_admits_unknown_branch():
    """Если филиала нет вовсе — честно пишем это, а не выдумываем адрес."""
    assert Placement(store="DNS").summary() == "DNS / branch: unknown"


def test_placement_defaults_are_unknown():
    placement = Placement(store="DNS")

    assert placement.city == UNKNOWN
    assert placement.branch == UNKNOWN
    assert placement.branch_address == UNKNOWN
    assert placement.branch_count is None


def test_store_result_ok_only_for_ok_status():
    assert StoreResult(store="dns", category="c", status="ok").ok
    assert not StoreResult(store="dns", category="c", status="empty").ok
    assert not StoreResult(store="dns", category="c", status="unreachable").ok


def test_product_as_dict_includes_derived_fields():
    product = Product(
        store="dns",
        title="Ноутбук",
        price=47999,
        old_price=54999,
        url="u",
        product_id="1",
        category="noutbuki",
    )
    data = product.as_dict()

    assert data["product_key"] == "dns:1"
    assert data["discount_pct"] == 12.7
    assert data["captured_at"]


def test_utcnow_is_iso_utc_seconds():
    value = utcnow()

    assert value.endswith("+00:00")
    assert len(value) == len("2026-10-23T10:00:00+00:00")
