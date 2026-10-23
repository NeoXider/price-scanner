"""XCOM-SHOP, Екатеринбург (ekaterinburg.xcom-shop.ru).

Bitrix + ddos-guard. Схема снята с живой витрины 2026-10-23 — страница
`/catalog/kompyutery_i_noytbyki/noytbyki/` отдала 24 карточки:

    .catalog_item[data-id][data-price][data-vendor][data-item-type]
        data-dl-product              -> JSON {id, name, price, brand, category}
        a.catalog_item__name[href]
        .catalog_item__new_price     -> «92 000 ₽»
        .catalog_item__old_price
        .stock-indicator[data-level] -> 0..4, шкала наличия
        .stock-indicator__popover-value -> «21 – 100» (остаток на складах)

Внимание на транслит в путях: у магазина «ноутбуки» = `noytbyki`,
«компьютеры» = `kompyutery`. Город берётся из поддомена.
"""

from __future__ import annotations

import json

from bs4 import BeautifulSoup

from ..models import Placement, Product, parse_price
from .base import StoreAdapter

BASE = "https://ekaterinburg.xcom-shop.ru"


class XcomStore(StoreAdapter):
    name = "xcom"
    display_name = "XCOM-SHOP"
    verified = True
    method = "HTML каталога (Bitrix), цена и артикул в data-атрибутах карточки"
    categories = {
        "noutbuki": "kompyutery_i_noytbyki/noytbyki",
        "personalnye-kompyutery": "kompyutery_i_noytbyki/personalnye_kompyutery",
        "monobloki": "kompyutery_i_noytbyki/monobloki",
        "videokarty": "komplektyyuschie_dlya_pk_i_noytbykov/videokarty",
    }

    def __init__(self, city: str = "Екатеринбург") -> None:
        super().__init__(city)

    def catalog_url(self, category: str, page: int = 1) -> str:
        slug = self.categories[category]
        url = f"{BASE}/catalog/{slug}/"
        return f"{url}?PAGEN_1={page}" if page > 1 else url

    def parse(self, payload: str, category: str) -> list[Product]:
        soup = BeautifulSoup(payload, "html.parser")
        products: list[Product] = []

        for card in soup.select(".catalog_item[data-id]"):
            price = parse_price(card.get("data-price"))
            meta = self._dl_product(card)
            if price is None:
                price = parse_price(meta.get("price"))
            if price is None:
                price_node = card.select_one(".catalog_item__new_price")
                price = parse_price(price_node.get_text() if price_node else None)
            if price is None:
                continue

            link = card.select_one("a.catalog_item__name") or card.select_one("a.catalog_item__image")
            href = link.get("href") if link else ""
            title = meta.get("name") or (link.get_text(" ", strip=True) if link else "")
            old_node = card.select_one(".catalog_item__old_price")

            products.append(
                Product(
                    store=self.name,
                    title=" ".join(str(title).split()),
                    price=price,
                    old_price=parse_price(old_node.get_text() if old_node else None),
                    available=self._available(card),
                    url=href if str(href).startswith("http") else f"{BASE}{href}",
                    product_id=str(card.get("data-id") or ""),
                    category=category,
                    city=self.city,
                    placement=self._placement(card, meta),
                )
            )
        return products

    @staticmethod
    def _dl_product(card) -> dict:
        """`data-dl-product` — самый чистый источник имени/бренда/категории."""
        raw = card.get("data-dl-product")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return {}

    @staticmethod
    def _available(card) -> bool | None:
        indicator = card.select_one(".stock-indicator[data-level]")
        if not indicator:
            return None
        try:
            return int(indicator["data-level"]) > 0
        except (ValueError, KeyError):
            return None

    def _placement(self, card, meta: dict) -> Placement:
        stock_note = "unknown"
        popover = card.select_one(".stock-indicator__popover-value")
        if popover:
            stock_note = f"остаток на складах: {popover.get_text(' ', strip=True)}"

        return Placement(
            store=self.display_name,
            city=self.city,
            # Витрина показывает общий остаток по складам, конкретный филиал не называет.
            branch="unknown",
            branch_available=self._avail_label(card),
            department=str(meta.get("category") or card.get("data-item-type") or "unknown"),
            stock_note=stock_note,
        )

    @staticmethod
    def _avail_label(card) -> str | None:
        label = card.select_one(".stock-indicator__label")
        return label.get_text(" ", strip=True) if label else None
