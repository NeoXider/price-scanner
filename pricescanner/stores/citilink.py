"""Citilink (citilink.ru).

Next.js: товары приезжают в `<script id="__NEXT_DATA__">`. Путь проверен на
живой витрине 2026-10-23:

    props.initialState.subcategory.productsFilter.payload.productsFilter.products[]

Поля карточки: `id, name, shortName, slug, isAvailable,
price{price, old, discount, club}, stock{countInStores, maxCountInStock},
selfDeliveries{availabilityByDays, availableInFavoriteStores}, brand, category`.

Ограничение витрины: SSR отдаёт только ~8 товаров на страницу. Для глубокого
скана Citilink использует `POST /graphql/` (`productsFilter`) — здесь не
реализовано, потому что запрос требует живой браузерной сессии.
"""

from __future__ import annotations

import json

from bs4 import BeautifulSoup

from ..models import Placement, Product, parse_price
from .base import StoreAdapter

BASE = "https://www.citilink.ru"
PRODUCTS_PATH = (
    "props",
    "initialState",
    "subcategory",
    "productsFilter",
    "payload",
    "productsFilter",
)


class CitilinkStore(StoreAdapter):
    name = "citilink"
    display_name = "Ситилинк"
    verified = True
    method = "JSON из __NEXT_DATA__ на странице каталога (SSR, ~8 товаров/стр.)"
    categories = {
        "noutbuki": "noutbuki",
        "videokarty": "videokarty",
        "moduli-pamyati": "moduli-pamyati",
        "ssd-nakopiteli": "ssd-nakopiteli",
        "processory": "processory",
        "materinskie-platy": "materinskie-platy",
        "smartfony": "smartfony",
        "monitory": "monitory",
    }

    def catalog_url(self, category: str, page: int = 1) -> str:
        slug = self.categories[category]
        url = f"{BASE}/catalog/{slug}/"
        return f"{url}?p={page}" if page > 1 else url

    def parse(self, payload: str, category: str) -> list[Product]:
        raw = self._next_data(payload)
        node: object = raw
        for key in PRODUCTS_PATH:
            if not isinstance(node, dict) or key not in node:
                return []
            node = node[key]
        if not isinstance(node, dict):
            return []

        products: list[Product] = []
        for item in node.get("products") or []:
            price_block = item.get("price") or {}
            price = parse_price(price_block.get("price"))
            if price is None:
                continue
            slug = item.get("slug") or ""
            products.append(
                Product(
                    store=self.name,
                    title=item.get("name") or item.get("shortName") or "",
                    price=price,
                    old_price=parse_price(price_block.get("old")),
                    available=item.get("isAvailable"),
                    url=f"{BASE}/product/{slug}/" if slug else BASE,
                    product_id=str(item.get("id") or ""),
                    category=category,
                    city=self.city,
                    placement=self._placement(item),
                )
            )
        return products

    @staticmethod
    def _next_data(payload: str) -> dict:
        """Достаёт __NEXT_DATA__. Принимает и готовый JSON — так удобнее в тестах."""
        stripped = payload.lstrip()
        if stripped.startswith("{"):
            return json.loads(stripped)
        soup = BeautifulSoup(payload, "html.parser")
        tag = soup.find("script", id="__NEXT_DATA__")
        if not tag or not tag.string:
            return {}
        return json.loads(tag.string)

    def _placement(self, item: dict) -> Placement:
        stock = item.get("stock") or {}
        self_delivery = item.get("selfDeliveries") or {}
        favourites = self_delivery.get("availableInFavoriteStores") or []

        in_stores = stock.get("countInStores")
        stock_note = "unknown"
        if in_stores not in (None, ""):
            stock_note = f"в магазинах: {in_stores}"

        # Конкретный филиал Citilink отдаёт только для «избранных» магазинов
        # пользователя; у анонимной сессии список пуст.
        branch = "unknown"
        branch_address = "unknown"
        if favourites:
            first = favourites[0]
            if isinstance(first, dict):
                branch = str(first.get("name") or first.get("id") or "unknown")
                branch_address = str(first.get("address") or "unknown")

        try:
            branch_count = int(in_stores) if in_stores not in (None, "") else None
        except (TypeError, ValueError):
            branch_count = None

        return Placement(
            store=self.display_name,
            city=self.city,
            branch=branch,
            branch_address=branch_address,
            branch_available=str(item.get("isAvailable")),
            branch_count=branch_count,
            department=str((item.get("category") or {}).get("name") or "unknown"),
            stock_note=stock_note,
        )
