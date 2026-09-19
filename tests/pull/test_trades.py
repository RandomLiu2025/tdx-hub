from datetime import date

import numpy as np
import pandas as pd
import pytest

from tdxhub.pull import trades_to_minutes

TZ = "Asia/Shanghai"
DAY = date(2025, 1, 6)


def trades(*rows, volume_column="vol"):
    data = pd.DataFrame(rows, columns=["time", "price", volume_column, "num"])
    return data


def at(frame, clock):
    return frame.loc[pd.Timestamp(f"2025-01-06 {clock}", tz=TZ)]


def test_trades_to_minutes_matches_go_241_bar_semantics_without_mutating_input():
    source = trades(
        ("09:30", 12.0, 2, 2),
        ("09:25", 10.0, 1, 1),
        ("09:30", 11.0, 3, 3),
        ("13:00", 13.0, 4, 4),
    )
    before = source.copy(deep=True)

    result = trades_to_minutes(source, date=DAY)

    pd.testing.assert_frame_equal(source, before)
    assert len(result) == 241
    assert result.index.name == "datetime"
    assert str(result.index.tz) == TZ
    assert result.index[0] == pd.Timestamp("2025-01-06 09:30", tz=TZ)
    assert result.index[120] == pd.Timestamp("2025-01-06 11:30", tz=TZ)
    assert result.index[121] == pd.Timestamp("2025-01-06 13:01", tz=TZ)
    assert result.index[-1] == pd.Timestamp("2025-01-06 15:00", tz=TZ)

    assert at(result, "09:30")["open"] == 10
    assert at(result, "09:30")["close"] == 10
    assert at(result, "09:30")["volume"] == 100
    assert at(result, "09:31")[["open", "high", "low", "close"]].tolist() == [12, 12, 11, 11]
    assert at(result, "09:31")["volume"] == 500
    assert at(result, "09:31")["amount"] == 5700
    assert at(result, "09:31")["order"] == 5
    assert at(result, "09:32")[["open", "high", "low", "close"]].tolist() == [11, 11, 11, 11]
    assert at(result, "09:32")[["volume", "amount", "order"]].tolist() == [0, 0, 0]
    assert at(result, "13:01")["close"] == 13
    assert at(result, "13:01")["volume"] == 400
    assert result["volume"].sum() == 1000
    assert result["amount"].sum() == 11900
    assert set(result["source"]) == {"trade"}
    assert set(result["volume_unit"]) == {"shares"}
    assert set(result["timezone"]) == {TZ}
    assert set(result["is_approximate"]) == {True}
    assert result.attrs == {"timezone": TZ, "volume_unit": "shares", "source": "trade"}


def test_trades_to_minutes_assigns_boundary_trades_to_next_compatible_minute():
    source = trades(
        ("09:25", 1.0, 1, 1),
        ("09:29", 2.0, 1, 1),
        ("09:30", 3.0, 1, 1),
        ("11:30", 4.0, 1, 1),
        ("13:00", 5.0, 1, 1),
        ("15:00", 6.0, 1, 1),
    )

    result = trades_to_minutes(source, date="20250106")

    assert at(result, "09:30")[["open", "close", "volume"]].tolist() == [1, 2, 200]
    assert at(result, "09:31")[["open", "close", "volume"]].tolist() == [3, 3, 100]
    assert at(result, "11:30")[["open", "close", "volume"]].tolist() == [4, 4, 100]
    assert at(result, "13:01")[["open", "close", "volume"]].tolist() == [5, 5, 100]
    assert at(result, "15:00")[["open", "close", "volume"]].tolist() == [6, 6, 100]


def test_trades_to_minutes_accepts_volume_alias_full_datetimes_and_missing_num():
    source = pd.DataFrame(
        {
            "time": [pd.Timestamp("2025-01-06 09:25", tz="UTC"), "2025-01-06 09:30:59"],
            "price": [10, 11],
            "volume": [2, 3],
        }
    )

    result = trades_to_minutes(source, date=pd.Timestamp("2025-01-06", tz=TZ))

    assert at(result, "09:30")[["close", "volume", "order"]].tolist() == [10, 200, 0]
    assert at(result, "09:31")[["close", "volume", "order"]].tolist() == [11, 300, 0]


@pytest.mark.parametrize("value", [10**400, complex(1, 2)])
def test_trades_to_minutes_normalizes_unsupported_numeric_values_to_value_error(value):
    source = pd.DataFrame(
        {
            "time": pd.Series(["09:25"], dtype=object),
            "price": pd.Series([value], dtype=object),
            "vol": pd.Series([1], dtype=object),
        }
    )

    with pytest.raises(ValueError, match="price"):
        trades_to_minutes(source, date=DAY)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (pd.DataFrame(), "empty"),
        (pd.DataFrame({"time": ["09:25"], "vol": [1]}), "price"),
        (pd.DataFrame({"time": ["09:25"], "price": [1]}), "volume"),
        (pd.DataFrame({"time": ["2025-01-05 09:25"], "price": [1], "vol": [1]}), "date"),
        (pd.DataFrame({"time": ["09:24"], "price": [1], "vol": [1]}), "time"),
        (pd.DataFrame({"time": ["11:31"], "price": [1], "vol": [1]}), "time"),
        (pd.DataFrame({"time": ["13:00"], "price": [0], "vol": [1]}), "price"),
        (pd.DataFrame({"time": ["13:00"], "price": [1], "vol": [-1]}), "volume"),
        (pd.DataFrame({"time": ["13:00"], "price": [1], "vol": [0]}), "volume"),
        (pd.DataFrame({"time": ["13:00"], "price": [np.nan], "vol": [1]}), "price"),
        (pd.DataFrame({"time": ["13:00"], "price": [np.inf], "vol": [1]}), "price"),
        (pd.DataFrame({"time": ["13:00"], "price": [1], "vol": [np.nan]}), "volume"),
        (pd.DataFrame({"time": ["13:00"], "price": [1], "vol": [1], "num": ["bad"]}), "num"),
    ],
)
def test_trades_to_minutes_rejects_invalid_or_incomplete_days(source, message):
    with pytest.raises((TypeError, ValueError), match=message):
        trades_to_minutes(source, date=DAY)
