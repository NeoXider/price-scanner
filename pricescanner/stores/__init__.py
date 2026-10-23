"""Реестр адаптеров магазинов."""

from __future__ import annotations

from .base import StoreAdapter
from .citilink import CitilinkStore
from .dns import DnsStore
from .mvideo import MvideoStore
from .unverified import (
    EldoradoStore,
    MarketProfStore,
    MegamarketStore,
    OzonStore,
    RegardStore,
    SpComputerStore,
    WildberriesStore,
    YandexMarketStore,
)
from .xcom import XcomStore

#: имя -> класс адаптера
REGISTRY: dict[str, type[StoreAdapter]] = {
    cls.name: cls
    for cls in (
        # парсер снят с живой витрины и закреплён фикстурой
        DnsStore,
        CitilinkStore,
        MvideoStore,
        XcomStore,
        # объявлены, парсера нет — см. stores/unverified.py
        OzonStore,
        WildberriesStore,
        YandexMarketStore,
        MegamarketStore,
        EldoradoStore,
        RegardStore,
        SpComputerStore,
        MarketProfStore,
    )
}

VERIFIED = [name for name, cls in REGISTRY.items() if cls.verified]


def get(name: str) -> StoreAdapter:
    """Создать адаптер по имени."""
    if name not in REGISTRY:
        raise KeyError(f"неизвестный магазин: {name}; есть: {', '.join(REGISTRY)}")
    return REGISTRY[name]()


def all_adapters(only_verified: bool = False) -> list[StoreAdapter]:
    names = VERIFIED if only_verified else list(REGISTRY)
    return [get(name) for name in names]


__all__ = ["REGISTRY", "VERIFIED", "StoreAdapter", "get", "all_adapters"]
