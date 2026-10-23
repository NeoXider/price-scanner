"""История цен в SQLite."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable, Sequence

from .models import Placement, Product

DEFAULT_DB = Path("data/prices.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    product_key  TEXT    NOT NULL,
    store        TEXT    NOT NULL,
    title        TEXT    NOT NULL,
    price        REAL    NOT NULL,
    old_price    REAL,
    available    INTEGER,
    url          TEXT,
    product_id   TEXT,
    city         TEXT,
    category     TEXT,
    placement    TEXT,
    captured_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_prices_key      ON prices(product_key, captured_at);
CREATE INDEX IF NOT EXISTS idx_prices_category ON prices(category, captured_at);
CREATE INDEX IF NOT EXISTS idx_prices_store    ON prices(store, captured_at);

CREATE TABLE IF NOT EXISTS scans (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    store        TEXT NOT NULL,
    category     TEXT NOT NULL,
    status       TEXT NOT NULL,
    reason       TEXT,
    found        INTEGER NOT NULL DEFAULT 0,
    captured_at  TEXT NOT NULL
);
"""


class PriceStore:
    """Тонкая обёртка над SQLite: запись снимков и чтение истории."""

    def __init__(self, path: str | Path = DEFAULT_DB) -> None:
        self.path = Path(path)
        if self.path.parent and str(self.path.parent) not in (".", ""):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "PriceStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- запись ---------------------------------------------------------

    def save_products(self, products: Iterable[Product]) -> int:
        rows = [
            (
                p.product_key,
                p.store,
                p.title,
                p.price,
                p.old_price,
                None if p.available is None else int(p.available),
                p.url,
                p.product_id,
                p.city,
                p.category,
                json.dumps(p.placement.as_dict(), ensure_ascii=False) if p.placement else None,
                p.captured_at,
            )
            for p in products
        ]
        if not rows:
            return 0
        self.conn.executemany(
            """INSERT INTO prices
               (product_key, store, title, price, old_price, available, url,
                product_id, city, category, placement, captured_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        self.conn.commit()
        return len(rows)

    def save_scan(
        self, store: str, category: str, status: str, found: int, captured_at: str, reason: str | None = None
    ) -> None:
        self.conn.execute(
            "INSERT INTO scans (store, category, status, reason, found, captured_at) VALUES (?,?,?,?,?,?)",
            (store, category, status, reason, found, captured_at),
        )
        self.conn.commit()

    # --- чтение ---------------------------------------------------------

    def last_prices(self, before: str | None = None) -> dict[str, float]:
        """Последняя известная цена по каждому товару.

        `before` ограничивает выборку снимками строго раньше указанного времени —
        именно это нужно `watch`, чтобы сравнивать с прошлым, а не с собой же.
        """
        params: dict[str, str] = {}
        where = ""
        if before:
            where = "WHERE captured_at < :before"
            params["before"] = before
        # Берём строку с максимальным captured_at в каждой группе: MAX() и price
        # в одном SELECT с GROUP BY — документированное поведение SQLite.
        rows = self.conn.execute(
            f"""SELECT product_key, price, MAX(captured_at) AS captured_at
                FROM prices {where}
                GROUP BY product_key""",
            params,
        ).fetchall()
        return {r["product_key"]: r["price"] for r in rows}

    def prices_for_product(self, product_key: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM prices WHERE product_key = ? ORDER BY captured_at",
            (product_key,),
        ).fetchall()

    def prices_by_title(self, pattern: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM prices WHERE title LIKE ? ORDER BY captured_at",
            (f"%{pattern}%",),
        ).fetchall()

    def prices_for_category(self, category: str, latest_only: bool = True) -> list[sqlite3.Row]:
        if not latest_only:
            return self.conn.execute(
                "SELECT * FROM prices WHERE category = ? ORDER BY captured_at",
                (category,),
            ).fetchall()
        return self.conn.execute(
            """SELECT * FROM prices WHERE category = ? AND captured_at = (
                   SELECT MAX(captured_at) FROM prices WHERE category = ?
               )""",
            (category, category),
        ).fetchall()

    def categories(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT category FROM prices WHERE category IS NOT NULL ORDER BY category"
        ).fetchall()
        return [r["category"] for r in rows]

    def latest_products(self, category: str | None = None) -> list[Product]:
        """Товары самого свежего снимка — вход для детектора аномалий."""
        if category:
            rows = self.prices_for_category(category)
        else:
            rows = self.conn.execute(
                "SELECT * FROM prices WHERE captured_at = (SELECT MAX(captured_at) FROM prices)"
            ).fetchall()
        return [row_to_product(r) for r in rows]

    def recent_scans(self, limit: int = 50) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM scans ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()


def row_to_product(row: sqlite3.Row | Sequence) -> Product:
    """Обратное преобразование строки БД в Product."""
    placement = None
    if row["placement"]:
        placement = Placement(**json.loads(row["placement"]))
    return Product(
        store=row["store"],
        title=row["title"],
        price=row["price"],
        url=row["url"] or "",
        product_id=row["product_id"] or "",
        category=row["category"] or "",
        old_price=row["old_price"],
        available=None if row["available"] is None else bool(row["available"]),
        city=row["city"] or "unknown",
        placement=placement,
        captured_at=row["captured_at"],
    )
