from __future__ import annotations

import pandas as pd
import pytest

from tdxhub.gbbq import (
    CATEGORY_NAMES,
    EquitySnapshot,
    adjust_prices,
    adjustment_factors,
    get_equity_snapshot,
    normalize_gbbq,
    turnover_rate,
)


def _prices(dates: list[str], close: list[float] | None = None) -> pd.DataFrame:
    values = close or [10.0] * len(dates)
    return pd.DataFrame(
        {
            "open": values,
            "high": values,
            "low": values,
            "close": values,
            "volume": [100.0 + index for index in range(len(dates))],
            "amount": [1000.0 + index for index in range(len(dates))],
        },
        index=pd.to_datetime(dates),
    )


def _actions(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_normalize_gbbq_adds_dates_and_category_names_without_mutating_input():
    raw = pd.DataFrame(
        {
            "year": [2024, 2024],
            "month": [5, 6],
            "day": [10, 20],
            "category": [1, 5],
            "fenhong": [2.5, None],
        }
    )

    result = normalize_gbbq(raw)

    assert list(result.index) == list(pd.to_datetime(["2024-05-10", "2024-06-20"]))
    assert result.index.name == "date"
    assert result["category_name"].tolist() == ["除权除息", "股本变化"]
    assert result["fenhong"].tolist() == [2.5, 0.0]
    assert "category_name" not in raw
    assert CATEGORY_NAMES[14] == "送认沽权证"


def test_get_equity_snapshot_uses_latest_effective_equity_event():
    data = _actions(
        [
            {
                "date": "2024-01-02",
                "code": "sh600000",
                "category": 5,
                "panhouliutong": 1_000_000,
                "houzongguben": 2_000_000,
            },
            {
                "date": "2024-02-01",
                "code": "sh600000",
                "category": 1,
                "panhouliutong": 9_999_999,
                "houzongguben": 9_999_999,
            },
            {
                "date": "2024-03-01",
                "code": "sh600000",
                "category": 7,
                "panhouliutong": 900_000,
                "houzongguben": 1_800_000,
            },
        ]
    )

    january = get_equity_snapshot(data, at="2024-02-15")
    latest = get_equity_snapshot(data)

    assert january == EquitySnapshot(
        date=pd.Timestamp("2024-01-02"),
        category=5,
        code="sh600000",
        float_equity=1_000_000,
        total_equity=2_000_000,
    )
    assert latest is not None
    assert latest.date == pd.Timestamp("2024-03-01")
    assert latest.turnover(90_000) == pytest.approx(10.0)


@pytest.mark.parametrize(
    ("volume_shares", "float_equity", "expected"),
    [(100_000, 1_000_000, 10.0), (0, 1_000_000, 0.0), (-1, 1_000_000, 0.0), (100, 0, 0.0)],
)
def test_turnover_rate_uses_shares(volume_shares, float_equity, expected):
    assert turnover_rate(volume_shares, float_equity) == expected


def test_affine_cash_dividend_is_not_reduced_to_a_ratio():
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    actions = _actions([{"date": "2024-01-03", "category": 1, "fenhong": 1.0}])

    factors = adjustment_factors(dates, actions)

    assert factors.loc[dates[0], "qfq_mul"] == pytest.approx(1.0)
    assert factors.loc[dates[0], "qfq_add"] == pytest.approx(-0.1)
    assert factors.loc[dates[1], "qfq_add"] == pytest.approx(0.0)
    assert factors.loc[dates[0], "hfq_add"] == pytest.approx(0.0)
    assert factors.loc[dates[1], "hfq_add"] == pytest.approx(0.1)


def test_same_day_events_are_all_compounded():
    prices = _prices(["2024-01-02", "2024-01-04"])
    actions = _actions(
        [
            {"date": "2024-01-03", "category": 1, "fenhong": 1.0},
            {"date": "2024-01-03", "category": 1, "fenhong": 2.0},
        ]
    )

    result = adjust_prices(prices, actions, "qfq")

    assert result.loc[pd.Timestamp("2024-01-02"), "close"] == 9.70
    assert result.loc[pd.Timestamp("2024-01-04"), "close"] == 10.00


def test_all_events_in_a_suspension_gap_are_compounded():
    prices = _prices(["2024-01-02", "2024-01-08"])
    actions = _actions(
        [
            {"date": "2024-01-03", "category": 1, "fenhong": 1.0},
            {"date": "2024-01-05", "category": 1, "songzhuangu": 10.0},
        ]
    )

    result = adjust_prices(prices, actions, "qfq")

    assert result.loc[pd.Timestamp("2024-01-02"), "close"] == 4.95
    assert result.loc[pd.Timestamp("2024-01-08"), "close"] == 10.00


def test_future_event_is_ignored():
    prices = _prices(["2024-01-02", "2024-01-03"])
    actions = _actions([{"date": "2024-02-01", "category": 1, "fenhong": 9.0}])

    result = adjust_prices(prices, actions, "qfq")

    pd.testing.assert_series_equal(result["close"], prices["close"])


def test_prices_use_decimal_round_half_up_to_cents():
    prices = _prices(["2024-01-02", "2024-01-03"], close=[1.105, 1.0])
    actions = _actions([{"date": "2024-01-03", "category": 1, "fenhong": 1.0}])

    result = adjust_prices(prices, actions, "qfq")

    assert result.loc[pd.Timestamp("2024-01-02"), "close"] == 1.01


def test_volume_and_amount_are_not_changed_by_adjustment():
    prices = _prices(["2024-01-02", "2024-01-03"])
    actions = _actions(
        [{"date": "2024-01-03", "category": 1, "fenhong": 1.0, "songzhuangu": 10.0}]
    )

    for method in ("qfq", "hfq"):
        result = adjust_prices(prices, actions, method)
        pd.testing.assert_series_equal(result["volume"], prices["volume"])
        pd.testing.assert_series_equal(result["amount"], prices["amount"])


def test_invalid_zero_denominator_does_not_divide_by_zero():
    prices = _prices(["2024-01-02", "2024-01-03"])
    actions = _actions([{"date": "2024-01-03", "category": 1, "songzhuangu": -10.0}])

    result = adjust_prices(prices, actions, "qfq")

    assert result.loc[pd.Timestamp("2024-01-02"), "close"] == 10.0


def test_enrich_turnover_matches_historical_float_equity_without_mutating_bars():
    from tdxhub.gbbq import enrich_turnover

    bars = pd.DataFrame(
        {"volume": [2_000.0, 1_000.0, 2_000.0, 1_000.0, 100.0]},
        index=pd.to_datetime(["2024-01-04", "2024-01-01", "2024-01-03", "2024-01-02", "2023-12-31"]),
    )
    original = bars.copy(deep=True)
    actions = _actions(
        [
            {
                "date": "2024-01-01",
                "code": "sh600000",
                "category": 5,
                "panhouliutong": 1_000_000,
            },
            {
                "date": "2024-01-02",
                "code": "600000",
                "category": 1,
                "panhouliutong": 9_999_999,
            },
            {
                "date": "2024-01-02",
                "code": "sz000001",
                "category": 5,
                "panhouliutong": 100,
            },
            {
                "date": "2024-01-03",
                "code": "SH.600000",
                "category": 7,
                "panhouliutong": 2_000_000,
            },
        ]
    )

    result = enrich_turnover(bars, actions, code="600000")

    pd.testing.assert_frame_equal(bars, original)
    assert result.index.tolist() == bars.index.tolist()
    assert result["turnover"].iloc[:4].tolist() == pytest.approx([10.0, 10.0, 10.0, 10.0])
    assert pd.isna(result["turnover"].iloc[4])
    assert result.attrs["turnover_unit"] == "percent"
    assert result.attrs["turnover_volume_unit"] == "lots"
    assert result.attrs["turnover_equity_unit"] == "shares"


def test_enrich_turnover_converts_native_xdxr_equity_from_ten_thousand_shares():
    from tdxhub.gbbq import enrich_turnover

    bars = pd.DataFrame(
        {"volume": [34_801.0]},
        index=pd.to_datetime(["2026-09-11"]),
    )
    actions = _actions(
        [
            {
                "date": "2026-05-28",
                "category": 5,
                "panhouliutong": 125_008.15625,
            }
        ]
    )
    actions.attrs["equity_unit"] = "ten_thousand_shares"

    result = enrich_turnover(bars, actions)

    assert result.iloc[0]["turnover"] == pytest.approx(0.2783898351)
    assert result.attrs["turnover_equity_unit"] == "shares"


def test_enrich_turnover_keeps_invalid_latest_equity_as_missing():
    from tdxhub.gbbq import enrich_turnover

    bars = _prices(["2024-01-02", "2024-01-03"])
    bars["volume"] = [1_000.0, 1_000.0]
    actions = _actions(
        [
            {"date": "2024-01-01", "category": 5, "panhouliutong": 1_000_000},
            {"date": "2024-01-03", "category": 5, "panhouliutong": 0},
        ]
    )

    result = enrich_turnover(bars, actions)

    assert result.loc[pd.Timestamp("2024-01-02"), "turnover"] == pytest.approx(10.0)
    assert pd.isna(result.loc[pd.Timestamp("2024-01-03"), "turnover"])


def test_enrich_turnover_returns_zero_for_non_positive_volume_with_valid_equity():
    from tdxhub.gbbq import enrich_turnover

    bars = _prices(["2024-01-02", "2024-01-03"])
    bars["volume"] = [0.0, -1.0]
    actions = _actions(
        [{"date": "2024-01-01", "category": 5, "panhouliutong": 1_000_000}]
    )

    result = enrich_turnover(bars, actions)

    assert result["turnover"].tolist() == pytest.approx([0.0, 0.0])


def test_enrich_turnover_returns_typed_column_for_empty_bars():
    from tdxhub.gbbq import enrich_turnover

    result = enrich_turnover(pd.DataFrame(), None)

    assert result.empty
    assert result.columns.tolist() == ["turnover"]
    assert str(result["turnover"].dtype) == "float64"
