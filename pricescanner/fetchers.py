"""Слой загрузки страниц.

Парсеры отделены от способа добычи HTML — это принципиально: российские
витрины по-разному относятся к чужим IP, и один клиент их не покроет.

- `HttpFetcher`    — обычный `requests`. Работает там, где нет антибота.
- `LocalFetcher`   — читает заранее сохранённые файлы. Нужен для офлайн-прогона
                     и для тестов на фикстурах.
- `BrowserFetcher` — Playwright, опциональная зависимость. Единственный способ
                     пройти JS-челленджи (Qrator, Group-IB, servicepipe).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Protocol

from .models import StoreUnreachable

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)

# Признаки того, что вместо каталога нам отдали заглушку антибота.
ANTIBOT_MARKERS = (
    "qrator",
    "ddos-guard",
    "servicepipe",
    "group-ib",
    "smartcaptcha",
    "не робот",
    "checking your browser",
)


class Fetcher(Protocol):
    """Контракт загрузчика: вернуть текст страницы или бросить StoreUnreachable."""

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> str: ...


def looks_like_antibot(status: int, body: str) -> str | None:
    """Возвращает причину, если ответ — заглушка антибота, иначе None."""
    if status in (401, 403, 429, 498, 503):
        return f"HTTP {status} (антибот или блокировка по IP)"
    head = body[:4000].lower()
    for marker in ANTIBOT_MARKERS:
        if marker in head:
            return f"в ответе маркер антибота: {marker}"
    return None


class HttpFetcher:
    """Обычный HTTP-клиент на requests с общей cookie-сессией."""

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        user_agent: str = DEFAULT_UA,
        cookies: dict[str, str] | None = None,
        delay: float = 0.0,
    ) -> None:
        import requests  # локальный импорт: без сети модуль тоже должен грузиться

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept-Language": "ru-RU,ru;q=0.9"})
        if cookies:
            self.session.cookies.update(cookies)
        self.timeout = timeout
        self.delay = delay

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> str:
        import requests

        if self.delay:
            time.sleep(self.delay)
        try:
            response = self.session.get(url, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise StoreUnreachable(url, f"сетевая ошибка: {type(exc).__name__}") from exc

        reason = looks_like_antibot(response.status_code, response.text)
        if reason:
            raise StoreUnreachable(url, reason)
        if response.status_code >= 400:
            raise StoreUnreachable(url, f"HTTP {response.status_code}")
        return response.text


class LocalFetcher:
    """Читает сохранённые страницы из каталога.

    Имя файла — URL, у которого всё небуквенное заменено на `_`. Так один и тот
    же адаптер работает и по сети, и на снятых заранее страницах.
    """

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    @staticmethod
    def filename_for(url: str) -> str:
        return "".join(c if c.isalnum() else "_" for c in url)[:150]

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> str:
        exact = self.directory / self.filename_for(url)
        for candidate in (exact, Path(f"{exact}.html"), Path(f"{exact}.json")):
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8")
        raise StoreUnreachable(url, f"нет локального файла в {self.directory}")


class BrowserFetcher:
    """Playwright: настоящий браузер для витрин за JS-челленджем.

    Устанавливается отдельно (`pip install price-scanner[browser]`
    и `playwright install chromium`). Без Playwright конструктор честно падает.
    """

    def __init__(self, *, headless: bool = True, timeout: float = 45.0, wait_ms: int = 2500) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - зависит от окружения
            raise StoreUnreachable(
                "browser",
                "не установлен playwright: pip install price-scanner[browser] "
                "&& playwright install chromium",
            ) from exc
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=headless)
        self._context = self._browser.new_context(user_agent=DEFAULT_UA, locale="ru-RU")
        self.timeout = timeout
        self.wait_ms = wait_ms

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> str:  # pragma: no cover
        page = self._context.new_page()
        try:
            if headers:
                page.set_extra_http_headers(headers)
            page.goto(url, timeout=self.timeout * 1000, wait_until="domcontentloaded")
            page.wait_for_timeout(self.wait_ms)
            html = page.content()
        except Exception as exc:
            raise StoreUnreachable(url, f"браузер не открыл страницу: {type(exc).__name__}") from exc
        finally:
            page.close()

        reason = looks_like_antibot(200, html)
        if reason:
            raise StoreUnreachable(url, reason)
        return html

    def close(self) -> None:  # pragma: no cover
        self._context.close()
        self._browser.close()
        self._playwright.stop()


def build_fetcher(kind: str, **kwargs: object) -> Fetcher:
    """Фабрика по имени из CLI: http | browser | local."""
    if kind == "http":
        return HttpFetcher(**kwargs)  # type: ignore[arg-type]
    if kind == "browser":
        return BrowserFetcher(**kwargs)  # type: ignore[arg-type]
    if kind == "local":
        return LocalFetcher(**kwargs)  # type: ignore[arg-type]
    raise ValueError(f"неизвестный загрузчик: {kind}")
