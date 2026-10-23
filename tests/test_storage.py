"""История цен в SQLite: запись снимков и чтение предыдущего среза."""

from __future__ import annotations

from pricescanner.models import Placement, Product
from pricescanner.storage import PriceStore, row_to_product


def make_product(
    price: float,
    product_id: str = "1",
    captured_at: str = "2026-10-23T10:00:00+00:00",
    store: str = "dns",
    category: str = "noutbuki",
    placement: Placement | None = None,
) -> Product:
    return Product(
        store=store,
        title=f"Ноутбук {product_id}",
        price=price,
        url=f"https://example.test/{product_id}",
        product_id=product_id,
        category=category,
        old_price=price + 10_000,
        available=True,
        city="Екатеринбург",
        placement=placement,
        captured_at=captured_at,
    )


def open_store(tmp_path) -> PriceStore:
    return PriceStore(tmp_path / "data" / "prices.db")


def test_save_and_read_back(tmp_path):
    with open_store(tmp_path) as store:
        saved = store.save_products([make_product(69_999, "a"), make_product(47_999, "b")])

        assert saved == 2
        rows = store.prices_for_product("dns:a")
        assert len(rows) == 1

        product = row_to_product(rows[0])
        assert product.store == "dns"
        assert product.price == 69_999
        assert product.old_price == 79_999
        assert product.available is True
        assert product.city == "Екатеринбург"
        assert product.product_key == "dns:a"
        assert product.captured_at == "2026-10-23T10:00:00+00:00"


def test_db_file_and_parent_directory_are_created(tmp_path):
    path = tmp_path / "nested" / "deeper" / "prices.db"
    with PriceStore(path):
        pass

    assert path.is_file()


def test_saving_nothing_is_not_an_error(tmp_path):
    with open_store(tmp_path) as store:
        assert store.save_products([]) == 0
        assert store.last_prices() == {}


def test_placement_survives_round_trip(tmp_path):
    placement = Placement(
        store="DNS",
        city="Екатеринбург",
        branch="unknown",
        branch_available="В наличии",
        branches_url="https://www.dns-shop.ru/shops/ekaterinburg/",
        branch_count=24,
        stock_note="в 24 магазинах",
    )
    with open_store(tmp_path) as store:
        store.save_products([make_product(69_999, "a", placement=placement)])
        restored = row_to_product(store.prices_for_product("dns:a")[0])

    assert restored.placement == placement


def test_last_prices_returns_latest_snapshot(tmp_path):
    """Снимков у товара много — last_prices() отдаёт цену самого свежего."""
    with open_store(tmp_path) as store:
        store.save_products([make_product(100_000, "a", captured_at="2026-10-21T10:00:00+00:00")])
        store.save_products([make_product(90_000, "a", captured_at="2026-10-22T10:00:00+00:00")])
        store.save_products([make_product(80_000, "a", captured_at="2026-10-23T10:00:00+00:00")])

        assert store.last_prices() == {"dns:a": 80_000}


def test_last_prices_before_gives_previous_slice(tmp_path):
    """Именно это нужно watch: сравнивать свежий срез с прошлым, а не с собой."""
    older = "2026-10-22T10:00:00+00:00"
    newest = "2026-10-23T10:00:00+00:00"
    with open_store(tmp_path) as store:
        store.save_products([make_product(100_000, "a", captured_at=older)])
        store.save_products([make_product(15_000, "a", captured_at=newest)])

        assert store.last_prices() == {"dns:a": 15_000}
        assert store.last_prices(before=newest) == {"dns:a": 100_000}


def test_last_prices_keeps_stores_apart(tmp_path):
    with open_store(tmp_path) as store:
        store.save_products(
            [
                make_product(69_999, "42", store="dns"),
                make_product(48_990, "42", store="citilink"),
            ]
        )

        assert store.last_prices() == {"dns:42": 69_999, "citilink:42": 48_990}


def test_latest_products_returns_only_newest_slice(tmp_path):
    with open_store(tmp_path) as store:
        store.save_products(
            [
                make_product(100_000, "a", captured_at="2026-10-22T10:00:00+00:00"),
                make_product(200_000, "b", captured_at="2026-10-22T10:00:00+00:00"),
            ]
        )
        store.save_products([make_product(80_000, "a", captured_at="2026-10-23T10:00:00+00:00")])

        latest = store.latest_products()

        assert [(p.product_key, p.price) for p in latest] == [("dns:a", 80_000)]


def test_prices_by_title_and_category(tmp_path):
    with open_store(tmp_path) as store:
        store.save_products(
            [
                make_product(69_999, "a", category="noutbuki"),
                make_product(5_999, "c", category="myshki"),
            ]
        )

        assert store.categories() == ["myshki", "noutbuki"]
        assert len(store.prices_by_title("Ноутбук")) == 2  # title = «Ноутбук <id>»
        assert len(store.prices_for_category("myshki")) == 1
        assert store.prices_for_product("dns:missing") == []


def test_category_history_vs_latest_only(tmp_path):
    with open_store(tmp_path) as store:
        store.save_products([make_product(100_000, "a", captured_at="2026-10-22T10:00:00+00:00")])
        store.save_products([make_product(80_000, "a", captured_at="2026-10-23T10:00:00+00:00")])

        assert len(store.prices_for_category("noutbuki")) == 1
        assert len(store.prices_for_category("noutbuki", latest_only=False)) == 2


def test_scans_log_records_unreachable_stores(tmp_path):
    """Недоступный магазин тоже попадает в журнал — с причиной, а не молча."""
    with open_store(tmp_path) as store:
        store.save_scan("dns", "noutbuki", "ok", 2, "2026-10-23T10:00:00+00:00")
        store.save_scan(
            "ozon", "noutbuki", "unreachable", 0, "2026-10-23T10:00:00+00:00", reason="антибот"
        )

        scans = store.recent_scans()

        assert [r["store"] for r in scans] == ["ozon", "dns"]
        assert scans[0]["status"] == "unreachable"
        assert scans[0]["reason"] == "антибот"
        assert scans[1]["found"] == 2


def test_reopening_same_file_keeps_history(tmp_path):
    path = tmp_path / "prices.db"
    with PriceStore(path) as store:
        store.save_products([make_product(69_999, "a")])
    with PriceStore(path) as store:
        assert store.last_prices() == {"dns:a": 69_999}
