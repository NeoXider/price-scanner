"""Детектор аномалий: цена ниже доли медианы и падение относительно истории."""

from __future__ import annotations

from pricescanner.anomaly import AnomalyConfig, detect
from pricescanner.models import Product


def make_product(price: float, product_id: str = "1", category: str = "noutbuki", store: str = "dns") -> Product:
    return Product(
        store=store,
        title=f"Ноутбук {product_id}",
        price=price,
        url=f"https://example.test/{product_id}",
        product_id=product_id,
        category=category,
    )


def normal_batch(category: str = "noutbuki", price: float = 100_000.0) -> list[Product]:
    """Пять «нормальных» товаров — минимум, при котором медиане можно верить."""
    return [make_product(price, product_id=f"n{i}", category=category) for i in range(5)]


# --- правило below_median ----------------------------------------------


def test_detects_price_below_median_share():
    """15 000 ₽ при медиане 100 000 — это 15%, порог 20% сработает."""
    cheap = make_product(15_000, product_id="cheap")
    found = detect(normal_batch() + [cheap])

    assert len(found) == 1
    assert found[0].rule == "below_median"
    assert found[0].product.product_id == "cheap"
    assert found[0].median == 100_000.0
    assert "медианы" in found[0].detail


def test_price_just_above_threshold_is_not_anomaly():
    """Порог включающий: 20 001 при медиане 100 000 — уже норма."""
    assert detect(normal_batch() + [make_product(20_001, product_id="edge")]) == []

    on_threshold = detect(normal_batch() + [make_product(20_000, product_id="edge")])
    assert [a.rule for a in on_threshold] == ["below_median"]


def test_median_is_computed_per_category():
    """Смешать телевизоры с ноутбуками — получить мусор, поэтому категории раздельны."""
    products = (
        normal_batch(category="noutbuki", price=100_000)
        + normal_batch(category="myshki", price=2_000)
        + [make_product(1_500, product_id="mouse", category="myshki")]
    )
    found = detect(products)

    # 1 500 ₽ дешёвая только на фоне ноутбуков; внутри мышек это 75% медианы
    assert found == []


def test_few_points_means_no_trusted_median():
    """Меньше min_points цен в категории — медиану не считаем вовсе."""
    products = [make_product(100_000, product_id=f"n{i}") for i in range(3)]
    products.append(make_product(1_500, product_id="cheap"))

    assert detect(products) == []


def test_cheap_items_below_min_price_are_ignored():
    """Аксессуар за 999 ₽ не должен засорять отчёт."""
    found = detect(normal_batch() + [make_product(999, product_id="cable")])

    assert found == []


def test_median_ratio_is_configurable():
    products = normal_batch() + [make_product(40_000, product_id="half")]

    assert detect(products) == []
    found = detect(products, config=AnomalyConfig(median_ratio=0.5))
    assert [a.product.product_id for a in found] == ["half"]


# --- правило price_drop -------------------------------------------------


def test_detects_price_drop_against_history():
    """Порог по умолчанию — падение на 80%: 100 000 -> 15 000 это -85%."""
    product = make_product(15_000, product_id="dropped")
    found = detect([product], previous_prices={"dns:dropped": 100_000})

    assert len(found) == 1
    anomaly = found[0]
    assert anomaly.rule == "price_drop"
    assert anomaly.previous_price == 100_000
    assert anomaly.drop_pct == 85.0
    assert "15000" in anomaly.detail.replace(" ", "")


def test_detects_twenty_percent_drop_with_configured_threshold():
    """С порогом 20% ловится и мягкое падение 100 000 -> 80 000."""
    product = make_product(80_000, product_id="soft")
    config = AnomalyConfig(drop_ratio=0.20)

    found = detect([product], previous_prices={"dns:soft": 100_000}, config=config)

    assert [a.rule for a in found] == ["price_drop"]
    assert found[0].drop_pct == 20.0

    # с порогом по умолчанию (-80%) это падение аномалией не считается
    assert detect([product], previous_prices={"dns:soft": 100_000}) == []


def test_drop_below_threshold_is_ignored():
    product = make_product(95_000, product_id="tiny")

    assert detect([product], previous_prices={"dns:tiny": 100_000}) == []


def test_price_growth_is_not_a_drop():
    product = make_product(120_000, product_id="grown")

    assert detect([product], previous_prices={"dns:grown": 100_000}) == []


def test_unknown_history_is_not_a_drop():
    """Товар впервые увиден — сравнивать не с чем, молчим."""
    assert detect([make_product(15_000, product_id="new")], previous_prices={}) == []


def test_history_matched_by_store_and_id():
    """product_key = store:id, поэтому чужая история не подхватывается."""
    product = make_product(15_000, product_id="42", store="dns")

    assert detect([product], previous_prices={"citilink:42": 100_000}) == []
    assert detect([product], previous_prices={"dns:42": 100_000})


# --- взаимодействие правил ---------------------------------------------


def test_both_rules_can_fire_for_one_product():
    """Правила независимы: товар может попасть в отчёт дважды, с разным объяснением."""
    cheap = make_product(15_000, product_id="both")
    found = detect(normal_batch() + [cheap], previous_prices={"dns:both": 100_000})

    assert {a.rule for a in found} == {"below_median", "price_drop"}
    assert all(a.product.product_id == "both" for a in found)


def test_normal_batch_is_quiet():
    assert detect(normal_batch(), previous_prices={}) == []


def test_anomaly_as_dict_carries_product_and_rule():
    cheap = make_product(15_000, product_id="cheap")
    anomaly = detect(normal_batch() + [cheap])[0]
    data = anomaly.as_dict()

    assert data["rule"] == "below_median"
    assert data["price"] == 15_000
    assert data["product_key"] == "dns:cheap"
    assert data["url"] == "https://example.test/cheap"
    assert data["placement"] == "unknown"  # у товара без placement не выдумываем место
