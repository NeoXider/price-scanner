"""DNS (dns-shop.ru).

Схема снята с живой витрины 2026-10-23 (каталог ноутбуков, город Екатеринбург).
Каталог рендерится на сервере, и цена лежит прямо в HTML — отдельный запрос
к `/ajax-state/product-buy/` для каталога не нужен:

    .catalog-product[data-code][data-avail-status]
        a.catalog-product__name[href][title]
        .product-buy__price                      -> «69 999 ₽»
        .delivery-info-widget[data-price][data-city-name]
        .order-avail-wrap_main .available        -> «В наличии»
        .order-avail-wrap_main a[href]           -> «в 24 магазинах» -> /shops/ekaterinburg/

Филиал DNS в каталоге не называет — отдаёт только количество магазинов города,
поэтому `branch` остаётся `unknown`, а число уходит в `branch_count`.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import Placement, Product, parse_price
from .base import StoreAdapter

BASE = "https://www.dns-shop.ru"
_SHOP_COUNT = re.compile(r"(\d+)\s*магазин")


class DnsStore(StoreAdapter):
    name = "dns"
    display_name = "DNS"
    verified = True
    method = "HTML каталога (server-side rendering), цена в разметке карточки"
    categories = {
        "noutbuki": "17a892f816404e77/noutbuki",
        "videokarty": "17a89aab16404e77/videokarty",
        "televizory": "17a8ae4916404e77/televizory",
    }

    def catalog_url(self, category: str, page: int = 1) -> str:
        slug = self.categories[category]
        url = f"{BASE}/catalog/{slug}/"
        return f"{url}?p={page}" if page > 1 else url

    def parse(self, payload: str, category: str) -> list[Product]:
        soup = BeautifulSoup(payload, "html.parser")
        products: list[Product] = []

        for card in soup.select(".catalog-product[data-code]"):
            link = card.select_one("a.catalog-product__name")
            if not link:
                continue

            # Числовой data-price надёжнее текста «69 999 ₽», но есть не всегда.
            widget = card.select_one(".delivery-info-widget")
            price = parse_price(widget.get("data-price")) if widget else None
            if price is None:
                price_node = card.select_one(".product-buy__price")
                price = parse_price(price_node.get_text() if price_node else None)
            if price is None:
                continue  # «Цена по запросу» / нет в продаже — не наш случай

            old_node = card.select_one(".product-buy__prev")
            title = link.get("title") or link.get_text(" ", strip=True)
            href = link.get("href") or ""

            products.append(
                Product(
                    store=self.name,
                    title=" ".join(title.split()),
                    price=price,
                    old_price=parse_price(old_node.get_text() if old_node else None),
                    available=card.get("data-avail-status") == "now",
                    url=href if href.startswith("http") else f"{BASE}{href}",
                    product_id=card.get("data-code", ""),
                    category=category,
                    city=self._city(card),
                    placement=self._placement(card),
                )
            )
        return products

    def _city(self, card) -> str:
        widget = card.select_one(".delivery-info-widget")
        if widget and widget.get("data-city-name"):
            return widget["data-city-name"]
        return self.city

    def _placement(self, card) -> Placement:
        avail = card.select_one(".order-avail-wrap_main")
        branch_available = None
        branches_url = None
        branch_count = None
        stock_note = "unknown"

        if avail:
            status = avail.select_one(".available")
            if status:
                branch_available = status.get_text(" ", strip=True)
            shops_link = avail.select_one("a[href]")
            if shops_link:
                href = shops_link.get("href", "")
                branches_url = href if href.startswith("http") else f"{BASE}{href}"
                text = shops_link.get_text(" ", strip=True)
                stock_note = text
                match = _SHOP_COUNT.search(text)
                if match:
                    branch_count = int(match.group(1))

        return Placement(
            store=self.display_name,
            city=self._city(card),
            # DNS в каталоге не называет конкретный филиал — только их число.
            branch="unknown",
            branch_available=branch_available,
            branches_url=branches_url,
            branch_count=branch_count,
            stock_note=stock_note,
        )
