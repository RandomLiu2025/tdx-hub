import pandas as pd
import pytest

from tdxhub.pull import merge_bars, merge_fallback, to_period


def frame(times, values, *, source="native", approximate=False):
    values = [float(value) for value in values]
    return pd.DataFrame(
        {
            "open": values,
            "high": [value + 1 for value in values],
            "low": [value - 1 for value in values],
            "close": [value + 0.5 for value in values],
            "volume": list(range(1, len(values) + 1)),
            "amount": [10.0] * len(values),
            "source": source,
            "is_approximate": approximate,
        },
        index=pd.DatetimeIndex(times, name="datetime", tz="Asia/Shanghai"),
    )


def test_merge_bars_sorts_and_last_frame_wins():
    older = frame(["2026-01-02", "2026-01-01"], [2, 1])
    newer = frame(["2026-01-02", "2026-01-03"], [20, 3], source="refresh")

    result = merge_bars(older, newer)

    assert list(result.index) == list(pd.date_range("2026-01-01", periods=3, tz="Asia/Shanghai"))
    assert list(result["open"]) == [1.0, 20.0, 3.0]
    assert result.loc[pd.Timestamp("2026-01-02", tz="Asia/Shanghai"), "source"] == "refresh"
    assert len(older) == 2


def test_fallback_only_fills_missing_timestamps_and_marks_provenance():
    primary = frame(["2026-01-01 09:31", "2026-01-01 09:33"], [1, 3])
    fallback = frame(["2026-01-01 09:32", "2026-01-01 09:33"], [2, 30])

    result = merge_fallback(primary, fallback, source="trade")

    assert list(result["open"]) == [1.0, 2.0, 3.0]
    middle = result.loc[pd.Timestamp("2026-01-01 09:32", tz="Asia/Shanghai")]
    assert middle["source"] == "trade"
    assert bool(middle["is_approximate"])


def test_fixed_period_aggregates_ohlcv_and_metadata():
    data = frame(pd.date_range("2026-01-01 09:31", periods=6, freq="min"), range(1, 7))
    data.loc[data.index[1], "source"] = "trade"
    data.loc[data.index[1], "is_approximate"] = True

    result = to_period(data, 5)

    assert len(result) == 2
    assert result.iloc[0]["open"] == 1
    assert result.iloc[0]["high"] == 6
    assert result.iloc[0]["low"] == 0
    assert result.iloc[0]["close"] == 5.5
    assert result.iloc[0]["volume"] == 15
    assert result.iloc[0]["amount"] == 50
    assert result.iloc[0]["source"] == "trade"
    assert bool(result.iloc[0]["is_approximate"])
    assert result.index[0] == data.index[4]


def test_merge_rejects_mixed_timezones():
    left = frame(["2026-01-01"], [1])
    right = left.copy()
    right.index = right.index.tz_convert("UTC")
    with pytest.raises(ValueError, match="timezone"):
        merge_bars(left, right)
