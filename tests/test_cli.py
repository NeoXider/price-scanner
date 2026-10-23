"""CLI: сборка снимка, статистика, watch, report — на локальных фикстурах.

Сеть не трогаем: `--fetcher local` читает заранее сохранённые страницы, имя
файла — URL с заменой всего небуквенного на `_` (см. `LocalFetcher`).
"""

from __future__ import annotations

import json

import pytest

from pricescanner.cli import main
from pricescanner.fetchers import LocalFetcher
from pricescanner.storage import PriceStore
from pricescanner.stores import get


@pytest.fixture
def local_pages(tmp_path, read_fixture):
    """Каталог страниц для `--fetcher local`: DNS и XCOM под их реальными URL."""
    pages = tmp_path / "pages"
    pages.mkdir()
    for store_name, fixture_name in (("dns", "dns_noutbuki.html"), ("xcom", "xcom_noutbuki.html")):
        url = get(store_name).catalog_url("noutbuki", 1)
        (pages / LocalFetcher.filename_for(url)).write_text(read_fixture(fixture_name), encoding="utf-8")
    return pages


def run(args: list[str]) -> int:
    return main(args)


def test_scan_list_exits_cleanly(capsys):
    assert run(["scan", "--list"]) == 0

    out = capsys.readouterr().out
    assert "dns" in out and "проверен" in out
    assert "ozon" in out and "не реализовано" in out


def test_scan_local_writes_snapshot(tmp_path, local_pages, capsys):
    db = tmp_path / "prices.db"
    code = run(
        [
            "--db", str(db),
            "scan", "--store", "dns", "--store", "xcom",
            "--category", "noutbuki",
            "--fetcher", "local", "--local-dir", str(local_pages),
        ]
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "магазинов: 2/2 ok" in out
    assert "[ok] dns/noutbuki: 2" in out
    assert "[ok] xcom/noutbuki: 2" in out

    with PriceStore(db) as store:
        assert len(store.last_prices()) == 4
        assert len(store.recent_scans()) == 2


def test_one_scan_is_one_snapshot(tmp_path, local_pages):
    """Все товары обхода должны лечь в БД с одним captured_at.

    Иначе срез «последнего снимка» (MAX(captured_at)) рассыпается на секунды и
    `watch`/`report`/`stats` видят лишь часть товаров.
    """
    db = tmp_path / "prices.db"
    run(
        [
            "--db", str(db),
            "scan", "--store", "dns", "--store", "xcom",
            "--category", "noutbuki",
            "--fetcher", "local", "--local-dir", str(local_pages),
        ]
    )

    with PriceStore(db) as store:
        stamps = {p.captured_at for p in store.latest_products()}
        assert len(stamps) == 1
        assert len(store.latest_products("noutbuki")) == 4


def test_scan_unreachable_store_returns_nonzero(tmp_path, capsys):
    """Нет ни одного живого магазина — код возврата 1, но без исключения."""
    code = run(
        [
            "--db", str(tmp_path / "prices.db"),
            "scan", "--store", "dns",
            "--category", "noutbuki",
            "--fetcher", "local", "--local-dir", str(tmp_path / "empty"),
            "--no-store",
        ]
    )

    assert code == 1
    assert "unreachable" in capsys.readouterr().out


def test_scan_unknown_store_is_reported(tmp_path, capsys):
    code = run(["--db", str(tmp_path / "prices.db"), "scan", "--store", "nosuchshop", "--no-store"])

    assert code == 2
    assert "nosuchshop" in capsys.readouterr().err


def test_no_store_leaves_db_untouched(tmp_path, local_pages):
    db = tmp_path / "prices.db"
    run(
        [
            "--db", str(db),
            "scan", "--store", "dns", "--category", "noutbuki",
            "--fetcher", "local", "--local-dir", str(local_pages),
            "--no-store",
        ]
    )

    assert not db.exists()


@pytest.mark.parametrize("fmt", ["md", "json", "csv"])
def test_scan_writes_report_in_each_format(tmp_path, local_pages, fmt):
    out = tmp_path / f"report.{fmt}"
    run(
        [
            "--db", str(tmp_path / "prices.db"),
            "scan", "--store", "dns", "--category", "noutbuki",
            "--fetcher", "local", "--local-dir", str(local_pages),
            "--no-store", "--report", str(out), "--format", fmt,
        ]
    )

    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    if fmt == "md":
        # md — сводка: магазины, статистика, аномалии. Полный список товаров в json/csv.
        assert "| dns | noutbuki | ok | 2 |" in text
    else:
        assert "HONOR MagicBook X16" in text
    if fmt == "json":
        assert json.loads(text)["summary"]["products_found"] == 2


def test_stats_and_watch_and_report_see_whole_snapshot(tmp_path, local_pages, capsys):
    db = tmp_path / "prices.db"
    run(
        [
            "--db", str(db),
            "scan", "--store", "dns", "--store", "xcom", "--category", "noutbuki",
            "--fetcher", "local", "--local-dir", str(local_pages),
        ]
    )
    capsys.readouterr()

    assert run(["--db", str(db), "stats", "--category", "noutbuki"]) == 0
    assert "точек 4" in capsys.readouterr().out

    assert run(["--db", str(db), "watch", "--category", "noutbuki"]) == 0
    assert "проверено товаров: 4" in capsys.readouterr().out

    out = tmp_path / "report.md"
    assert run(["--db", str(db), "report", "--category", "noutbuki", "--out", str(out)]) == 0
    assert "товаров: 4" in capsys.readouterr().out
    assert out.is_file()


def test_stats_by_product_shows_history(tmp_path, local_pages, capsys):
    db = tmp_path / "prices.db"
    for _ in range(2):
        run(
            [
                "--db", str(db),
                "scan", "--store", "dns", "--category", "noutbuki",
                "--fetcher", "local", "--local-dir", str(local_pages),
            ]
        )
    capsys.readouterr()

    assert run(["--db", str(db), "stats", "--product", "dns:5633157"]) == 0
    out = capsys.readouterr().out
    assert "точек 2" in out
    assert "69 999 ₽" in out
    assert "история:" in out


def test_watch_finds_drop_against_previous_snapshot(tmp_path, capsys):
    """Правило price_drop сравнивает свежий срез с прошлым, а не сам с собой."""
    from tests.test_storage import make_product

    db = tmp_path / "prices.db"
    with PriceStore(db) as store:
        store.save_products([make_product(100_000, "a", captured_at="2026-10-22T10:00:00+00:00")])
        store.save_products([make_product(15_000, "a", captured_at="2026-10-23T10:00:00+00:00")])

    assert run(["--db", str(db), "watch", "--category", "noutbuki"]) == 0
    out = capsys.readouterr().out
    assert "аномалий: 1" in out
    assert "price_drop" not in out  # в stdout уходит человекочитаемый detail
    assert "-85%" in out


def test_watch_and_report_on_empty_db(tmp_path, capsys):
    db = tmp_path / "prices.db"

    assert run(["--db", str(db), "watch"]) == 1
    assert "сначала запустите scan" in capsys.readouterr().err

    assert run(["--db", str(db), "report", "--out", str(tmp_path / "r.md")]) == 1
    assert "сначала запустите scan" in capsys.readouterr().err


def test_stats_on_missing_category(tmp_path, capsys):
    assert run(["--db", str(tmp_path / "prices.db"), "stats", "--category", "kofemolki"]) == 1
    assert "нет данных" in capsys.readouterr().err
