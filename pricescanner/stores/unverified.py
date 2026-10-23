"""Магазины, для которых парсер НЕ написан, потому что разметку получить не удалось.

Это сознательное решение, а не заготовка «на будущее». Правило проекта: парсер
живёт в репозитории только если его схема снята с живой витрины и закреплена
фикстурой в `tests/fixtures/`. Писать селекторы по памяти или по чужим статьям —
значит обещать покрытие, которого нет.

Каждая запись ниже хранит результат настоящего зонда от 2026-10-23 с
датацентрового IP (OVH, 57.128.190.28): что именно ответила витрина. Адаптер
существует, он зарегистрирован, вызывается и возвращает `unreachable` с этой
причиной — скан из-за него не падает.

Если у вас residential-IP и Playwright, часть из них, скорее всего, откроется:
снимите разметку, напишите парсер, положите фикстуру и переведите адаптер в
`verified = True`. Порядок описан в README, раздел «Как добавить магазин».
"""

from __future__ import annotations

from ..fetchers import Fetcher
from ..models import Product, StoreResult
from .base import StoreAdapter

PROBE_DATE = "2026-10-23"


class UnverifiedStore(StoreAdapter):
    """Объявленный магазин без проверенного парсера."""

    verified = False

    #: что ответила витрина на зонде
    probe_result: str = ""

    def catalog_url(self, category: str, page: int = 1) -> str:
        return self.categories.get(category, "")

    def parse(self, payload: str, category: str) -> list[Product]:
        raise NotImplementedError(
            f"{self.name}: парсер не реализован — разметка не получена ({self.probe_result})"
        )

    def scan(self, fetcher: Fetcher, category: str, pages: int = 1) -> StoreResult:
        return StoreResult(
            store=self.name,
            category=category,
            status="unreachable",
            reason=f"парсер не реализован: {self.probe_result} (зонд {PROBE_DATE})",
            url=self.catalog_url(category),
        )


class OzonStore(UnverifiedStore):
    name = "ozon"
    display_name = "Ozon"
    method = "не реализовано"
    probe_result = "соединение не устанавливается (read timeout по HTTP, chrome-error в браузере)"
    categories = {"noutbuki": "https://www.ozon.ru/search/?text=ноутбук"}


class WildberriesStore(UnverifiedStore):
    name = "wildberries"
    display_name = "Wildberries"
    method = "не реализовано"
    probe_result = (
        "search.wb.ru -> HTTP 403 (Server: wbaas) и по HTTP, и из браузера; "
        "сайт показывает «Возможно, нужно выключить VPN»"
    )
    categories = {"noutbuki": "https://www.wildberries.ru/catalog/0/search.aspx?search=ноутбук"}


class YandexMarketStore(UnverifiedStore):
    name = "yandex-market"
    display_name = "Яндекс Маркет"
    method = "не реализовано"
    probe_result = "HTTP 403 с заголовком X-Yandex-Captcha, в браузере TimeoutException"
    categories = {"noutbuki": "https://market.yandex.ru/search?text=ноутбук"}


class MegamarketStore(UnverifiedStore):
    name = "megamarket"
    display_name = "Мегамаркет"
    method = "не реализовано"
    probe_result = "слайдер-капча servicepipe вместо каталога («Хотим проверить, что вы не робот»)"
    categories = {"noutbuki": "https://megamarket.ru/catalog/noutbuki/"}


class EldoradoStore(UnverifiedStore):
    name = "eldorado"
    display_name = "Эльдорадо"
    method = "не реализовано"
    probe_result = (
        "HTTP 503 + JS-челлендж Group-IB на всех путях, включая /bff/products/v2/search; "
        "в браузере страница не дорендеривается"
    )
    categories = {"noutbuki": "https://www.eldorado.ru/c/noutbuki/"}


class RegardStore(UnverifiedStore):
    name = "regard"
    display_name = "Регард"
    method = "не реализовано"
    probe_result = "read timeout по HTTP, chrome-error в браузере — хост не отвечает с этого IP"
    categories = {"noutbuki": "https://www.regard.ru/catalog/1053/noutbuki"}


class SpComputerStore(UnverifiedStore):
    name = "sp-computer"
    display_name = "СП-Компьютер (Екб)"
    method = "не реализовано"
    probe_result = "read timeout по HTTP с этого IP"
    categories = {"noutbuki": "https://sp-computer.ru/catalog/"}


class MarketProfStore(UnverifiedStore):
    name = "market-prof"
    display_name = "Маркет-Проф (Екб)"
    method = "не реализовано"
    probe_result = "read timeout по HTTP с этого IP"
    categories = {"noutbuki": "https://market-prof.com/catalog/"}
