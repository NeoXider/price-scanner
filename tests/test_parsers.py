"""Парсеры магазинов на фикстурах, снятых с живых витрин 2026-10-23.

Фикстуры — единственный источник правды о разметке: если витрина поменяет
вёрстку, тест не узнает об этом, зато узнает о поломке самого парсера.
"""

from __future__ import annotations

import pytest

from pricescanner.models import Product
from pricescanner.stores import REGISTRY, VERIFIED, get
from pricescanner.stores.citilink import CitilinkStore
from pricescanner.stores.dns import DnsStore
from pricescanner.stores.mvideo import MvideoStore
from pricescanner.stores.xcom import XcomStore

# магазин -> фикстура каталога ноутбуков
HTML_STORES = {
    "dns": "dns_noutbuki.html",
    "citilink": "citilink_noutbuki.json",
    "xcom": "xcom_noutbuki.html",
}

MVIDEO_ROUTES = {
    "products/v2/search": "mvideo_search.json",
    "products/prices": "mvideo_prices.json",
    "product-details?productId=402234028": "mvideo_details_402234028.json",
}


# --- общие требования ко всем парсерам ---------------------------------


@pytest.mark.parametrize("store_name,fixture_name", sorted(HTML_STORES.items()))
def test_parse_returns_products(store_name, fixture_name, read_fixture):
    """Каждый проверенный парсер извлекает товары из фикстуры без исключений."""
    products = get(store_name).parse(read_fixture(fixture_name), "noutbuki")

    assert products, f"{store_name}: из фикстуры не извлечено ни одного товара"
    for product in products:
        assert isinstance(product, Product)
        assert product.store == store_name
        assert product.category == "noutbuki"
        assert product.title.strip(), "пустое название товара"
        assert product.price > 0, f"нулевая цена у {product.product_id}"
        assert product.product_id, "товар без собственного id магазина"
        assert product.url.startswith("http"), f"ссылка не абсолютная: {product.url}"
        assert product.placement is not None
        assert product.placement.summary()
        assert product.captured_at


@pytest.mark.parametrize("store_name,fixture_name", sorted(HTML_STORES.items()))
def test_product_keys_unique(store_name, fixture_name, read_fixture):
    """История цен опирается на product_key — в одном срезе он не должен дублироваться."""
    products = get(store_name).parse(read_fixture(fixture_name), "noutbuki")
    keys = [p.product_key for p in products]

    assert len(keys) == len(set(keys))
    assert all(key.startswith(f"{store_name}:") for key in keys)


@pytest.mark.parametrize("store_name", sorted(HTML_STORES))
def test_parse_of_garbage_does_not_raise(store_name):
    """Витрина может отдать заглушку вместо каталога — парсер обязан вернуть []."""
    adapter = get(store_name)

    assert adapter.parse("<html><body>Проверка браузера</body></html>", "noutbuki") == []
    assert adapter.parse("", "noutbuki") == []


@pytest.mark.parametrize("store_name", sorted(HTML_STORES))
def test_catalog_url_and_pagination(store_name):
    adapter = get(store_name)
    first = adapter.catalog_url("noutbuki", 1)
    second = adapter.catalog_url("noutbuki", 2)

    assert first.startswith("https://")
    assert second != first, "вторая страница совпала с первой — пагинация не работает"


# --- DNS ----------------------------------------------------------------


def test_dns_parses_prices_and_availability(read_fixture):
    products = DnsStore().parse(read_fixture("dns_noutbuki.html"), "noutbuki")
    by_id = {p.product_id: p for p in products}

    assert set(by_id) == {"5633157", "5608550"}

    fresh = by_id["5633157"]
    assert fresh.price == 69999.0
    assert fresh.old_price is None
    assert fresh.available is True
    assert fresh.city == "Екатеринбург"  # data-city-name из виджета доставки
    assert "HONOR MagicBook X16" in fresh.title
    assert fresh.url == (
        "https://www.dns-shop.ru/product/3497d8af5554d582/"
        "16-noutbuk-honor-magicbook-x16-amd-2025-seryj/"
    )

    discounted = by_id["5608550"]
    assert discounted.price == 47999.0
    assert discounted.old_price == 54999.0
    assert discounted.discount_pct == 12.7
    assert discounted.available is False  # data-avail-status != now


