"""Статистика цен на заранее известных числах."""

from __future__ import annotations

import pytest

from pricescanner import stats


def test_compute_on_known_numbers():
    """[10,20,30,40,50]: все шесть величин считаются вручную и сверяются."""
    result = stats.compute([10, 20, 30, 40, 50])

    assert result.count == 5
    assert result.min == 10
    assert result.max == 50
    assert result.average == 30.0
    assert result.median == 30.0
    # линейная интерполяция: pos = 0.1*(5-1) = 0.4 -> 10 + (20-10)*0.4
    assert result.p10 == 14.0
    # pos = 0.9*(5-1) = 3.6 -> 40 + (50-40)*0.6
    assert result.p90 == 46.0


def test_median_of_even_count_interpolates():
    assert stats.median([10, 20, 30, 40]) == 25.0
    assert stats.compute([10, 20, 30, 40]).median == 25.0


def test_compute_on_real_prices():
    prices = [47999, 48990, 61490, 69999, 92000, 109999, 122072, 139990, 141990]
    result = stats.compute(prices)

    assert result.count == 9
    assert result.min == 47999
    assert result.max == 141990
    assert result.median == 92000  # пятый из девяти
    assert result.average == round(sum(prices) / 9, 2)
    assert result.min <= result.p10 <= result.median <= result.p90 <= result.max


def test_single_value_collapses_to_itself():
    result = stats.compute([69999])

    assert result.count == 1
    assert result.min == result.max == result.median == 69999
    assert result.p10 == result.p90 == 69999.0


def test_zeros_and_none_are_dropped_as_junk():
    """Нули и None — мусор витрин («цена по запросу»), в статистику не идут."""
    result = stats.compute([0, None, 100, 200, 0])

    assert result.count == 2
    assert result.min == 100
    assert result.max == 200


def test_empty_input_gives_empty_stats():
    result = stats.compute([])

    assert result.count == 0
    assert result.min is None
    assert result.median is None
    assert result.as_dict() == {
        "count": 0,
        "min": None,
        "max": None,
        "average": None,
        "median": None,
        "p10": None,
        "p90": None,
    }


def test_percentile_edges():
    values = [10, 20, 30, 40, 50]

    assert stats.percentile(values, 0.0) == 10
    assert stats.percentile(values, 1.0) == 50
    assert stats.percentile([], 0.5) is None


def test_percentile_rejects_q_out_of_range():
    with pytest.raises(ValueError):
        stats.percentile([1, 2, 3], 1.5)


def test_percentile_ignores_input_order():
    assert stats.percentile([50, 10, 30, 20, 40], 0.5) == 30.0


def test_as_dict_is_json_ready():
    data = stats.compute([10, 20, 30]).as_dict()

    assert set(data) == {"count", "min", "max", "average", "median", "p10", "p90"}
    assert data["median"] == 20.0
