from pathlib import Path

import pytest

from pricescanner.models import StoreUnreachable

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture
def read_fixture():
    def _read(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return _read


class FixtureFetcher:
    """Fetcher, который отдаёт фикстуры по подстроке URL.

    Нужен адаптерам с многошаговым обходом (M.Video): они дёргают несколько
    роутов, и каждому надо подсунуть свой заранее снятый ответ.
    """

    def __init__(self, routes: dict[str, str]) -> None:
        self.routes = routes
        self.calls: list[str] = []

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> str:
        self.calls.append(url)
        for marker, fixture in self.routes.items():
            if marker in url:
                return (FIXTURES / fixture).read_text(encoding="utf-8")
        raise StoreUnreachable("fixture", f"нет фикстуры для {url}")


@pytest.fixture
def fixture_fetcher():
    return FixtureFetcher
