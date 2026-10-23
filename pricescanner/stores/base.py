"""Контракт адаптера магазина."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..fetchers import Fetcher
from ..models import Product, StoreResult, StoreUnreachable


class StoreAdapter(ABC):
    """Один магазин.

    `parse` обязан быть чистой функцией от текста страницы — именно это
    позволяет проверять его на фикстурах без сети.
    """

    #: машинное имя для CLI и БД
    name: str = ""
    #: отображаемое имя сети
    display_name: str = ""
    #: True только если схема парсинга снята с живой витрины и зафиксирована в тестах
    verified: bool = False
    #: как добываются данные — одной строкой, для README и `scan --list`
    method: str = ""
    #: доступные категории: ключ -> человекочитаемое имя
    categories: dict[str, str] = {}

    def __init__(self, city: str = "unknown") -> None:
        self.city = city

    @abstractmethod
    def catalog_url(self, category: str, page: int = 1) -> str:
        """URL страницы каталога для категории."""

    @abstractmethod
    def parse(self, payload: str, category: str) -> list[Product]:
        """Разобрать ответ витрины в список товаров."""

    def scan(
        self, fetcher: Fetcher, category: str, pages: int = 1
    ) -> StoreResult:
        """Обойти категорию. Любая ошибка -> status=unreachable, скан не падает."""
        if category not in self.categories:
            return StoreResult(
                store=self.name,
                category=category,
                status="unreachable",
                reason=f"категория «{category}» не настроена; есть: {', '.join(self.categories)}",
            )

        products: list[Product] = []
        first_url = self.catalog_url(category, 1)
        for page in range(1, pages + 1):
            url = self.catalog_url(category, page)
            try:
                payload = fetcher.get(url)
                products.extend(self.parse(payload, category))
            except StoreUnreachable as exc:
                if products:
                    break  # часть страниц уже собрана — отдаём что есть
                return StoreResult(
                    store=self.name,
                    category=category,
                    status="unreachable",
                    reason=exc.reason,
                    url=url,
                )
            except Exception as exc:  # разметка поехала — это тоже не повод падать
                if products:
                    break
                return StoreResult(
                    store=self.name,
                    category=category,
                    status="unreachable",
                    reason=f"ошибка разбора: {type(exc).__name__}: {exc}",
                    url=url,
                )

        return StoreResult(
            store=self.name,
            category=category,
            status="ok" if products else "empty",
            products=products,
            url=first_url,
            reason=None if products else "страница разобрана, но товаров не найдено",
        )
