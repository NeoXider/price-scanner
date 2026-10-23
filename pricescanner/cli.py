"""CLI: scan / stats / watch / report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import report as report_mod
from . import stats as stats_mod
from . import stores
from .anomaly import AnomalyConfig, detect
from .fetchers import BrowserFetcher, HttpFetcher, LocalFetcher
from .models import Product, StoreResult, utcnow
from .storage import DEFAULT_DB, PriceStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="price-scanner",
        description="Сканер цен по российским магазинам электроники: история, статистика, аномалии.",
    )
    parser.add_argument("--db", default=str(DEFAULT_DB), help=f"путь к SQLite (по умолчанию {DEFAULT_DB})")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="обойти магазины и записать срез цен")
    scan.add_argument("--store", action="append", help="магазин (можно несколько); по умолчанию все проверенные")
    scan.add_argument("--category", action="append", help="категория (можно несколько)")
    scan.add_argument("--pages", type=int, default=1, help="сколько страниц каталога брать")
    scan.add_argument(
        "--fetcher", choices=("http", "browser", "local"), default="http", help="способ загрузки страниц"
    )
    scan.add_argument("--local-dir", default="data/pages", help="каталог страниц для --fetcher local")
    scan.add_argument("--all-stores", action="store_true", help="включая магазины без парсера")
    scan.add_argument("--list", action="store_true", help="показать магазины и выйти")
    scan.add_argument("--no-store", action="store_true", help="не писать в БД")
    scan.add_argument("--report", help="путь к файлу отчёта")
    scan.add_argument("--format", choices=("md", "json", "csv"), default="md")

    stats_cmd = sub.add_parser("stats", help="статистика цен по товару или категории")
    group = stats_cmd.add_mutually_exclusive_group(required=True)
    group.add_argument("--product", help="product_key (store:id) или часть названия")
    group.add_argument("--category", help="категория")
    stats_cmd.add_argument("--history", action="store_true", help="по категории — вся история, не только срез")

    watch = sub.add_parser("watch", help="проверить последний срез на аномалии")
    watch.add_argument("--category", help="ограничить одной категорией")
    watch.add_argument("--median-ratio", type=float, default=0.20, help="цена <= ratio * медианы категории")
    watch.add_argument("--drop-ratio", type=float, default=0.80, help="падение >= ratio от прошлой цены")
    watch.add_argument("--min-price", type=float, default=1000.0, help="игнорировать всё дешевле")
    watch.add_argument("--min-points", type=int, default=5, help="минимум цен в категории для медианы")
    watch.add_argument("--report", help="путь к файлу отчёта")
    watch.add_argument("--format", choices=("md", "json", "csv"), default="md")

    rep = sub.add_parser("report", help="собрать отчёт из БД без обхода магазинов")
    rep.add_argument("--category", help="ограничить одной категорией")
    rep.add_argument("--out", default="reports/report.md", help="путь к файлу отчёта")
    rep.add_argument("--format", choices=("md", "json", "csv"), default="md")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {"scan": cmd_scan, "stats": cmd_stats, "watch": cmd_watch, "report": cmd_report}
    return handlers[args.command](args)


# --- scan ---------------------------------------------------------------


def cmd_scan(args: argparse.Namespace) -> int:
    if args.list:
        return _print_stores()

    adapters = _select_adapters(args)
    if not adapters:
        print("нечего сканировать: ни один магазин не выбран", file=sys.stderr)
        return 2

    fetcher = _build_fetcher(args)
    results: list[StoreResult] = []

    for adapter in adapters:
        categories = args.category or list(adapter.categories)
        for category in categories:
            if category not in adapter.categories:
                continue  # у магазина просто нет такой категории — это не ошибка
            results.append(adapter.scan(fetcher, category, pages=args.pages))

    if not results:
        print("ни одна пара магазин/категория не совпала", file=sys.stderr)
        return 2

    products = [p for r in results for p in r.products]
    anomalies: list = []
    store: PriceStore | None = None

    # Один обход — один снимок, одно время. Иначе каждый товар уносит в БД
    # собственную секунду (M.Video дочитывает имена по одному id и растягивает
    # обход на минуты), а `watch`/`report`/`stats` ищут срез по MAX(captured_at)
    # и видят только тот хвост товаров, что попал в последнюю секунду.
    captured_at = utcnow()
    for product in products:
        product.captured_at = captured_at

    if not args.no_store:
        store = PriceStore(args.db)
        previous = store.last_prices()
        anomalies = detect(products, previous)
        store.save_products(products)
        for result in results:
            store.save_scan(
                result.store, result.category, result.status, len(result.products), captured_at, result.reason
            )
    else:
        anomalies = detect(products)

    report = report_mod.build(results, anomalies, _category_stats(products))
    print(report_mod.stdout_summary(report))

    if args.report:
        path = report_mod.write(report, args.report, args.format)
        print(f"отчёт: {path}")
    if store:
        store.close()
    return 0 if any(r.ok for r in results) else 1


def _print_stores() -> int:
    print(f"{'магазин':<14} {'парсер':<10} способ")
    for name, cls in stores.REGISTRY.items():
        mark = "проверен" if cls.verified else "нет"
        print(f"{name:<14} {mark:<10} {cls.method}")
        if cls.categories:
            print(f"{'':<25} категории: {', '.join(cls.categories)}")
    return 0


def _select_adapters(args: argparse.Namespace) -> list:
    if args.store:
        selected = []
        for name in args.store:
            try:
                selected.append(stores.get(name))
            except KeyError as exc:
                print(exc, file=sys.stderr)
        return selected
    return stores.all_adapters(only_verified=not args.all_stores)


def _build_fetcher(args: argparse.Namespace):
    if args.fetcher == "local":
        return LocalFetcher(args.local_dir)
    if args.fetcher == "browser":
        return BrowserFetcher()
    return HttpFetcher(delay=0.5)


def _category_stats(products: list[Product]) -> dict[str, stats_mod.PriceStats]:
    buckets: dict[str, list[float]] = {}
    for product in products:
        buckets.setdefault(product.category, []).append(product.price)
    return {category: stats_mod.compute(prices) for category, prices in buckets.items()}


# --- stats --------------------------------------------------------------


def cmd_stats(args: argparse.Namespace) -> int:
    with PriceStore(args.db) as store:
        if args.product:
            rows = store.prices_for_product(args.product) or store.prices_by_title(args.product)
            label = f"товар {args.product}"
        else:
            rows = store.prices_for_category(args.category, latest_only=not args.history)
            label = f"категория {args.category}"

        if not rows:
            print(f"нет данных: {label}", file=sys.stderr)
            return 1

        summary = stats_mod.compute(r["price"] for r in rows)
        print(f"{label}: точек {summary.count}")
        for field in ("min", "p10", "median", "average", "p90", "max"):
            value = getattr(summary, field)
            print(f"  {field:<8} {report_mod.format_price(value)} ₽")

        if args.product:
            print("\nистория:")
            for row in rows[-10:]:
                print(f"  {row['captured_at']}  {report_mod.format_price(row['price'])} ₽  {row['store']}")
    return 0


# --- watch --------------------------------------------------------------


def cmd_watch(args: argparse.Namespace) -> int:
    config = AnomalyConfig(
        median_ratio=args.median_ratio,
        drop_ratio=args.drop_ratio,
        min_price=args.min_price,
        min_points=args.min_points,
    )
    with PriceStore(args.db) as store:
        products = store.latest_products(args.category)
        if not products:
            print("в БД нет снимков — сначала запустите scan", file=sys.stderr)
            return 1

        newest = max(p.captured_at for p in products)
        # Сравниваем только с тем, что было ДО последнего снимка, иначе товар
        # сравнивался бы сам с собой и падение никогда бы не нашлось.
        previous = store.last_prices(before=newest)
        anomalies = detect(products, previous, config)

        results = [
            StoreResult(store=name, category=args.category or "*", status="ok", products=[])
            for name in sorted({p.store for p in products})
        ]
        report = report_mod.build(results, anomalies, _category_stats(products))
        report["summary"]["products_found"] = len(products)

        if not anomalies:
            print(f"аномалий нет (проверено товаров: {len(products)})")
        else:
            print(f"аномалий: {len(anomalies)} из {len(products)} товаров")
            for anomaly in anomalies:
                product = anomaly.product
                placement = product.placement.summary() if product.placement else "unknown"
                print(
                    f"  ! {product.store} | {product.title[:60]} | "
                    f"{report_mod.format_price(product.price)} ₽ | {anomaly.detail} | {placement} | {product.url}"
                )

        if args.report:
            print(f"отчёт: {report_mod.write(report, args.report, args.format)}")
    return 0


# --- report -------------------------------------------------------------


def cmd_report(args: argparse.Namespace) -> int:
    with PriceStore(args.db) as store:
        products = store.latest_products(args.category)
        if not products:
            print("в БД нет снимков — сначала запустите scan", file=sys.stderr)
            return 1

        by_store: dict[tuple[str, str], list[Product]] = {}
        for product in products:
            by_store.setdefault((product.store, product.category), []).append(product)

        results = [
            StoreResult(store=s, category=c, status="ok", products=items)
            for (s, c), items in sorted(by_store.items())
        ]
        newest = max(p.captured_at for p in products)
        anomalies = detect(products, store.last_prices(before=newest))

        report = report_mod.build(results, anomalies, _category_stats(products))
        path = report_mod.write(report, args.out, args.format)
        print(report_mod.stdout_summary(report))
        print(f"отчёт: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
