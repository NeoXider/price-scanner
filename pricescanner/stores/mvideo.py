"""M.Video (mvideo.ru).

Единственный из проверенных магазинов, который полностью работает на обычном
`requests` — нужны только cookie города. Проверено 2026-10-23:

    GET /bff/products/v2/search?query=&limit=&offset=   -> body.products[] = id'шники (строки)
    GET /bff/products/prices?productIds=a,b,c           -> body.materialPrices[].price
    GET /bff/product-details?productId=X                -> body.name, body.nameTranslit

Без cookie `MVID_CITY_ID, MVID_REGION_ID, MVID_REGION_SHOP, MVID_TIMEZONE_OFFSET`
BFF отвечает 400 и прямо перечисляет, чего не хватает.

Два ограничения витрины:
- имя товара отдаётся только по одному id за запрос, пакетного роута нет
  (`/bff/product-details/list` -> 403, `/bff/products/details` -> 404);
- поиск нечёткий: по «видеокарта» приезжают видеоняни, поэтому есть `min_price`.
"""

from __future__ import annotations

import json

from ..fetchers import Fetcher
from ..models import Placement, Product, StoreResult, StoreUnreachable, parse_price
from .base import StoreAdapter

BASE = "https://www.mvideo.ru"

#: Cookie города. По умолчанию Москва; меняется через `--city-cookies`.
MOSCOW_COOKIES = {
    "MVID_CITY_ID": "CityCZ_975",
    "MVID_REGION_ID": "1",
    "MVID_REGION_SHOP": "S002",
    "MVID_TIMEZONE_OFFSET": "3",
}


class MvideoStore(StoreAdapter):
    name = "mvideo"
    display_name = "М.Видео"
    verified = True
    method = "публичный BFF JSON API (search + prices + product-details), работает на requests"
    categories = {
        "noutbuki": "ноутбук",
        "videokarty": "видеокарта",
        "televizory": "телевизор",
        "smartfony": "смартфон",
    }

    def __init__(
        self,
        city: str = "Москва",
        *,
        limit: int = 30,
        min_price: float = 2000.0,
        cookies: dict[str, str] | None = None,
    ) -> None:
        super().__init__(city)
        self.limit = min(limit, 200)  # больше витрина не отдаёт
        self.min_price = min_price
        self.cookies = cookies or MOSCOW_COOKIES

    def catalog_url(self, category: str, page: int = 1) -> str:
        query = self.categories[category]
        offset = (page - 1) * self.limit
        return f"{BASE}/bff/products/v2/search?query={query}&limit={self.limit}&offset={offset}"

    def parse(self, payload: str, category: str) -> list[Product]:
        """Разбор одной страницы у M.Video невозможен: цена и имя лежат в разных
        роутах BFF, и собрать товар из одного ответа нельзя. Метод остаётся,
        чтобы класс выполнял контракт `StoreAdapter`; весь обход — в `scan`.
        """
        return []

    def _headers(self) -> dict[str, str]:
        cookie = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        return {"Accept": "application/json", "Cookie": cookie}

    def scan(self, fetcher: Fetcher, category: str, pages: int = 1) -> StoreResult:
        """Трёхшаговый обход: ищем id -> берём цены пачкой -> дочитываем имена."""
        if category not in self.categories:
            return StoreResult(
                store=self.name,
                category=category,
                status="unreachable",
                reason=f"категория «{category}» не настроена; есть: {', '.join(self.categories)}",
            )

        search_url = self.catalog_url(category, 1)
        try:
            ids: list[str] = []
            for page in range(1, pages + 1):
                ids.extend(self._search(fetcher, category, page))
            ids = list(dict.fromkeys(ids))  # витрина может повторить id между страницами
            if not ids:
                return StoreResult(
                    store=self.name,
                    category=category,
                    status="empty",
                    reason="поиск не вернул товаров",
                    url=search_url,
                )

            prices = self._prices(fetcher, ids)
            products = self._build(fetcher, ids, prices, category)
        except StoreUnreachable as exc:
            return StoreResult(
                store=self.name, category=category, status="unreachable", reason=exc.reason, url=search_url
            )
        except Exception as exc:
            return StoreResult(
                store=self.name,
                category=category,
                status="unreachable",
                reason=f"ошибка разбора: {type(exc).__name__}: {exc}",
                url=search_url,
            )

        return StoreResult(
            store=self.name,
            category=category,
            status="ok" if products else "empty",
            products=products,
            url=search_url,
            reason=None if products else "все найденные товары отсеяны по min_price",
        )

    def _search(self, fetcher: Fetcher, category: str, page: int) -> list[str]:
        raw = fetcher.get(self.catalog_url(category, page), headers=self._headers())
        body = (json.loads(raw) or {}).get("body") or {}
        return [str(pid) for pid in (body.get("products") or [])]

    def _prices(self, fetcher: Fetcher, ids: list[str]) -> dict[str, dict]:
        """Цены пачками по 50 id — на большем BFF начинает отваливаться."""
        prices: dict[str, dict] = {}
        for chunk_start in range(0, len(ids), 50):
            chunk = ids[chunk_start : chunk_start + 50]
            url = (
                f"{BASE}/bff/products/prices?productIds={','.join(chunk)}"
                "&isPromoApplied=true&addBonusRubles=true"
            )
            raw = fetcher.get(url, headers=self._headers())
            body = (json.loads(raw) or {}).get("body") or {}
            for entry in body.get("materialPrices") or []:
                pid = str(entry.get("productId") or "")
                if pid:
                    prices[pid] = entry.get("price") or {}
        return prices

    def _build(
        self, fetcher: Fetcher, ids: list[str], prices: dict[str, dict], category: str
    ) -> list[Product]:
        products: list[Product] = []
        for pid in ids:
            block = prices.get(pid) or {}
            price = parse_price(block.get("salePrice") or block.get("basePromoPrice"))
            if price is None or price < self.min_price:
                continue  # отсекаем мусор и нерелевантную выдачу нечёткого поиска

            title, slug = self._details(fetcher, pid)
            products.append(
                Product(
                    store=self.name,
                    title=title,
                    price=price,
                    old_price=parse_price(block.get("basePrice")),
                    available=None,  # наличие в этом ответе не приходит
                    url=f"{BASE}/products/{slug}-{pid}" if slug else f"{BASE}/products/{pid}",
                    product_id=pid,
                    category=category,
                    city=self.city,
                    placement=Placement(
                        store=self.display_name,
                        city=self.city,
                        # BFF цен/поиска не отдаёт ни филиал, ни остаток по магазину.
                        branch="unknown",
                        stock_note="unknown",
                    ),
                )
            )
        return products

    def _details(self, fetcher: Fetcher, pid: str) -> tuple[str, str]:
        """Имя и translit-слуг товара. Пакетного роута у витрины нет."""
        try:
            raw = fetcher.get(f"{BASE}/bff/product-details?productId={pid}", headers=self._headers())
            body = (json.loads(raw) or {}).get("body") or {}
            return str(body.get("name") or pid), str(body.get("nameTranslit") or "")
        except (StoreUnreachable, ValueError):
            # Имя — не причина терять цену: товар уедет в историю под своим id.
            return pid, ""
