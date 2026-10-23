"""price-scanner — сканер цен по российским магазинам электроники.

Собирает срезы цен, держит историю в SQLite, считает статистику по категориям
и ищет аномально низкие цены (ошибки витрин, двойные промо, рассинхрон городов).
"""

__version__ = "0.1.0"

from .models import Anomaly, Placement, Product, StoreResult, StoreUnreachable  # noqa: F401

__all__ = ["Anomaly", "Placement", "Product", "StoreResult", "StoreUnreachable", "__version__"]