def test_dns_placement_keeps_branch_unknown(read_fixture):
    """DNS в каталоге не называет филиал — только число магазинов города."""
    products = DnsStore().parse(read_fixture("dns_noutbuki.html"), "noutbuki")
    placement = products[0].placement

    assert placement.store == "DNS"
    assert placement.city == "Екатеринбург"
    assert placement.branch == "unknown"
    assert placement.branch_count == 24
    assert placement.branch_available == "В наличии"
    assert placement.branches_url == "https://www.dns-shop.ru/shops/ekaterinburg/"


# --- Citilink -----------------------------------------------------------


def test_citilink_parses_next_data(read_fixture):
    products = CitilinkStore().parse(read_fixture("citilink_noutbuki.json"), "noutbuki")

    assert [p.product_id for p in products] == ["2174077", "2136020", "2162521"]
    assert [p.price for p in products] == [48990.0, 139990.0, 141990.0]
    assert [p.old_price for p in products] == [55990.0, 167990.0, 158990.0]
    assert all(p.available is True for p in products)

    first = products[0]
    assert first.title.startswith("Ноутбук CHUWI Corebook X")
    assert first.url == (
        "https://www.citilink.ru/product/"
        "noutbuk-chuwi-corebook-x-ryzen-5-5500u-16gb-ssd512gb-vega-7-14-2k-w11h/"
    )
    assert first.placement.department == "Ноутбуки"
    assert first.placement.branch == "unknown"  # филиал только для избранных магазинов


def test_citilink_accepts_full_html_page(read_fixture):
    """Парсер должен одинаково понимать и голый JSON, и страницу с __NEXT_DATA__."""
    raw_json = read_fixture("citilink_noutbuki.json")
    page = f'<html><body><script id="__NEXT_DATA__" type="application/json">{raw_json}</script></body></html>'

    from_json = CitilinkStore().parse(raw_json, "noutbuki")
    from_html = CitilinkStore().parse(page, "noutbuki")

    assert [p.product_id for p in from_html] == [p.product_id for p in from_json]
    assert [p.price for p in from_html] == [p.price for p in from_json]


def test_citilink_missing_path_returns_empty():
    """Next.js переехал на другой путь в состоянии — не падаем, отдаём пустой список."""
    assert CitilinkStore().parse('{"props": {"initialState": {}}}', "noutbuki") == []


# --- M.Video ------------------------------------------------------------


def test_mvideo_three_step_scan(fixture_fetcher):
    """search -> prices -> product-details: цены из пачки, имя по одному id."""
    fetcher = fixture_fetcher(MVIDEO_ROUTES)
    result = MvideoStore(limit=5).scan(fetcher, "noutbuki")

    assert result.status == "ok"
    # поиск отдал 5 id, цены пришли на 3 — остальные отбрасываются
    assert [p.product_id for p in result.products] == ["402234028", "401002749", "400679051"]

    by_id = {p.product_id: p for p in result.products}
    assert by_id["402234028"].price == 109999.0
    assert by_id["402234028"].old_price == 149999.0
    assert by_id["401002749"].price == 38164.0
    assert by_id["400679051"].price == 122072.0

    named = by_id["402234028"]
    assert named.title.startswith("Ноутбук ASUS UM3406GA-QD133")
    assert named.url.endswith("-402234028")
    assert named.city == "Москва"
    assert named.available is None  # наличие в ответах BFF не приходит


def test_mvideo_survives_missing_details(fixture_fetcher):
    """Имя товара — не причина терять цену: без product-details остаётся id."""
    fetcher = fixture_fetcher(
        {"products/v2/search": "mvideo_search.json", "products/prices": "mvideo_prices.json"}
    )
    result = MvideoStore(limit=5).scan(fetcher, "noutbuki")

    assert result.status == "ok"
    assert [p.title for p in result.products] == ["402234028", "401002749", "400679051"]


def test_mvideo_min_price_filters_fuzzy_search(fixture_fetcher):
    """Поиск М.Видео нечёткий, поэтому дешёвую выдачу отсекает min_price."""
    fetcher = fixture_fetcher(MVIDEO_ROUTES)
    result = MvideoStore(limit=5, min_price=120_000).scan(fetcher, "noutbuki")

    # остаются только 122 072 ₽; 109 999 и 38 164 отсечены
    assert [p.product_id for p in result.products] == ["400679051"]


def test_mvideo_unreachable_store_does_not_raise(fixture_fetcher):
    result = MvideoStore(limit=5).scan(fixture_fetcher({}), "noutbuki")

    assert result.status == "unreachable"
    assert result.products == []
    assert result.reason


def test_mvideo_sends_city_cookies(fixture_fetcher):
    """Без cookie города BFF отвечает 400 — заголовок обязан уходить в каждый запрос."""
    adapter = MvideoStore(limit=5)
    headers = adapter._headers()

    assert "MVID_CITY_ID=CityCZ_975" in headers["Cookie"]
    assert "MVID_REGION_SHOP=S002" in headers["Cookie"]


# --- XCOM-SHOP ----------------------------------------------------------


def test_xcom_parses_data_attributes(read_fixture):
    products = XcomStore().parse(read_fixture("xcom_noutbuki.html"), "noutbuki")
    by_id = {p.product_id: p for p in products}

    assert set(by_id) == {"1200144", "1188002"}

    lenovo = by_id["1200144"]
    assert lenovo.price == 92000.0
    assert lenovo.old_price is None
    assert lenovo.available is True
    assert lenovo.title.startswith("Ноутбук Lenovo ThinkPad E16 Gen 2")
    assert lenovo.url == "https://ekaterinburg.xcom-shop.ru/lenovo_thinkpad_e16_gen_2_1200144.html"
    assert lenovo.placement.department == "Компьютеры и ноутбуки/Ноутбуки"
    assert lenovo.placement.stock_note == "остаток на складах: 21 – 100"

    asus = by_id["1188002"]
    assert asus.price == 61490.0
    assert asus.old_price == 74990.0
    assert asus.available is False  # stock-indicator data-level=0


def test_xcom_city_from_subdomain(read_fixture):
    products = XcomStore().parse(read_fixture("xcom_noutbuki.html"), "noutbuki")

    assert all(p.city == "Екатеринбург" for p in products)
    assert products[0].placement.store == "XCOM-SHOP"


# --- реестр -------------------------------------------------------------


def test_registry_marks_only_fixture_backed_stores_as_verified():
    """verified=True обещает проверенный парсер — ровно те четыре, что в тестах."""
    assert set(VERIFIED) == {"dns", "citilink", "mvideo", "xcom"}


def test_unverified_stores_declare_reason():
    """Магазин без парсера обязан объяснять, почему его нет, а не молчать."""
    for name, cls in REGISTRY.items():
        if cls.verified:
            continue
        assert cls.method, f"{name}: не указан способ/причина отсутствия парсера"


@pytest.mark.parametrize("store_name", sorted(REGISTRY))
def test_every_registered_store_can_be_instantiated(store_name):
    """`scan` без --store поднимает все адаптеры: недостроенный класс уронит весь обход."""
    adapter = get(store_name)

    assert adapter.name == store_name
    assert adapter.categories


@pytest.mark.parametrize("store_name", sorted(set(REGISTRY) - set(VERIFIED)))
def test_unverified_store_returns_unreachable_instead_of_crashing(store_name, fixture_fetcher):
    """Магазин без парсера обязан отдать unreachable с причиной, а не уронить скан."""
    adapter = get(store_name)
    category = next(iter(adapter.categories))
    result = adapter.scan(fixture_fetcher({}), category)

    assert result.status == "unreachable"
    assert result.products == []
    assert adapter.probe_result in result.reason

    with pytest.raises(NotImplementedError):
        adapter.parse("<html></html>", category)


def test_get_unknown_store_raises():
    with pytest.raises(KeyError):
        get("ozon-shop-nonexistent")


def test_scan_rejects_unknown_category(fixture_fetcher):
    result = DnsStore().scan(fixture_fetcher({}), "kofemolki")

    assert result.status == "unreachable"
    assert "kofemolki" in result.reason
